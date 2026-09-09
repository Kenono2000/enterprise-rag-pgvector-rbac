import pytest
from sdlc_harness.orchestrator import Orchestrator
from sdlc_harness.webhooks.parser import parse_github_webhook

def test_webhook_parsing():
    mock_payload = {
        "issue": {
            "number": 123,
            "title": "Fix bug in auth",
            "body": "The auth module is failing"
        },
        "repository": {
            "full_name": "org/repo"
        }
    }
    event = parse_github_webhook(mock_payload)
    assert event.issue_id == "123"
    assert event.source == "github"

@pytest.mark.asyncio
async def test_orchestrator_init():
    orch = Orchestrator(issue_id="123")
    assert orch.budget.max_tokens == 25000
    assert len(orch.steps) == 0
    
    orch.add_step("Planner", "Initialize", "Starting the task")
    assert len(orch.steps) == 1
    assert orch.steps[0].agent_name == "Planner"
