"""
agent/providers/__init__.py
----------------------------
Public API for the providers subpackage.

Import the factory here so callers only need:
    from agent.providers import get_provider
"""

from agent.providers.base import AIProvider
from agent.providers.openai_provider import OpenAIProvider
from agent.providers.ollama_provider import OllamaProvider


def get_provider(name: str) -> AIProvider:
    """
    Factory that returns the correct AIProvider instance.

    Parameters
    ----------
    name : str
        "openai" or "ollama" (case-insensitive).

    Raises
    ------
    ValueError
        If an unknown provider name is given.
    """
    match name.lower():
        case "openai":
            return OpenAIProvider()
        case "ollama":
            return OllamaProvider()
        case _:
            raise ValueError(
                f"Unknown provider '{name}'. "
                "Valid options are: 'openai', 'ollama'."
            )


__all__ = ["AIProvider", "OpenAIProvider", "OllamaProvider", "get_provider"]