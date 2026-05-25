# -*- coding: utf-8 -*-
"""config_handler.py — REST handler for admin configuration."""
from __future__ import annotations
import json, os, sys, time
from typing import Any, Dict, List, Optional

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from splunk.persistconn.application import PersistentServerConnectionApplication
from logger import get_logger
from kvstore_client import KVStoreClient
from handler_utils import get_session_key, json_response, normalize_payload
from config_admin.config_detection import detect_local_splunk_config, detect_email_config
from config_admin.config_test_connectivity import test_connectivity
from config_admin.config_secrets import (
    SECRET_FIELDS, get_splunk_service, read_secret, read_all_secrets,
    write_secret,
)

logger = get_logger(__name__)

COLLECTION = "query_tester_config"
CONFIG_KEY = "main"
REQUIRED_FIELDS = frozenset(["hec_token", "splunk_host", "hec_host"])
CONFIG_CACHE_TTL = 60
_config_cache = None   # type: Optional[Dict[str, Any]]
_config_cache_time = 0.0


def invalidate_config_cache():
    # type: () -> None
    global _config_cache, _config_cache_time
    _config_cache = None
    _config_cache_time = 0.0

def get_cached_config(session_key):
    # type: (str) -> Dict[str, Any]
    global _config_cache, _config_cache_time
    if _config_cache is not None and (time.time() - _config_cache_time) < CONFIG_CACHE_TTL:
        return _config_cache
    _config_cache = _load_config_from_storage(session_key)
    _config_cache_time = time.time()
    return _config_cache

def _load_config_from_storage(session_key):
    # type: (str) -> Dict[str, Any]
    kv = KVStoreClient(session_key)
    try:
        stored = kv.get_by_id(COLLECTION, CONFIG_KEY)
    except ValueError:
        stored = {}

    detected = detect_local_splunk_config(session_key)
    detected_fields = []  # type: List[str]
    merged = dict(stored)
    for key, val in detected.items():
        if key not in merged or not merged[key]:
            merged[key] = val
            detected_fields.append(key)
    merged["_detected"] = detected_fields
    merged.pop("_key", None)
    merged.pop("_user", None)
    return merged


def _is_configured(session_key):
    # type: (str) -> bool
    """App is configured when HEC token is set (required for test execution)."""
    try:
        kv = KVStoreClient(session_key)
        try:
            stored = kv.get_by_id(COLLECTION, CONFIG_KEY)
        except ValueError:
            stored = {}
        # Check HEC token in KVStore config first
        hec_token = stored.get("hec_token", "")
        if not hec_token:
            # Fall back to storage/passwords
            service = get_splunk_service(session_key)
            secrets = read_all_secrets(service)
            hec_token = secrets.get("hec_token", "")
        return bool(hec_token and hec_token.strip())
    except Exception:
        return False


class ConfigHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line="", command_arg=""):
        # type: (str, str) -> None
        super().__init__()

    def handle(self, in_string):
        # type: (str) -> Dict[str, Any]
        try:
            request = json.loads(in_string)
        except Exception:
            return json_response({"error": "Bad request"}, 400)

        method = request.get("method", "GET").upper()
        path = request.get("rest_path", "")
        try:
            if method == "GET":
                return self._route_get(request, path)
            elif method == "POST":
                return self._route_post(request, path)
            return json_response({"error": "Method not allowed"}, 405)
        except Exception as exc:
            logger.error("Config handler error: %s", str(exc), exc_info=True)
            return json_response({"error": "Internal server error"}, 500)

    def _route_get(self, request, path):
        # type: (Dict[str, Any], str) -> Dict[str, Any]
        if "/status" in path: return self._handle_status(request)
        if "/secret/" in path: return self._handle_get_secret(request, path)
        if "/email/detect" in path: return self._handle_email_detect(request)
        return self._handle_get(request)

    def _route_post(self, request, path):
        # type: (Dict[str, Any], str) -> Dict[str, Any]
        if path.endswith("/test"): return self._handle_test(request)
        return self._handle_post(request)

    def _handle_get(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        service = get_splunk_service(session_key)
        return self._build_config_response(session_key, service)

    def _build_config_response(self, session_key, service):
        # type: (str, Any) -> Dict[str, Any]
        config = get_cached_config(session_key)
        safe = dict(config)
        secrets = read_all_secrets(service)
        for field in SECRET_FIELDS:
            safe[field] = {"set": field in secrets and bool(secrets[field])}
        return json_response(safe)

    def _handle_post(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))
        plain = payload.get("plain", {})
        secrets_input = payload.get("secrets", {})

        kv = KVStoreClient(session_key)
        try:
            existing = kv.get_by_id(COLLECTION, CONFIG_KEY)
        except ValueError:
            existing = {}
        existing.update(plain)
        existing.pop("_key", None)
        existing.pop("_user", None)
        kv.upsert(COLLECTION, CONFIG_KEY, existing)

        service = get_splunk_service(session_key)
        if secrets_input:
            for field, value in secrets_input.items():
                if field in SECRET_FIELDS and value:
                    write_secret(service, field, value)

        invalidate_config_cache()
        self._apply_runtime_updates(plain)
        logger.info("Config saved by %s", (request.get("session") or {}).get("user", "unknown"))
        return self._build_config_response(session_key, service)

    def _handle_status(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        from auth_utils import is_admin as check_admin
        admin = check_admin(session_key)
        configured = _is_configured(session_key)
        return json_response({"configured": configured, "is_admin": admin})

    def _handle_get_secret(self, request, path):
        # type: (Dict[str, Any], str) -> Dict[str, Any]
        session_key = get_session_key(request)
        parts = path.rstrip("/").split("/")
        secret_name = parts[-1] if parts else ""
        if secret_name not in SECRET_FIELDS:
            return json_response({"error": "Unknown secret field"}, 400)
        service = get_splunk_service(session_key)
        value = read_secret(service, secret_name)
        return json_response({"value": value})

    def _handle_email_detect(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        return json_response(detect_email_config(get_session_key(request)))

    @staticmethod
    def _apply_runtime_updates(plain):
        # type: (Dict[str, Any]) -> None
        try:
            from runtime_config import invalidate_runtime_cache
            invalidate_runtime_cache()
        except Exception:
            pass
        if plain.get("log_level"):
            try:
                from logger import reconfigure_log_level
                reconfigure_log_level(plain["log_level"])
            except Exception:
                pass

    def _handle_test(self, request):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        session_key = get_session_key(request)
        config = dict(get_cached_config(session_key))
        config.update(read_all_secrets(get_splunk_service(session_key)))
        return json_response(test_connectivity(config))
