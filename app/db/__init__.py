"""
app/db package
Consolidates DatabaseManager, connection pooling, and LLM services.
"""

from app.db.manager import DatabaseManager, get_db_url
from app.db.llm import generate_embedding, chat_completion, chat_completion_stream, chat_completion_stream_sync
from app.db.azure_search import azure_hybrid_search, get_search_client

__all__ = [
    "DatabaseManager",
    "get_db_url",
    "generate_embedding",
    "chat_completion",
    "chat_completion_stream",
    "chat_completion_stream_sync",
    "azure_hybrid_search",
    "get_search_client",
]

