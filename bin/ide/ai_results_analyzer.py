# -*- coding: utf-8 -*-
"""
ai_results_analyzer.py — Post-execution AI analysis of query results.

Sends SPL + result summary to the LLM for contextual insights.
Returns [] gracefully if LLM is not configured or fails.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from logger import get_logger

logger = get_logger(__name__)

MAX_SAMPLE_ROWS = 10

RESULTS_SYSTEM_PROMPT = (
    "You are a Splunk query results analyst. Given an SPL query, its results "
    "summary, and optionally prior analysis notes and user context, provide "
    "brief actionable notes. Focus on: result patterns, data quality issues, "
    "optimization suggestions, and anything unexpected. "
    "Return ONLY a JSON array of objects with: "
    "severity (error/warning/info), "
    "category (results_insight/optimization/data_quality/best_practice), "
    "message (string), suggestion (string or null). "
    "No explanation. No markdown. JSON array only."
)


class AiResultsAnalyzer:
    """Analyze query results via LLM. Returns [] if not configured."""

    def __init__(self, session_key):
        # type: (str) -> None
        self._session_key = session_key

    def analyze(self, spl, app, result_count, sample_rows, user_context, prior_analysis):
        # type: (str, str, int, List[Dict[str, Any]], str, List[Dict[str, Any]]) -> List[Dict[str, Any]]
        """Run LLM analysis on query results. Returns [] on any failure."""
        try:
            llm_cfg = self._get_llm_config()
        except ValueError:
            logger.info("LLM not configured — skipping AI results analysis.")
            return []

        user_message = self._build_user_message(
            spl, app, result_count, sample_rows, user_context, prior_analysis,
        )

        try:
            from handlers.llm_proxy_handler import _call_llm
            raw = _call_llm(llm_cfg, RESULTS_SYSTEM_PROMPT, user_message)
            return self._parse_response(raw)
        except Exception as exc:
            logger.warning("AI results analysis failed: %s", exc)
            return []

    def _get_llm_config(self):
        # type: () -> Dict[str, Any]
        """Load LLM config from runtime settings. Raises ValueError if not configured."""
        from runtime_config import get_runtime_config
        cfg = get_runtime_config(self._session_key)

        endpoint = str(cfg.get("llm_endpoint") or "").strip()
        if not endpoint:
            raise ValueError("LLM endpoint not configured.")

        api_key = str(cfg.get("llm_api_key") or "").strip()
        if not api_key:
            raise ValueError("LLM API key not configured.")

        return {
            "endpoint": endpoint,
            "model": str(cfg.get("llm_model") or "gpt-4o-mini").strip(),
            "max_tokens": int(cfg.get("llm_max_tokens") or 1024),
            "api_key": api_key,
        }

    @staticmethod
    def _build_user_message(spl, app, result_count, sample_rows, user_context, prior_analysis):
        # type: (str, str, int, List[Dict[str, Any]], str, List[Dict[str, Any]]) -> str
        """Build the user message for the LLM call."""
        parts = [
            "App: {0}".format(app),
            "",
            "SPL:\n{0}".format(spl),
            "",
            "Result count: {0}".format(result_count),
        ]

        if sample_rows:
            sample = sample_rows[:MAX_SAMPLE_ROWS]
            parts.append("")
            parts.append("Sample rows (first {0}):".format(len(sample)))
            parts.append(json.dumps(sample, default=str))

        if user_context and user_context.strip():
            parts.append("")
            parts.append("User context: {0}".format(user_context.strip()))

        if prior_analysis:
            parts.append("")
            parts.append("Prior analysis notes:")
            for note in prior_analysis[:20]:
                msg = note.get("message", "") if isinstance(note, dict) else str(note)
                parts.append("- {0}".format(msg))

        return "\n".join(parts)

    @staticmethod
    def _parse_response(raw):
        # type: (str) -> List[Dict[str, Any]]
        """Parse LLM response JSON array into note dicts."""
        text = raw.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            first_nl = text.find("\n")
            last_fence = text.rfind("```")
            if first_nl != -1 and last_fence > first_nl:
                text = text[first_nl + 1:last_fence].strip()

        notes_raw = json.loads(text)
        if not isinstance(notes_raw, list):
            logger.warning("LLM returned non-array: %s", type(notes_raw).__name__)
            return []

        result = []  # type: List[Dict[str, Any]]
        for item in notes_raw:
            if not isinstance(item, dict):
                continue
            result.append({
                "id": str(uuid.uuid4()),
                "severity": str(item.get("severity", "info")),
                "category": str(item.get("category", "results_insight")),
                "message": str(item.get("message", "")),
                "suggestion": item.get("suggestion"),
            })
        return result
