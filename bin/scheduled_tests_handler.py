# -*- coding: utf-8 -*-
"""scheduled_tests_handler.py — REST handler for scheduled test CRUD."""
from __future__ import annotations

import json
import os
import random
import sys
import threading
import uuid
from typing import Any, Dict, List, Tuple

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
from scheduling.scheduled_search_manager import (
    create_saved_search, update_saved_search, delete_saved_search,
)

logger = get_logger(__name__)

COLLECTION_SCHEDULED_TESTS = "scheduled_tests"
BOOL_FIELDS = ("enabled", "alertOnFailure")

def _hour_from_range(minute, start, end):
    # type: (int, int, int) -> int
    """Deterministic hour from minute, matching frontend hourFromRange."""
    return start + (minute % (end - start + 1))


def _build_cron(interval_key, minute):
    # type: (str, int) -> str
    """Build a full 5-field cron from interval key + minute. Must match frontend buildCron."""
    if interval_key == "daily":
        return "{0} {1} * * *".format(minute, _hour_from_range(minute, 6, 9))
    if interval_key == "2d":
        return "{0} {1} */2 * *".format(minute, _hour_from_range(minute, 6, 9))
    if interval_key == "3d":
        return "{0} {1} */3 * *".format(minute, _hour_from_range(minute, 6, 9))
    if interval_key == "evening":
        return "{0} {1} * * *".format(minute, _hour_from_range(minute, 18, 21))
    if interval_key == "weekly":
        return "{0} 22 * * 5".format(minute)
    return "{0} 6 * * *".format(minute)


# Used only for suggest_minute pattern matching (finding existing tests with same interval)
INTERVAL_PATTERNS = {
    "daily": None,       # use _build_cron instead
    "2d": None,
    "3d": None,
    "evening": None,
    "weekly": None,
    # Legacy keys (kept for backward compat with existing schedules)
    "hourly": "* * * *",
    "2h": "*/2 * * *",
    "4h": "*/4 * * *",
    "6h": "*/6 * * *",
    "12h": "*/12 * * *",
}


def _normalize_bools(record):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """KVStore stores booleans as '1'/'0' strings. Normalize back to bool."""
    for field in BOOL_FIELDS:
        val = record.get(field)
        if isinstance(val, str):
            record[field] = val not in ("0", "false", "False", "")
    return record


def _async_saved_search(fn, session_key, record):
    # type: (Any, str, Dict[str, Any]) -> None
    try:
        fn(session_key, record)
    except Exception as exc:
        logger.warning("Async saved search op failed: %s", exc)


def _async_saved_search_delete(session_key, record_id):
    # type: (str, str) -> None
    try:
        delete_saved_search(session_key, record_id)
    except Exception as exc:
        logger.warning("Async saved search delete failed for %s: %s", record_id, exc)


def _validate_cron(cron):
    # type: (str) -> None
    """Reject cron schedules that run every minute — too aggressive for test runs."""
    parts = cron.strip().split()
    if len(parts) == 5 and parts[0] == '*' and parts[1] == '*':
        raise ValueError(
            "Schedule runs too frequently (every minute). "
            "Use at least a 5-minute interval (e.g. */5 * * * *)."
        )


def _suggest_minute(kv, interval_key):
    # type: (KVStoreClient, str) -> Dict[str, Any]
    """Pick a spread-out time slot for the given interval to avoid thundering herd."""
    if interval_key == "weekly":
        return _suggest_weekly_slot(kv)

    if interval_key not in INTERVAL_PATTERNS:
        return {"error": "Unknown interval_key: {0}".format(interval_key)}

    try:
        records = kv.get_all(COLLECTION_SCHEDULED_TESTS)
    except Exception:
        records = []

    # Collect used minutes for records matching this interval key
    used_minutes = []  # type: List[int]
    for rec in records:
        if rec.get("intervalKey") == interval_key:
            cron = rec.get("cronSchedule", "")
            parts = cron.strip().split()
            if len(parts) == 5:
                try:
                    used_minutes.append(int(parts[0]))
                except (ValueError, TypeError):
                    pass

    # Pick unused minute, or least-used if all taken
    all_minutes = list(range(60))
    unused = [m for m in all_minutes if m not in used_minutes]
    if unused:
        minute = random.choice(unused)
    else:
        counts = {}  # type: Dict[int, int]
        for m in used_minutes:
            counts[m] = counts.get(m, 0) + 1
        min_count = min(counts.values()) if counts else 0
        least_used = [m for m, c in counts.items() if c == min_count]
        minute = random.choice(least_used) if least_used else random.randint(0, 59)

    cron = _build_cron(interval_key, minute)
    return {"minute": minute, "cron": cron}


# Weekly window: Friday 18:00 through Sunday 08:00
# Slots are (day_of_week, hour) pairs — cron day: 5=Fri, 6=Sat, 0=Sun
_WEEKLY_SLOTS = (
    [(5, h) for h in range(18, 24)] +   # Friday 18:00-23:00
    [(6, h) for h in range(0, 24)] +     # Saturday 00:00-23:00
    [(0, h) for h in range(0, 8)]        # Sunday 00:00-07:00
)


def _suggest_weekly_slot(kv):
    # type: (KVStoreClient) -> Dict[str, Any]
    """Pick a spread-out (day, hour, minute) within the Fri-Sun weekend window."""
    try:
        records = kv.get_all(COLLECTION_SCHEDULED_TESTS)
    except Exception:
        records = []

    # Collect used (day, hour) for weekly records
    used_slots = []  # type: List[Tuple[int, int]]
    for rec in records:
        if rec.get("intervalKey") != "weekly":
            continue
        cron = rec.get("cronSchedule", "")
        parts = cron.strip().split()
        if len(parts) == 5:
            try:
                used_slots.append((int(parts[4]), int(parts[1])))
            except (ValueError, TypeError):
                pass

    # Pick unused (day, hour) slot
    unused = [s for s in _WEEKLY_SLOTS if s not in used_slots]
    if unused:
        day, hour = random.choice(unused)
    else:
        # All slots taken — pick least-used
        counts = {}  # type: Dict[Tuple[int, int], int]
        for s in used_slots:
            counts[s] = counts.get(s, 0) + 1
        min_count = min(counts.values()) if counts else 0
        least = [s for s, c in counts.items() if c == min_count]
        day, hour = random.choice(least) if least else random.choice(_WEEKLY_SLOTS)

    minute = random.randint(0, 59)
    cron = "{0} {1} * * {2}".format(minute, hour, day)
    return {"minute": minute, "cron": cron}


def _build_record(payload, username="unknown"):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    record_id = payload.get("id") or str(uuid.uuid4())
    return {
        "id": record_id,
        "testId": payload.get("testId", ""),
        "testName": payload.get("testName", ""),
        "app": payload.get("app", ""),
        "savedSearchOrigin": payload.get("savedSearchOrigin"),
        "cronSchedule": payload.get("cronSchedule", "0 6 * * *"),
        "intervalKey": payload.get("intervalKey", ""),
        "enabled": payload.get("enabled", True),
        "createdAt": payload.get("createdAt") or now_iso(),
        "createdBy": username,
        "lastRunAt": None,
        "lastRunStatus": None,
        "alertOnFailure": payload.get("alertOnFailure", False),
        "emailRecipients": payload.get("emailRecipients", []),
        "queueStatus": "idle",
        "queuedAt": "",
    }


class ScheduledTestsHandler(PersistentServerConnectionApplication):

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

        # Check for action parameter in query string
        query = request.get("query", {})
        if isinstance(query, list):
            query = dict(q if isinstance(q, (list, tuple)) and len(q) == 2 else ("", "") for q in query)
        action = query.get("action", "") if isinstance(query, dict) else ""
        if action == "suggest_minute":
            interval_key = query.get("interval_key", "") if isinstance(query, dict) else ""
            result = _suggest_minute(kv, str(interval_key))
            if "error" in result:
                return json_response(result, 400)
            return json_response(result)

        records = kv.get_all(COLLECTION_SCHEDULED_TESTS)
        for r in records:
            _normalize_bools(r)
        return json_response(records)

    def _handle_post(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))
        if not str(payload.get("testId", "")).strip():
            raise ValueError("testId is required.")
        if not str(payload.get("cronSchedule", "")).strip():
            raise ValueError("cronSchedule is required.")
        _validate_cron(payload["cronSchedule"])
        record = _build_record(payload, get_username(request))
        record["version"] = 1
        kv = KVStoreClient(session_key)
        kv.upsert(COLLECTION_SCHEDULED_TESTS, record["id"], record)
        threading.Thread(
            target=_async_saved_search,
            args=(create_saved_search, session_key, record),
            daemon=True,
        ).start()
        logger.info("Created scheduled test: %s", record["id"])
        return json_response(record, 201)

    def _handle_put(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        record_id = extract_id(request)
        if not record_id:
            raise ValueError("Missing record ID in URL path.")
        payload = normalize_payload(request.get("payload"))
        kv = KVStoreClient(session_key)
        existing = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, record_id)

        forbidden = check_ownership(existing, get_username(request), session_key)
        if forbidden:
            return forbidden

        if "cronSchedule" in payload:
            _validate_cron(str(payload["cronSchedule"]))

        ok, new_version = check_and_increment_version(existing, payload.pop("version", None))
        if not ok:
            return json_response({"error": "conflict", "currentVersion": new_version}, 409)

        existing.update(payload)
        existing["id"] = record_id
        existing["version"] = new_version
        kv.upsert(COLLECTION_SCHEDULED_TESTS, record_id, existing)
        threading.Thread(
            target=_async_saved_search,
            args=(update_saved_search, session_key, existing),
            daemon=True,
        ).start()
        _normalize_bools(existing)
        logger.info("Updated scheduled test: %s", record_id)
        return json_response(existing)

    def _handle_delete(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        record_id = extract_id(request)
        if not record_id:
            raise ValueError("Missing record ID in URL path.")
        kv = KVStoreClient(session_key)
        existing = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, record_id)

        forbidden = check_ownership(existing, get_username(request), session_key)
        if forbidden:
            return forbidden

        kv.delete(COLLECTION_SCHEDULED_TESTS, record_id)
        threading.Thread(
            target=_async_saved_search_delete,
            args=(session_key, record_id),
            daemon=True,
        ).start()
        logger.info("Deleted scheduled test: %s", record_id)
        return json_response({"deleted": record_id})
