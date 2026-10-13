from __future__ import annotations

import json
import unittest

from zafin_os.runtime import AgentRuntime, ModelResponse, ToolCall, ToolRegistry


class QueueModel:
    def __init__(self, *responses: ModelResponse) -> None:
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((messages, tools))
        return self.responses.pop(0)


def registry_with_add() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        name="add",
        description="Add two numbers.",
        parameters={
            "type": "object",
            "properties": {"left": {"type": "number"}, "right": {"type": "number"}},
            "required": ["left", "right"],
            "additionalProperties": False,
        },
        handler=lambda left, right: left + right,
    )
    return tools


class ToolRegistryTests(unittest.TestCase):
    def test_rejects_duplicate_tool_names(self):
        tools = registry_with_add()
        with self.assertRaisesRegex(ValueError, "already registered"):
            tools.register("add", "Duplicate", {"type": "object"}, lambda: None)

    def test_rejects_non_object_parameter_schema(self):
        with self.assertRaisesRegex(ValueError, "JSON Schema object"):
            ToolRegistry().register("lookup", "Lookup", {"type": "string"}, lambda: None)

    def test_unknown_tool_returns_an_error_result(self):
        result = registry_with_add().execute(
            ToolCall("call-1", "delete_everything", {})
        )
        self.assertEqual(json.loads(result), {"error": "Tool is not registered: delete_everything"})

    def test_handler_failure_returns_an_error_result(self):
        tools = ToolRegistry()

        def fail():
            raise OSError("unavailable")

        tools.register("lookup", "Lookup", {"type": "object"}, fail)
        result = tools.execute(ToolCall("call-1", "lookup", {}))
        self.assertEqual(json.loads(result), {"error": "OSError: unavailable"})

    def test_non_object_arguments_are_not_passed_to_handler(self):
        result = registry_with_add().execute(
            ToolCall("call-1", "add", [20, 22])  # type: ignore[arg-type]
        )
        self.assertEqual(json.loads(result), {"error": "Tool arguments must be a JSON object."})


class AgentRuntimeTests(unittest.TestCase):
    def test_executes_registered_tool_and_returns_final_response(self):
        model = QueueModel(
            ModelResponse(
                tool_calls=[ToolCall("call-1", "add", {"left": 20, "right": 22})]
            ),
            ModelResponse(content="42"),
        )

        answer = AgentRuntime(model, registry_with_add()).run("What is 20 plus 22?")

        self.assertEqual(answer, "42")
        messages, definitions = model.requests[1]
        self.assertEqual(definitions[0]["function"]["name"], "add")
        tool_message = next(message for message in messages if message["role"] == "tool")
        self.assertEqual(json.loads(tool_message["content"]), {"result": 42})

    def test_returns_final_response_without_tools(self):
        model = QueueModel(ModelResponse(content="Hello"))
        self.assertEqual(AgentRuntime(model, registry_with_add()).run("Say hello"), "Hello")

    def test_empty_prompt_is_rejected(self):
        model = QueueModel()
        with self.assertRaisesRegex(ValueError, "Prompt cannot be empty"):
            AgentRuntime(model, registry_with_add()).run("  ")

    def test_tool_round_limit_is_enforced(self):
        model = QueueModel(
            ModelResponse(tool_calls=[ToolCall("call-1", "add", {"left": 1, "right": 2})]),
            ModelResponse(tool_calls=[ToolCall("call-2", "add", {"left": 3, "right": 4})]),
        )
        with self.assertRaisesRegex(RuntimeError, "exceeded the limit of 1"):
            AgentRuntime(model, registry_with_add(), max_steps=1).run("Keep adding")

    def test_max_steps_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "at least 1"):
            AgentRuntime(QueueModel(), registry_with_add(), max_steps=0)


if __name__ == "__main__":
    unittest.main()
