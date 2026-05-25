# -*- coding: utf-8 -*-
"""
Manual email send test — standalone, throwaway.

Run from repo root:
    py packages/query-tester/stage/bin/tests/test_email_manual.py

Or from bin/:
    py tests/test_email_manual.py

CONFIRMED WORKING SETTINGS:
    (fill in after successful send)
    SMTP_SERVER = ???
    SMTP_PORT   = ???
    AUTH        = ???
    TLS         = ???
"""
from __future__ import annotations

import os
import sys
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Path setup so we can import from bin/ ────────────────────────────────────
_this_dir = os.path.dirname(os.path.abspath(__file__))
_bin_dir = os.path.dirname(_this_dir)
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

# ── Test recipient (hardcoded, do NOT change config.py) ─────────────────────
TEST_RECIPIENT = "guystern007@outlook.com"

# ── SMTP configs to try, in order ────────────────────────────────────────────
# ── Override via environment variables for interactive use ────────────────
# Set SMTP_USER and SMTP_PASS env vars to authenticate.
# Example:
#   set SMTP_USER=guystern007@outlook.com
#   set SMTP_PASS=your-app-password
#   py tests/test_email_manual.py
_env_user = os.environ.get("SMTP_USER", "")
_env_pass = os.environ.get("SMTP_PASS", "")
_env_auth = (_env_user, _env_pass) if _env_user else None
_env_from = _env_user if _env_user else "svc_ijump@souf.org"

SMTP_ATTEMPTS = [
    # --- Corporate relay (only works on internal network) ---
    {
        "label": "CASNLB:25 (plain, no auth)",
        "host": "CASNLB",
        "port": 25,
        "use_starttls": False,
        "auth": None,
        "mail_from": "svc_ijump@souf.org",
    },
    # --- Outlook SMTP with env-var credentials ---
    {
        "label": "smtp-mail.outlook.com:587 (STARTTLS, env auth)",
        "host": "smtp-mail.outlook.com",
        "port": 587,
        "use_starttls": True,
        "auth": _env_auth,
        "mail_from": _env_from,
    },
    # --- Outlook SMTP_SSL on port 465 ---
    {
        "label": "smtp-mail.outlook.com:465 (SSL, env auth)",
        "host": "smtp-mail.outlook.com",
        "port": 465,
        "use_starttls": False,
        "use_ssl": True,
        "auth": _env_auth,
        "mail_from": _env_from,
    },
    # --- O365 SMTP with env-var credentials ---
    {
        "label": "smtp.office365.com:587 (STARTTLS, env auth)",
        "host": "smtp.office365.com",
        "port": 587,
        "use_starttls": True,
        "auth": _env_auth,
        "mail_from": _env_from,
    },
    # --- localhost relay (if Splunk or other relay is running) ---
    {
        "label": "localhost:25 (plain, no auth)",
        "host": "localhost",
        "port": 25,
        "use_starttls": False,
        "auth": None,
        "mail_from": "svc_ijump@souf.org",
    },
]


def build_test_email_via_module():
    """Use the real alert_email module to build the HTML body."""
    from alerts.alert_email import build_failure_email

    test_name = "E2E Email Test — Manual Verification"
    ran_at = "2026-03-16T14:30:00Z"
    status = "fail"
    spl_drift = False

    scenario_results = [
        {
            "scenarioName": "Scenario 1: Login failures",
            "passed": False,
            "error": "",
            "resultCount": 5,
            "validations": [
                {
                    "field": "src_ip",
                    "condition": "exists",
                    "expected": "",
                    "actual": "10.0.0.1",
                    "passed": True,
                    "message": "",
                },
                {
                    "field": "action",
                    "condition": "equals",
                    "expected": "failure",
                    "actual": "success",
                    "passed": False,
                    "message": "Expected 'failure' but got 'success'",
                },
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
                {
                    "field": "count",
                    "condition": "greater_than",
                    "expected": "0",
                    "actual": "10",
                    "passed": True,
                    "message": "",
                },
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
        test_name=test_name,
        ran_at=ran_at,
        status=status,
        scenario_results=scenario_results,
        spl_drift_detected=spl_drift,
        test_id="test-abc-123",
        full_results=full_results,
    )

    return subject, html_body


def try_send(attempt, subject, html_body):
    """Try a single SMTP configuration. Returns True on success."""
    label = attempt["label"]
    host = attempt["host"]
    port = attempt["port"]
    use_starttls = attempt["use_starttls"]
    auth = attempt["auth"]

    print("\n" + "=" * 60)
    print("ATTEMPT: {0}".format(label))
    print("=" * 60)

    mail_from = attempt.get("mail_from", "svc_ijump@souf.org")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = TEST_RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    use_ssl = attempt.get("use_ssl", False)

    try:
        print("  Connecting to {0}:{1} (ssl={2}) ...".format(host, port, use_ssl))
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        server.set_debuglevel(1)  # full SMTP conversation to stdout

        if use_starttls and not use_ssl:
            print("  Sending STARTTLS ...")
            server.starttls()

        if auth:
            print("  Authenticating as {0} ...".format(auth[0]))
            server.login(auth[0], auth[1])

        print("  Sending from {0} to {1} ...".format(mail_from, TEST_RECIPIENT))
        server.sendmail(mail_from, [TEST_RECIPIENT], msg.as_string())
        server.quit()

        print("\n  >>> SUCCESS: Email sent via {0} <<<".format(label))
        return True

    except smtplib.SMTPAuthenticationError as e:
        print("\n  FAILED (auth error): {0}".format(e))
        traceback.print_exc()
        return False
    except smtplib.SMTPException as e:
        print("\n  FAILED (SMTP error): {0}".format(e))
        traceback.print_exc()
        return False
    except OSError as e:
        print("\n  FAILED (connection error): {0}".format(e))
        traceback.print_exc()
        return False
    except Exception as e:
        print("\n  FAILED (unexpected): {0}".format(e))
        traceback.print_exc()
        return False


def main():
    global SMTP_ATTEMPTS

    print("Building email using alert_email module ...")
    try:
        subject, html_body = build_test_email_via_module()
    except Exception as e:
        print("ERROR: Failed to build email body: {0}".format(e))
        traceback.print_exc()
        sys.exit(1)

    print("Subject: {0}".format(subject))
    print("Body length: {0} chars".format(len(html_body)))
    print("Recipient: {0}".format(TEST_RECIPIENT))

    # Save HTML preview so content can be verified in a browser
    preview_path = os.path.join(_this_dir, "email_preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>{0}</title></head><body style='background:#1e293b;padding:40px'>"
                "{1}</body></html>".format(subject, html_body))
    print("HTML preview saved to: {0}".format(preview_path))

    # If no env-var credentials, prompt the user
    if not _env_user:
        print("\n--- No SMTP_USER env var set. ---")
        print("Outlook SMTP requires authentication.")
        print("You can set SMTP_USER and SMTP_PASS env vars, or enter now:")
        try:
            user_input = input("  SMTP username (e.g. guystern007@outlook.com), or Enter to skip: ").strip()
            if user_input:
                import getpass
                pass_input = getpass.getpass("  SMTP password (or app password): ")
                # Rebuild attempts with interactive credentials
                SMTP_ATTEMPTS = [
                    {
                        "label": "CASNLB:25 (plain, no auth)",
                        "host": "CASNLB",
                        "port": 25,
                        "use_starttls": False,
                        "auth": None,
                        "mail_from": "svc_ijump@souf.org",
                    },
                    {
                        "label": "smtp-mail.outlook.com:587 (STARTTLS, interactive auth)",
                        "host": "smtp-mail.outlook.com",
                        "port": 587,
                        "use_starttls": True,
                        "auth": (user_input, pass_input),
                        "mail_from": user_input,
                    },
                    {
                        "label": "smtp.office365.com:587 (STARTTLS, interactive auth)",
                        "host": "smtp.office365.com",
                        "port": 587,
                        "use_starttls": True,
                        "auth": (user_input, pass_input),
                        "mail_from": user_input,
                    },
                ]
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipping interactive auth.")

    for attempt in SMTP_ATTEMPTS:
        if attempt.get("auth") is None and attempt["host"] != "CASNLB" and attempt["host"] != "localhost":
            print("\n  Skipping {0} (no credentials)".format(attempt["label"]))
            continue
        success = try_send(attempt, subject, html_body)
        if success:
            print("\n" + "=" * 60)
            print("DONE — email sent successfully.")
            print("Working config: {0}".format(attempt["label"]))
            print("Update config.py with these settings.")
            print("=" * 60)
            sys.exit(0)

    print("\n" + "=" * 60)
    print("ALL ATTEMPTS FAILED — no email was sent.")
    print("Check SMTP server availability, firewall rules, and credentials.")
    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()
