#!/usr/bin/env python
"""Test script to verify the enhanced HITL approval flow."""
import sys
import os
import asyncio
sys.path.insert(0, '.')

async def main():
    try:
        from agent.workflow import LangGraphSDLCWorkflow, ApprovalCard
        from agent.guardrails import PolicyEngine
        from agent.parser import parse_github_webhook
        
        print("✓ imports successful")
        
        # Sample webhook payload
        payload = {
            "action": "opened",
            "issue": {
                "number": 1,
                "title": "Create a hello world script 1",
                "body": "Add a new file named hello_world.py that prints Hello from Autonomous Agent 1."
            },
            "repository": {
                "full_name": "Kenono2000/enterprise-rag-pgvector-rbac"
            }
        }
        
        # Parse the webhook
        event = parse_github_webhook(payload)
        print(f"✓ Parsed webhook event: {event}")
        
        # Test the finalize method directly
        workflow = LangGraphSDLCWorkflow(require_hitl_for_high_risk=True)
        
        # Create a state that would trigger finalize with high-risk file
        state = {
            "event": event,
            "branch": "feature/test-1",
            "patches": [{"file_path": "app/auth/config.py", "content": "AUTH_TOKEN_TTL = 900"}],
            "payload": payload,
            "attempt": 0,
            "max_attempts": 3,
            "error": None,
            "violations": [],
            "crew_trace": [],
            "hermes_skill": None,
            "hermes_trajectory": None,
            "recalled_skills": [],
            "approval_card": None,
            "rolled_back": False,
            "test_result": None,
            "triage_summary": None,
            "judge_verdict": None,
            "crew_trace": [],
            "hermes_skill": None,
            "hermes_trajectory": None,
        }
        
        print("🔄 Calling finalize()...")
        final_state = await workflow.finalize(state)
        
        print(f"\n✓ finalize() completed")
        print(f"  Status: {final_state.get('status')}")
        print(f"  Patches: {len(final_state.get('patches', []))}")
        print(f"  Approval card: {final_state.get('approval_card')}")
        
        if final_state.get('approval_card'):
            card = final_state['approval_card']
            print(f"\n  Card risk_tier: {card.get('risk_tier')}")
            print(f"  Card requires_human_approval: {card.get('requires_human_approval')}")
            print(f"  Card status: {card.get('status')}")
            print(f"  Card reason: {card.get('reason')}")
        
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())