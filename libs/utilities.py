__all__ = [
    "expand_user_roles",
    "get_db_connection",
    "get_documents",
    "get_embedding_model",
    "get_llm",
    "get_ollama_host",
    "get_retry_attempts",
    "get_timeout_seconds",
    "load_config",
    "log_error",
    "remove_comments_and_docstrings",
    "safe_calculate",
    "split_chunks",
    "truncate_and_normalize",
]

import ast
import operator
import os
import re
from pathlib import Path
from typing import Union

import numpy as np
import psycopg2
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, UnstructuredMarkdownLoader
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROLE_HIERARCHY = {
    "admin": ["admin", "executive", "finance_analyst", "engineering"],
    "finance_lead": ["finance_lead", "finance_analyst"],
    "engineering": ["engineering"]
}

_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

_DOCSTRING_PATTERN = re.compile(r'"""[\s\S]*?"""')

def expand_user_roles(raw_roles: list[str]) -> list[str]:
    expanded = set()
    for role in raw_roles:
        expanded.update(ROLE_HIERARCHY.get(role, [role]))
    return list(expanded)

def truncate_and_normalize(
    embedding: Union[list[float], "np.ndarray"],
    target_dim: int = 1536
) -> list[float]:
    vec = np.asarray(embedding[:target_dim], dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0.0:
        return vec.tolist()
    normalized_vec = vec / norm
    return normalized_vec.tolist()

def load_config(env_path: str | None = None) -> tuple[str, str]:
    if env_path is None:
        env_path = str(Path(__file__).parent / ".env")
    load_dotenv(env_path)
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    database_url = os.getenv("DATABASE_URL", "")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY missing from .env.")
    if not database_url:
        raise ValueError("DATABASE_URL missing from .env.")
    return openai_api_key, database_url

def get_documents(file_paths: list[str]) -> list[Document]:
    print(f"📄 Loading {len(file_paths)} document(s)...")
    documents = []
    for file_path in file_paths:
        try:
            suffix = Path(file_path).suffix.lower()
            if suffix == ".pdf":
                loader = PyPDFLoader(file_path)
            elif suffix == ".md":
                loader = UnstructuredMarkdownLoader(file_path)
            else:
                print(f"⚠️ Skipping unsupported file: {file_path}")
                continue
            documents.extend(loader.load())
            print(f"  [✓] Loaded {file_path}")
        except (OSError, RuntimeError) as e:
            print(f"❌ Failed to load {file_path}: {e}")
    return documents

def split_chunks(
    documents: list[Document],
    chunk_size: int = 2000,
    chunk_overlap: int = 200,
    separators: list[str] | None = None
) -> list[Document]:
    if separators is None:
        separators = ["\n\n", "\n", " ", ""]
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✂️ Created {len(chunks)} text chunks.")
    return chunks

def get_embedding_model(api_key: str) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="text-embedding-3-large",
        dimensions=1536,
        openai_api_key=api_key
    )

def get_llm(api_key: str, model: str = "gpt-4o", temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(model=model, temperature=temperature, openai_api_key=api_key)

def get_db_connection(database_url: str, timeout: int = 30):
    return psycopg2.connect(database_url, connect_timeout=timeout)

# --- Ollama utilities (extracted from py-scripts/ollama-models.py) ---------

def get_ollama_host(cli_host: str | None = None) -> str:
    """Return the Ollama host, preferring a CLI override, then the environment, then localhost."""
    host = cli_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    return host.rstrip('/')


def get_timeout_seconds(default: int = 60) -> int:
    """Return the per-request timeout from the environment or a safer default."""
    raw_value = os.getenv("OLLAMA_TIMEOUT_SECONDS", str(default))
    try:
        timeout = int(raw_value)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        return timeout
    except (TypeError, ValueError):
        print(f"[WARN] Invalid OLLAMA_TIMEOUT_SECONDS='{raw_value}'. Using default {default} seconds.")
        return default


def get_retry_attempts(default: int = 1) -> int:
    """Return how many times a timed-out request should be retried."""
    raw_value = os.getenv("OLLAMA_RETRY_ATTEMPTS", str(default))
    try:
        attempts = int(raw_value)
        if attempts <= 0:
            raise ValueError("retry attempts must be positive")
        return attempts
    except (TypeError, ValueError):
        print(f"[WARN] Invalid OLLAMA_RETRY_ATTEMPTS='{raw_value}'. Using default {default} attempt.")
        return default

# --- Logging utility (extracted from py-pgvector-local/api.py) -------------

def log_error(stage: str, error: Exception) -> None:
    """Log an error message with stage context and traceback."""
    import traceback
    print(f"[ERROR] {stage}: {error}")
    traceback.print_exc()

def safe_calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely using AST parsing.
    Supports: +, -, *, /, ** and parentheses.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        def _eval(node):
            match node:
                case ast.Constant(value=v) if isinstance(v, int | float):
                    return v
                case ast.BinOp(left=left, op=op, right=right) if type(op) in _SAFE_OPERATORS:
                    return _SAFE_OPERATORS[type(op)](_eval(left), _eval(right))
                case ast.UnaryOp(op=op, operand=operand) if type(op) in _SAFE_OPERATORS:
                    return _SAFE_OPERATORS[type(op)](_eval(operand))
                case _:
                    raise ValueError(f"Unsupported expression: {ast.dump(node)}")
        result = _eval(tree.body)
        return str(result)
    except (ValueError, ZeroDivisionError, SyntaxError) as e:
        return f"Error evaluating expression: {e}"

def remove_comments_and_docstrings(filepath: str) -> None:
    """Remove comments and docstrings from a source code file."""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    content = _DOCSTRING_PATTERN.sub('', content)
    content = re.sub(r'--.*', '', content)
    content = re.sub(r'#.*', '', content)
    lines = [line for line in content.split('\n') if line.strip()]
    with open(filepath, 'w', encoding='utf-8') as file:
        file.write('\n'.join(lines))
    print(f"Cleaned: {filepath}")
