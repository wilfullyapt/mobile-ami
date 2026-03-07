from abc import ABC, abstractmethod

class BaseAgent(ABC):
    @abstractmethod
    def process(self, text: str) -> str:
        pass
