#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""query_tester.py — Splunk REST entry point for the Query Tester backend."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from splunk.persistconn.application import PersistentServerConnectionApplication

from logger import get_logger
from handler_utils import (
    get_session_key, get_username, json_response, normalize_payload,
)
from core.test_runner import TestRunner

logger = get_logger(__name__)

COLLECTION_RUN_HISTORY = "test_run_history"
ERROR_RESPONSE = {
    "status": "error", "message": "Internal server error.",
    "testName": "", "testType": "", "timestamp": "",
    "totalScenarios": 0, "passedScenarios": 0,
    "errors": [{"code": "INTERNAL_ERROR",
                "message": "Internal server error.", "severity": "error"}],
    "warnings": [],
    "splAnalysis": {"unauthorizedCommands": [], "unusualCommands": [],
                    "uniqLimitations": None, "commandsUsed": []},
    "scenarioResults": [],
}


def _get_cold_config(session_key):
    # type: (str) -> Optional[Dict[str, Any]]
    """Read runtime config once for TestRunner injection. Returns None on error."""
    try:
        from runtime_config import get_runtime_config
        cfg = get_runtime_config(session_key)
        return {
            "hec_host": cfg.get("hec_host"),
            "hec_port": cfg.get("hec_port"),
            "hec_scheme": cfg.get("hec_scheme"),
            "hec_token": cfg.get("hec_token"),
            "hec_ssl_verify": cfg.get("hec_ssl_verify"),
            "hec_timeout": cfg.get("hec_timeout"),
            "temp_index": cfg.get("temp_index"),
            "temp_sourcetype": cfg.get("temp_sourcetype"),
        }
    except Exception:
        return None


def _write_manual_history(session_key, payload, result, duration_ms, username):
    # type: (str, Dict[str, Any], Dict[str, Any], int, str) -> None
    try:
        from kvstore_client import KVStoreClient
        kv = KVStoreClient(session_key)
        record = {
            "id": str(uuid.uuid4()),
            "scheduledTestId": None,
            "testId": payload.get("testId", ""),
            "ranBy": username,
            "ranAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": result.get("status", "error"),
            "durationMs": duration_ms,
            "triggerType": "manual",
            "splSnapshotHash": "",
            "splDriftDetected": False,
            "resultSummary": "Manual run: {0}".format(
                result.get("status", "error"),
            ),
            "scenarioResults": json.dumps([]),
        }
        kv.upsert(COLLECTION_RUN_HISTORY, record["id"], record)
    except Exception as exc:
        logger.warning("Failed to write manual run history: %s", exc)


class QueryTesterHandler(PersistentServerConnectionApplication):
    """Main REST handler. Delegates sub-paths and runs tests."""

    def __init__(self, command_line="", command_arg=""):
        # type: (str, str) -> None
        super().__init__()
        self._current_runner = None  # type: Any

    def handle(self, in_string):
        # type: (str) -> Dict[str, Any]
        try:
            request = json.loads(in_string)
        except Exception:
            return json_response(
                {"status": "error", "message": "Bad request"}, 400,
            )

        rest_path = request.get("rest_path", "")
        if "/config" in rest_path:
            return self._delegate_config(in_string)
        if "/command_policy" in rest_path:
            return self._delegate_command_policy(in_string)
        if "/llm" in rest_path:
            return self._delegate_llm(request)
        if "/bug_report" in rest_path:
            return self._handle_bug_report(request)
        if "/ide_run" in rest_path:
            return self._delegate_ide_run(request)
        if "/analyze_spl" in rest_path:
            return self._delegate_analyze_spl(request)
        if "/chat_skills" in rest_path:
            return self._delegate_chat_skills(request)
        if "/splunk_rest" in rest_path:
            return self._delegate_splunk_rest(request)

        method = request.get("method", "GET").upper()
        if method == "GET":
            return json_response({"status": "ok", "service": "query_tester"})
        if method == "POST":
            return self._handle_post(request)
        if method == "DELETE":
            return self._handle_delete(request)
        return json_response(
            {"status": "error", "message": "Method not allowed"}, 405,
        )

    def _delegate_config(self, in_string):
        # type: (str) -> Dict[str, Any]
        from config_admin.config_handler import ConfigHandler
        return ConfigHandler().handle(in_string)

    def _delegate_command_policy(self, in_string):
        # type: (str) -> Dict[str, Any]
        from handlers.command_policy_handler import CommandPolicyHandler
        return CommandPolicyHandler().handle(in_string)

    def _delegate_llm(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        from handlers.llm_proxy_handler import handle_llm_proxy
        return handle_llm_proxy(request)

    def _delegate_analyze_spl(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """Delegate SPL analysis to the analyzer service."""
        try:
            session_key = get_session_key(request)
            method = request.get("method", "GET").upper()
            payload = normalize_payload(request.get("payload"))
            from analysis.spl_analyzer_service import SplAnalyzerHandler
            handler = SplAnalyzerHandler(session_key)
            result, status_code = handler.handle(method, payload)
            return json_response(result, status_code)
        except ValueError as exc:
            logger.warning("Analyze SPL validation error: %s", exc)
            return json_response({"error": str(exc)}, 400)
        except Exception as exc:
            logger.error("Analyze SPL failed: %s", exc, exc_info=True)
            return json_response(
                {"error": "Analysis error: {0}".format(exc)}, 500,
            )

    def _delegate_ide_run(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """Delegate IDE query execution to the IDE run handler."""
        try:
            session_key = get_session_key(request)
            method = request.get("method", "GET").upper()
            payload = normalize_payload(request.get("payload"))
            from ide.ide_run_handler import IdeRunHandler
            handler = IdeRunHandler(session_key, request)
            result, status_code = handler.handle(method, payload)
            return json_response(result, status_code)
        except ValueError as exc:
            logger.warning("IDE run validation error: %s", exc)
            return json_response({"error": str(exc)}, 400)
        except Exception as exc:
            logger.error("IDE run failed: %s", exc, exc_info=True)
            return json_response(
                {"error": "Internal server error: {0}".format(exc)}, 500,
            )

    def _delegate_chat_skills(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        try:
            session_key = get_session_key(request)
            method = request.get("method", "GET").upper()
            payload = normalize_payload(request.get("payload"))
            from handlers.chat_skills_handler import ChatSkillsHandler
            handler = ChatSkillsHandler(session_key, get_username(request))
            result, status_code = handler.handle(method, payload)
            return json_response(result, status_code)
        except Exception as exc:
            logger.error("Chat skills error: %s", exc, exc_info=True)
            return json_response({"error": str(exc)}, 500)

    def _delegate_splunk_rest(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        from handlers.splunk_rest_proxy_handler import handle_splunk_rest_proxy
        return handle_splunk_rest_proxy(request)

    def _handle_bug_report(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        if request.get("method", "GET").upper() != "POST":
            return json_response({"error": "Method not allowed"}, 405)
        try:
            session_key = get_session_key(request)
            payload = normalize_payload(request.get("payload"))
            description = str(payload.get("description", "")).strip()
            if not description:
                return json_response({"error": "Description is required."}, 400)
            report_type = payload.get("reportType", "bug")
            from alerts.bug_report_handler import send_bug_report
            send_bug_report(session_key, report_type, description,
                            get_username(request), {
                                "reportGeneratedAt": payload.get("reportGeneratedAt", ""),
                                "reportType": report_type, "description": description,
                                "currentTest": payload.get("currentTest"),
                                "allTests": payload.get("allTests"),
                                "testResponse": payload.get("testResponse"),
                            })
            return json_response({"status": "ok", "message": "Report sent."})
        except ValueError as exc:
            logger.warning("Bug report validation error: %s", exc)
            return json_response({"error": str(exc)}, 400)
        except Exception as exc:
            logger.error("Failed to send bug report: %s", exc, exc_info=True)
            return json_response({"error": "Failed to send report: {0}".format(exc)}, 500)

    def _handle_post(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        try:
            session_key = get_session_key(request)
            payload = normalize_payload(request.get("payload"))
            start_ms = int(time.time() * 1000)
            cold_config = _get_cold_config(session_key)
            username = get_username(request)
            test_name = payload.get("testName", "")
            logger.info("Manual test run started by %s: %s", username, test_name)
            runner = TestRunner(session_key, config=cold_config)
            self._current_runner = runner
            result, status_code = runner.run_test(payload)
            duration_ms = int(time.time() * 1000) - start_ms
            run_status = result.get("status", "error")
            logger.info("Manual test run completed: %s, status=%s, duration=%dms, user=%s",
                        test_name, run_status, duration_ms, username)
            _write_manual_history(
                session_key, payload, result, duration_ms, username,
            )
            return json_response(result, status_code)
        except Exception as exc:
            logger.error("Error handling POST: %s", str(exc), exc_info=True)
            return json_response(ERROR_RESPONSE, 500)
        finally:
            self._current_runner = None

    def _handle_delete(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        runner = self._current_runner
        if runner is None:
            return json_response({"status": "ok", "message": "No test running."})
        try:
            runner.cancel()
            return json_response({"status": "ok", "message": "Test cancelled."})
        except Exception as exc:
            logger.error("Error cancelling test: %s", str(exc), exc_info=True)
            return json_response({"status": "error", "message": str(exc)}, 500)
