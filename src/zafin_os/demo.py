"""Offline model and tool for demonstrating the runtime without credentials."""

from __future__ import annotations

from typing import Any

from .runtime import ModelResponse, ToolCall


class DemoModel:
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(content="The registered add tool returned 42.")
        return ModelResponse(
            tool_calls=[
                ToolCall(
                    id="demo-add-1",
                    name="add",
                    arguments={"left": 20, "right": 22},
                )
            ]
        )
