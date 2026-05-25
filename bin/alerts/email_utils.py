# -*- coding: utf-8 -*-
"""
email_utils.py — Shared email configuration, validation, and SMTP transport.

Used by alert_email.py (failure notifications) and bug_report_handler.py
(bug reports). Centralises config loading and SMTP connection logic.
"""
from __future__ import annotations

import re
import smtplib
from typing import Any, Dict, List, Optional

from config import (
    SMTP_SERVER, SMTP_PORT, MAIL_FROM, DEFAULT_ALERT_EMAIL, SPLUNK_WEB_URL,
)
from logger import get_logger

logger = get_logger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(address):
    # type: (str) -> bool
    """Return True if *address* looks like a valid email."""
    return bool(EMAIL_PATTERN.match(address.strip()))


def infer_tls_mode(stored_mode, smtp_port, auth_method):
    # type: (str, int, str) -> str
    """Auto-detect TLS mode from port when not explicitly configured."""
    if stored_mode:
        return stored_mode
    if auth_method in ("password", "oauth2", "apikey"):
        if smtp_port == 465:
            return "ssl"
        if smtp_port == 587:
            return "starttls"
    return ""


def get_email_config(session_key=None):
    # type: (Optional[str]) -> Dict[str, Any]
    """Load email/SMTP config from runtime config or fall back to config.py."""
    if session_key:
        try:
            from runtime_config import get_runtime_config
            cfg = get_runtime_config(session_key)
            port = int(cfg.get("smtp_port", SMTP_PORT))
            auth = cfg.get("email_auth_method", "none")
            tls = infer_tls_mode(cfg.get("tls_mode", ""), port, auth)
            # Build web URL from splunk_host + scheme (Setup page fields).
            # splunk_web_url is rarely set directly; fall back to host/scheme.
            web_url = cfg.get("splunk_web_url", "")
            if not web_url or "localhost" in web_url or "127.0.0.1" in web_url:
                host = cfg.get("splunk_host", "")
                scheme = cfg.get("splunk_scheme", "https")
                web_port = cfg.get("splunk_web_port", "443")
                if host and host not in ("localhost", "127.0.0.1"):
                    # Omit port for standard ports (443 for https, 80 for http)
                    if (scheme == "https" and web_port == "443") or (scheme == "http" and web_port == "80"):
                        web_url = "{0}://{1}".format(scheme, host)
                    else:
                        web_url = "{0}://{1}:{2}".format(scheme, host, web_port)
                else:
                    web_url = SPLUNK_WEB_URL
            return {
                "smtp_server": cfg.get("smtp_server", SMTP_SERVER),
                "smtp_port": port,
                "mail_from": cfg.get("mail_from", MAIL_FROM),
                "default_alert_email": cfg.get(
                    "default_alert_email", DEFAULT_ALERT_EMAIL,
                ),
                "splunk_web_url": web_url,
                "smtp_password": cfg.get("smtp_password", ""),
                "smtp_username": cfg.get("smtp_username", ""),
                "email_auth_method": auth,
                "tls_mode": tls,
            }
        except Exception as exc:
            logger.warning(
                "Runtime config unavailable, using static config: %s", exc,
            )
    return {
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "mail_from": MAIL_FROM,
        "default_alert_email": DEFAULT_ALERT_EMAIL,
        "splunk_web_url": SPLUNK_WEB_URL,
        "smtp_password": "",
        "smtp_username": "",
        "email_auth_method": "none",
        "tls_mode": "",
    }


def send_smtp_message(cfg, msg, recipients):
    # type: (Dict[str, Any], Any, List[str]) -> None
    """Open an SMTP connection using *cfg* and send *msg* to *recipients*."""
    smtp_server = cfg["smtp_server"]
    smtp_port = int(cfg["smtp_port"])
    mail_from = cfg["mail_from"]
    tls_mode = cfg.get("tls_mode", "")
    auth_method = cfg.get("email_auth_method", "none")
    smtp_username = cfg.get("smtp_username", "")
    smtp_password = cfg.get("smtp_password", "")

    if tls_mode == "ssl":
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
    else:
        server = smtplib.SMTP(smtp_server, smtp_port)
        if tls_mode == "starttls":
            server.starttls()
    if auth_method == "password" and smtp_username and smtp_password:
        server.login(smtp_username, smtp_password)
    server.sendmail(mail_from, recipients, msg.as_string())
    server.quit()
