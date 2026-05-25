# -*- coding: utf-8 -*-
"""
spl_analyzer_service.py — Orchestrates static + LLM SPL analysis.

Merges notes from both analyzers, deduplicates by message text.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from logger import get_logger

logger = get_logger(__name__)


class SplAnalyzerHandler:
    """Handle POST /data/tester/analyze_spl requests."""

    def __init__(self, session_key):
        # type: (str) -> None
        """Initialise with session key for LLM config access."""
        self._session_key = session_key

    def handle(self, method, payload):
        # type: (str, Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        """Dispatch by HTTP method. Only POST is accepted."""
        if method != "POST":
            return {"error": "Method not allowed"}, 405

        spl = str(payload.get("spl") or "").strip()
        app = str(payload.get("app") or "").strip()
        user_context = str(payload.get("userContext") or "").strip()

        if not spl:
            return {"error": "Missing required field: spl"}, 400

        # --- Static analysis (always runs) ---
        static_result = self._run_static(spl, app)
        static_notes = static_result.get("notes", [])
        field_usage = static_result.get("fieldUsage", _empty_field_usage())

        # --- LLM analysis (optional) ---
        llm_notes = self._run_llm(spl, app, user_context)

        # --- Merge and deduplicate ---
        merged = self._merge_notes(static_notes, llm_notes)

        return {
            "notes": merged,
            "fieldUsage": field_usage,
        }, 200

    def _run_static(self, spl, app):
        # type: (str, str) -> Dict[str, Any]
        """Run static analysis. Returns empty result on error."""
        try:
            from analysis.static_analyzer import StaticSplAnalyzer
            return StaticSplAnalyzer().analyze(spl, app)
        except Exception as exc:
            logger.error("Static analysis failed: %s", exc, exc_info=True)
            return {"notes": [], "fieldUsage": _empty_field_usage()}

    def _run_llm(self, spl, app, user_context):
        # type: (str, str, str) -> List[Dict[str, Any]]
        """Run LLM analysis. Returns [] on error or if not configured."""
        try:
            from analysis.llm_analyzer import LlmSplAnalyzer
            return LlmSplAnalyzer().analyze(spl, app, user_context, self._session_key)
        except Exception as exc:
            logger.warning("LLM analysis failed: %s", exc)
            return []

    def _merge_notes(self, static_notes, llm_notes):
        # type: (List[Dict[str, Any]], List[Dict[str, Any]]) -> List[Dict[str, Any]]
        """Merge notes from both sources, deduplicating by message text."""
        seen = set()  # type: set
        merged = []  # type: List[Dict[str, Any]]

        for note in static_notes:
            msg = note.get("message", "")
            if msg not in seen:
                seen.add(msg)
                note["source"] = "static"
                merged.append(note)

        for note in llm_notes:
            msg = note.get("message", "")
            if msg not in seen:
                seen.add(msg)
                note["source"] = "llm"
                merged.append(note)

        return merged


def _empty_field_usage():
    # type: () -> Dict[str, List[str]]
    """Return an empty field usage structure."""
    return {"input": [], "created": [], "available_unused": []}
