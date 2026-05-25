# -*- coding: utf-8 -*-
"""
Send test email via Outlook SMTP using OAuth2 (XOAUTH2).

Uses MSAL device-code flow so no app registration is needed.
Authenticates with the well-known Thunderbird client ID.

Run:
    py tests/test_email_oauth.py
"""
from __future__ import annotations

import base64
import os
import sys
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import msal

# ── Path setup ───────────────────────────────────────────────────────────────
_this_dir = os.path.dirname(os.path.abspath(__file__))
_bin_dir = os.path.dirname(_this_dir)
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

# ── Config ───────────────────────────────────────────────────────────────────
TEST_RECIPIENT = "guystern007@outlook.com"
SENDER = "guystern007@outlook.com"
SMTP_HOST = "smtp-mail.outlook.com"
SMTP_PORT = 587

# Thunderbird public client ID — works for personal Microsoft accounts.
CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
SCOPES = ["https://outlook.office.com/SMTP.Send"]


def get_oauth_token():
    """Acquire an OAuth2 access token via device-code flow."""
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/consumers",
    )

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Failed to create device flow: {0}".format(flow))

    print("\n" + "=" * 60)
    print("To authenticate, open a browser and go to:")
    print("  {0}".format(flow["verification_uri"]))
    print("Enter this code: {0}".format(flow["user_code"]))
    print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError("Token acquisition failed: {0}".format(
            result.get("error_description", result)))

    print("Token acquired for: {0}".format(result.get("id_token_claims", {}).get("preferred_username", "unknown")))
    return result["access_token"]


def xoauth2_string(user, token):
    """Build the XOAUTH2 SASL string."""
    auth_str = "user={0}\x01auth=Bearer {1}\x01\x01".format(user, token)
    return auth_str


def build_email():
    """Build the test email using the real alert_email module."""
    from alerts.alert_email import build_failure_email

    scenario_results = [
        {
            "scenarioName": "Scenario 1: Login failures",
            "passed": False,
            "error": "",
            "resultCount": 5,
            "validations": [
                {"field": "src_ip", "condition": "exists", "expected": "",
                 "actual": "10.0.0.1", "passed": True, "message": ""},
                {"field": "action", "condition": "equals", "expected": "failure",
                 "actual": "success", "passed": False,
                 "message": "Expected 'failure' but got 'success'"},
            ],
            "resultRows": [
                {"src_ip": "10.0.0.1", "action": "success", "user": "admin", "count": "3"},
                {"src_ip": "10.0.0.2", "action": "failure", "user": "bob", "count": "1"},
                {"src_ip": "10.0.0.3", "action": "success", "user": "alice", "count": "7"},
            ],
        },
        {
            "scenarioName": "Scenario 2: Index check",
            "passed": True,
            "error": "",
            "resultCount": 10,
            "validations": [
                {"field": "count", "condition": "greater_than", "expected": "0",
                 "actual": "10", "passed": True, "message": ""},
            ],
            "resultRows": [],
        },
    ]

    full_results = {
        "passedScenarios": 1,
        "totalScenarios": 2,
        "message": "1 of 2 scenarios failed",
    }

    subject, html_body = build_failure_email(
        test_name="E2E Email Test - OAuth2 Verification",
        ran_at="2026-03-16T14:30:00Z",
        status="fail",
        scenario_results=scenario_results,
        spl_drift_detected=False,
        test_id="test-abc-123",
        full_results=full_results,
    )
    return subject, html_body


def main():
    print("Building email body ...")
    subject, html_body = build_email()
    print("Subject: {0}".format(subject))
    print("Body length: {0} chars".format(len(html_body)))

    # Save HTML preview
    preview_path = os.path.join(_this_dir, "email_preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>{0}</title></head><body style='background:#1e293b;padding:40px'>"
                "{1}</body></html>".format(subject, html_body))
    print("HTML preview: {0}".format(preview_path))

    print("\nAcquiring OAuth2 token ...")
    try:
        token = get_oauth_token()
    except Exception as e:
        print("ERROR getting token: {0}".format(e))
        traceback.print_exc()
        sys.exit(1)

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = TEST_RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print("\nConnecting to {0}:{1} ...".format(SMTP_HOST, SMTP_PORT))
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.set_debuglevel(1)
        server.ehlo()
        server.starttls()
        server.ehlo()

        # Authenticate with XOAUTH2
        auth_string = xoauth2_string(SENDER, token)
        auth_bytes = base64.b64encode(auth_string.encode("utf-8")).decode("ascii")
        code, resp = server.docmd("AUTH", "XOAUTH2 " + auth_bytes)
        if code != 235:
            print("AUTH failed: {0} {1}".format(code, resp))
            server.quit()
            sys.exit(1)

        print("\nAuthenticated! Sending email ...")
        server.sendmail(SENDER, [TEST_RECIPIENT], msg.as_string())
        server.quit()

        print("\n" + "=" * 60)
        print("SUCCESS! Email sent to {0}".format(TEST_RECIPIENT))
        print("Check your inbox.")
        print("=" * 60)

    except Exception as e:
        print("\nFAILED: {0}".format(e))
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
