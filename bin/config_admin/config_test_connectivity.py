# -*- coding: utf-8 -*-
"""
config_test_connectivity.py — Live connectivity tests for HEC and SMTP.
Called by config_handler POST /test endpoint.
"""
from __future__ import annotations

import http.client
import smtplib
import ssl
import urllib.parse
from typing import Any, Dict

from logger import get_logger

logger = get_logger(__name__)


def test_connectivity(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Run HEC and SMTP connectivity tests. Returns combined status dict."""
    result = _test_hec(config)
    result.update(_test_smtp(config))
    return result


def _test_hec(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    hec_host = config.get("hec_host", "")
    hec_port = config.get("hec_port", "8088")
    hec_token = config.get("hec_token", "")
    if not hec_host or not hec_token:
        return {"hec": "error", "hec_detail": "HEC host or token not configured"}
    try:
        conn = _make_conn(config.get("hec_scheme", "https"), hec_host, int(hec_port))
        conn.request("GET", "/services/collector/health",
                     headers={"Authorization": "Splunk " + hec_token})
        status = conn.getresponse().status
        conn.close()
        if status == 200:
            return {"hec": "ok", "hec_detail": "HEC reachable on port {0}".format(hec_port)}
        return {"hec": "error", "hec_detail": "HEC returned status {0}".format(status)}
    except Exception as exc:
        return {"hec": "error", "hec_detail": str(exc)}


def _test_smtp(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    auth_method = config.get("email_auth_method", "none")
    handler = SMTP_HANDLERS.get(auth_method, _smtp_unknown)
    return handler(config)


def _smtp_plain(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    server = config.get("smtp_server", "")
    port = int(config.get("smtp_port", 25))
    if not server:
        return {"smtp": "error", "smtp_detail": "SMTP server not configured"}
    for mode, factory in [("starttls", _try_starttls), ("ssl", _try_ssl), ("plain", _try_plain)]:
        result = factory(server, port)
        if result:
            return {"smtp": "ok", "smtp_detail": result, "tls_mode": mode}
    return {"smtp": "error", "smtp_detail": "All connection methods failed", "tls_mode": None}


def _try_starttls(server, port):
    # type: (str, int) -> str
    try:
        c = smtplib.SMTP(server, port, timeout=10)
        c.ehlo()
        c.starttls()
        c.ehlo()
        c.quit()
        return "Connected via STARTTLS on port {0}".format(port)
    except Exception:
        return ""


def _try_ssl(server, port):
    # type: (str, int) -> str
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        c = smtplib.SMTP_SSL(server, port, timeout=10, context=ctx)
        c.ehlo()
        c.quit()
        return "Connected via SSL on port {0}".format(port)
    except Exception:
        return ""


def _try_plain(server, port):
    # type: (str, int) -> str
    try:
        c = smtplib.SMTP(server, port, timeout=10)
        c.ehlo()
        c.quit()
        return "Connected (plain) on port {0}".format(port)
    except Exception:
        return ""


def _smtp_password(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    server = config.get("smtp_server", "")
    port = int(config.get("smtp_port", 587))
    username = config.get("smtp_username", "")
    password = config.get("smtp_password", "")
    if not server:
        return {"smtp": "error", "smtp_detail": "SMTP server not configured"}
    if not username or not password:
        return {"smtp": "error", "smtp_detail": "SMTP username or password not set"}
    tls_mode = config.get("tls_mode", "starttls")
    try:
        if tls_mode == "ssl":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            c = smtplib.SMTP_SSL(server, port, timeout=10, context=ctx)
        else:
            c = smtplib.SMTP(server, port, timeout=10)
            c.ehlo()
            c.starttls()
            c.ehlo()
        c.login(username, password)
        c.quit()
        return {"smtp": "ok", "smtp_detail": "Authenticated via {0} on port {1}".format(tls_mode, port), "tls_mode": tls_mode}
    except Exception as exc:
        return {"smtp": "error", "smtp_detail": str(exc), "tls_mode": tls_mode}


def _smtp_oauth2(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    client_id = config.get("oauth_client_id", "")
    client_secret = config.get("oauth_client_secret", "")
    token_url = config.get("oauth_token_url", "")
    if not client_id or not client_secret or not token_url:
        return {"smtp": "error", "smtp_detail": "OAuth2 credentials incomplete"}
    try:
        parsed = urllib.parse.urlparse(token_url)
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": client_id,
            "client_secret": client_secret,
            "scope": config.get("oauth_scope", "https://outlook.office365.com/.default"),
        })
        conn = _make_conn(parsed.scheme, parsed.hostname, parsed.port or 443)
        conn.request("POST", parsed.path, body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        status = conn.getresponse().status
        conn.close()
        if status == 200:
            return {"smtp": "ok", "smtp_detail": "OAuth2 token acquired", "tls_mode": None}
        return {"smtp": "error", "smtp_detail": "Token request failed: {0}".format(status), "tls_mode": None}
    except Exception as exc:
        return {"smtp": "error", "smtp_detail": str(exc), "tls_mode": None}


def _smtp_apikey(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    if not config.get("email_api_key"):
        return {"smtp": "error", "smtp_detail": "Email API key not set"}
    return {"smtp": "ok", "smtp_detail": "API key configured", "tls_mode": None}


def _smtp_unknown(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    return {"smtp": "error", "smtp_detail": "Unknown auth method", "tls_mode": None}


def _make_conn(scheme, host, port):
    # type: (str, str, int) -> Any
    if scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return http.client.HTTPSConnection(host, port, context=ctx, timeout=10)
    return http.client.HTTPConnection(host, port, timeout=10)


SMTP_HANDLERS = {
    "none": _smtp_plain,
    "password": _smtp_password,
    "oauth2": _smtp_oauth2,
    "apikey": _smtp_apikey,
}
