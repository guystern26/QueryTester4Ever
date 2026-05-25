# -*- coding: utf-8 -*-
"""
ai_summary_action.py — Alert action: AI-powered summary email.

When a saved search fires, this action:
1. Reads the search results from the alert payload
2. Hashes the data (excluding AI fields) to detect changes
3. If data changed since last run → calls LLM for a new summary
4. If unchanged → reuses the cached summary (no LLM call)
5. Sends an email with the AI summary + a results table

Requires: LLM configured in config.py (LLM_ENDPOINT, LLM_API_KEY).
Rate limit: respects MIN_INTERVAL_SECS (10 min) between LLM calls.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from logger import get_logger
from aiguy.llm import get_llm_config, call_llm, log_usage
from aiguy.formatter import format_table
from aiguy.cache import load_cache, save_cache
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from alerts.email_utils import get_email_config, is_valid_email, send_smtp_message

logger = get_logger(__name__)

AI_SUMMARY_PROMPT = (
    "You are an alert analyst for Splunk. A saved search just triggered.\n"
    "Analyze the results and write a clear summary for the oncall engineer.\n\n"
    "Structure your response as:\n"
    "SEVERITY: (critical / warning / info)\n"
    "SUMMARY: 1-2 sentences on what happened.\n"
    "DETAILS: Key observations from the data (2-4 bullet points).\n"
    "ACTION: What should the oncall do next (1-2 sentences).\n\n"
    "Be specific — reference actual values, counts, and hosts from the data.\n"
    "No markdown code blocks. Use plain text only."
)

MAX_RESULTS_FOR_EMAIL = 50  # max rows in the email table
MAX_RESULTS_FOR_AI = 20     # max rows sent to LLM
MIN_CRON_INTERVAL_SECS = 600  # 10 min — reject faster schedules

_LAST_RUN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".aiguy_cache", "ai_summary_last_run.json",
)


def _check_rate_limit(search_name):
    # type: (str) -> Optional[str]
    """Return an error message if this search fired too recently, else None."""
    try:
        if os.path.exists(_LAST_RUN_FILE):
            with open(_LAST_RUN_FILE, "r") as f:
                last_runs = json.load(f)
        else:
            last_runs = {}
        last_ts = last_runs.get(search_name, 0)
        elapsed = time.time() - last_ts
        if elapsed < MIN_CRON_INTERVAL_SECS:
            remaining = int(MIN_CRON_INTERVAL_SECS - elapsed)
            return (
                "AI Summary skipped: search '{0}' fired {1}s ago "
                "(minimum interval is {2}s). "
                "Set your cron schedule to 10 minutes or more."
            ).format(search_name, int(elapsed), MIN_CRON_INTERVAL_SECS)
    except Exception:
        pass
    return None


def _record_run(search_name):
    # type: (str) -> None
    """Record that this search just ran."""
    try:
        cache_dir = os.path.dirname(_LAST_RUN_FILE)
        if not os.path.isdir(cache_dir):
            os.makedirs(cache_dir)
        last_runs = {}
        if os.path.exists(_LAST_RUN_FILE):
            with open(_LAST_RUN_FILE, "r") as f:
                last_runs = json.load(f)
        last_runs[search_name] = time.time()
        with open(_LAST_RUN_FILE, "w") as f:
            json.dump(last_runs, f)
    except Exception:
        pass


def _read_payload():
    # type: () -> Dict[str, Any]
    """Read the alert action payload from stdin."""
    raw = sys.stdin.read()
    return json.loads(raw)


def _read_results_from_payload(payload):
    # type: (Dict[str, Any]) -> List[Dict[str, str]]
    """Read search results from the results_file in the payload."""
    results_file = payload.get("results_file", "")
    if not results_file or not os.path.exists(results_file):
        return []
    rows = []
    with open(results_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _hash_results(rows):
    # type: (List[Dict[str, str]]) -> str
    """Hash results (excluding AI fields) for change detection."""
    skip = {"ai_answer", "aiguy_timestamp", "aiguy_source", "ai_summary"}
    filtered = []
    for row in rows:
        clean = {k: v for k, v in row.items() if k not in skip}
        filtered.append(json.dumps(clean, sort_keys=True))
    return hashlib.md5("\n".join(filtered).encode("utf-8")).hexdigest()


def _build_results_html(rows):
    # type: (List[Dict[str, str]]) -> str
    """Build an HTML table from search results."""
    if not rows:
        return "<p>No results.</p>"
    keys = [k for k in rows[0].keys() if not k.startswith("_")]
    if not keys:
        keys = list(rows[0].keys())
    keys = keys[:15]  # cap columns

    display_rows = rows[:MAX_RESULTS_FOR_EMAIL]
    header = "".join(
        '<th style="padding:6px 10px;text-align:left;font-size:12px;'
        'color:#94a3b8;border-bottom:2px solid #334155;'
        'font-family:Arial,sans-serif">{0}</th>'.format(_esc(k))
        for k in keys
    )
    body_rows = []
    for row in display_rows:
        cells = "".join(
            '<td style="padding:5px 10px;font-size:12px;color:#e2e8f0;'
            'border-bottom:1px solid #1e293b;font-family:Arial,sans-serif'
            '">{0}</td>'.format(_esc(str(row.get(k, "")))[:200])
            for k in keys
        )
        body_rows.append("<tr>{0}</tr>".format(cells))

    truncated = ""
    if len(rows) > MAX_RESULTS_FOR_EMAIL:
        truncated = (
            '<tr><td colspan="{0}" style="padding:8px 10px;font-size:11px;'
            'color:#64748b;font-style:italic;font-family:Arial,sans-serif">'
            "... {1} more rows not shown</td></tr>"
        ).format(len(keys), len(rows) - MAX_RESULTS_FOR_EMAIL)

    return (
        '<table style="width:100%;border-collapse:collapse;'
        'background:#0f172a;border:1px solid #1e293b">'
        "<tr>{header}</tr>{body}{truncated}</table>"
    ).format(header=header, body="".join(body_rows), truncated=truncated)


def _build_email_html(search_name, summary, results_html, cached):
    # type: (str, str, str, bool) -> str
    """Build the full email HTML."""
    cache_badge = ""
    if cached:
        cache_badge = (
            '<span style="display:inline-block;padding:2px 8px;'
            'font-size:10px;background:#1e293b;color:#64748b;'
            'border-radius:3px;margin-left:8px">cached</span>'
        )

    return """\
<html>
<body style="margin:0;padding:20px;background:#0f172a;color:#e2e8f0;
font-family:Arial,sans-serif">
<table style="width:100%;max-width:800px;margin:0 auto">
<tr><td>

<h2 style="color:#93c5fd;margin:0 0 4px 0;font-size:18px">
AI Alert Summary{cache_badge}</h2>
<p style="color:#64748b;font-size:12px;margin:0 0 16px 0">
{search_name}</p>

<div style="background:#162033;border:1px solid #334155;
border-left:3px solid #93c5fd;padding:16px;margin:0 0 20px 0">
<pre style="margin:0;white-space:pre-wrap;font-size:13px;
color:#e2e8f0;font-family:Arial,sans-serif;line-height:1.6">
{summary}</pre>
</div>

<h3 style="color:#94a3b8;font-size:14px;margin:0 0 8px 0">
Results</h3>
{results_html}

<p style="color:#475569;font-size:11px;margin:16px 0 0 0">
Powered by | aiguy &mdash; Query Tester AI</p>

</td></tr>
</table>
</body>
</html>""".format(
        cache_badge=cache_badge,
        search_name=_esc(search_name),
        summary=_esc(summary),
        results_html=results_html,
    )


def _esc(text):
    # type: (str) -> str
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def run():
    """Main entry point for the alert action."""
    t_start = time.time()

    try:
        payload = _read_payload()
    except Exception as exc:
        logger.error("Failed to read payload: %s", exc)
        return 1

    config = payload.get("configuration", {})
    search_name = payload.get("search_name", "Unknown Search")
    session_key = payload.get("session_key", "")
    recipients_raw = config.get("recipients", "")
    custom_prompt = config.get("prompt", "")

    # Rate limit: reject searches that fire more often than every 10 min
    rate_err = _check_rate_limit(search_name)
    if rate_err:
        logger.error(rate_err)
        return 1
    _record_run(search_name)

    # Parse recipients
    recipients = [
        r.strip() for r in recipients_raw.replace(";", ",").split(",")
        if r.strip() and is_valid_email(r.strip())
    ]
    if not recipients:
        from config import DEFAULT_ALERT_EMAIL
        if DEFAULT_ALERT_EMAIL:
            recipients = [DEFAULT_ALERT_EMAIL]
    if not recipients:
        logger.warning("No recipients configured for ai_summary action.")
        return 0

    # Read results
    rows = _read_results_from_payload(payload)
    if not rows:
        logger.info("No results for ai_summary — skipping.")
        return 0

    # Hash results for change detection
    data_hash = _hash_results(rows)
    cache_key = "summary_{0}".format(search_name)

    # Check cache: has data changed since last run?
    cached = load_cache("ai_summary", cache_key, "")
    last_hash = cached.get("_hash", "")
    last_summary = cached.get("_summary", "")
    use_cached = last_hash == data_hash and last_summary

    if use_cached:
        summary = last_summary
        logger.info(
            "ai_summary for '%s': data unchanged, using cached summary.",
            search_name,
        )
    else:
        # Data changed — call LLM
        try:
            llm_cfg = get_llm_config(session_key)
        except Exception as exc:
            logger.error("LLM config error: %s", exc)
            summary = "(AI summary unavailable: {0})".format(exc)
            use_cached = False
        else:
            prompt = custom_prompt or AI_SUMMARY_PROMPT
            table = format_table(rows[:MAX_RESULTS_FOR_AI])
            spl = payload.get("search", "")
            user_msg = (
                "Alert: {name}\n"
                "SPL: {spl}\n\n"
                "Results ({count} rows):\n{table}"
            ).format(
                name=search_name,
                spl=spl or "(not available)",
                count=len(rows),
                table=table,
            )
            try:
                summary = call_llm(llm_cfg, prompt, user_msg)
            except Exception as exc:
                logger.error("LLM call failed: %s", exc)
                summary = "(AI summary failed: {0})".format(exc)

            # Save to cache
            save_cache("ai_summary", cache_key, "", {
                "_hash": data_hash,
                "_summary": summary,
            })

        logger.info(
            "ai_summary for '%s': data changed, generated new summary.",
            search_name,
        )

    # Build and send email
    results_html = _build_results_html(rows)
    html = _build_email_html(search_name, summary, results_html, use_cached)

    try:
        email_cfg = get_email_config(session_key)
        subject = "AI Summary: {0}".format(search_name)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_cfg.get("mail_from", "splunk@localhost")
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(summary, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        send_smtp_message(email_cfg, msg, recipients)
        logger.info(
            "ai_summary email sent for '%s' to %s",
            search_name, ", ".join(recipients),
        )
    except Exception as exc:
        logger.error("Failed to send ai_summary email: %s", exc)

    log_usage(
        "ai_summary", "", custom_prompt or "auto",
        "cached" if use_cached else "live",
        len(rows), t_start,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
