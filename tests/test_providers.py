from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from zafin_os.providers import OpenAICompatibleProvider


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_completion_url_accepts_service_root_v1_and_full_endpoint(self):
        self.assertEqual(
            OpenAICompatibleProvider("https://example.test", "m", "").endpoint,
            "https://example.test/v1/chat/completions",
        )
        self.assertEqual(
            OpenAICompatibleProvider("https://example.test/v1/", "m", "").endpoint,
            "https://example.test/v1/chat/completions",
        )
        self.assertEqual(
            OpenAICompatibleProvider(
                "https://example.test/custom/chat/completions", "m", ""
            ).endpoint,
            "https://example.test/custom/chat/completions",
        )

    def test_local_http_endpoint_is_allowed(self):
        provider = OpenAICompatibleProvider("http://localhost:9000/v1", "m", "")
        self.assertEqual(provider.endpoint, "http://localhost:9000/v1/chat/completions")

    def test_remote_http_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only for a local"):
            OpenAICompatibleProvider("http://models.example.test/v1", "m", "secret")

    def test_credentials_in_base_url_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Do not include credentials"):
            OpenAICompatibleProvider("https://user:pass@example.test/v1", "m", "")

    def test_non_absolute_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absolute HTTPS URL"):
            OpenAICompatibleProvider("models.example.test/v1", "m", "")

    def test_sends_messages_and_parses_tool_calls(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "example-model", "secret"
        )
        body = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "add",
                                    "arguments": '{"left":20,"right":22}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(body).encode()

        with patch(
            "zafin_os.providers.urllib.request.urlopen", return_value=response
        ) as urlopen:
            result = provider.complete(
                [{"role": "user", "content": "Add these numbers"}],
                [{"type": "function", "function": {"name": "add"}}],
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(payload["model"], "example-model")
        self.assertEqual(payload["messages"][0]["content"], "Add these numbers")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(result.tool_calls[0].name, "add")
        self.assertEqual(result.tool_calls[0].arguments, {"left": 20, "right": 22})

    def test_invalid_tool_argument_json_is_reported(self):
        provider = OpenAICompatibleProvider("https://example.test", "m", "")
        body = {"choices": [{"message": {"tool_calls": [{"function": {"name": "add", "arguments": "{"}}]}}]}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(body).encode()
        with patch("zafin_os.providers.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON for tool add"):
                provider.complete([], [])

    def test_http_errors_include_status_and_response_body(self):
        provider = OpenAICompatibleProvider("https://example.test", "m", "")
        error = HTTPError(
            "https://example.test/v1/chat/completions",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rate limited"),
        )
        with patch(
            "zafin_os.providers.urllib.request.urlopen", side_effect=error
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429: rate limited"):
                provider.complete([], [])


if __name__ == "__main__":
    unittest.main()
