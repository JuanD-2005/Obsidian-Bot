"""
main.py
-------
Obsidian AI Agent — CLI entrypoint.

Entry points:
    obsidian-agent --help
    obsidian-agent create -t "Project" -d "Fix auth bug"
    obsidian-agent create -t "Project" --interactive
    echo "Fix auth bug" | obsidian-agent create -t "Project"
"""

from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from agent.config import settings
from agent import file_manager
from agent.input_modes import resolve_data
from agent.providers import get_provider

# ---------------------------------------------------------------------------
# App + shared consoles
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="obsidian-agent",
    help="Autonomous knowledge management assistant for Obsidian vaults.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True, style="bold red")


# ---------------------------------------------------------------------------
# Reusable option types
# ---------------------------------------------------------------------------

TemplateArg = Annotated[
    str,
    typer.Option(
        "--template", "-t",
        help="Template name (filename without .md extension).",
        show_default=False,
    ),
]

# --data is now Optional — can be replaced by --interactive or stdin
DataArg = Annotated[
    Optional[str],
    typer.Option(
        "--data", "-d",
        help=(
            "Raw input to structure into the note. "
            "Omit to use --interactive or stdin."
        ),
        show_default=False,
    ),
]

InteractiveArg = Annotated[
    bool,
    typer.Option(
        "--interactive", "-i",
        help="Open a multiline editor to enter the note data interactively.",
        is_flag=True,
    ),
]

ProviderArg = Annotated[
    Optional[str],
    typer.Option(
        "--provider", "-p",
        help="'openai' or 'ollama'. Overrides DEFAULT_AI_PROVIDER in .env.",
    ),
]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def create(
    template: TemplateArg,
    data: DataArg = None,
    interactive: InteractiveArg = False,
    provider: ProviderArg = None,
) -> None:
    """
    Generate a new Obsidian note from a template and raw input data.

    \b
    Input modes (pick one):
        --data/-d    Inline string on the command line.
        --interactive/-i  Opens a multiline editor in the terminal.
        stdin        Pipe text in: echo "…" | obsidian-agent create -t X

    \b
    Examples:
        obsidian-agent create -t "Project" -d "Fix auth bug on the backend"
        obsidian-agent create -t "Meeting" -i
        echo "Onboarding call with Alice" | obsidian-agent create -t "Meeting"
        obsidian-agent create -t "Project" -d "Deploy infra" -p openai
    """
    resolved_provider = provider or settings.default_ai_provider

    console.print(
        Panel.fit(
            f"[bold cyan]Obsidian AI Agent[/bold cyan]\n"
            f"Template : [green]{template}[/green]\n"
            f"Provider : [yellow]{resolved_provider}[/yellow]",
            border_style="cyan",
        )
    )

    # Validate paths before doing any I/O
    try:
        settings.assert_paths_exist()
    except RuntimeError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 1 — Resolve input data (inline / interactive / stdin)
    # ------------------------------------------------------------------
    raw_data = resolve_data(data, interactive, console)

    # ------------------------------------------------------------------
    # Step 2 — Load template
    # ------------------------------------------------------------------
    console.print(f"[dim]Reading template '[cyan]{template}[/cyan]'…[/dim]")
    try:
        template_content = file_manager.read_template(template)
    except FileNotFoundError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 3 — Generate with LLM
    # ------------------------------------------------------------------
    console.print(f"[dim]Calling [yellow]{resolved_provider}[/yellow]…[/dim]")
    try:
        llm = get_provider(resolved_provider)
        generated_md = llm.generate(template_content, raw_data)
    except (ValueError, RuntimeError) as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 4 — Write to vault
    # ------------------------------------------------------------------
    try:
        output_path = file_manager.write_note(generated_md, topic=template)
    except OSError as exc:
        err_console.print(f"Could not write output file: {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"\n[bold green]✔ Note created:[/bold green] [cyan]{output_path}[/cyan]"
    )


@app.command()
def list_templates() -> None:
    """List all available Markdown templates in the configured Templates folder."""
    try:
        settings.assert_paths_exist()
    except RuntimeError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    templates = sorted(settings.templates_path.glob("*.md"))  # type: ignore[union-attr]

    if not templates:
        console.print("[yellow]No templates found in:[/yellow]", settings.templates_path)
        return

    console.print(f"[bold]Templates in[/bold] [cyan]{settings.templates_path}[/cyan]:\n")
    for tmpl in templates:
        console.print(f"  • [green]{tmpl.stem}[/green]")


@app.command()
def config_info() -> None:
    """Print the active configuration (useful for debugging .env setup)."""
    console.print(Panel.fit(
        f"[bold]Active configuration[/bold]\n\n"
        f"Vault path      : {settings.obsidian_vault_path}\n"
        f"Templates path  : {settings.templates_path}\n"
        f"Output path     : {settings.output_path}\n"
        f"Default provider: {settings.default_ai_provider}\n"
        f"OpenAI model    : {settings.openai_model}\n"
        f"Ollama host     : {settings.ollama_host}\n"
        f"Ollama model    : {settings.ollama_model}",
        border_style="blue",
    ))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()