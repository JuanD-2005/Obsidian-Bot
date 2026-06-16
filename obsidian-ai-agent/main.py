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
            f"[bold cyan]Obsidian AI Agent[/bold cyan]\n\n"
            f"  [bold]Template :[/bold] [green]{template}[/green]\n"
            f"  [bold]Provider :[/bold] [yellow]{resolved_provider.title()}[/yellow]",
            border_style="cyan",
            title="[bold cyan]Initialization[/bold cyan]",
        )
    )

    # Validate paths before doing any I/O
    try:
        settings.assert_paths_exist()
    except RuntimeError as exc:
        err_console.print(
            Panel(
                f"[bold red]Configuration Error:[/bold red] {exc}",
                border_style="red",
                title="Error",
                title_align="left",
            )
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 1 — Resolve input data (inline / interactive / stdin)
    # ------------------------------------------------------------------
    raw_data = resolve_data(data, interactive, console)

    # ------------------------------------------------------------------
    # Step 2 — Load template
    # ------------------------------------------------------------------
    console.print(f"[dim]Reading template '[cyan]{template}[/cyan]'...[/dim]")
    try:
        template_content = file_manager.read_template(template)
    except FileNotFoundError as exc:
        err_console.print(
            Panel(
                f"[bold red]Template Error:[/bold red] {exc}",
                border_style="red",
                title="Error",
                title_align="left",
            )
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 3 — Generate with LLM
    # ------------------------------------------------------------------
    try:
        llm = get_provider(resolved_provider)
        with console.status(
            f"[bold status.spinner]Procesando con {resolved_provider.title()}...[/bold status.spinner]",
            spinner="dots",
        ):
            generated_md = llm.generate(template_content, raw_data)
    except (ValueError, RuntimeError) as exc:
        err_console.print(
            Panel(
                f"[bold red]AI Provider Error ({resolved_provider.title()}):[/bold red] {exc}",
                border_style="red",
                title="Error",
                title_align="left",
            )
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 4 — Write to vault
    # ------------------------------------------------------------------
    try:
        output_path = file_manager.write_note(generated_md, topic=template)
    except OSError as exc:
        err_console.print(
            Panel(
                f"[bold red]File System Error:[/bold red] {exc}",
                border_style="red",
                title="Error",
                title_align="left",
            )
        )
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold green]✔ Note successfully created![/bold green]\n\n"
            f"  [bold]File Path:[/bold]  [cyan]{output_path}[/cyan]\n"
            f"  [bold]Template:[/bold]   [yellow]{template}[/yellow]\n"
            f"  [bold]Provider:[/bold]   [magenta]{resolved_provider.title()}[/magenta]",
            title="[bold green]Success[/bold green]",
            border_style="green",
            expand=False,
        )
    )


@app.command()
def list_templates() -> None:
    """List all available Markdown templates in the configured Templates folder."""
    try:
        settings.assert_paths_exist()
    except RuntimeError as exc:
        err_console.print(
            Panel(
                f"[bold red]Configuration Error:[/bold red] {exc}",
                border_style="red",
                title="Error",
                title_align="left",
            )
        )
        raise typer.Exit(code=1)

    templates = sorted(settings.templates_path.glob("*.md"))  # type: ignore[union-attr]

    if not templates:
        console.print(
            Panel(
                f"[yellow]No templates found in directory:[/yellow]\n[cyan]{settings.templates_path}[/cyan]",
                border_style="yellow",
                title="Warning",
                title_align="left",
            )
        )
        return

    template_list = "\n".join(f"  • [green]{tmpl.stem}[/green]" for tmpl in templates)
    console.print(
        Panel(
            f"[bold]Available templates inside vault:[/bold]\n\n{template_list}",
            title=f"[bold cyan]Templates in {settings.templates_path.name}[/bold cyan]",
            border_style="cyan",
            expand=False,
        )
    )


@app.command()
def config_info() -> None:
    """Print the active configuration (useful for debugging .env setup)."""
    console.print(Panel.fit(
        f"[bold cyan]Obsidian AI Agent — Active Configuration[/bold cyan]\n\n"
        f"  [bold]Vault path[/bold]       : [cyan]{settings.obsidian_vault_path}[/cyan]\n"
        f"  [bold]Templates path[/bold]   : [cyan]{settings.templates_path}[/cyan]\n"
        f"  [bold]Output path[/bold]      : [cyan]{settings.output_path}[/cyan]\n"
        f"  [bold]Default provider[/bold] : [yellow]{settings.default_ai_provider}[/yellow]\n"
        f"  [bold]OpenAI model[/bold]     : [magenta]{settings.openai_model}[/magenta]\n"
        f"  [bold]Ollama host[/bold]      : [magenta]{settings.ollama_host}[/magenta]\n"
        f"  [bold]Ollama model[/bold]     : [magenta]{settings.ollama_model}[/magenta]",
        border_style="blue",
        title="[bold blue]Configuration Details[/bold blue]",
    ))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()