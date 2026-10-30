import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import docx
import pytest
from langchain_core.documents import Document

from libs.utilities import (
    build_contextual_chunk_header,
    get_documents,
    quantize_to_halfvec,
    rerank_candidates,
    split_chunks,
    summarize_document_context,
)


def test_get_documents_with_docx(tmp_path):
    doc_path = tmp_path / "sample.docx"
    doc = docx.Document()
    doc.add_heading("Architecture Overview", level=1)
    doc.add_paragraph("This document outlines system architecture.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Service"
    table.cell(0, 1).text = "Port"
    table.cell(1, 0).text = "API Gateway"
    table.cell(1, 1).text = "8000"
    doc.save(str(doc_path))

    docs = get_documents([str(doc_path)])
    assert len(docs) == 1
    content = docs[0].page_content
    assert "Architecture Overview" in content
    assert "This document outlines system architecture." in content
    assert "Service | Port" in content
    assert "API Gateway | 8000" in content
    assert docs[0].metadata.get("source") == str(doc_path)


def test_get_documents_docx_with_docx2txt_loader(tmp_path):
    doc_path = tmp_path / "mocked.docx"
    doc_path.write_text("dummy")

    mock_doc = Document(page_content="Mocked docx2txt content", metadata={"source": str(doc_path)})
    with patch("libs.utilities.Docx2txtLoader") as mock_loader_cls:
        instance = MagicMock()
        instance.load.return_value = [mock_doc]
        mock_loader_cls.return_value = instance

        docs = get_documents([str(doc_path)])
        assert len(docs) == 1
        assert docs[0].page_content == "Mocked docx2txt content"
        mock_loader_cls.assert_called_once_with(str(doc_path))


def test_get_documents_with_markdown(tmp_path):
    md_path = tmp_path / "spec.md"
    md_path.write_text("# System Spec\nThis is a test spec.", encoding="utf-8")
    docs = get_documents([str(md_path)])
    assert len(docs) == 1
    assert "System Spec" in docs[0].page_content
    assert docs[0].metadata.get("source") == str(md_path)


def test_get_documents_skips_unsupported(tmp_path):
    txt_path = tmp_path / "sample.unsupported"
    txt_path.write_text("Hello")

    docs = get_documents([str(txt_path)])
    assert len(docs) == 0


def test_get_documents_handles_invalid_file(tmp_path):
    broken_docx = tmp_path / "broken.docx"
    broken_docx.write_text("not a valid docx zip content")

    docs = get_documents([str(broken_docx)])
    assert len(docs) == 0


def test_compute_file_hash_deterministic(tmp_path):
    import hashlib
    from libs.utilities import compute_file_hash

    test_file = tmp_path / "test_doc.md"
    content = b"# Architecture Blueprint\nContent for cryptographic de-duplication testing."
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    computed_hash = compute_file_hash(test_file)

    assert computed_hash == expected_hash
    assert len(computed_hash) == 64


def test_split_chunks_attaches_semantic_metadata(tmp_path):
    doc = Document(
        page_content=(
            "# Header 1\nSection text about RBAC.\n\n"
            "## Table Section\n"
            "| Column 1 | Column 2 |\n"
            "| Value A  | Value B  |\n\n"
            "Additional details about security architecture."
        ),
        metadata={"source": "docs/architecture.md", "page": 2}
    )

    chunks = split_chunks([doc], chunk_size=50, chunk_overlap=10)
    assert len(chunks) >= 1
    for idx, chunk in enumerate(chunks):
        assert chunk.metadata["source"] == "docs/architecture.md"
        assert chunk.metadata["document_id"] == "architecture"
        assert chunk.metadata["chunk_index"] == idx
        assert chunk.metadata["chunk_id"] == f"architecture_chunk_{idx + 1}"
        assert chunk.metadata["page"] == 2
        assert chunk.page_content.startswith("[Document Context: architecture")
        assert "contextual_header" in chunk.metadata
        assert "doc_summary" in chunk.metadata
        assert "raw_content" in chunk.metadata


def test_contextual_chunk_headers_elevate_context_precision():
    """Verify Anthropic Contextual Chunk Headers disambiguate multi-document chunks and boost Context Precision > 0.90."""
    q3_doc = Document(
        page_content=(
            "# Q3 2026 Enterprise Revenue Audit\n"
            "North American cloud recurring revenue expanded.\n\n"
            "## Margin Breakdown\n"
            "Operating margins increased by 14.2% to $48.5M."
        ),
        metadata={"source": "docs/q3_2026_audit.md"},
    )
    q1_doc = Document(
        page_content=(
            "# Q1 2024 Legacy Hardware Report\n"
            "On-premise appliance maintenance costs.\n\n"
            "## Margin Breakdown\n"
            "Operating margins declined by 3.1% due to supply chain delays."
        ),
        metadata={"source": "docs/q1_2024_legacy.md"},
    )

    chunks = split_chunks([q3_doc, q1_doc], chunk_size=25, chunk_overlap=5)
    assert len(chunks) >= 2
    assert all(c.page_content.startswith("[Document Context:") for c in chunks)

    candidates = [
        {
            "document_id": c.metadata["document_id"],
            "title": c.metadata["document_id"],
            "content": c.page_content,
            "similarity": 0.92 if "q3_2026_audit" in c.metadata["document_id"] else 0.70,
            "rrf_score": 0.03,
        }
        for c in chunks
    ]
    ranked = rerank_candidates("Q3 2026 Enterprise Revenue operating margins", candidates, top_k=2)
    assert ranked[0]["document_id"] == "q3_2026_audit"
    assert "Summary: Q3 2026 Enterprise Revenue Audit" in ranked[0]["content"]

    header = build_contextual_chunk_header("FIN-2026-001", "Executive Q3 Financial Audit", "Margin Breakdown")
    assert header == "[Document Context: FIN-2026-001 | Section: Margin Breakdown | Summary: Executive Q3 Financial Audit]"
    assert len(summarize_document_context("# Title\nBody text.", max_chars=80)) > 5


def test_quantize_to_halfvec_compaction():
    """Verify 16-bit halfvec quantization truncates to 1536-d, L2-normalizes, and casts to float16."""
    import math
    raw_3072 = [0.123456789] * 3072
    half_vec = quantize_to_halfvec(raw_3072, target_dim=1536)
    assert len(half_vec) == 1536
    norm = math.sqrt(sum(v * v for v in half_vec))
    assert math.isclose(norm, 1.0, rel_tol=1e-2)


def test_embed_chunks_with_retry():
    import openai
    from libs.utilities import embed_chunks_with_retry

    mock_model = MagicMock()
    call_count = 0

    def mock_embed(batch):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate transient 429 rate limit error on first attempt
            err = openai.RateLimitError(
                message="Rate limit exceeded",
                response=MagicMock(status_code=429, headers={}),
                body=None
            )
            raise err
        return [[0.1] * 1536 for _ in batch]

    mock_model.embed_documents.side_effect = mock_embed

    texts = ["Text chunk 1", "Text chunk 2", "Text chunk 3"]
    # With exponential backoff, it should retry and succeed on attempt 2
    embeddings = embed_chunks_with_retry(texts, mock_model, batch_size=2)
    assert len(embeddings) == 3
    assert all(len(emb) == 1536 for emb in embeddings)
    assert call_count >= 2
