from __future__ import annotations

import unittest

from twinbox_core.llm import clean_json_text, resolve_backend


class LLMTest(unittest.TestCase):
    def test_resolve_backend_prefers_openai_compatible_settings(self) -> None:
        backend = resolve_backend(
            env={
                "LLM_API_KEY": "test-key",
                "LLM_MODEL": "test-model",
                "LLM_API_URL": "https://example.com/v1/chat/completions",
                "LLM_TIMEOUT": "42",
                "LLM_RETRIES": "3",
            }
        )

        self.assertEqual(backend.backend, "openai")
        self.assertEqual(backend.model, "test-model")
        self.assertEqual(backend.url, "https://example.com/v1/chat/completions")
        self.assertEqual(backend.timeout, 42)
        self.assertEqual(backend.retries, 3)

    def test_clean_json_text_repairs_fenced_trailing_comma_response(self) -> None:
        raw = """```json
        {
          "items": [
            {"id": "1", "intent": "human",},
          ],
        }
        ```"""

        cleaned = clean_json_text(raw)

        self.assertIn('"intent": "human"', cleaned)
        self.assertIn('"items"', cleaned)


if __name__ == "__main__":
    unittest.main()
