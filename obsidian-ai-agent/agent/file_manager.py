"""
agent/file_manager.py
----------------------
All filesystem I/O for the agent.

Two responsibilities:
  1. Read a named .md template from the configured Templates folder.
  2. Write a generated Markdown string to a new file in the Output folder,
     using a deterministic, collision-safe naming convention.

Naming convention for output files:
    YYYY-MM-DD_<topic-slug>[_N].md

    Where N is appended (starting at 2) only when the base name already
    exists in the output directory — so we never silently overwrite notes.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from agent.config import settings


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_template(name: str) -> str:
    """
    Return the full text of a template file.

    Parameters
    ----------
    name : str
        Template name WITHOUT the .md extension.
        Case-insensitive search is performed so that
        "project" matches "Project.md".

    Returns
    -------
    str
        Raw Markdown content of the template.

    Raises
    ------
    FileNotFoundError
        If no matching template is found.
    """
    templates_dir: Path = settings.templates_path  # type: ignore[assignment]

    # Exact match first (fast path)
    exact = templates_dir / f"{name}.md"
    if exact.is_file():
        return exact.read_text(encoding="utf-8")

    # Case-insensitive fallback
    needle = name.lower()
    for candidate in templates_dir.glob("*.md"):
        if candidate.stem.lower() == needle:
            return candidate.read_text(encoding="utf-8")

    available = ", ".join(p.stem for p in sorted(templates_dir.glob("*.md")))
    raise FileNotFoundError(
        f"Template '{name}.md' not found in {templates_dir}.\n"
        f"Available templates: {available or '(none)'}"
    )


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_note(content: str, topic: str) -> Path:
    """
    Write *content* to a new .md file in the configured output directory.

    Parameters
    ----------
    content : str
        The fully generated Markdown string.
    topic : str
        Used to build the filename slug (e.g. "Project" → "project").

    Returns
    -------
    Path
        Absolute path to the file that was written.
    """
    output_dir: Path = settings.output_path  # type: ignore[assignment]
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = _build_filename(topic)
    output_path = _resolve_unique_path(output_dir, base_name)
    output_path.write_text(content, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """
    Convert arbitrary text to a filesystem-safe lowercase slug.

    "Fix Auth Bug (Backend)" → "fix-auth-bug-backend"
    """
    text = text.lower().strip()
    # Replace whitespace and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)
    # Remove anything that's not alphanumeric or a hyphen
    text = re.sub(r"[^\w-]", "", text)
    # Collapse multiple consecutive hyphens
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _build_filename(topic: str) -> str:
    """Return the base filename (without suffix) for today's note."""
    today = date.today().isoformat()   # "2025-06-15"
    slug = _slugify(topic)
    return f"{today}_{slug}"


def _resolve_unique_path(directory: Path, base_name: str) -> Path:
    """
    Return a Path that does not yet exist in *directory*.

    Strategy:
        first try  → <base_name>.md
        collisions → <base_name>_2.md, <base_name>_3.md, …
    """
    candidate = directory / f"{base_name}.md"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = directory / f"{base_name}_{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1