from agents.base_agent import BaseAgent
from core.llm import LLM

class QAAgent(BaseAgent):
    def __init__(self):
        self.llm = LLM()

    def process(self, text: str) -> str:
        return self.llm.query(text)
