from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.rag import router as rag_router
from app.db.manager import DatabaseManager

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

@app.get("/")
async def root():
    return {"message": "Autonomous SDLC Agent Harness API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
