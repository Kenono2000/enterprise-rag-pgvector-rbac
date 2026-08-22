import os
import json
import asyncpg
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
database_url = os.getenv("DATABASE_URL")

# FAIL LOUDLY: Ensure the database URL is actually present
if not database_url:
    raise ValueError("❌ CRITICAL: DATABASE_URL environment variable is not set. Please configure it in Render.")

class Citation(BaseModel):
    document_id: str
    title: str
    similarity_score: float

class RAGQueryRequest(BaseModel):
    question: str = Field(..., example="What were the Q3 financial results?")

class RAGResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence_score: float
    authorized_roles_evaluated: List[str]

class IngestDocumentRequest(BaseModel):
    document_id: str
    title: str
    content: str
    allowed_roles: List[str]

db_pool: Optional[asyncpg.Pool] = None
openai_client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    print("🔌 Connecting to PostgreSQL database...")
    db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    print("✅ Database connection pool established successfully!")
    yield
    print("🔌 Closing database connection pool...")
    await db_pool.close()

app = FastAPI(
    title="Zero-Trust Enterprise RAG Microservice",
    description="Asynchronous RAG API with In-Database RBAC and Matryoshka Vector Indexing",
    version="2.0.0",
    lifespan=lifespan
)
# ... (keep the rest of your main.py exactly as it was) ...