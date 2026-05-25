# -*- coding: utf-8 -*-
"""alert_email_body.py — Top-level failure email body assembly."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from alerts.alert_email_tables import esc
from alerts.alert_email_html import format_scenario_block

APP_ROUTE = "/app/QueryTester/QueryTesterApp"

# Dark-mode CSS — webmail clients (Gmail, OWA, Apple Mail).
DARK_CSS = (
    "<style>:root{color-scheme:light dark;supported-color-schemes:light dark}"
    "@media(prefers-color-scheme:dark){"
    ".em-body{background-color:#1a1a2e!important}.em-card{background-color:#16213e!important}"
    ".em-head{color:#e2e8f0!important}.em-sub{color:#94a3b8!important}"
    ".em-text{color:#cbd5e1!important}.em-muted{color:#64748b!important}"
    ".em-border{border-color:#334155!important}"
    ".em-row-even{background-color:#16213e!important}.em-row-odd{background-color:#1a1a2e!important}"
    ".em-row-fail{background-color:#2d1b1b!important}.em-scen-head{background-color:#1e293b!important}"
    ".em-scen-border{border-color:#475569!important}"
    ".em-footer{background-color:#0f172a!important;color:#64748b!important;border-color:#334155!important}"
    ".em-drift{background-color:#422006!important;color:#fde68a!important;border-color:#a16207!important}"
    ".em-status-bg{background-color:transparent!important}}"
    "[data-ogsc] .em-body{background-color:#1a1a2e!important}"
    "[data-ogsc] .em-card{background-color:#16213e!important}"
    "[data-ogsc] .em-head{color:#e2e8f0!important}"
    "[data-ogsc] .em-sub{color:#94a3b8!important}"
    "[data-ogsc] .em-text{color:#cbd5e1!important}"
    "[data-ogsc] .em-muted{color:#64748b!important}"
    "[data-ogsc] .em-footer{background-color:#0f172a!important;color:#64748b!important}"
    "[data-ogsc] .em-drift{background-color:#422006!important;color:#fde68a!important}"
    "</style>"
)


def _build_test_link(test_id, splunk_web_url):
    # type: (str, str) -> str
    return "{base}{route}?test_id={tid}".format(
        base=splunk_web_url.rstrip("/"),
        route=APP_ROUTE,
        tid=test_id,
    )


def _drift_section(spl_drift_detected):
    # type: (bool) -> str
    if not spl_drift_detected:
        return ""
    return (
        '<tr><td class="em-card" bgcolor="#ffffff" style="padding:0 24px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr><td style="padding:0 0 12px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr bgcolor="#fffbeb">'
        '<td class="em-drift" style="padding:10px 14px;'
        'border-left:4px solid #d97706;font-size:13px;color:#92400e;'
        'font-family:Arial,sans-serif">'
        "&#9888; <strong>SPL drift detected</strong> &mdash; the saved "
        "search SPL has changed since this test was created."
        "</td></tr></table></td></tr></table></td></tr>"
    )


def _link_section(test_id, splunk_web_url):
    # type: (str, str) -> str
    if not test_id:
        return ""
    url = _build_test_link(test_id, splunk_web_url)
    return (
        '<tr><td style="padding:16px 0 0">'
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td bgcolor="#2563eb" style="padding:10px 24px">'
        '<a href="{url}" style="color:#ffffff;font-size:13px;'
        "font-weight:bold;text-decoration:none;"
        'font-family:Arial,sans-serif">Open Test in Query Tester</a>'
        "</td></tr></table></td></tr>"
    ).format(url=url)


def _summary_section(full_results):
    # type: (Any) -> str
    if not full_results:
        return ""
    passed = full_results.get("passedScenarios", 0)
    total = full_results.get("totalScenarios", 0)
    msg = full_results.get("message", "")
    return (
        '<tr><td class="em-sub" style="padding:0 0 12px;font-size:13px;'
        'color:#6b7280;font-family:Arial,sans-serif">'
        "{passed}/{total} scenarios passed{msg}</td></tr>"
    ).format(
        passed=passed, total=total,
        msg=" &mdash; " + esc(msg) if msg else "",
    )


def _logo_url(splunk_web_url):
    # type: (str) -> str
    """Build the URL to the QT logo hosted in the Splunk app static dir."""
    base = splunk_web_url.rstrip("/") if splunk_web_url else ""
    return "{0}/static/app/QueryTester/appIconAlt_2x.png".format(base)


def build_failure_email(
    test_name,           # type: str
    ran_at,              # type: str
    status,              # type: str
    scenario_results,    # type: List[Dict[str, Any]]
    spl_drift_detected,  # type: bool
    test_id="",          # type: str
    full_results=None,   # type: Any
    splunk_web_url="",   # type: str
):
    # type: (...) -> Tuple[str, str]
    """Build subject and Outlook-compatible HTML body for a failure email."""
    subject = "[Query Tester] Test Failed: {0}".format(test_name)
    status_color = "#dc2626" if status in ("fail", "error") else "#d97706"
    status_label = status.upper()
    status_bg = "#fef2f2" if status in ("fail", "error") else "#fffbeb"
    logo = _logo_url(splunk_web_url)

    scenarios = "\n".join(
        "<tr><td style=\"padding:0 0 4px\">"
        + format_scenario_block(s) + "</td></tr>"
        for s in scenario_results
    )

    body = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        "{dark_css}</head>"
        '<body class="em-body" style="margin:0;padding:0;'
        'background-color:#f3f4f6;font-family:Arial,sans-serif">'
        "<!--[if mso]>"
        '<table cellpadding="0" cellspacing="0" border="0" width="700"'
        ' align="center"><tr><td><![endif]-->'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' style="max-width:700px;margin:0 auto">'
        '<tr><td bgcolor="#1e293b" style="padding:0;height:4px;'
        'font-size:0;line-height:0">&nbsp;</td></tr>'
        '<tr><td class="em-card" bgcolor="#ffffff"'
        ' style="padding:24px 24px 16px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        "<tr>"
        '<td class="em-head" style="font-size:22px;font-weight:bold;'
        'color:#1f2937;font-family:Arial,sans-serif">'
        "Test Failure Report</td>"
        '<td style="text-align:right;vertical-align:top">'
        '<img src="{logo}" alt="QT" width="48" height="48"'
        ' style="display:inline-block;width:48px;height:48px" />'
        "</td></tr>"
        '<tr><td class="em-sub" colspan="2"'
        ' style="padding:4px 0 0;font-size:14px;'
        'color:#6b7280;font-family:Arial,sans-serif">'
        "{test_name}</td></tr></table></td></tr>"
        '<tr><td class="em-card" bgcolor="#ffffff"'
        ' style="padding:0 24px 16px">'
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td class="em-sub" style="padding:4px 0;font-size:13px;'
        'color:#6b7280;font-family:Arial,sans-serif;font-weight:bold">'
        "Status:</td>"
        '<td class="em-status-bg" bgcolor="{status_bg}"'
        ' style="padding:4px 12px;font-size:13px;color:{status_color};'
        'font-weight:bold;font-family:Arial,sans-serif">'
        "{status_label}</td></tr><tr>"
        '<td class="em-sub" style="padding:4px 0;font-size:13px;'
        'color:#6b7280;font-family:Arial,sans-serif;font-weight:bold">'
        "Run time:</td>"
        '<td class="em-text" style="padding:4px 12px;font-size:13px;'
        'color:#374151;font-family:Arial,sans-serif">{ran_at}</td>'
        "</tr></table></td></tr>"
        "{drift}"
        '<tr><td class="em-card" bgcolor="#ffffff" style="padding:0 24px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr><td class="em-head em-border" style="padding:8px 0 12px;'
        'border-top:1px solid #e5e7eb;font-size:16px;font-weight:bold;'
        'color:#1f2937;font-family:Arial,sans-serif">'
        "Scenario Results</td></tr>{summary}</table></td></tr>"
        '<tr><td class="em-card" bgcolor="#ffffff"'
        ' style="padding:0 24px 16px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        "{scenarios}</table></td></tr>"
        '<tr><td class="em-card" bgcolor="#ffffff"'
        ' style="padding:0 24px 24px">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        "{link}</table></td></tr>"
        '<tr><td class="em-footer" bgcolor="#f9fafb"'
        ' style="padding:16px 24px;border-top:1px solid #e5e7eb;'
        'font-size:11px;color:#9ca3af;font-family:Arial,sans-serif">'
        "This email was sent by the Query Tester scheduled runner. "
        "The test definition is attached as a JSON file."
        "</td></tr></table>"
        "<!--[if mso]></td></tr></table><![endif]-->"
        "</body></html>"
    ).format(
        dark_css=DARK_CSS,
        test_name=esc(test_name),
        logo=logo,
        status_color=status_color,
        status_bg=status_bg,
        status_label=status_label,
        ran_at=esc(ran_at),
        drift=_drift_section(spl_drift_detected),
        summary=_summary_section(full_results),
        scenarios=scenarios,
        link=_link_section(test_id, splunk_web_url),
    )
    return subject, body
