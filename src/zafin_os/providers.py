"""Model provider implementations using only the Python standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from .runtime import ModelResponse, ToolCall


class OpenAICompatibleProvider:
    """Chat completions client for OpenAI-compatible API endpoints."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60,
    ) -> None:
        if not base_url.strip() or not model.strip():
            raise ValueError("base_url and model are required")
        validated_url = self._validate_base_url(base_url)
        self.endpoint = self._completion_url(validated_url)
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("Do not include credentials in base_url")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url cannot include a query or fragment")
        if parsed.scheme == "http" and parsed.hostname.lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Plain HTTP is allowed only for a local model endpoint")
        return base_url.rstrip("/")

    @staticmethod
    def _completion_url(base_url: str) -> str:
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as result:
                body = json.loads(result.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Model endpoint returned HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach model endpoint: {exc.reason}") from exc

        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model endpoint returned an unexpected response shape") from exc

        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            raw_arguments = function.get("arguments", "{}")
            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Model returned invalid JSON for tool {function.get('name', 'unknown')}"
                ) from exc
            calls.append(
                ToolCall(
                    id=item.get("id", ""),
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )

        return ModelResponse(content=message.get("content"), tool_calls=calls)
