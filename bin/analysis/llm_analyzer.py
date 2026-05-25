# -*- coding: utf-8 -*-
"""
llm_analyzer.py — LLM-powered SPL analysis.

Sends the query + user context to the configured LLM endpoint for deeper
analysis. Returns [] gracefully if LLM is not configured or fails.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from logger import get_logger

logger = get_logger(__name__)

ANALYSIS_SYSTEM_PROMPT = (
    "You are a Splunk SPL analyzer. Analyze this query for: field name typos "
    "compared to common Splunk field names, unused available fields, optimization "
    "opportunities, and best practice violations.\n"
    "Common Splunk fields: _time, _raw, source, sourcetype, host, index, _indextime, "
    "linecount, splunk_server. CIM fields: action, app, dest, dest_ip, dest_port, "
    "dvc, src, src_ip, src_port, status, user, vendor_product.\n"
    "Key notes: stats removes raw events (use eventstats to keep them), "
    "transaction needs maxspan to avoid runaway grouping, "
    "values() produces multi-valued fields (use mvjoin to flatten).\n"
    "The user describes their intent: {user_context}. "
    "Return ONLY a JSON array of objects with: "
    'severity (error/warning/info), '
    'category (typo/unused_field/optimization/best_practice/syntax_warning), '
    'message (human-readable), line (number or null), suggestion (string or null). '
    "No explanation. No markdown. JSON array only."
)


class LlmSplAnalyzer:
    """LLM-powered SPL analyzer. Returns [] if not configured."""

    def analyze(self, spl, app, user_context, session_key):
        # type: (str, str, str, str) -> List[Dict[str, Any]]
        """Run LLM analysis on the SPL query.

        Returns a list of note dicts, or [] on any failure.
        """
        try:
            llm_cfg = self._get_llm_config(session_key)
        except ValueError:
            logger.info("LLM not configured — skipping AI analysis.")
            return []

        context = user_context.strip() if user_context else "No specific intent provided."
        system_prompt = ANALYSIS_SYSTEM_PROMPT.format(user_context=context)
        user_message = "App: {0}\n\nSPL:\n{1}".format(app, spl)

        try:
            from handlers.llm_proxy_handler import _call_llm
            raw = _call_llm(llm_cfg, system_prompt, user_message)
            return self._parse_response(raw)
        except Exception as exc:
            logger.warning("LLM analysis failed: %s", exc)
            return []

    def _get_llm_config(self, session_key):
        # type: (str) -> Dict[str, Any]
        """Load LLM config from runtime settings. Raises ValueError if not configured."""
        from runtime_config import get_runtime_config
        cfg = get_runtime_config(session_key)

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

    def _parse_response(self, raw):
        # type: (str) -> List[Dict[str, Any]]
        """Parse LLM response into a list of note dicts."""
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
                "category": str(item.get("category", "best_practice")),
                "message": str(item.get("message", "")),
                "line": item.get("line"),
                "suggestion": item.get("suggestion"),
            })
        return result
