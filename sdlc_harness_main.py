import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from app.api.rag import router as rag_router
from app.db.manager import DatabaseManager
from sdlc_harness.langgraph_workflow import LangGraphSDLCWorkflow
from sdlc_harness.lifecycle import verify_github_signature

@asynccontextmanager
async def lifespan(app: FastAPI):
    await DatabaseManager.get_pool()
    yield
    await DatabaseManager.close()

app = FastAPI(
    title="Enterprise SDLC Harness",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(rag_router)


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    if not verify_github_signature(
        body, x_hub_signature_256, os.getenv("GITHUB_WEBHOOK_SECRET")
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
        return await LangGraphSDLCWorkflow().run(payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.get("/")
async def root():
    return {"message": "Autonomous SDLC Agent Harness API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)