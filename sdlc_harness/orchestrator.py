from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
import subprocess
import os

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ExecutionBudget:
    max_steps: int = 6
    max_tokens: int = 25000
    current_step: int = 0
    tokens_used: int = 0

class ExecutionStep(BaseModel):
    step_id: int
    agent_name: str
    action: str
    thought: str
    observation: Optional[str] = None
    status: StepStatus = StepStatus.PENDING

async def trigger_coder_agent_repair(branch: str, error_log: str, budget: ExecutionBudget):
    """
    Mock trigger for the Coder Agent to repair the code based on test failures.
    In production, this would call the CodeWriterAgent ReAct loop.
    """
    print(f"🔧 Step {budget.current_step}: Triggering repair loop for {branch}...")
    # Simulated logic: Agent receives error_log and updates code via FastMCP tools
    budget.tokens_used += 1500 # Simulate token consumption

class Orchestrator:
    def __init__(self, issue_id: str, budget: Optional[ExecutionBudget] = None):
        self.issue_id = issue_id
        self.budget = budget or ExecutionBudget()
        self.steps: List[ExecutionStep] = []

    async def run_test_repair_loop(self, branch: str) -> bool:
        """Autonomous inner-loop: writes code -> runs pytest -> repairs on failure."""
        sandbox_root = os.getenv("SDLC_SANDBOX_ROOT", "/workspace/sandbox")
        
        while self.budget.current_step < self.budget.max_steps:
            self.budget.current_step += 1
            
            # Execute tests inside isolated environment
            print(f"🧪 Step {self.budget.current_step}: Running verification suite...")
            res = subprocess.run(
                ["pytest", "tests/unit"], 
                capture_output=True, 
                text=True,
                cwd=sandbox_root
            )
            
            if res.returncode == 0:
                print("✅ Quality Gate Passed.")
                return True
            
            # Feed stderr back to LLM to self-heal
            repair_context = res.stderr[-1500:] if res.stderr else res.stdout[-1500:]
            
            self.add_step(
                agent="TestFixer",
                action="Run Tests",
                thought=f"Tests failed with exit code {res.returncode}. Initiating repair."
            )
            
            await trigger_coder_agent_repair(branch, repair_context, self.budget)
            
            if self.budget.tokens_used > self.budget.max_tokens:
                raise RuntimeError("Token budget exceeded during self-correction.")

        raise TimeoutError("Execution step budget exceeded without passing test suite.")

    def add_step(self, agent: str, action: str, thought: str):
        step = ExecutionStep(
            step_id=len(self.steps) + 1,
            agent_name=agent,
            action=action,
            thought=thought
        )
        self.steps.append(step)
        return step
