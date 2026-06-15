"""
agent/providers/base.py
-----------------------
Abstract contract that every LLM backend must satisfy.

Using typing.Protocol (structural subtyping) instead of ABC so that:
  - providers don't need to explicitly inherit from a base class
  - it's trivial to add a third-party or mock provider in tests
  - runtime isinstance() checks still work via @runtime_checkable
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Prompt construction — shared by all providers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a precise Markdown note generator for an Obsidian knowledge base.

Rules you MUST follow without exception:
1. Return ONLY raw Markdown text — no prose, no greetings, no explanations.
2. Preserve the EXACT structure (headings, sections, YAML front-matter) of
   the template you receive. Do NOT add or remove top-level sections.
3. Fill every placeholder or empty section with concise, relevant content
   derived from the user data.
4. If a section is not relevant to the user data, write a short N/A note
   rather than omitting the heading.
5. Do NOT wrap the output in a code fence (no ```markdown … ```).
6. The output must be valid Obsidian-flavoured Markdown.
"""


def build_user_message(template_content: str, raw_data: str) -> str:
    """
    Compose the user-turn message sent to the model.

    Keeping template and data clearly delimited makes the instruction
    unambiguous regardless of what the user types as raw_data.
    """
    return (
        "## Template\n\n"
        f"{template_content.strip()}\n\n"
        "---\n\n"
        "## User Data\n\n"
        f"{raw_data.strip()}\n\n"
        "---\n\n"
        "Generate the completed Obsidian note now."
    )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class AIProvider(Protocol):
    """
    Structural interface for LLM backends.

    Any class that implements `generate(template_content, raw_data) -> str`
    satisfies this protocol — no explicit inheritance required.
    """

    def generate(self, template_content: str, raw_data: str) -> str:
        """
        Parameters
        ----------
        template_content:
            Full text of the chosen .md template file.
        raw_data:
            The raw user input describing the note's content.

        Returns
        -------
        str
            Raw Markdown string ready to be written to disk.
            Must never include conversational filler or code fences.
        """
        ...