from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for all tools. Subclass to add new capabilities."""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Run the tool. Return string result for the model."""
        ...

    def to_schema(self) -> dict:
        """Return OpenAI/Ollama-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
