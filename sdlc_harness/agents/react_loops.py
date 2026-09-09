from typing import List, Dict, Any, Optional
from app.db.llm import chat_completion

class BaseAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    async def act(self, context: str, task: str) -> str:
        prompt = f"Role: {self.role}\nContext: {context}\nTask: {task}\n\nThink step-by-step and decide the next action."
        return await chat_completion(prompt)

class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__("Planner", "Senior Software Architect")

class CodeWriterAgent(BaseAgent):
    def __init__(self):
        super().__init__("CodeWriter", "Lead Software Engineer")

class TestFixerAgent(BaseAgent):
    def __init__(self):
        super().__init__("TestFixer", "SDET Specialist")

class ReActLoop:
    def __init__(self, agent: BaseAgent):
        self.agent = agent

    async def run(self, task: str, context: str, max_steps: int = 5):
        steps = []
        for i in range(max_steps):
            action_thought = await self.agent.act(context, task)
            steps.append({"step": i, "thought_action": action_thought})
            # In a real implementation, we would parse the action, execute it via MCP tools, 
            # and feed the observation back into the loop.
            if "FINAL_ANSWER" in action_thought:
                break
        return steps
