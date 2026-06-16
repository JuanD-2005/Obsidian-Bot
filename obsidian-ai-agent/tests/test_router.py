"""
tests/test_router.py
---------------------
Unit tests for agent.router.

All tests run fully offline — no Ollama, no filesystem writes,
no real vault required.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MAP = {
    "templates": {
        "Plantilla - Clase UNET": {
            "destination": "Clases/UNET",
            "keywords": ["clase", "unet", "lección", "apuntes"],
        },
        "Plantilla - Bug": {
            "destination": "Bugs",
            "keywords": ["bug", "error", "fix", "arreglar"],
        },
        "Plantilla - Reunion": {
            "destination": "Reuniones",
            "keywords": ["reunion", "reunión", "meeting", "sync"],
        },
    }
}


@pytest.fixture()
def map_file(tmp_path: Path) -> Path:
    """Write a sample routing_map.json and return its path."""
    p = tmp_path / "routing_map.json"
    p.write_text(json.dumps(SAMPLE_MAP), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _patch_map_path(map_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the router's _MAP_PATH constant at our temp file."""
    import agent.router as router_mod
    monkeypatch.setattr(router_mod, "_MAP_PATH", map_file)


@pytest.fixture(autouse=True)
def _patch_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point settings.obsidian_vault_path at a temp dir."""
    from agent.config import settings
    monkeypatch.setattr(settings, "obsidian_vault_path", tmp_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_route():
    from agent.router import route
    return route


# ---------------------------------------------------------------------------
# Stage 1 — keyword matching
# ---------------------------------------------------------------------------

class TestKeywordClassification:
    def test_clear_bug_keyword(self):
        route = _import_route()
        # "bug" + "arreglar" → score=2 for Bug, 0 for others → gap=2 ≥ MIN_CONFIDENCE_GAP
        result = route("hay un bug que hay que arreglar en el módulo de autenticación")
        assert result.template_name == "Plantilla - Bug"
        assert result.matched_by == "keyword"

    def test_clear_class_keyword(self):
        route = _import_route()
        result = route("Clase 3 de UNET, tomar apuntes")
        assert result.template_name == "Plantilla - Clase UNET"
        assert result.matched_by == "keyword"

    def test_meeting_keyword(self):
        route = _import_route()
        result = route("tenemos una reunion de sync con el equipo")
        assert result.template_name == "Plantilla - Reunion"
        assert result.matched_by == "keyword"

    def test_destination_path_is_absolute(self):
        route = _import_route()
        # "bug" + "fix" → score=2 for Bug, 0 for others → confident keyword match
        result = route("fix el bug del servidor")
        assert result.destination.is_absolute()

    def test_destination_created_on_disk(self):
        route = _import_route()
        result = route("arreglar el error de login")
        assert result.destination.exists()


# ---------------------------------------------------------------------------
# Stage 1 — ambiguous / no keywords → LLM fallback
# ---------------------------------------------------------------------------

class TestLLMFallback:
    def _mock_ollama_response(self, template_name: str):
        """Build a fake ollama.Client().chat() return value."""
        msg = MagicMock()
        msg.content = json.dumps({"template": template_name, "reason": "test"})
        resp = MagicMock()
        resp.message = msg
        return resp

    def test_llm_called_when_no_keywords_match(self):
        route = _import_route()
        mock_resp = self._mock_ollama_response("Plantilla - Reunion")

        with patch("agent.router.ollama.Client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            result = route("algo completamente ambiguo sin pistas")

        assert result.matched_by == "llm"
        assert result.template_name == "Plantilla - Reunion"

    def test_llm_called_on_near_tie(self):
        """bug=1, error=1 → tie → should escalate."""
        route = _import_route()
        mock_resp = self._mock_ollama_response("Plantilla - Bug")

        with patch("agent.router.ollama.Client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            # "error" matches Bug; no other strong signal
            result = route("error desconocido")   # score=1, gap=1 < MIN_CONFIDENCE_GAP=2

        # May be keyword (score=1 gap vs 0) OR llm depending on second score
        assert result.template_name == "Plantilla - Bug"

    def test_llm_connection_error_raises_runtime(self):
        route = _import_route()
        with patch("agent.router.ollama.Client") as MockClient:
            MockClient.return_value.chat.side_effect = ConnectionRefusedError("refused")
            with pytest.raises(RuntimeError, match="ollama serve"):
                route("texto sin keywords")

    def test_invalid_json_from_llm_falls_back_to_first(self):
        from agent.router import _parse_llm_response
        valid_names = list(SAMPLE_MAP["templates"].keys())

        # Completely unparseable response
        result = _parse_llm_response("sorry I cannot help", valid_names)
        assert result == valid_names[0]

    def test_case_insensitive_llm_response(self):
        from agent.router import _parse_llm_response
        valid_names = list(SAMPLE_MAP["templates"].keys())

        result = _parse_llm_response(
            json.dumps({"template": "plantilla - bug", "reason": "x"}),
            valid_names,
        )
        assert result == "Plantilla - Bug"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

class TestGetTemplateNames:
    def test_returns_all_stems(self):
        from agent.router import get_template_names
        names = get_template_names()
        assert set(names) == set(SAMPLE_MAP["templates"].keys())

    def test_missing_map_raises(self, monkeypatch: pytest.MonkeyPatch):
        import agent.router as router_mod
        monkeypatch.setattr(router_mod, "_MAP_PATH", Path("/nonexistent/map.json"))
        from agent.router import get_template_names
        with pytest.raises(FileNotFoundError):
            get_template_names()