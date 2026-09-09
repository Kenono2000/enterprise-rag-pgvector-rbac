from pydantic import BaseModel
from typing import List, Optional

class SDLCEvent(BaseModel):
    source: str # e.g., "github", "jira"
    event_type: str # e.g., "issue_opened"
    issue_id: str
    title: str
    description: str
    repository: str

def parse_github_webhook(payload: dict) -> SDLCEvent:
    # Logic to transform GitHub webhook to internal SDLCEvent
    return SDLCEvent(
        source="github",
        event_type="issue_opened",
        issue_id=str(payload["issue"]["number"]),
        title=payload["issue"]["title"],
        description=payload["issue"]["body"],
        repository=payload["repository"]["full_name"]
    )
