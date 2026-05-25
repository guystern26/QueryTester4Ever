# -*- coding: utf-8 -*-
"""
alert_email_html.py — Scenario block rendering for failure emails.

Pure functions: data in, HTML string out. No side effects.
Uses table-based layout only (no divs, no border-radius, no flex).

Re-exports ``esc`` and ``build_failure_email`` for backward compatibility.
"""
from __future__ import annotations

from typing import Any, Dict, List

from alerts.alert_email_tables import esc, format_result_rows_table


def _format_validation_row(v):
    # type: (Dict[str, Any]) -> str
    """Render a single validation result row."""
    passed = v.get("passed", False)
    icon = "&#10003;" if passed else "&#10007;"
    color = "#16a34a" if passed else "#dc2626"
    td = (
        'class="em-text em-border" style="padding:5px 10px;font-size:12px;'
        'border-bottom:1px solid #e5e7eb;color:#374151;'
        'font-family:Arial,sans-serif"'
    )
    return (
        "<tr>"
        '<td class="em-border" style="padding:5px 10px;font-size:14px;'
        'border-bottom:1px solid #e5e7eb;color:{color};'
        'font-family:Arial,sans-serif;text-align:center"'
        ">{icon}</td>"
        "<td {td}>{field}</td>"
        "<td {td}>{condition}</td>"
        "<td {td}>{expected}</td>"
        "<td {td}>{actual}</td>"
        "<td {td}>{msg}</td>"
        "</tr>"
    ).format(
        color=color, icon=icon, td=td,
        field=esc(str(v.get("field", ""))),
        condition=esc(str(v.get("condition", ""))),
        expected=esc(str(v.get("expected", ""))),
        actual=esc(str(v.get("actual", ""))),
        msg=esc(str(v.get("message", ""))),
    )


def format_scenario_block(scenario):
    # type: (Dict[str, Any]) -> str
    """Render a single scenario as an Outlook-compatible HTML block."""
    passed = scenario.get("passed", False)
    name = esc(scenario.get("scenarioName", "Unknown"))
    badge_bg = "#16a34a" if passed else "#dc2626"
    badge_text = "PASS" if passed else "FAIL"

    header = (
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' class="em-scen-border"'
        ' style="margin-bottom:16px;border:1px solid #d1d5db">'
        '<tr><td class="em-scen-head" bgcolor="#f3f4f6"'
        ' style="padding:10px 12px;font-family:Arial,sans-serif">'
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td bgcolor="{bg}" style="padding:3px 10px;font-size:11px;'
        'font-weight:bold;color:#ffffff;font-family:Arial,sans-serif;'
        'letter-spacing:0.5px">{badge}</td>'
        '<td class="em-head" style="padding-left:10px;font-size:14px;'
        'font-weight:bold;color:#1f2937;'
        'font-family:Arial,sans-serif">{name}</td>'
        "</tr></table></td></tr>"
    ).format(bg=badge_bg, badge=badge_text, name=name)

    body_parts = _build_scenario_body(scenario)

    return (
        header
        + '<tr><td><table cellpadding="0" cellspacing="0" border="0"'
        ' width="100%">' + body_parts + "</table></td></tr></table>"
    )


def _build_scenario_body(scenario):
    # type: (Dict[str, Any]) -> str
    """Build the inner body of a scenario block."""
    parts = []  # type: List[str]
    error = scenario.get("error", "")
    if error:
        parts.append(
            '<tr><td style="padding:8px 12px;color:#dc2626;font-size:13px;'
            'font-family:Arial,sans-serif">Error: {0}</td></tr>'.format(
                esc(error),
            )
        )

    validations = scenario.get("validations", [])
    if validations:
        parts.append(_build_validation_table(validations))

    result_count = scenario.get("resultCount")
    if result_count is not None:
        parts.append(
            '<tr><td class="em-muted" style="padding:6px 12px;'
            'color:#9ca3af;font-size:11px;font-family:Arial,sans-serif">'
            "Result rows: {0}</td></tr>".format(result_count)
        )

    if not scenario.get("passed", False):
        rows_table = format_result_rows_table(scenario)
        if rows_table:
            parts.append(
                "<tr><td style=\"padding:4px 12px 8px\">"
                "{0}</td></tr>".format(rows_table)
            )

    if not parts:
        return (
            '<tr><td class="em-muted" style="padding:8px 12px;'
            'color:#9ca3af;font-size:12px;font-family:Arial,sans-serif">'
            "No validation details</td></tr>"
        )
    return "\n".join(parts)


def _build_validation_table(validations):
    # type: (List[Dict[str, Any]]) -> str
    th = (
        'class="em-muted em-border" style="padding:5px 10px;'
        'text-align:left;font-size:11px;font-weight:bold;color:#6b7280;'
        'border-bottom:2px solid #d1d5db;font-family:Arial,sans-serif"'
    )
    rows = "\n".join(_format_validation_row(v) for v in validations)
    return (
        "<tr><td>"
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' style="border-collapse:collapse">'
        "<thead><tr>"
        "<th {th}></th>"
        "<th {th}>Field</th>"
        "<th {th}>Condition</th>"
        "<th {th}>Expected</th>"
        "<th {th}>Actual</th>"
        "<th {th}>Message</th>"
        "</tr></thead>"
        "<tbody>{rows}</tbody></table>"
        "</td></tr>".format(th=th, rows=rows)
    )
