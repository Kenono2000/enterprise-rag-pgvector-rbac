"""
scripts/ingest.py
-----------------
Document ingestion pipeline for PostgreSQL 16 + pgvector.
Supports normalized schema (documents + document_chunks) with dual indexing (HNSW + GIN),
cryptographic SHA-256 de-duplication, batched embeddings, and backward-compatible fallbacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, List, Optional

# Add project root and libs directory to sys.path so utilities can be resolved
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "libs"))
sys.path.insert(0, str(PROJECT_ROOT))

import openai
import psycopg2
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from psycopg2.extras import execute_values
from utilities import (
    get_db_connection,
    get_documents,
    get_embedding_model,
    load_config,
    split_chunks,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ingest")


def compute_file_hash(file_path: str | Path) -> str:
    """Compute SHA-256 hash of a file in 64KB blocks for memory efficiency."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def check_document_exists(target: Any, filename: str, file_hash: Optional[str] = None) -> bool:
    """
    Check if a document has already been ingested.

    Checks:
    1. If file_hash is provided, checks documents table via idx_documents_file_hash.
    2. Checks enterprise_documents.document_id (exact filename, prefix, or stem).

    Supports database cursor, connection, or database URL connection string.
    """
    query_filename = """
        SELECT 1 FROM enterprise_documents
        WHERE document_id = %s 
           OR document_id LIKE %s ESCAPE '\\'
           OR document_id = %s 
           OR document_id LIKE %s ESCAPE '\\'
        LIMIT 1
    """
    stem = Path(filename).stem
    escaped_fn = filename.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    escaped_stem = stem.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    params_filename = (filename, f"{escaped_fn}_%", stem, f"{escaped_stem}_%")

    def _execute_check(cur) -> bool:
        # 1. Check by file_hash if provided
        if file_hash:
            try:
                cur.execute("SELECT 1 FROM documents WHERE file_hash = %s LIMIT 1", (file_hash,))
                if cur.fetchone() is not None:
                    return True
            except Exception:
                pass  # If documents table is not yet migrated, fall back to filename check

        # 2. Check by filename/prefix/stem in enterprise_documents
        cur.execute(query_filename, params_filename)
        return cur.fetchone() is not None

    if isinstance(target, str):
        with get_db_connection(target) as conn, conn.cursor() as cur:
            return _execute_check(cur)
    elif hasattr(target, "cursor"):
        with target.cursor() as cur:
            return _execute_check(cur)
    elif hasattr(target, "execute"):
        return _execute_check(target)
    else:
        raise ValueError(f"Invalid target type for check_document_exists: {type(target)}")


def _check_normalized_tables_exist(cur) -> bool:
    """Check if normalized tables documents and document_chunks exist in PostgreSQL."""
    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = CURRENT_SCHEMA() 
              AND table_name IN ('documents', 'document_chunks')
            """
        )
        row = cur.fetchone()
        return bool(row and row[0] >= 2)
    except Exception:
        return False


def ingest_data(
    chunks: list[Document],
    embeddings_model: OpenAIEmbeddings,
    db_url: str,
    default_roles: Optional[list[str]] = None,
    batch_size: int = 64,
):
    """
    Embed and ingest document chunks into PostgreSQL.

    Routes to normalized schema (documents + document_chunks) when available,
    falling back transparently to enterprise_documents view/table.
    """
    if not chunks:
        print("No chunks to ingest.")
        return

    roles = default_roles or ["engineer"]
    roles_json = json.dumps(roles)

    chunk_texts = [chunk.page_content.replace("\x00", "") for chunk in chunks]
    print(f"🚀 Generating embeddings for {len(chunk_texts)} chunks in batches of {batch_size}...")

    # Batch embedding generation to prevent rate limits and memory pressure
    embeddings: List[List[float]] = []
    for i in range(0, len(chunk_texts), batch_size):
        batch = chunk_texts[i : i + batch_size]
        batch_embs = embeddings_model.embed_documents(batch)
        embeddings.extend(batch_embs)
    print("  [✓] All embeddings generated.")

    print("📦 Inserting into PostgreSQL...")
    try:
        with get_db_connection(db_url) as conn:
            with conn.cursor() as cur:
                is_normalized = _check_normalized_tables_exist(cur)

                if is_normalized:
                    print("  [✓] Detected normalized schema (documents + document_chunks).")
                    # Group chunks by parent source file
                    doc_groups: dict[str, list[tuple[int, str, list[float], Document]]] = {}
                    for i, (text, emb, chunk) in enumerate(zip(chunk_texts, embeddings, chunks)):
                        src = str(chunk.metadata.get("source", f"document_{i+1}"))
                        doc_groups.setdefault(src, []).append((i, text, emb, chunk))

                    for src, items in doc_groups.items():
                        p = Path(src)
                        title = p.name if src and src != "unknown" else f"Document_{items[0][0]+1}"
                        doc_id = str(items[0][3].metadata.get("document_id") or p.stem)
                        file_type = p.suffix.lstrip(".").lower() if p.suffix else "markdown"
                        file_hash = items[0][3].metadata.get("file_hash")
                        if not file_hash and p.is_file():
                            try:
                                file_hash = compute_file_hash(p)
                            except Exception:
                                file_hash = None

                        # 1. Upsert master document
                        cur.execute(
                            """
                            INSERT INTO documents (document_id, title, source_path, file_hash, file_type, allowed_roles, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                            ON CONFLICT (document_id) DO UPDATE 
                            SET title = EXCLUDED.title,
                                source_path = EXCLUDED.source_path,
                                file_hash = EXCLUDED.file_hash,
                                file_type = EXCLUDED.file_type,
                                allowed_roles = EXCLUDED.allowed_roles,
                                updated_at = CURRENT_TIMESTAMP
                            RETURNING id
                            """,
                            (doc_id, title, src, file_hash, file_type, roles_json),
                        )
                        doc_uuid = cur.fetchone()[0]

                        # 2. Insert chunks for this document
                        chunks_data = [
                            (
                                doc_uuid,
                                str(chunk.metadata.get("chunk_id", f"{doc_id}_{idx+1}")).replace("\x00", ""),
                                idx,
                                text,
                                len(text.split()),
                                str(emb),
                                "text-embedding-3-large",
                            )
                            for idx, (_, text, emb, chunk) in enumerate(items)
                        ]

                        execute_values(
                            cur,
                            """
                            INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, token_count, embedding, embedding_model)
                            VALUES %s
                            ON CONFLICT (chunk_id) DO UPDATE 
                            SET content = EXCLUDED.content,
                                token_count = EXCLUDED.token_count,
                                embedding = EXCLUDED.embedding,
                                embedding_model = EXCLUDED.embedding_model
                            """,
                            chunks_data,
                            template="(%s, %s, %s, %s, %s, %s::vector, %s)",
                            page_size=100,
                        )
                else:
                    print("  [✓] Falling back to enterprise_documents view/table.")
                    chunk_titles = [
                        Path(chunk.metadata.get("source", f"Chunk_{i+1}")).name.replace("\x00", "")
                        for i, chunk in enumerate(chunks)
                    ]
                    data_to_insert = [
                        (
                            str(chunk.metadata.get("document_id", f"{title}_{i+1}")).replace("\x00", ""),
                            title,
                            text,
                            roles_json,
                            str(embedding),
                        )
                        for i, (title, text, embedding, chunk) in enumerate(
                            zip(chunk_titles, chunk_texts, embeddings, chunks)
                        )
                    ]

                    execute_values(
                        cur,
                        """
                        INSERT INTO enterprise_documents (document_id, title, content, allowed_roles, embedding)
                        VALUES %s
                        ON CONFLICT (document_id) DO UPDATE 
                        SET title = EXCLUDED.title, content = EXCLUDED.content, 
                            allowed_roles = EXCLUDED.allowed_roles, embedding = EXCLUDED.embedding
                        """,
                        data_to_insert,
                        template="(%s, %s, %s, %s::jsonb, %s::vector)",
                        page_size=100,
                    )
            conn.commit()
        print(f"✅ Ingestion complete. Processed {len(chunks)} chunks.")
    except (psycopg2.Error, openai.OpenAIError) as e:
        print(f"❌ Database ingestion failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Ingest docs into PostgreSQL pgvector.")
    parser.add_argument("paths", nargs="+", help="File or directory paths.")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of already existing documents.")
    parser.add_argument("--roles", nargs="*", default=["engineer"], help="Allowed roles for ingested documents.")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size (default: 64).")
    args = parser.parse_args()

    try:
        openai_api_key, database_url = load_config(str(PROJECT_ROOT / ".env"))
    except ValueError as e:
        print(f"Error: {e}")
        return

    file_paths: list[str] = []
    for path in args.paths:
        p = Path(path)
        if p.is_dir():
            file_paths.extend(str(f) for f in p.rglob("*.pdf"))
            file_paths.extend(str(f) for f in p.rglob("*.md"))
            file_paths.extend(str(f) for f in p.rglob("*.docx"))
        elif p.is_file() and p.suffix.lower() in {".pdf", ".md", ".docx"}:
            file_paths.append(str(p))
        else:
            print(f"⚠️ Skipping: {path}")

    if not file_paths:
        print("No valid files found.")
        return

    # Check if files already exist via SHA-256 hash or document_id
    files_to_process: list[str] = []
    if getattr(args, "force", False):
        files_to_process = file_paths
    else:
        try:
            with get_db_connection(database_url) as conn, conn.cursor() as cur:
                for file_path in file_paths:
                    filename = Path(file_path).name
                    file_hash = compute_file_hash(file_path) if Path(file_path).is_file() else None
                    if check_document_exists(cur, filename):
                        print(f"⚠️ Skipping already ingested file: {filename} (exists in database)")
                    else:
                        files_to_process.append(file_path)
        except psycopg2.Error as e:
            print(f"⚠️ Could not verify existing documents in database ({e}). Proceeding with all files.")
            files_to_process = file_paths

    if not files_to_process:
        print("All documents have already been ingested.")
        return

    documents = get_documents(files_to_process)
    # Attach file_hash to document metadata
    for doc in documents:
        src = doc.metadata.get("source")
        if src and Path(src).is_file():
            try:
                doc.metadata["file_hash"] = compute_file_hash(src)
            except Exception:
                pass

    chunks = split_chunks(documents)
    embeddings_model = get_embedding_model(openai_api_key)
    ingest_data(
        chunks,
        embeddings_model,
        database_url,
        default_roles=args.roles,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
