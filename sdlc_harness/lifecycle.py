"""
sdlc_harness/lifecycle.py (Backward compatibility shim)
Forwards to agent.parser and agent.workflow.
"""

from agent.parser import verify_github_signature, parse_github_webhook, SDLCEvent
from agent.workflow import LangGraphSDLCWorkflow, TestResult

# SDLCWorkflow alias pointing to the compiled workflow
SDLCWorkflow = LangGraphSDLCWorkflow

__all__ = [
    "verify_github_signature",
    "parse_github_webhook",
    "SDLCEvent",
    "SDLCWorkflow",
    "TestResult",
]