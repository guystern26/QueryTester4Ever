# -*- coding: utf-8 -*-
"""handler_utils.py — Shared utilities for all REST handlers."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

from logger import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def get_session_key(request):
    # type: (Dict[str, Any]) -> str
    """Extract the Splunk session key from a REST request."""
    session = request.get("session") or {}
    key = (
        session.get("authtoken")
        or session.get("sessionKey")
        or request.get("system_authtoken")
    )
    if not key:
        raise ValueError("Missing session key in request.")
    return key


def get_username(request):
    # type: (Dict[str, Any]) -> str
    """Extract the authenticated username from the session."""
    session = request.get("session") or {}
    return session.get("user", "unknown")


def json_response(data, status=200):
    # type: (Any, int) -> Dict[str, Any]
    """Build a Splunk REST JSON response dict."""
    return {
        "payload": json.dumps(data, default=str),
        "status": status,
        "headers": {"Content-Type": "application/json"},
    }


def normalize_payload(raw_body):
    # type: (Any) -> Dict[str, Any]
    """Parse the request payload into a dict, handling all Splunk formats."""
    if raw_body is None:
        return {}
    if isinstance(raw_body, (list, tuple)) and raw_body:
        raw_body = raw_body[0]
    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8")
    if isinstance(raw_body, str):
        if not raw_body.strip():
            return {}
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    raise ValueError("Unsupported payload type: {0}".format(type(raw_body).__name__))


def extract_id(request):
    # type: (Dict[str, Any]) -> Optional[str]
    """Extract a record ID from query params, form params, or URL path."""
    for source in ("query", "form"):
        container = request.get(source) or []
        if isinstance(container, dict):
            val = container.get("id")
            if val:
                return str(val)
        elif isinstance(container, list):
            for pair in container:
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] == "id":
                    return str(pair[1])
    rest_path = request.get("rest_path", "")
    parts = rest_path.strip("/").split("/")
    if len(parts) >= 3:
        return parts[-1]
    return None


def get_query_param(request, param):
    # type: (Dict[str, Any], str) -> str
    """Extract a single named query parameter from the request."""
    query = request.get("query") or {}
    if isinstance(query, list):
        for pair in query:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                if pair[0] == param:
                    return str(pair[1])
        return ""
    if isinstance(query, dict):
        return str(query.get(param, ""))
    return ""


def now_iso():
    # type: () -> str
    """Return the current UTC time as an ISO 8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Request skeleton — TASK 1
# ---------------------------------------------------------------------------

def handle_rest_request(in_string, method_map, logger_ref=None):
    # type: (str, Dict[str, Callable], Any) -> Dict[str, Any]
    """Parse JSON, route by HTTP method, and wrap in standard try/except.

    *method_map* maps HTTP verbs to callables that accept ``(request_dict)``
    and return a ``json_response`` dict.  Unmatched methods get 405.
    ``ValueError`` → 400, any other ``Exception`` → 500.
    """
    try:
        request = json.loads(in_string)
    except Exception:
        return json_response({"error": "Bad request"}, 400)
    method = request.get("method", "GET").upper()
    handler_fn = method_map.get(method)
    if handler_fn is None:
        return json_response({"error": "Method not allowed"}, 405)
    log = logger_ref or _logger
    try:
        return handler_fn(request)
    except ValueError as exc:
        log.warning("Client error: %s", str(exc))
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:
        log.error("Server error: %s", str(exc), exc_info=True)
        return json_response({"error": "Internal server error"}, 500)


# ---------------------------------------------------------------------------
# Auth & ownership — TASK 2
# ---------------------------------------------------------------------------

def is_admin_user(session_key, username):
    # type: (str, str) -> bool
    """Check if the user has an admin role via splunklib."""
    try:
        from splunk_connect import get_service
        service = get_service(session_key, app="QueryTester", owner="nobody")
        user = service.users[username]
        roles = user.content.get("roles", [])
        return "admin" in roles
    except Exception:
        return False


def check_ownership(record, session_user, session_key):
    # type: (Dict[str, Any], str, str) -> Optional[Dict[str, Any]]
    """Return a 403 response if *session_user* doesn't own *record*, else None.

    Admins bypass.  Records with empty ``createdBy`` (legacy) allow anyone.
    """
    owner = record.get("createdBy", "")
    if owner and session_user != owner and not is_admin_user(session_key, session_user):
        return json_response(
            {"error": "Forbidden: you can only modify your own records."}, 403
        )
    return None


# ---------------------------------------------------------------------------
# Optimistic locking — TASK 3
# ---------------------------------------------------------------------------

def check_and_increment_version(stored_record, payload_version):
    # type: (Dict[str, Any], Optional[int]) -> Tuple[bool, int]
    """Optimistic locking: compare versions and compute the next one.

    Returns ``(True, new_version)`` on success.
    Returns ``(False, stored_version)`` on conflict (caller should 409).
    Legacy records (version 0 or missing) skip the check.
    """
    stored_version = int(stored_record.get("version") or 0)
    if payload_version is not None and int(payload_version) != stored_version:
        return False, stored_version
    return True, stored_version + 1
