from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolParam:
    name: str
    type: str          # "string", "integer", "number", "boolean"
    description: str
    required: bool = True


class BaseTool(ABC):
    """
    Abstract base for all agent tools.

    Subclasses declare name, description, and parameters as class attributes,
    then implement execute(**kwargs).
    """
    name: str
    description: str
    parameters: list[ToolParam] = field(default_factory=list)

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Run the tool and return a plain-text result."""

    def to_llm_schema(self) -> dict:
        """
        Returns an Ollama-compatible tool schema dict for function calling.
        See: https://ollama.com/blog/tool-support
        """
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }
