"""
agent/input_modes.py
---------------------
Data-acquisition strategies for the `create` command.

Three ways to get the raw user data into the agent:

  1. --data "…"          Inline string on the command line (original behaviour).
  2. --interactive / -i  Opens a prompt_toolkit editor in the terminal.
                         The user types freely, sends with Alt+Enter (or Esc→Enter),
                         and can abort with Ctrl+C.
  3. stdin pipe          echo "…" | obsidian-agent create -t Project
                         Detected automatically when stdin is not a TTY.

Public surface
--------------
    resolve_data(data, interactive, console) -> str

    Call this once per `create` invocation.  It figures out which mode applies
    and either returns the text or raises typer.Exit(1) on failure.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.rule import Rule


# ---------------------------------------------------------------------------
# Public resolver — single entry point for main.py
# ---------------------------------------------------------------------------

def resolve_data(
    data: str | None,
    interactive: bool,
    console: Console,
) -> str:
    """
    Determine which input mode to use and return the raw data string.

    Priority
    --------
    1. Explicit --data value (fastest path, no extra I/O).
    2. --interactive flag   (opens the prompt_toolkit editor).
    3. stdin is a pipe      (reads until EOF).
    4. Nothing provided     (print usage hint and exit 1).

    Parameters
    ----------
    data:
        Value of the --data CLI option, or None if not passed.
    interactive:
        True when the user passed --interactive / -i.
    console:
        Rich Console used for status messages.

    Returns
    -------
    str
        Non-empty raw data string.
    """
    # Mode 1 — inline --data
    if data is not None:
        stripped = data.strip()
        if not stripped:
            _die("--data value is empty.")
        return stripped

    # Mode 2 — interactive editor
    if interactive:
        return _interactive_editor(console)

    # Mode 3 — stdin pipe  (sys.stdin.isatty() is False when piped)
    if not sys.stdin.isatty():
        return _read_stdin(console)

    # Mode 4 — nothing provided
    _die(
        "No input data supplied.\n\n"
        "Choose one of:\n"
        "  [cyan]--data[/cyan] [dim]'your text here'[/dim]          inline string\n"
        "  [cyan]--interactive[/cyan] [dim](-i)[/dim]               open multiline editor\n"
        "  [cyan]echo 'text' | obsidian-agent create …[/cyan]  pipe via stdin"
    )
    raise AssertionError("unreachable")   # keeps mypy happy after _die


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def _interactive_editor(console: Console) -> str:
    """
    Open a full-featured multiline prompt in the terminal.

    Key bindings
    ------------
    Alt+Enter  (or Esc then Enter)  →  submit
    Ctrl+C / Ctrl+D                 →  abort
    Arrow keys, Home/End            →  cursor movement
    """
    # Lazy import — prompt_toolkit is optional for non-interactive use
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
    except ImportError:
        _die(
            "prompt_toolkit is required for --interactive mode.\n"
            "Install it with:  pip install prompt-toolkit"
        )

    console.print(Rule("[bold cyan]Interactive Input[/bold cyan]"))
    console.print(
        "[dim]Type your note data below. "
        "Press [bold]Alt+Enter[/bold] (or [bold]Esc → Enter[/bold]) to submit, "
        "[bold]Ctrl+C[/bold] to abort.[/dim]\n"
    )

    # Custom key bindings so Enter adds a newline and Alt+Enter submits
    bindings = KeyBindings()

    @bindings.add(Keys.Escape, Keys.ControlJ)   # Esc + Enter (some terminals)
    @bindings.add("escape", "enter")             # Alt+Enter on most terminals
    def _submit(event):                          # noqa: ANN001
        event.current_buffer.validate_and_handle()

    session: PromptSession = PromptSession(
        multiline=True,
        key_bindings=bindings,
        bottom_toolbar=HTML(
            "<b>Alt+Enter</b> submit  "
            "<b>Ctrl+C</b> abort  "
            "<b>↑↓←→</b> navigate"
        ),
    )

    try:
        text: str = session.prompt("  ")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=0)

    text = text.strip()
    if not text:
        _die("No input entered in interactive mode.")

    console.print()   # blank line after the editor block
    return text


def _read_stdin(console: Console) -> str:
    """Read all of stdin (used when the process is part of a pipeline)."""
    console.print("[dim]Reading data from stdin…[/dim]")
    try:
        text = sys.stdin.read().strip()
    except KeyboardInterrupt:
        console.print("\n[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=0)

    if not text:
        _die("stdin was empty — nothing to process.")

    return text


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _die(message: str) -> None:
    """Print an error to stderr and exit with code 1."""
    err = Console(stderr=True)
    err.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=1)