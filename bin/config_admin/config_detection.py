# -*- coding: utf-8 -*-
"""
config_detection.py — Auto-detect local Splunk environment settings.
Called by config_handler to pre-populate unset config fields.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from logger import get_logger

logger = get_logger(__name__)


def detect_local_splunk_config(session_key):
    # type: (str) -> Dict[str, Any]
    """Read config from the local Splunk instance. Returns only found fields."""
    detected = {}  # type: Dict[str, Any]
    try:
        from splunk_connect import get_service
        service = get_service(session_key, app="QueryTester", owner="nobody")
        _detect_server_info(service, detected)
        _detect_server_settings(service, detected)
        _detect_hec(service, detected)
        _detect_email(service, detected)
        _detect_temp_index(service, detected)
    except Exception as exc:
        logger.warning("Auto-detection partially failed: %s", exc)
    return detected


def detect_email_config(session_key):
    # type: (str) -> Dict[str, Any]
    """Explicitly re-run email detection from alert_actions.conf."""
    result = {}  # type: Dict[str, Any]
    try:
        from splunk_connect import get_service
        service = get_service(session_key, app="QueryTester", owner="nobody")
        resp = service.get("configs/conf-alert_actions/email", output_mode="json")
        data = json.loads(resp.body.read())
        content = data.get("entry", [{}])[0].get("content", {})
        _map_email_fields(content, result)
        result["source"] = "splunk_native"
    except Exception as exc:
        logger.debug("Email detection failed: %s", exc)
        result["source"] = "none"
    return result


def _detect_server_info(service, detected):
    # type: (Any, Dict[str, Any]) -> None
    try:
        resp = service.get("server/info", output_mode="json")
        data = json.loads(resp.body.read())
        content = data.get("entry", [{}])[0].get("content", {})
        host = content.get("host_fqdn") or content.get("host", "")
        if host:
            detected["splunk_host"] = host
        mgmt_port = content.get("mgmtHostPort", "")
        if ":" in mgmt_port:
            detected["splunk_port"] = mgmt_port.split(":")[-1]
    except Exception as exc:
        logger.debug("server/info detection failed: %s", exc)


def _detect_server_settings(service, detected):
    # type: (Any, Dict[str, Any]) -> None
    try:
        resp = service.get("server/settings", output_mode="json")
        data = json.loads(resp.body.read())
        content = data.get("entry", [{}])[0].get("content", {})
        http_port = content.get("httpport", "")
        host = detected.get("splunk_host", "localhost")
        enable_ssl = content.get("enableSplunkWebSSL", False)
        scheme = "https" if enable_ssl else "http"
        if http_port:
            detected["splunk_web_url"] = "{0}://{1}:{2}".format(scheme, host, http_port)
    except Exception as exc:
        logger.debug("server/settings detection failed: %s", exc)


def _detect_hec(service, detected):
    # type: (Any, Dict[str, Any]) -> None
    try:
        resp = service.get("data/inputs/http", output_mode="json")
        data = json.loads(resp.body.read())
        entries = data.get("entry", [])

        for entry in entries:
            name = entry.get("name", "")
            content = entry.get("content", {})
            if name == "http":
                port = content.get("port", "")
                if port:
                    detected["hec_port"] = str(port)
                ssl = content.get("enableSSL", True)
                detected["hec_ssl_verify"] = "false"
                detected["hec_scheme"] = "https" if ssl else "http"
                host = detected.get("splunk_host", "localhost")
                detected["hec_host"] = host
                break

        token_entries = [e for e in entries if e.get("name", "") != "http"]
        if len(token_entries) == 1:
            token_val = token_entries[0].get("content", {}).get("token", "")
            if token_val:
                detected["hec_token"] = token_val
    except Exception as exc:
        logger.debug("HEC detection failed: %s", exc)


def _detect_email(service, detected):
    # type: (Any, Dict[str, Any]) -> None
    try:
        resp = service.get("configs/conf-alert_actions/email", output_mode="json")
        data = json.loads(resp.body.read())
        content = data.get("entry", [{}])[0].get("content", {})
        _map_email_fields(content, detected)
    except Exception as exc:
        logger.debug("Email detection failed: %s", exc)


def _map_email_fields(content, detected):
    # type: (Dict[str, Any], Dict[str, Any]) -> None
    """Map alert_actions.conf [email] fields to app config fields."""
    mailserver = content.get("mailserver", "")
    if mailserver:
        if ":" in mailserver:
            parts = mailserver.rsplit(":", 1)
            detected["smtp_server"] = parts[0]
            detected["smtp_port"] = parts[1]
        else:
            detected["smtp_server"] = mailserver

    mail_from = content.get("from", "")
    if mail_from:
        detected["mail_from"] = mail_from

    use_ssl = str(content.get("use_ssl", "0"))
    use_tls = str(content.get("use_tls", "0"))
    if use_ssl in ("1", "true", "True"):
        detected["tls_mode"] = "ssl"
    elif use_tls in ("1", "true", "True"):
        detected["tls_mode"] = "starttls"

    auth_user = content.get("auth_username", "")
    if auth_user:
        detected["smtp_username"] = auth_user
        detected["email_auth_method"] = "password"


def _detect_temp_index(service, detected):
    # type: (Any, Dict[str, Any]) -> None
    try:
        service.get("data/indexes/temp_query_tester", output_mode="json")
        detected["temp_index"] = "temp_query_tester"
    except Exception:
        pass
