"""Command line entry point for the first Zafin AI OS runtime milestone."""

from __future__ import annotations

import argparse
import os
import sys

from .demo import DemoModel
from .providers import OpenAICompatibleProvider
from .runtime import AgentRuntime, ToolRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded tool-using agent.")
    parser.add_argument("prompt", nargs="?", help="The task to give the agent")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the offline demonstration without a model API key",
    )
    parser.add_argument(
        "--max-steps", type=int, default=8, help="Maximum number of tool rounds (default: 8)"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    registry = ToolRegistry()
    registry.register(
        name="add",
        description="Add two numbers and return their sum.",
        parameters={
            "type": "object",
            "properties": {
                "left": {"type": "number"},
                "right": {"type": "number"},
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
        handler=lambda left, right: left + right,
    )

    if args.demo:
        model = DemoModel()
        prompt = args.prompt or "Add 20 and 22."
    else:
        prompt = args.prompt
        if not prompt:
            print("Provide a prompt, or use --demo.", file=sys.stderr)
            return 2
        base_url = os.environ.get("ZAFIN_AI_BASE_URL", "https://api.openai.com/v1")
        model_name = os.environ.get("ZAFIN_AI_MODEL", "gpt-4o-mini")
        api_key = os.environ.get("ZAFIN_AI_API_KEY", "")
        if not api_key and "api.openai.com" in base_url:
            print("Set ZAFIN_AI_API_KEY or use --demo.", file=sys.stderr)
            return 2
        model = OpenAICompatibleProvider(base_url, model_name, api_key)

    try:
        answer = AgentRuntime(model, registry, max_steps=args.max_steps).run(prompt)
    except (RuntimeError, ValueError) as exc:
        print(f"Agent run failed: {exc}", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
