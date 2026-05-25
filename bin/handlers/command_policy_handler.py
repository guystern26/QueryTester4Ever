# -*- coding: utf-8 -*-
"""command_policy_handler.py — REST handler for SPL command policy."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from splunk.persistconn.application import PersistentServerConnectionApplication

from logger import get_logger
from kvstore_client import KVStoreClient
from handler_utils import (
    get_session_key, json_response, normalize_payload,
    get_query_param, handle_rest_request,
)

logger = get_logger(__name__)

COLLECTION = "query_tester_command_policy"
POLICY_CACHE_TTL = 60
MUTABLE_DEFAULT_FIELDS = frozenset(["severity", "label", "allowed"])
_policy_cache = None   # type: Optional[List[Dict[str, Any]]]
_policy_cache_time = 0.0
DEFAULT_COMMAND_POLICY = [
    {"command": "delete",       "severity": "danger",  "label": "Permanently deletes index data", "allowed": "false", "is_default": "true"},
    {"command": "drop",         "severity": "danger",  "label": "Drops index or dataset",        "allowed": "false", "is_default": "true"},
    {"command": "outputlookup", "severity": "warning", "label": "Writes to a lookup file",       "allowed": "true",  "is_default": "true"},
    {"command": "inputlookup",  "severity": "info",    "label": "Reads from a lookup file",      "allowed": "true",  "is_default": "true"},
    {"command": "rest",         "severity": "warning", "label": "Makes external REST calls",     "allowed": "false", "is_default": "true"},
    {"command": "sendemail",    "severity": "warning", "label": "Sends email from Splunk",       "allowed": "false", "is_default": "true"},
    {"command": "collect",      "severity": "warning", "label": "Writes results to an index",    "allowed": "true",  "is_default": "true"},
    {"command": "map",          "severity": "warning", "label": "Can trigger many subsearches",  "allowed": "true",  "is_default": "true"},
    {"command": "runshellscript", "severity": "danger", "label": "Executes shell commands",      "allowed": "false", "is_default": "true"},
]


def invalidate_policy_cache():
    # type: () -> None
    global _policy_cache, _policy_cache_time
    _policy_cache = None
    _policy_cache_time = 0.0


def get_cached_policy(session_key):
    # type: (str) -> List[Dict[str, Any]]
    global _policy_cache, _policy_cache_time
    if _policy_cache is not None and (time.time() - _policy_cache_time) < POLICY_CACHE_TTL:
        return _policy_cache
    _policy_cache = _load_policy(session_key)
    _policy_cache_time = time.time()
    return _policy_cache


def _load_policy(session_key):
    # type: (str) -> List[Dict[str, Any]]
    kv = KVStoreClient(session_key)
    records = kv.get_all(COLLECTION)
    if not records:
        records = _seed_defaults(kv)
    return _clean(records)


def _seed_defaults(kv):
    # type: (KVStoreClient) -> List[Dict[str, Any]]
    for entry in DEFAULT_COMMAND_POLICY:
        kv.upsert(COLLECTION, entry["command"], dict(entry))
    logger.info("Seeded %d default command policy entries", len(DEFAULT_COMMAND_POLICY))
    return [dict(e) for e in DEFAULT_COMMAND_POLICY]


def _clean(records):
    # type: (List[Dict[str, Any]]) -> List[Dict[str, Any]]
    for rec in records:
        rec.pop("_key", None)
        rec.pop("_user", None)
    return records


def _wipe_collection(kv):
    # type: (KVStoreClient) -> None
    for rec in kv.get_all(COLLECTION):
        key = rec.get("_key") or rec.get("command", "")
        if key:
            try:
                kv.delete(COLLECTION, key)
            except Exception:
                pass


class CommandPolicyHandler(PersistentServerConnectionApplication):
    """CRUD handler for SPL command policy."""

    def __init__(self, command_line="", command_arg=""):
        # type: (str, str) -> None
        super().__init__()

    def handle(self, in_string):
        # type: (str) -> Dict[str, Any]
        return handle_rest_request(in_string, {
            "GET": self._handle_get,
            "POST": self._handle_post,
            "DELETE": self._handle_delete,
        }, logger)

    def _handle_post(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        path = request.get("rest_path", "")
        if "/single" in path:
            return self._handle_upsert_single(request)
        return self._handle_replace_all(request)

    def _handle_get(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        return json_response(get_cached_policy(session_key))

    def _handle_replace_all(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))
        kv = KVStoreClient(session_key)
        _wipe_collection(kv)
        if payload.get("reset"):
            invalidate_policy_cache()
            return json_response(_clean(_seed_defaults(kv)))
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("Expected 'entries' array or 'reset' flag.")
        saved = []  # type: List[Dict[str, Any]]
        for entry in entries:
            cmd = entry.get("command", "").strip()
            if not cmd:
                continue
            record = {"command": cmd, "severity": entry.get("severity", "warning"),
                      "label": entry.get("label", ""), "allowed": entry.get("allowed", "true"),
                      "is_default": entry.get("is_default", "false")}
            kv.upsert(COLLECTION, cmd, record)
            saved.append(record)
        invalidate_policy_cache()
        return json_response(saved)

    def _handle_upsert_single(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))
        cmd = payload.get("command", "").strip()
        if not cmd:
            raise ValueError("Missing required field: command")
        kv = KVStoreClient(session_key)
        try:
            existing = kv.get_by_id(COLLECTION, cmd)
            if existing.get("is_default") == "true":
                for key in payload:
                    if key not in MUTABLE_DEFAULT_FIELDS and key != "command":
                        raise ValueError("Cannot modify '{0}' on default command.".format(key))
                for f in MUTABLE_DEFAULT_FIELDS:
                    if f in payload:
                        existing[f] = payload[f]
                kv.upsert(COLLECTION, cmd, existing)
                invalidate_policy_cache()
                return json_response(_clean([existing])[0])
        except ValueError:
            pass
        record = {"command": cmd, "severity": payload.get("severity", "warning"),
                  "label": payload.get("label", ""), "allowed": payload.get("allowed", "true"),
                  "is_default": "false"}
        kv.upsert(COLLECTION, cmd, record)
        invalidate_policy_cache()
        return json_response(record, 201)

    def _handle_delete(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        cmd = get_query_param(request, "command")
        if not cmd:
            raise ValueError("Missing required query parameter: command")
        kv = KVStoreClient(session_key)
        existing = kv.get_by_id(COLLECTION, cmd)
        if existing.get("is_default") == "true":
            return json_response({"error": "Default commands cannot be removed."}, 400)
        kv.delete(COLLECTION, cmd)
        invalidate_policy_cache()
        return json_response({"deleted": cmd})
