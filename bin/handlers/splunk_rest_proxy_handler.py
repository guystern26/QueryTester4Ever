"""splunk_rest_proxy_handler.py — Proxies whitelisted Splunk REST calls for the AI agent."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from handler_utils import get_session_key, json_response, normalize_payload
from logger import get_logger
from splunk_connect import get_service

logger = get_logger(__name__)

# Whitelisted endpoint patterns the agent is allowed to query.
# Each entry is a compiled regex matching the Splunk REST path (no leading slash).
# Only GET requests are proxied — no mutations.
ALLOWED_PATTERNS = [
    re.compile(r"^services/saved/searches$"),
    re.compile(r"^services/saved/searches/.+$"),
    re.compile(r"^services/alerts/fired_alerts$"),
    re.compile(r"^services/alerts/fired_alerts/.+$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/saved/searches$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/saved/searches/.+$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/alerts/fired_alerts$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/alerts/fired_alerts/.+$"),
    re.compile(r"^services/apps/local$"),
    re.compile(r"^services/apps/local/.+$"),
    re.compile(r"^services/data/indexes$"),
    re.compile(r"^services/data/indexes/.+$"),
    re.compile(r"^services/server/info$"),
    re.compile(r"^services/configs/conf-savedsearches$"),
    re.compile(r"^services/configs/conf-savedsearches/.+$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/data/indexes$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/data/indexes/.+$"),
    re.compile(r"^services/data/lookup-table-files$"),
    re.compile(r"^services/data/lookup-table-files/.+$"),
    re.compile(r"^services/data/transforms/lookups$"),
    re.compile(r"^services/data/transforms/lookups/.+$"),
    re.compile(r"^services/data/props/sourcetypes$"),
    re.compile(r"^services/data/props/sourcetypes/.+$"),
    re.compile(r"^services/admin/macros$"),
    re.compile(r"^services/admin/macros/.+$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/admin/macros$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/admin/macros/.+$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/data/props/sourcetypes$"),
    re.compile(r"^servicesNS/[^/]+/[^/]+/data/props/sourcetypes/.+$"),
]

MAX_RESULTS = 50
MAX_RESPONSE_ENTRIES = 100


def _is_allowed(path):
    # type: (str) -> bool
    """Check if the path matches any whitelisted pattern."""
    clean = path.lstrip("/")
    for pattern in ALLOWED_PATTERNS:
        if pattern.match(clean):
            return True
    return False


def _parse_entries(body):
    # type: (Dict[str, Any]) -> List[Dict[str, Any]]
    """Extract entry list from Splunk REST response, keeping only key fields."""
    entries = body.get("entry", [])
    result = []  # type: List[Dict[str, Any]]
    for entry in entries[:MAX_RESPONSE_ENTRIES]:
        item = {
            "name": entry.get("name", ""),
            "id": entry.get("id", ""),
        }  # type: Dict[str, Any]
        content = entry.get("content", {})
        if isinstance(content, dict):
            # Include all content fields but cap string values at 500 chars
            trimmed = {}  # type: Dict[str, Any]
            for k, v in content.items():
                if isinstance(v, str) and len(v) > 500:
                    trimmed[k] = v[:500] + "..."
                else:
                    trimmed[k] = v
            item["content"] = trimmed
        result.append(item)
    return result


def handle_splunk_rest_proxy(request):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Proxy a whitelisted GET request to the local Splunk REST API."""
    method = request.get("method", "GET").upper()
    if method != "POST":
        return json_response({"error": "Use POST to proxy REST calls"}, 405)

    try:
        session_key = get_session_key(request)
    except Exception as exc:
        return json_response({"error": "Auth error: {0}".format(exc)}, 401)

    payload = normalize_payload(request.get("payload"))
    path = str(payload.get("path", "")).strip()
    params = payload.get("params", {})

    if not path:
        return json_response({"error": "Missing 'path' field"}, 400)

    if not _is_allowed(path):
        logger.warning("Blocked REST proxy request to: %s", path)
        return json_response(
            {"error": "Endpoint not allowed: {0}".format(path)}, 403,
        )

    if not isinstance(params, dict):
        params = {}

    # Force output_mode and cap count
    params["output_mode"] = "json"
    if "count" not in params:
        params["count"] = str(MAX_RESULTS)
    else:
        try:
            cnt = int(params["count"])
            if cnt > MAX_RESULTS or cnt < 0:
                params["count"] = str(MAX_RESULTS)
        except (ValueError, TypeError):
            params["count"] = str(MAX_RESULTS)

    try:
        service = get_service(session_key)
        # Use the low-level HTTP GET on the service
        clean_path = "/" + path.lstrip("/")
        resp = service.http.get(clean_path, **params)
        body = resp.body.read()
        data = json.loads(body)

        entries = _parse_entries(data)
        total = len(data.get("entry", []))
        return json_response({
            "entries": entries,
            "totalCount": total,
            "path": path,
        })
    except Exception as exc:
        logger.error("Splunk REST proxy error for %s: %s", path, exc)
        return json_response(
            {"error": "REST call failed: {0}".format(exc)}, 500,
        )
