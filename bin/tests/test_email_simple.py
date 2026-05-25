# -*- coding: utf-8 -*-
"""Simple Gmail SMTP send test."""
from __future__ import annotations
import os, sys, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_this_dir = os.path.dirname(os.path.abspath(__file__))
_bin_dir = os.path.dirname(_this_dir)
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

EMAIL = "guystern007@gmail.com"
PASSWORD = "ggdneiqkpowiluxh"

from alerts.alert_email import build_failure_email
subject, body = build_failure_email(
    test_name="E2E Email Test - Manual Verification",
    ran_at="2026-03-16T14:30:00Z", status="fail",
    scenario_results=[
        {"scenarioName": "Scenario 1: Login failures", "passed": False, "error": "", "resultCount": 5,
         "validations": [
             {"field": "src_ip", "condition": "exists", "expected": "", "actual": "10.0.0.1", "passed": True, "message": ""},
             {"field": "action", "condition": "equals", "expected": "failure", "actual": "success", "passed": False, "message": "Expected 'failure' but got 'success'"},
         ],
         "resultRows": [
             {"src_ip": "10.0.0.1", "action": "success", "user": "admin", "count": "3"},
             {"src_ip": "10.0.0.2", "action": "failure", "user": "bob", "count": "1"},
             {"src_ip": "10.0.0.3", "action": "success", "user": "alice", "count": "7"},
         ]},
        {"scenarioName": "Scenario 2: Index check", "passed": True, "error": "", "resultCount": 10,
         "validations": [{"field": "count", "condition": "greater_than", "expected": "0", "actual": "10", "passed": True, "message": ""}],
         "resultRows": []},
    ],
    spl_drift_detected=False, test_id="test-abc-123",
    full_results={"passedScenarios": 1, "totalScenarios": 2, "message": "1 of 2 scenarios failed"},
)

msg = MIMEMultipart()
msg["Subject"] = subject
msg["From"] = EMAIL
msg["To"] = EMAIL
msg.attach(MIMEText(body, "html", "utf-8"))

print("Connecting to smtp.gmail.com:587 ...")
server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
server.starttls()
server.login(EMAIL, PASSWORD)
server.sendmail(EMAIL, [EMAIL], msg.as_string())
server.quit()
print("SUCCESS — email sent to " + EMAIL)
