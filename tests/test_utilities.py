import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import docx
import pytest
from langchain_core.documents import Document

from libs.utilities import get_documents


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
