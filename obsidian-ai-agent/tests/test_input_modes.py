"""
tests/test_input_modes.py
--------------------------
Unit tests for agent.input_modes.resolve_data().

All tests are fully offline — no vault, no LLM, no filesystem writes.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest
import typer
from rich.console import Console

from agent.input_modes import resolve_data

# A Rich console that swallows output so tests stay quiet
_SILENT = Console(file=io.StringIO())


# ---------------------------------------------------------------------------
# Mode 1 — inline --data
# ---------------------------------------------------------------------------

class TestInlineData:
    def test_returns_data_unchanged(self):
        result = resolve_data(data="Fix the auth bug", interactive=False, console=_SILENT)
        assert result == "Fix the auth bug"

    def test_strips_surrounding_whitespace(self):
        result = resolve_data(data="  spaces  \n", interactive=False, console=_SILENT)
        assert result == "spaces"

    def test_empty_string_exits_1(self):
        with pytest.raises(typer.Exit) as exc_info:
            resolve_data(data="   ", interactive=False, console=_SILENT)
        assert exc_info.value.exit_code == 1

    def test_data_takes_priority_over_interactive_flag(self):
        # Even if --interactive is set, explicit --data wins
        result = resolve_data(data="explicit wins", interactive=True, console=_SILENT)
        assert result == "explicit wins"


# ---------------------------------------------------------------------------
# Mode 2 — interactive editor
# ---------------------------------------------------------------------------

class TestInteractiveMode:
    def test_returns_editor_output(self):
        with patch("agent.input_modes._interactive_editor", return_value="typed text") as mock_editor:
            result = resolve_data(data=None, interactive=True, console=_SILENT)
        mock_editor.assert_called_once_with(_SILENT)
        assert result == "typed text"

    def test_keyboard_interrupt_exits_0(self):
        """
        _interactive_editor re-raises typer.Exit(0) on Ctrl+C.
        resolve_data must not swallow it.
        """
        with patch("agent.input_modes._interactive_editor", side_effect=typer.Exit(code=0)):
            with pytest.raises(typer.Exit) as exc_info:
                resolve_data(data=None, interactive=True, console=_SILENT)
        assert exc_info.value.exit_code == 0


# ---------------------------------------------------------------------------
# Mode 3 — stdin pipe
# ---------------------------------------------------------------------------

class TestStdinMode:
    def _fake_stdin(self, content: str):
        """Return a StringIO that looks like a closed pipe (isatty=False)."""
        buf = io.StringIO(content)
        buf.isatty = lambda: False   # type: ignore[method-assign]
        return buf

    def test_reads_piped_stdin(self):
        fake = self._fake_stdin("piped content\n")
        with patch("sys.stdin", fake):
            result = resolve_data(data=None, interactive=False, console=_SILENT)
        assert result == "piped content"

    def test_strips_stdin_whitespace(self):
        fake = self._fake_stdin("  \n  trimmed  \n  ")
        with patch("sys.stdin", fake):
            result = resolve_data(data=None, interactive=False, console=_SILENT)
        assert result == "trimmed"

    def test_empty_stdin_exits_1(self):
        fake = self._fake_stdin("   \n")
        with patch("sys.stdin", fake):
            with pytest.raises(typer.Exit) as exc_info:
                resolve_data(data=None, interactive=False, console=_SILENT)
        assert exc_info.value.exit_code == 1


# ---------------------------------------------------------------------------
# Mode 4 — nothing provided
# ---------------------------------------------------------------------------

class TestNothingProvided:
    def test_exits_1_when_no_input_and_tty(self):
        """
        When stdin IS a TTY (interactive terminal) and neither --data
        nor --interactive are given, we should exit 1 with a hint.
        """
        tty_stdin = MagicMock()
        tty_stdin.isatty.return_value = True

        with patch("sys.stdin", tty_stdin):
            with pytest.raises(typer.Exit) as exc_info:
                resolve_data(data=None, interactive=False, console=_SILENT)
        assert exc_info.value.exit_code == 1