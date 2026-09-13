import json
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from app.api.rag import router as rag_router
from app.db.manager import DatabaseManager
from sdlc_harness.langgraph_workflow import LangGraphSDLCWorkflow
from sdlc_harness.lifecycle import verify_github_signature

# Configure logging to show in console
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
    force=True
)
logger = logging.getLogger("sdlc_harness")
logger.setLevel(logging.INFO)
logging.getLogger().setLevel(logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Enterprise SDLC Harness...")
    await DatabaseManager.get_pool()
    logger.info("Database pool initialized.")
    yield
    logger.info("Shutting down Enterprise SDLC Harness...")
    await DatabaseManager.close()

app = FastAPI(
    title="Enterprise SDLC Harness",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(rag_router)


@app.post("/")
@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    logger.info(f"Received GitHub webhook event: {x_github_event}")
    if x_github_event == "ping":
        return {"message": "pong"}

    body = await request.body()
    if not verify_github_signature(
        body, x_hub_signature_256, os.getenv("GITHUB_WEBHOOK_SECRET")
    ):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    if x_github_event != "issues" and x_github_event is not None:
        logger.info(f"Skipping non-issue event: {x_github_event}")
        return {"message": f"Skipping event: {x_github_event}"}

    try:
        payload = json.loads(body)
        logger.info(f"Processing issue event for repository: {payload.get('repository', {}).get('full_name')}")
        result = await LangGraphSDLCWorkflow().run(payload)
        logger.info("Workflow completed successfully")
        return result
    except (ValueError, RuntimeError) as exc:
        logger.error(f"Workflow failed: {str(exc)}")
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.get("/")
async def root():
    return {"message": "Autonomous SDLC Agent Harness API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)