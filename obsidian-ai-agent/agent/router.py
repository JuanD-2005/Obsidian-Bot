"""
agent/router.py
---------------
Intelligent template router.

Given raw user text, decides which template to use and where to save the note.

Strategy — two-stage hybrid classifier
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Stage 1 — Local keyword matching (zero latency, deterministic)
    Scan the user's text for keywords defined in routing_map.json.
    If one template scores clearly above the rest (gap ≥ MIN_CONFIDENCE_GAP),
    return it immediately without touching the network.

Stage 2 — LLM classification (fallback, only when local is ambiguous)
    Build a tightly-constrained prompt that forces the model to return a
    single JSON object: {"template": "<stem>", "reason": "<one sentence>"}.
    Parse the response, validate the chosen template exists, and return.

Public API
----------
    route(raw_text: str) -> RouteResult
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ollama
from ollama import ResponseError

from agent.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAP_PATH = Path(__file__).parent.parent / "routing_map.json"

# Minimum score difference between best and second-best for local match
# to be considered "confident enough" to skip the LLM call.
MIN_CONFIDENCE_GAP = 2


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteResult:
    """Everything the pipeline needs to process a note."""
    template_name: str       # exact stem as it appears in routing_map.json
    destination: Path        # absolute path: vault_root / mapped_destination
    matched_by: str          # "keyword" | "llm" — useful for debugging / logs


# ---------------------------------------------------------------------------
# Map loading
# ---------------------------------------------------------------------------

def _load_map() -> dict[str, Any]:
    """Load and return the parsed routing_map.json."""
    if not _MAP_PATH.exists():
        raise FileNotFoundError(
            f"routing_map.json not found at {_MAP_PATH}.\n"
            "Create it or restore it from the project root."
        )
    return json.loads(_MAP_PATH.read_text(encoding="utf-8"))


def get_template_names() -> list[str]:
    """Return the list of template stems defined in routing_map.json."""
    data = _load_map()
    return list(data["templates"].keys())


# ---------------------------------------------------------------------------
# Stage 1 — keyword matching
# ---------------------------------------------------------------------------

def _keyword_score(text: str, keywords: list[str]) -> int:
    """
    Count how many keywords from the list appear in the lowercased text.
    Whole-word matching to avoid 'bug' matching 'debugging' accidentally.
    """
    text_lower = text.lower()
    score = 0
    for kw in keywords:
        # Use word-boundary matching for single-word keywords;
        # substring match for multi-word phrases.
        if " " in kw:
            if kw.lower() in text_lower:
                score += 1
        else:
            pattern = rf"\b{re.escape(kw.lower())}\b"
            if re.search(pattern, text_lower):
                score += 1
    return score


def _local_classify(raw_text: str, templates_data: dict[str, Any]) -> tuple[str, int] | None:
    """
    Return (template_name, score) if one template wins with enough confidence,
    or None if the result is too ambiguous.
    """
    scores: list[tuple[str, int]] = []
    for name, meta in templates_data.items():
        score = _keyword_score(raw_text, meta.get("keywords", []))
        scores.append((name, score))

    scores.sort(key=lambda x: x[1], reverse=True)

    best_name, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0

    if best_score == 0:
        return None  # no keywords matched at all → escalate to LLM

    if (best_score - second_score) >= MIN_CONFIDENCE_GAP:
        return best_name, best_score

    return None  # tie or near-tie → escalate to LLM


# ---------------------------------------------------------------------------
# Stage 2 — LLM classification
# ---------------------------------------------------------------------------

_ROUTER_SYSTEM = """\
You are a routing classifier for an Obsidian note-taking system.
Your ONLY job is to select the most appropriate template for the user's text.

You MUST respond with a single JSON object and nothing else — no prose, no markdown fences.
Format: {"template": "<exact template name from the list>", "reason": "<one sentence>"}
"""


def _llm_classify(raw_text: str, template_names: list[str]) -> str:
    """
    Ask Ollama to pick the best template. Returns the template name string.
    Raises RuntimeError on connectivity or parsing failure.
    """
    names_block = "\n".join(f"- {n}" for n in template_names)
    user_message = (
        f"Available templates:\n{names_block}\n\n"
        f"User text:\n{raw_text.strip()}\n\n"
        "Which template should be used? Respond ONLY with the JSON object."
    )

    client = ollama.Client(host=settings.ollama_host)

    try:
        response = client.chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user",   "content": user_message},
            ],
            format="json",        # Ollama structured output — forces JSON mode
            options={
                "temperature": 0.0,   # fully deterministic for classification
                "num_predict": 128,   # we only need a tiny JSON blob
            },
        )
    except ResponseError as exc:
        raise RuntimeError(
            f"Ollama routing error (model='{settings.ollama_model}'): {exc.error}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {settings.ollama_host}.\n"
            f"Is 'ollama serve' running?\nDetail: {exc}"
        ) from exc

    raw_json = response.message.content or ""
    return _parse_llm_response(raw_json, template_names)


def _parse_llm_response(raw_json: str, valid_names: list[str]) -> str:
    """
    Parse and validate the LLM's JSON response.
    Falls back to the first template rather than crashing on bad JSON.
    """
    # Strip accidental code fences
    clean = raw_json.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(clean)
        chosen = parsed.get("template", "").strip()
    except json.JSONDecodeError:
        # LLM ignored the format instruction — try to extract any matching name
        for name in valid_names:
            if name.lower() in raw_json.lower():
                return name
        # Last resort: default to first template
        return valid_names[0]

    # Exact match
    if chosen in valid_names:
        return chosen

    # Case-insensitive fallback
    chosen_lower = chosen.lower()
    for name in valid_names:
        if name.lower() == chosen_lower:
            return name

    # Partial match (model may have shortened the name)
    for name in valid_names:
        if chosen_lower in name.lower() or name.lower() in chosen_lower:
            return name

    # Couldn't validate — default to first
    return valid_names[0]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def route(raw_text: str) -> RouteResult:
    """
    Classify *raw_text* and return a RouteResult with template + destination.

    Parameters
    ----------
    raw_text : str
        The unstructured text the user wants to convert into a note.

    Returns
    -------
    RouteResult

    Raises
    ------
    RuntimeError
        If Ollama is unreachable and local classification also failed.
    FileNotFoundError
        If routing_map.json is missing.
    """
    data = _load_map()
    templates_data: dict[str, Any] = data["templates"]
    template_names = list(templates_data.keys())

    # Stage 1 — try local keyword matching first
    local_result = _local_classify(raw_text, templates_data)

    if local_result is not None:
        chosen_name = local_result[0]
        matched_by = "keyword"
    else:
        # Stage 2 — escalate to LLM
        chosen_name = _llm_classify(raw_text, template_names)
        matched_by = "llm"

    # Resolve absolute destination path
    dest_relative = templates_data[chosen_name]["destination"]
    destination = settings.obsidian_vault_path / dest_relative
    destination.mkdir(parents=True, exist_ok=True)

    return RouteResult(
        template_name=chosen_name,
        destination=destination,
        matched_by=matched_by,
    )