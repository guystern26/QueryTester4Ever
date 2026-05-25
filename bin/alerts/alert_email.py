# -*- coding: utf-8 -*-
"""
alert_email.py — Email sending for scheduled test failures.

Also exports ``build_result_summary`` and ``extract_scenario_results``
(merged from the former alert_helpers.py).
"""
from __future__ import annotations

import json
import re
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from typing import Any, Dict, List, Optional

from config import SPLUNK_WEB_URL
from logger import get_logger
from alerts.email_utils import get_email_config, is_valid_email, send_smtp_message
from alerts.alert_email_body import build_failure_email

logger = get_logger(__name__)

SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_\-]")


# ---------------------------------------------------------------------------
# Result summary helpers (merged from alert_helpers.py)
# ---------------------------------------------------------------------------

def build_result_summary(result):
    # type: (Dict[str, Any]) -> str
    """Build a human-readable summary from the test result."""
    status = result.get("status", "error")
    passed = result.get("passedScenarios", 0)
    total = result.get("totalScenarios", 0)
    return "Status: {0}, Passed: {1}/{2}".format(status, passed, total)


def extract_scenario_results(result):
    # type: (Dict[str, Any]) -> List[Dict[str, Any]]
    """Extract scenario results for the history record."""
    return [
        {
            "scenarioId": sr.get("scenarioId", ""),
            "scenarioName": sr.get("scenarioName", ""),
            "passed": sr.get("passed", False),
            "message": sr.get("message", ""),
        }
        for sr in result.get("scenarioResults", [])
    ]


def _build_attachment(test_name, definition, full_results):
    # type: (str, Dict[str, Any], Optional[Dict[str, Any]]) -> MIMEBase
    """Build JSON attachment matching the app's import format."""
    test_id = definition.get("id", "")
    payload = {
        "version": 2,
        "savedAt": full_results.get("timestamp", "") if full_results else "",
        "activeTestId": test_id,
        "testDefinition": [definition],
        "payload": [],
    }  # type: Dict[str, Any]
    if full_results:
        payload["testResults"] = full_results

    content = json.dumps(payload, indent=2, default=str)
    part = MIMEBase("application", "json")
    part.set_payload(content.encode("utf-8"))
    encoders.encode_base64(part)

    safe_name = SAFE_NAME_PATTERN.sub("_", test_name)[:60]
    filename = "splunk-query-tester-{0}.json".format(safe_name)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


def _deduplicate_recipients(recipients, default_email):
    # type: (List[str], str) -> List[str]
    """Deduplicate, validate, and fall back to default if empty."""
    if not recipients:
        recipients = [default_email]
    valid = []  # type: List[str]
    seen = set()  # type: set
    for r in recipients:
        addr = r.strip() if r else ""
        if not addr or addr.lower() in seen:
            continue
        if not is_valid_email(addr):
            logger.warning("Skipping malformed email address: %s", addr)
            continue
        seen.add(addr.lower())
        valid.append(addr)
    return valid


def send_failure_emails(
    recipients,          # type: List[str]
    test_name,           # type: str
    ran_at,              # type: str
    status,              # type: str
    scenario_results,    # type: List[Dict[str, Any]]
    spl_drift_detected,  # type: bool
    test_id="",          # type: str
    definition=None,     # type: Optional[Dict[str, Any]]
    full_results=None,   # type: Optional[Dict[str, Any]]
    session_key=None,    # type: Optional[str]
):
    # type: (...) -> None
    """Send failure notification to all valid recipients."""
    email_cfg = get_email_config(session_key)
    web_url = email_cfg.get("splunk_web_url", SPLUNK_WEB_URL)

    logger.info(
        "Email config: server=%s port=%s auth=%s tls=%s from=%s",
        email_cfg["smtp_server"], email_cfg["smtp_port"],
        email_cfg.get("email_auth_method"), email_cfg.get("tls_mode"),
        email_cfg["mail_from"],
    )

    valid = _deduplicate_recipients(recipients, email_cfg["default_alert_email"])
    if not valid:
        logger.warning("No valid recipients for test '%s'", test_name)
        return

    subject, html_body = build_failure_email(
        test_name, ran_at, status, scenario_results, spl_drift_detected,
        test_id=test_id, full_results=full_results, splunk_web_url=web_url,
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = email_cfg["mail_from"]
    msg["To"] = ", ".join(valid)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if definition:
        msg.attach(_build_attachment(test_name, definition, full_results))

    try:
        send_smtp_message(email_cfg, msg, valid)
        logger.info(
            "Failure email sent to %s for test '%s'",
            ", ".join(valid), test_name,
        )
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", ", ".join(valid), exc)
