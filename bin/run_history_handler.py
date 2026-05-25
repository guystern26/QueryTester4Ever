# -*- coding: utf-8 -*-
"""run_history_handler.py — REST handler for test run history."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from splunk.persistconn.application import PersistentServerConnectionApplication

from logger import get_logger
from kvstore_client import KVStoreClient
from handler_utils import (
    get_session_key, json_response, get_query_param, handle_rest_request,
)

logger = get_logger(__name__)

COLLECTION_RUN_HISTORY = "test_run_history"
MAX_HISTORY = 50


class RunHistoryHandler(PersistentServerConnectionApplication):
    """Read-only handler for test run history."""

    def __init__(self, command_line="", command_arg=""):
        # type: (str, str) -> None
        super().__init__()

    def handle(self, in_string):
        # type: (str) -> Dict[str, Any]
        return handle_rest_request(in_string, {
            "GET": self._handle_get,
        }, logger)

    def _handle_get(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        scheduled_test_id = get_query_param(request, "scheduled_test_id")
        kv = KVStoreClient(session_key)
        if scheduled_test_id:
            records = kv.query(
                COLLECTION_RUN_HISTORY,
                {"scheduledTestId": scheduled_test_id},
            )
        else:
            records = kv.get_all(COLLECTION_RUN_HISTORY)
        for rec in records:
            if isinstance(rec.get("scenarioResults"), str):
                try:
                    rec["scenarioResults"] = json.loads(rec["scenarioResults"])
                except (json.JSONDecodeError, TypeError):
                    rec["scenarioResults"] = []
        records.sort(key=lambda rec: rec.get("ranAt", ""), reverse=True)
        return json_response(records[:MAX_HISTORY])
