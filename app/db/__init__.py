"""
app/db package
Consolidates DatabaseManager, connection pooling, and LLM services.
"""

from app.db.manager import DatabaseManager, get_db_url
from app.db.llm import generate_embedding, chat_completion, chat_completion_stream, chat_completion_stream_sync

__all__ = [
    "DatabaseManager",
    "get_db_url",
    "generate_embedding",
    "chat_completion",
    "chat_completion_stream",
    "chat_completion_stream_sync",
]

