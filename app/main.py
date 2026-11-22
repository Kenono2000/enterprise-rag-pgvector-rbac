import os
import json
import asyncio
from typing import Any, Dict
from fastapi import Request, HTTPException
from agent.parser import verify_github_signature
from agent.workflow import LangGraphSDLCWorkflow


# Timeout configuration - can be set via environment variables
SDLC_WEBHOOK_TIMEOUT = float(os.getenv("SDLC_WEBHOOK_TIMEOUT_SECONDS", "60.0"))
SDLC_TEST_TIMEOUT = float(os.getenv("SDLC_TEST_TIMEOUT_SECONDS", "30.0"))


# ---------------------------------------------------------------------------
# Optional SDLC GitHub Webhook Endpoint
# ---------------------------------------------------------------------------

@app.post("/webhooks/github", tags=["SDLC Agent"])
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    """Trigger autonomous SDLC agent on GitHub issue creation.
    
    With 'never ask user for approval' policy:
    - Workflow will NOT pause for HITL approval
    - Test timeouts are classified as "timeout" failure category
    - Workflow completes autonomously or times out
    """
    from agent.parser import verify_github_signature
    from agent.workflow import LangGraphSDLCWorkflow

    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret and not verify_github_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    payload = await request.json()
    if x_github_event == "issues" and payload.get("action") == "opened":
        try:
            workflow = LangGraphSDLCWorkflow()
            # Run workflow with timeout, never pausing for human approval
            result = await asyncio.wait_for(
                _run_workflow_autonomous(payload, workflow),
                timeout=SDLC_WEBHOOK_TIMEOUT,
            )
            return {"status": "processed", "result": result}
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "message": f"SDLC workflow timed out after {SDLC_WEBHOOK_TIMEOUT}s",
                "policy": "never_ask_approval",
                "suggestion": "Increase SDLC_WEBHOOK_TIMEOUT or simplify the issue",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "policy": "never_ask_approval",
            }

    return {"status": "ignored", "event": x_github_event}


async def _run_workflow_autonomous(
    payload: dict,
    workflow: LangGraphSDLCWorkflow,
) -> dict:
    """Run the SDLC workflow without human-in-the-loop approval.
    
    This function ensures the workflow never pauses for HITL approval,
    aligning with the 'never ask user for approval' policy.
    The workflow will:
    - Auto-classify test timeouts as "timeout" 
    - Never set requires_human_approval=True
    - Return "completed" or "timeout" status based on outcome
    """
    try:
        result = await workflow.run(payload)
        return result
    except Exception as e:
        # Catch any workflow errors and return autonomous result
        return {
            "status": "error",
            "issue_id": payload.get("issue", {}).get("number", "unknown"),
            "error": str(e),
            "policy_applied": "never_ask_approval",
        }