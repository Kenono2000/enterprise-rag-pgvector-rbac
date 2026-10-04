import argparse
import json
import sys
from pathlib import Path

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


def check_document_exists(target, filename: str) -> bool:
    """
    Check if ingested filename already exists in enterprise_documents.document_id.

    Supports database cursor, connection, or database URL connection string.
    Checks exact filename match, chunk prefix match (e.g., filename_1),
    and stem match (e.g., filename without extension).
    """
    query = """
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
    params = (filename, f"{escaped_fn}_%", stem, f"{escaped_stem}_%")

    if isinstance(target, str):
        with get_db_connection(target) as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone() is not None
    elif hasattr(target, "cursor"):
        with target.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone() is not None
    elif hasattr(target, "execute"):
        target.execute(query, params)
        return target.fetchone() is not None
    else:
        raise ValueError(f"Invalid target type for check_document_exists: {type(target)}")


def ingest_data(chunks: list[Document], embeddings_model: OpenAIEmbeddings, db_url: str):
    if not chunks:
        print("No chunks to ingest.")
        return
    chunk_texts = [chunk.page_content.replace("\x00", "") for chunk in chunks]
    chunk_titles = [Path(chunk.metadata.get("source", f"Chunk_{i+1}")).name.replace("\x00", "") for i, chunk in enumerate(chunks)]
    print(f"🚀 Generating embeddings for {len(chunk_texts)} chunks...")
    embeddings = embeddings_model.embed_documents(chunk_texts)
    print("  [✓] Embeddings generated.")
    default_roles = json.dumps(["engineer"])
    data_to_insert = [
        (
            str(chunk.metadata.get("document_id", f"{title}_{i+1}")).replace("\x00", ""),
            title,
            text,
            default_roles,
            str(embedding)
        )
        for i, (title, text, embedding, chunk) in enumerate(zip(chunk_titles, chunk_texts, embeddings, chunks))
    ]
    print("📦 Inserting into PostgreSQL...")
    try:
        with get_db_connection(db_url) as conn, conn.cursor() as cur:
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
                page_size=100
            )
        print(f"✅ Ingestion complete. Inserted {len(data_to_insert)} chunks.")
    except (psycopg2.Error, openai.OpenAIError) as e:
        print(f"❌ Database ingestion failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="Ingest docs into pgvector.")
    parser.add_argument("paths", nargs='+', help="File or directory paths.")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of already existing documents.")
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

    # Check if ingested filename already exists in enterprise_documents.document_id
    files_to_process: list[str] = []
    if getattr(args, "force", False):
        files_to_process = file_paths
    else:
        try:
            with get_db_connection(database_url) as conn, conn.cursor() as cur:
                for file_path in file_paths:
                    filename = Path(file_path).name
                    if check_document_exists(cur, filename):
                        print(f"⚠️ Skipping already ingested file: {filename} (exists in enterprise_documents.document_id)")
                    else:
                        files_to_process.append(file_path)
        except psycopg2.Error as e:
            print(f"⚠️ Could not verify existing documents in database ({e}). Proceeding with all files.")
            files_to_process = file_paths

    if not files_to_process:
        print("All documents have already been ingested.")
        return

    documents = get_documents(files_to_process)
    chunks = split_chunks(documents)
    embeddings_model = get_embedding_model(openai_api_key)
    ingest_data(chunks, embeddings_model, database_url)

if __name__ == "__main__":
    main()
