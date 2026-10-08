from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from scripts.ingest import check_document_exists, main


def test_check_document_exists_true_with_cursor():
    mock_cursor = MagicMock(spec=["execute", "fetchone"])
    mock_cursor.fetchone.return_value = (1,)

    exists = check_document_exists(mock_cursor, "source.pdf")
    assert exists is True
    assert mock_cursor.execute.called
    query, params = mock_cursor.execute.call_args[0]
    assert "documents" in query
    assert "enterprise_documents" not in query
    assert "document_id" in query
    assert params[0] == "source.pdf"
    assert params[1] == "source.pdf_%"


def test_check_document_exists_false_with_cursor():
    mock_cursor = MagicMock(spec=["execute", "fetchone"])
    mock_cursor.fetchone.return_value = None

    exists = check_document_exists(mock_cursor, "nonexistent.docx")
    assert exists is False
    assert mock_cursor.execute.called


def test_check_document_exists_with_connection():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    exists = check_document_exists(mock_conn, "test_doc.md")
    assert exists is True
    assert mock_cur.execute.called


def test_check_document_exists_with_db_url():
    with patch("scripts.ingest.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        exists = check_document_exists("postgresql://dummy_url", "test_doc.pdf")
        assert exists is True
        mock_get_conn.assert_called_once_with("postgresql://dummy_url")


def test_check_document_exists_invalid_target():
    with pytest.raises(ValueError, match="Invalid target type"):
        check_document_exists(12345, "invalid.pdf")


@patch("scripts.ingest.ingest_data")
@patch("scripts.ingest.get_embedding_model")
@patch("scripts.ingest.split_chunks")
@patch("scripts.ingest.get_documents")
@patch("scripts.ingest.check_document_exists")
@patch("scripts.ingest.get_db_connection")
@patch("scripts.ingest.load_config")
def test_main_skips_existing_files(
    mock_load_config,
    mock_get_db_connection,
    mock_check_exists,
    mock_get_docs,
    mock_split,
    mock_emb,
    mock_ingest,
    tmp_path,
    monkeypatch,
    capsys,
):
    mock_load_config.return_value = ("fake_key", "fake_url")
    file1 = tmp_path / "already_ingested.pdf"
    file1.write_text("content1")
    file2 = tmp_path / "new_file.docx"
    file2.write_text("content2")

    # file1 exists, file2 does not exist
    def fake_check(cur, filename):
        return filename == "already_ingested.pdf"

    mock_check_exists.side_effect = fake_check
    mock_get_docs.return_value = []
    mock_split.return_value = []

    monkeypatch.setattr("sys.argv", ["ingest.py", str(file1), str(file2)])
    main()

    # get_documents should only receive file2
    mock_get_docs.assert_called_once_with([str(file2)])
    captured = capsys.readouterr().out
    assert "Skipping already ingested file: already_ingested.pdf" in captured


@patch("scripts.ingest.ingest_data")
@patch("scripts.ingest.get_embedding_model")
@patch("scripts.ingest.split_chunks")
@patch("scripts.ingest.get_documents")
@patch("scripts.ingest.check_document_exists")
@patch("scripts.ingest.get_db_connection")
@patch("scripts.ingest.load_config")
def test_main_force_flag_includes_all(
    mock_load_config,
    mock_get_db_connection,
    mock_check_exists,
    mock_get_docs,
    mock_split,
    mock_emb,
    mock_ingest,
    tmp_path,
    monkeypatch,
):
    mock_load_config.return_value = ("fake_key", "fake_url")
    file1 = tmp_path / "file1.pdf"
    file1.write_text("content1")

    mock_check_exists.return_value = True  # Even if it exists
    mock_get_docs.return_value = []
    mock_split.return_value = []

    monkeypatch.setattr("sys.argv", ["ingest.py", "--force", str(file1)])
    main()

    # check_document_exists should not have been called because --force bypasses it
    assert not mock_check_exists.called
    mock_get_docs.assert_called_once_with([str(file1)])
