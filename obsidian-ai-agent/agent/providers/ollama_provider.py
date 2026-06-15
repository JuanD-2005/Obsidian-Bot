"""
agent/providers/ollama_provider.py
------------------------------------
LLM backend that calls a local Ollama instance.

Requires:
    OLLAMA_HOST   — default: http://localhost:11434
    OLLAMA_MODEL  — default: llama3

Ollama must be running locally:
    ollama serve
    ollama pull llama3   # or whichever model is configured
"""

from __future__ import annotations

import ollama
from ollama import ResponseError

from agent.config import settings
from agent.providers.base import SYSTEM_PROMPT, build_user_message


class OllamaProvider:
    """
    Calls a local Ollama instance via the official Python client.

    Uses the chat endpoint (ollama.chat) to keep the same
    system/user message structure as the OpenAI provider.
    """

    def __init__(self) -> None:
        # Point the client at the configured host
        self._client = ollama.Client(host=settings.ollama_host)
        self._model = settings.ollama_model

    # ------------------------------------------------------------------
    # Public API (satisfies AIProvider protocol)
    # ------------------------------------------------------------------

    def generate(self, template_content: str, raw_data: str) -> str:
        """Send template + data to the local model, return raw Markdown."""
        try:
            response = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": build_user_message(template_content, raw_data)},
                ],
                options={
                    "temperature": 0.3,
                    "num_predict": 4096,
                },
            )
        except ResponseError as exc:
            # Covers model-not-found, context-length errors, etc.
            raise RuntimeError(
                f"Ollama error (model='{self._model}'): {exc.error}\n"
                f"Make sure the model is pulled: ollama pull {self._model}"
            ) from exc
        except Exception as exc:
            # Connection refused, timeout, etc.
            raise RuntimeError(
                f"Could not reach Ollama at {settings.ollama_host}.\n"
                f"Is 'ollama serve' running?\nDetail: {exc}"
            ) from exc

        content = response.message.content
        if not content:
            raise RuntimeError("Ollama returned an empty response.")

        return self._clean(content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean(text: str) -> str:
        """Strip accidental code fences (same logic as OpenAI provider)."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        return text.strip()