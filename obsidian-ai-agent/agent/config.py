"""
config.py
---------
Single source of truth for all runtime settings.

Pydantic-settings reads values in this priority order:
  1. Environment variables (exported in the shell)
  2. Variables declared in a .env file
  3. Default values defined below

Usage anywhere in the project:
    from agent.config import settings
    print(settings.vault_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look for a .env file starting from the project root
        env_file=".env",
        env_file_encoding="utf-8",
        # Ignore extra keys that might exist in .env
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Vault / filesystem
    # ------------------------------------------------------------------
    obsidian_vault_path: Path = Path.home() / "ObsidianVault"
    templates_path: Path | None = None   # defaults to <vault>/Templates
    output_path: Path | None = None      # defaults to <vault>/Generated

    # ------------------------------------------------------------------
    # AI provider selection
    # ------------------------------------------------------------------
    default_ai_provider: Literal["openai", "ollama"] = "ollama"

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("obsidian_vault_path", mode="before")
    @classmethod
    def _expand_vault(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    @model_validator(mode="after")
    def _set_derived_paths(self) -> "Settings":
        """Fill in template/output paths that depend on the vault path."""
        if self.templates_path is None:
            self.templates_path = self.obsidian_vault_path / "Templates"
        else:
            self.templates_path = Path(self.templates_path).expanduser().resolve()

        if self.output_path is None:
            self.output_path = self.obsidian_vault_path / "Generated"
        else:
            self.output_path = Path(self.output_path).expanduser().resolve()

        return self

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def assert_paths_exist(self) -> None:
        """
        Raise RuntimeError if critical directories don't exist.
        Called at command runtime, not at import time, so tests can
        construct Settings freely without a real vault on disk.
        """
        missing = [
            p for p in (self.obsidian_vault_path, self.templates_path)
            if not p.exists()  # type: ignore[union-attr]
        ]
        if missing:
            raise RuntimeError(
                "The following configured paths do not exist:\n"
                + "\n".join(f"  {p}" for p in missing)
                + "\nCheck your .env file or create the directories first."
            )

        # Output dir is created on demand — make it now if absent
        self.output_path.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere.
# ---------------------------------------------------------------------------
settings = Settings()