# -*- coding: utf-8 -*-
"""saved_tests_handler.py — REST handler for saved test library CRUD."""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Dict, List

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from splunk.persistconn.application import PersistentServerConnectionApplication

from logger import get_logger
from kvstore_client import KVStoreClient
from handler_utils import (
    get_session_key, get_username, json_response,
    normalize_payload, extract_id, now_iso,
    handle_rest_request, check_ownership, check_and_increment_version,
)
from scheduling.scheduled_search_manager import delete_saved_search
from config import MAX_DEFINITION_SIZE_BYTES

logger = get_logger(__name__)

COLLECTION_SAVED_TESTS = "saved_tests"
COLLECTION_SCHEDULED_TESTS = "scheduled_tests"


def _sort_by_updated(records):
    # type: (List[Dict[str, Any]]) -> List[Dict[str, Any]]
    return sorted(records, key=lambda r: r.get("updatedAt", ""), reverse=True)


def _check_definition_size(definition):
    # type: (Any) -> None
    """Raise ValueError if the definition exceeds MAX_DEFINITION_SIZE_BYTES."""
    raw = json.dumps(definition) if isinstance(definition, dict) else str(definition or "")
    size = len(raw.encode("utf-8"))
    if size > MAX_DEFINITION_SIZE_BYTES:
        raise ValueError(
            "Test definition is too large to save ({0:.1f} MB). "
            "Reduce the number of scenarios or events.".format(size / (1024 * 1024))
        )


class SavedTestsHandler(PersistentServerConnectionApplication):
    """CRUD handler for the saved test library."""

    def __init__(self, command_line="", command_arg=""):
        # type: (str, str) -> None
        super().__init__()

    def handle(self, in_string):
        # type: (str) -> Dict[str, Any]
        return handle_rest_request(in_string, {
            "GET": self._handle_get,
            "POST": self._handle_post,
            "PUT": self._handle_put,
            "DELETE": self._handle_delete,
        }, logger)

    def _handle_get(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        kv = KVStoreClient(session_key)
        records = kv.get_all(COLLECTION_SAVED_TESTS)
        for rec in records:
            if isinstance(rec.get("definition"), str):
                try:
                    rec["definition"] = json.loads(rec["definition"])
                except (json.JSONDecodeError, TypeError):
                    rec["definition"] = {}
        return json_response(_sort_by_updated(records))

    def _handle_post(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Test name is required.")
        timestamp = now_iso()
        definition = payload.get("definition", {})
        _check_definition_size(definition)

        record = {
            "id": str(uuid.uuid4()),
            "name": payload.get("name", ""),
            "app": payload.get("app", ""),
            "testType": payload.get("testType", "standard"),
            "validationType": payload.get("validationType", "standard"),
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "createdBy": get_username(request),
            "scenarioCount": payload.get("scenarioCount", 0),
            "description": payload.get("description", ""),
            "definition": json.dumps(definition) if isinstance(definition, dict) else definition,
            "version": 1,
        }
        kv = KVStoreClient(session_key)
        kv.upsert(COLLECTION_SAVED_TESTS, record["id"], record)
        logger.info("Created saved test: %s", record["id"])
        record["definition"] = definition
        return json_response(record, 201)

    def _handle_put(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        record_id = extract_id(request)
        if not record_id:
            raise ValueError("Missing record ID in URL path.")
        payload = normalize_payload(request.get("payload"))
        kv = KVStoreClient(session_key)
        existing = kv.get_by_id(COLLECTION_SAVED_TESTS, record_id)

        forbidden = check_ownership(existing, get_username(request), session_key)
        if forbidden:
            return forbidden

        ok, new_version = check_and_increment_version(existing, payload.pop("version", None))
        if not ok:
            return json_response({"error": "conflict", "currentVersion": new_version}, 409)

        created_at = existing.get("createdAt")
        created_by = existing.get("createdBy")
        existing.update(payload)
        existing["id"] = record_id
        existing["createdAt"] = created_at
        existing["createdBy"] = created_by
        existing["updatedAt"] = now_iso()
        existing["version"] = new_version

        definition = existing.get("definition", {})
        _check_definition_size(definition)
        if isinstance(definition, dict):
            existing["definition"] = json.dumps(definition)

        kv.upsert(COLLECTION_SAVED_TESTS, record_id, existing)
        logger.info("Updated saved test: %s (version %d)", record_id, new_version)

        if isinstance(existing.get("definition"), str):
            existing["definition"] = json.loads(existing["definition"])
        return json_response(existing)

    def _handle_delete(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        record_id = extract_id(request)
        if not record_id:
            raise ValueError("Missing record ID in URL path.")
        kv = KVStoreClient(session_key)
        existing = kv.get_by_id(COLLECTION_SAVED_TESTS, record_id)

        forbidden = check_ownership(existing, get_username(request), session_key)
        if forbidden:
            return forbidden

        try:
            scheduled = kv.query(COLLECTION_SCHEDULED_TESTS, {"testId": record_id})
        except Exception:
            scheduled = []
        for sched in scheduled:
            sched_id = sched.get("_key") or sched.get("id", "")
            if not sched_id:
                continue
            try:
                kv.delete(COLLECTION_SCHEDULED_TESTS, sched_id)
                delete_saved_search(session_key, sched_id)
                logger.info("Cascade-deleted schedule %s for test %s", sched_id, record_id)
            except Exception as exc:
                logger.warning("Failed to cascade-delete schedule %s: %s", sched_id, exc)

        kv.delete(COLLECTION_SAVED_TESTS, record_id)
        logger.info("Deleted saved test: %s", record_id)
        return json_response({"deleted": record_id})
