"""
agent/providers/openai_provider.py
-----------------------------------
LLM backend that calls the OpenAI chat completions API.

Requires:
    OPENAI_API_KEY  — set in .env
    OPENAI_MODEL    — default: gpt-4o-mini
"""

from __future__ import annotations

from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError

from agent.config import settings
from agent.providers.base import SYSTEM_PROMPT, build_user_message


class OpenAIProvider:
    """
    Calls the OpenAI chat completions endpoint.

    The client is instantiated lazily on first use so that importing this
    module never fails even when OPENAI_API_KEY is absent (e.g. when the
    user chose the ollama provider).
    """

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or export it in the shell."
            )
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    # ------------------------------------------------------------------
    # Public API (satisfies AIProvider protocol)
    # ------------------------------------------------------------------

    def generate(self, template_content: str, raw_data: str) -> str:
        """Send template + data to OpenAI, return raw Markdown."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": build_user_message(template_content, raw_data)},
                ],
                temperature=0.3,   # low temperature = more deterministic structure
                max_tokens=4096,
            )
        except AuthenticationError as exc:
            raise RuntimeError(
                f"OpenAI authentication failed — check your OPENAI_API_KEY.\n{exc}"
            ) from exc
        except RateLimitError as exc:
            raise RuntimeError(
                f"OpenAI rate limit reached. Try again in a moment.\n{exc}"
            ) from exc
        except APIConnectionError as exc:
            raise RuntimeError(
                f"Could not reach the OpenAI API. Check your internet connection.\n{exc}"
            ) from exc

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI returned an empty response.")

        return self._clean(content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean(text: str) -> str:
        """
        Strip accidental code fences the model might add despite instructions.
        e.g.  ```markdown\n...\n```  →  ...
        """
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (with optional language tag)
            text = text.split("\n", 1)[-1]
            # Remove closing fence
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        return text.strip()