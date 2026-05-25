# -*- coding: utf-8 -*-
"""
bug_report_handler.py — Send bug report / feature request emails via SMTP.
"""
from __future__ import annotations

import json
import re
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from typing import Any, Dict

from logger import get_logger
from alerts.email_utils import get_email_config, is_valid_email, send_smtp_message
from alerts.alert_email_tables import esc

logger = get_logger(__name__)

SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_\-]")


def _build_attachment(payload):
    # type: (Dict[str, Any]) -> MIMEBase
    """Wrap payload in the app's import format for the JSON attachment."""
    tests = payload.get("allTests") or []
    current = payload.get("currentTest")
    if current and current not in tests:
        tests = [current] + tests
    active_id = current.get("id", "") if current else ""
    if not active_id and tests:
        active_id = tests[0].get("id", "")
    importable = {
        "version": 2,
        "savedAt": payload.get("reportGeneratedAt", ""),
        "activeTestId": active_id,
        "testDefinition": tests,
        "payload": [],
    }  # type: Dict[str, Any]
    if payload.get("testResponse"):
        importable["testResults"] = payload["testResponse"]
    content = json.dumps(importable, indent=2, default=str)
    part = MIMEBase("application", "json")
    part.set_payload(content.encode("utf-8"))
    encoders.encode_base64(part)
    name = current.get("name", "") if current else ""
    if not name:
        name = "report"
    safe = SAFE_NAME_PATTERN.sub("_", name)[:60]
    part.add_header(
        "Content-Disposition", "attachment",
        filename="splunk-query-tester-{0}.json".format(safe),
    )
    return part


def _build_html(report_type, description, username):
    # type: (str, str, str) -> str
    """Outlook-compatible table-based HTML for bug report emails."""
    label = "Bug Report" if report_type == "bug" else "Feature Request"
    color = "#dc2626" if report_type == "bug" else "#2563eb"
    accent_bg = "#fef2f2" if report_type == "bug" else "#eff6ff"
    return (
        "<!DOCTYPE html>"
        '<html><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="light dark">'
        "</head><body style=\"margin:0;padding:0;background-color:#f3f4f6;"
        'font-family:Arial,sans-serif">'
        "<!--[if mso]>"
        '<table cellpadding="0" cellspacing="0" border="0" width="600"'
        ' align="center"><tr><td><![endif]-->'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' style="max-width:600px;margin:0 auto">'
        '<tr><td bgcolor="{color}" style="padding:0;height:4px;'
        'font-size:0;line-height:0">&nbsp;</td></tr>'
        '<tr bgcolor="#ffffff"><td style="padding:24px 24px 16px">'
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td bgcolor="{accent_bg}" style="padding:4px 12px;font-size:11px;'
        'font-weight:bold;color:{color};font-family:Arial,sans-serif;'
        'letter-spacing:0.5px">{label}</td></tr></table>'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' style="margin-top:12px">'
        '<tr><td style="font-size:20px;font-weight:bold;color:#1f2937;'
        'font-family:Arial,sans-serif">Query Tester {label}</td></tr>'
        "</table></td></tr>"
        '<tr bgcolor="#ffffff"><td style="padding:0 24px 16px">'
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="padding:4px 0;font-size:13px;color:#6b7280;'
        'font-weight:bold;font-family:Arial,sans-serif;width:100px">'
        "Reported by:</td>"
        '<td style="padding:4px 12px;font-size:13px;color:#374151;'
        'font-family:Arial,sans-serif">{user}</td>'
        "</tr></table></td></tr>"
        '<tr bgcolor="#ffffff"><td style="padding:0 24px 24px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr><td style="padding:0 0 6px;font-size:12px;font-weight:bold;'
        'color:#6b7280;font-family:Arial,sans-serif">Description</td></tr>'
        '<tr><td bgcolor="#f9fafb" style="padding:12px;font-size:14px;'
        "color:#374151;font-family:Arial,sans-serif;"
        'border:1px solid #e5e7eb;white-space:pre-wrap">{desc}</td></tr>'
        "</table></td></tr>"
        '<tr><td bgcolor="#f9fafb" style="padding:14px 24px;border-top:1px '
        'solid #e5e7eb;font-size:11px;color:#9ca3af;'
        'font-family:Arial,sans-serif">'
        "The full test definition and results are attached as a JSON file."
        "</td></tr></table>"
        "<!--[if mso]></td></tr></table><![endif]-->"
        "</body></html>"
    ).format(
        color=color, accent_bg=accent_bg, label=label,
        user=esc(username), desc=esc(description),
    )


def send_bug_report(session_key, report_type, description, username, payload):
    # type: (str, str, str, str, Dict[str, Any]) -> None
    """Send a bug report email with JSON attachment to the default email."""
    cfg = get_email_config(session_key)
    recipient = cfg["default_alert_email"]

    if not recipient or not is_valid_email(recipient):
        raise ValueError(
            "No valid default alert email configured. "
            "Set it in the Admin Setup page."
        )

    label = "Bug Report" if report_type == "bug" else "Feature Request"
    subject = "[Query Tester] {0}: {1}".format(
        label,
        (description[:60] + "...") if len(description) > 60 else description,
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = cfg["mail_from"]
    msg["To"] = recipient.strip()
    msg.attach(MIMEText(_build_html(report_type, description, username),
                        "html", "utf-8"))
    msg.attach(_build_attachment(payload))

    logger.info(
        "Sending bug report email to %s (server=%s port=%s auth=%s)",
        recipient, cfg["smtp_server"], cfg["smtp_port"],
        cfg.get("email_auth_method"),
    )
    send_smtp_message(cfg, msg, [recipient.strip()])
    logger.info("Bug report email sent successfully to %s", recipient)
