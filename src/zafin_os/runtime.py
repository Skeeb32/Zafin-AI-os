"""Bounded agent loop and explicit, allowlisted tool registry."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class Model(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        """Return the next assistant message, optionally requesting registered tools."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    def model_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Tools the runtime may call. No model-provided code is evaluated."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("Tool names may contain letters, numbers, and underscores.")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        if parameters.get("type") != "object":
            raise ValueError("Tool parameters must use a JSON Schema object.")
        self._tools[name] = Tool(name, description, parameters, handler)

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.model_definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            return json.dumps({"error": f"Tool is not registered: {call.name}"})
        if not isinstance(call.arguments, dict):
            return json.dumps({"error": "Tool arguments must be a JSON object."})
        validation_error = _validate_value(call.arguments, tool.parameters, "arguments")
        if validation_error:
            return json.dumps({"error": f"Invalid arguments for tool {call.name}: {validation_error}"})
        try:
            result = tool.handler(**call.arguments)
            return json.dumps({"result": result}, default=str)
        except Exception as exc:  # Return tool failures to the model for recovery.
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    if expected == "null":
        return value is None
    return False


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> str | None:
    expected = schema.get("type")
    if expected and not _matches_type(value, expected):
        return f"{path} must be {expected}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of the allowed values"

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                return f"{path}.{name} is required"
        for name, child in value.items():
            child_schema = properties.get(name)
            if child_schema is None:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    return f"{path}.{name} is not allowed"
                if isinstance(additional, dict):
                    child_schema = additional
            if child_schema is not None:
                error = _validate_value(child, child_schema, f"{path}.{name}")
                if error:
                    return error

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            error = _validate_value(item, schema["items"], f"{path}[{index}]")
            if error:
                return error
    return None


class AgentRuntime:
    """Run a model/tool conversation with a hard limit on tool rounds."""

    def __init__(self, model: Model, tools: ToolRegistry, max_steps: int = 8) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model = model
        self.tools = tools
        self.max_steps = max_steps

    def run(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        for step in range(self.max_steps + 1):
            response = self.model.complete(messages, self.tools.definitions())
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
            }
            if response.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in response.tool_calls
                ]
            messages.append(assistant_message)

            if not response.tool_calls:
                return response.content or ""
            if step == self.max_steps:
                raise RuntimeError(
                    f"Model exceeded the limit of {self.max_steps} tool rounds"
                )

            for call in response.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": self.tools.execute(call),
                    }
                )

        raise RuntimeError("Agent stopped without a final response")
