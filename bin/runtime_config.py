# -*- coding: utf-8 -*-
"""
runtime_config.py — Runtime configuration bridge.

Reads dynamic config from KVStore (set via the Setup page) with fallback
to static config.py defaults. Also reads secrets from storage/passwords.

Usage:
    from runtime_config import get_runtime_config
    cfg = get_runtime_config(session_key)
    hec_host = cfg["hec_host"]
    smtp_server = cfg["smtp_server"]
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from logger import get_logger

logger = get_logger(__name__)

COLLECTION = "query_tester_config"
CONFIG_KEY = "main"
CACHE_TTL = 120  # seconds

_cache = None   # type: Optional[Dict[str, Any]]
_cache_time = 0.0

# Fields that map from KVStore keys to config.py constants.
# Format: (kvstore_key, config_module_attr, type_converter)
_FIELD_MAP = [
    ("splunk_host", "SPLUNK_HOST", str),
    ("splunk_port", "SPLUNK_PORT", int),
    ("splunk_scheme", "SPLUNK_SCHEME", str),
    ("splunk_username", "SPLUNK_USERNAME", str),
    ("splunk_web_url", "SPLUNK_WEB_URL", str),
    ("hec_host", "HEC_HOST", str),
    ("hec_port", "HEC_PORT", int),
    ("hec_scheme", "HEC_SCHEME", str),
    ("hec_ssl_verify", "HEC_SSL_VERIFY", None),  # special bool handling
    ("hec_timeout", "HEC_TIMEOUT", int),
    ("hec_token", "HEC_TOKEN", str),
    ("temp_index", "TEMP_INDEX", str),
    ("temp_sourcetype", "TEMP_SOURCETYPE", str),
    ("smtp_server", "SMTP_SERVER", str),
    ("smtp_port", "SMTP_PORT", int),
    ("mail_from", "MAIL_FROM", str),
    ("default_alert_email", "DEFAULT_ALERT_EMAIL", str),
    ("smtp_username", None, str),
    ("email_auth_method", None, str),
    ("tls_mode", None, str),
    ("llm_endpoint", "LLM_ENDPOINT", str),
    ("llm_model", "LLM_MODEL", str),
    ("llm_max_tokens", "LLM_MAX_TOKENS", int),
    ("max_parallel_tests", "MAX_PARALLEL_TESTS", int),
    ("log_level", "LOG_LEVEL", str),
]

# Secret fields read from storage/passwords instead of KVStore
_SECRET_FIELDS = frozenset(["hec_token", "smtp_password", "llm_api_key"])


def _to_bool(val):
    # type: (Any) -> bool
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes")


def _get_static_defaults():
    # type: () -> Dict[str, Any]
    """Load fallback values from config.py."""
    import config as static_cfg
    defaults = {}  # type: Dict[str, Any]
    for kv_key, attr, _ in _FIELD_MAP:
        if attr is not None and hasattr(static_cfg, attr):
            defaults[kv_key] = getattr(static_cfg, attr)
    return defaults


def _read_kvstore_config(session_key):
    # type: (str) -> Dict[str, Any]
    """Read config from KVStore. Returns empty dict on any error."""
    try:
        from kvstore_client import KVStoreClient
        kv = KVStoreClient(session_key)
        record = kv.get_by_id(COLLECTION, CONFIG_KEY)
        record.pop("_key", None)
        record.pop("_user", None)
        return record
    except Exception as exc:
        logger.warning("Could not read runtime config from KVStore: %s", exc)
        return {}


def _read_secrets(session_key):
    # type: (str) -> Dict[str, str]
    """Read secret fields from storage/passwords."""
    try:
        from config_admin.config_secrets import get_splunk_service, read_all_secrets
        service = get_splunk_service(session_key)
        return read_all_secrets(service)
    except Exception as exc:
        logger.warning("Could not read secrets for runtime config: %s", exc)
        return {}


def get_runtime_config(session_key):
    # type: (str) -> Dict[str, Any]
    """
    Return merged config: KVStore overrides > secrets > config.py defaults.
    Result is cached for CACHE_TTL seconds.
    """
    global _cache, _cache_time
    now = time.time()
    if _cache is not None and (now - _cache_time) < CACHE_TTL:
        return dict(_cache)

    # Start with static defaults
    merged = _get_static_defaults()

    # Layer KVStore config on top (non-empty values only)
    kv_config = _read_kvstore_config(session_key)
    for kv_key, attr, converter in _FIELD_MAP:
        val = kv_config.get(kv_key)
        if val is not None and str(val).strip():
            if converter is None:
                merged[kv_key] = _to_bool(val)
            else:
                try:
                    merged[kv_key] = converter(val)
                except (ValueError, TypeError):
                    pass  # keep default

    # Layer secrets on top (override static and KVStore)
    secrets = _read_secrets(session_key)
    for field, value in secrets.items():
        if value:
            merged[field] = value

    _cache = dict(merged)
    _cache_time = now
    return dict(merged)


def invalidate_runtime_cache():
    # type: () -> None
    """Clear the runtime config cache. Call after config save."""
    global _cache, _cache_time
    _cache = None
    _cache_time = 0.0
