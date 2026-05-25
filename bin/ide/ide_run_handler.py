# -*- coding: utf-8 -*-
"""
ide_run_handler.py — Execute SPL queries for the IDE view.

Reuses query_executor and spl_analyzer but does NOT validate results.
The user may legitimately want 0 results.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from handler_utils import get_username

logger = get_logger(__name__)

MAX_IDE_RESULT_ROWS = 1000


def _serialize_analysis(analysis):
    # type: (Any) -> Dict[str, Any]
    """Convert SplAnalysis dataclass to camelCase dict."""
    return {
        "unauthorizedCommands": analysis.unauthorized_commands,
        "unusualCommands": analysis.unusual_commands,
        "uniqLimitations": analysis.uniq_limitations,
        "commandsUsed": analysis.commands_used,
        "warnings": analysis.warnings,
    }


EMPTY_SPL_ANALYSIS = {
    "unauthorizedCommands": [],
    "unusualCommands": [],
    "uniqLimitations": None,
    "commandsUsed": [],
    "warnings": [],
}  # type: Dict[str, Any]


class IdeRunHandler:
    """Handle IDE query execution requests."""

    def __init__(self, session_key, request):
        # type: (str, Dict[str, Any]) -> None
        """Initialise with session key and full request for user extraction."""
        self._session_key = session_key
        self._username = get_username(request)

    def handle(self, method, payload):
        # type: (str, Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        """Dispatch by HTTP method. Only POST is accepted."""
        if method != "POST":
            return {"error": "Method not allowed"}, 405
        return self._run(payload)

    def _run(self, payload):
        # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        """Execute the IDE query and return results."""
        app = (payload.get("app") or "").strip()
        query = (payload.get("query") or "").strip()

        if not app:
            return {"error": "Missing required field: app"}, 400
        if not query:
            return {"error": "Missing required field: query"}, 400

        time_range = payload.get("timeRange") or {}
        earliest = str(time_range.get("earliest", "0"))
        latest = str(time_range.get("latest", "now"))

        logger.info(
            "IDE run by user=%s app=%s query=%.120s",
            self._username, app, query,
        )

        allow_blocked = bool(payload.get("allowBlocked", False))

        # --- SPL analysis ---
        analysis = EMPTY_SPL_ANALYSIS
        try:
            from spl.spl_analyzer import analyze as analyze_spl
            from spl.preflight import get_blocked_commands_set

            blocked = get_blocked_commands_set(self._session_key)
            spl_analysis = analyze_spl(query, blocked_commands=blocked)
            analysis = _serialize_analysis(spl_analysis)

            if spl_analysis.unauthorized_commands:
                # Always hard-block 'delete' — it permanently removes data
                hard_blocked = [c for c in spl_analysis.unauthorized_commands
                                if c.lower() == "delete"]
                if hard_blocked:
                    msg = "Blocked command: {0}".format(", ".join(hard_blocked))
                    return self._error_response(msg, analysis), 403
                # Other blocked commands: allow if user confirmed
                if not allow_blocked:
                    msg = "Blocked commands detected: {0}".format(
                        ", ".join(spl_analysis.unauthorized_commands),
                    )
                    return self._error_response(msg, analysis), 403
                logger.info("User confirmed blocked commands: %s",
                            ", ".join(spl_analysis.unauthorized_commands))
        except Exception as exc:
            logger.warning("SPL analysis failed: %s", exc)

        # --- Execute query ---
        start_ms = int(time.time() * 1000)
        try:
            from spl.query_executor import QueryExecutor

            executor = QueryExecutor(self._session_key)
            rows = executor.run(
                spl=query,
                app=app,
                earliest_time=earliest,
                latest_time=latest,
            )
            duration_ms = int(time.time() * 1000) - start_ms

            # Cap result rows
            capped = rows[:MAX_IDE_RESULT_ROWS]  # type: List[Dict[str, Any]]
            warnings = analysis.get("warnings", [])  # type: List[Dict[str, Any]]
            if len(rows) > MAX_IDE_RESULT_ROWS:
                warnings = list(warnings) + [{
                    "message": "Results capped at {0} rows ({1} total).".format(
                        MAX_IDE_RESULT_ROWS, len(rows),
                    ),
                    "severity": "warning",
                }]

            # AI results analysis (best-effort)
            ai_notes = []  # type: List[Dict[str, Any]]
            try:
                from ide.ai_results_analyzer import AiResultsAnalyzer
                analyzer = AiResultsAnalyzer(self._session_key)
                sample = capped[:10]
                prior = payload.get("priorAnalysis", [])
                user_ctx = (payload.get("userContext") or "").strip()
                ai_notes = analyzer.analyze(
                    query, app, len(rows), sample, user_ctx, prior,
                )
            except Exception:
                logger.warning("AI results analysis failed", exc_info=True)

            return {
                "status": "success",
                "resultCount": len(rows),
                "executionTimeMs": duration_ms,
                "resultRows": capped,
                "splAnalysis": analysis,
                "aiNotes": ai_notes,
                "warnings": warnings,
                "errors": [],
            }, 200

        except RuntimeError as exc:
            duration_ms = int(time.time() * 1000) - start_ms
            logger.warning(
                "IDE query execution failed after %d ms: %s",
                duration_ms, exc,
            )
            return self._error_response(str(exc), analysis, duration_ms), 200

        except Exception as exc:
            duration_ms = int(time.time() * 1000) - start_ms
            logger.error(
                "Unexpected IDE query error after %d ms: %s",
                duration_ms, exc, exc_info=True,
            )
            return self._error_response(str(exc), analysis, duration_ms), 200

    @staticmethod
    def _error_response(message, analysis=None, duration_ms=0):
        # type: (str, Optional[Dict[str, Any]], int) -> Dict[str, Any]
        """Build a standard IDE error response."""
        return {
            "status": "error",
            "message": message,
            "resultCount": 0,
            "executionTimeMs": duration_ms,
            "resultRows": [],
            "splAnalysis": analysis or EMPTY_SPL_ANALYSIS,
            "aiNotes": [],
            "warnings": [],
            "errors": [{
                "code": "EXECUTION_ERROR",
                "message": message,
                "severity": "error",
            }],
        }
