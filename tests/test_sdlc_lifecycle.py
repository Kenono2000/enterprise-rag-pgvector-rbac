import hashlib
import hmac
import subprocess

import pytest

from sdlc_harness.lifecycle import SDLCWorkflow, verify_github_signature


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


@pytest.mark.asyncio
async def test_workflow_applies_tests_and_commits(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    payload = {
        "issue": {"number": 123, "title": "Fix value", "body": "Update the value."},
        "repository": {"full_name": "org/repo"},
        "patches": [{"file_path": "value.py", "content": "VALUE = 2\n"}],
    }
    result = await SDLCWorkflow(
        str(tmp_path), test_command="python -m pytest -q", push=False
    ).run(payload)

    assert result["status"] == "completed"
    assert result["branch"] == "feature/AGENT-123-fix-value"
    assert result["pushed"] is False
    assert result["pull_request_created"] is False
    assert "Fix value" in git(tmp_path, "log", "-1", "--format=%s").stdout


def test_webhook_signature():
    body = b'{"ok":true}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, f"sha256={digest}", "secret")
    assert not verify_github_signature(body, "sha256=bad", "secret")