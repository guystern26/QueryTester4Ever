# -*- coding: utf-8 -*-
"""
hec_config.py
Resolve HEC (HTTP Event Collector) connection settings from runtime config
with static config.py fallback.
"""
from __future__ import annotations

import os
import ssl
from typing import Any, Dict, Optional

from logger import get_logger
from config import (
    HEC_HOST, HEC_PORT, HEC_SCHEME, HEC_TOKEN, HEC_SSL_VERIFY,
    HEC_TIMEOUT, TEMP_INDEX, TEMP_SOURCETYPE,
)

logger = get_logger(__name__)

_FALSE_STRINGS = {"0", "false", "False", "no", "No", ""}


def _to_bool(val):
    # type: (Any) -> bool
    """Normalize KVStore boolean values (may be string '0'/'false')."""
    if isinstance(val, bool):
        return val
    return str(val) not in _FALSE_STRINGS


def get_hec_config(session_key=None):
    # type: (Optional[str]) -> Dict[str, Any]
    """Get HEC config from runtime config or fall back to static config."""
    if session_key:
        try:
            from runtime_config import get_runtime_config
            cfg = get_runtime_config(session_key)
            return {
                "hec_host": cfg.get("hec_host", HEC_HOST),
                "hec_port": int(cfg.get("hec_port", HEC_PORT)),
                "hec_scheme": cfg.get("hec_scheme", HEC_SCHEME),
                "hec_token": cfg.get("hec_token", HEC_TOKEN),
                "hec_ssl_verify": cfg.get("hec_ssl_verify", HEC_SSL_VERIFY),
                "hec_timeout": int(cfg.get("hec_timeout", HEC_TIMEOUT)),
                "temp_index": cfg.get("temp_index", TEMP_INDEX),
                "temp_sourcetype": cfg.get("temp_sourcetype", TEMP_SOURCETYPE),
            }
        except Exception as exc:
            logger.debug("Runtime config unavailable, using static: %s", exc)
    return {
        "hec_host": HEC_HOST,
        "hec_port": HEC_PORT,
        "hec_scheme": HEC_SCHEME,
        "hec_token": HEC_TOKEN,
        "hec_ssl_verify": HEC_SSL_VERIFY,
        "hec_timeout": HEC_TIMEOUT,
        "temp_index": TEMP_INDEX,
        "temp_sourcetype": TEMP_SOURCETYPE,
    }


def get_hec_token(session_key=None):
    # type: (Optional[str]) -> str
    """Read the HEC token from runtime config, static config, or environment."""
    if session_key:
        cfg = get_hec_config(session_key)
        token = cfg.get("hec_token", "")
        if token:
            return token
    token = HEC_TOKEN or os.environ.get("QUERY_TESTER_HEC_TOKEN", "")
    if not token:
        raise RuntimeError(
            "HEC token is not configured. Set HEC_TOKEN in bin/config.py "
            "or export QUERY_TESTER_HEC_TOKEN environment variable."
        )
    return token


def resolve_hec_context(session_key):
    # type: (str) -> Dict[str, Any]
    """Pre-resolve all HEC connection details into a reusable context dict.

    Returns dict with: hec_url, hec_token, hec_timeout, ssl_ctx, index, sourcetype.
    Call once per TestRunner and reuse across scenarios to avoid repeated
    runtime_config lookups, URL formatting, and SSL context creation.
    """
    cfg = get_hec_config(session_key)
    token = cfg["hec_token"] or get_hec_token(session_key)
    url = "{0}://{1}:{2}/services/collector/event".format(
        cfg["hec_scheme"], cfg["hec_host"], cfg["hec_port"],
    )
    ctx = ssl.create_default_context()
    if not _to_bool(cfg["hec_ssl_verify"]):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return {
        "hec_url": url,
        "hec_token": token,
        "hec_timeout": int(cfg["hec_timeout"]),
        "ssl_ctx": ctx,
        "index": cfg["temp_index"],
        "sourcetype": cfg["temp_sourcetype"],
    }
