"""
Base classes and helper utilities for MCP tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Generic, Type, TypeVar

from pydantic import BaseModel


InputModelT = TypeVar("InputModelT", bound=BaseModel)
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class ToolExecutionError(RuntimeError):
    """Raised when a tool fails in a controlled manner."""


class ToolMetadata(BaseModel):
    """Serializable metadata for tool registration."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


class BaseTool(ABC, Generic[InputModelT, OutputModelT]):
    """Abstract base class for all tools."""

    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[Type[InputModelT]]
    output_model: ClassVar[Type[OutputModelT]]

    @classmethod
    def metadata(cls) -> ToolMetadata:
        """Return metadata for registering the tool with the MCP server."""

        return ToolMetadata(
            name=cls.name,
            description=cls.description,
            input_schema=cls.input_model.model_json_schema(),
            output_schema=cls.output_model.model_json_schema(),
        )

    async def invoke(self, raw_args: Dict[str, Any]) -> OutputModelT:
        """Validate input, execute tool logic, and return serializable result."""

        try:
            args = self.input_model.model_validate(raw_args or {})
        except Exception as exc:  # pragma: no cover - pydantic validation handles details
            raise ToolExecutionError(f"Invalid arguments: {exc}") from exc

        result = await self._run(args)
        if isinstance(result, self.output_model):
            return result
        return self.output_model.model_validate(result)

    @abstractmethod
    async def _run(self, arguments: InputModelT) -> OutputModelT | dict[str, Any]:
        """Execute the tool."""

