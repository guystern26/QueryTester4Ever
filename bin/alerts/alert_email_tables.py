# -*- coding: utf-8 -*-
"""alert_email_tables.py — Result row table rendering for failure emails."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

MAX_EMAIL_ROWS = 20
RUN_ID_PATTERN = re.compile(r"^run_id_[0-9a-f]{6,16}$", re.IGNORECASE)
HIDDEN_SPLUNK_FIELDS = frozenset([
    "punct", "source", "sourcetype", "splunk_server", "splunk_server_group",
    "index", "host", "linecount", "timeendpos", "timestartpos",
    "eventtype", "tag", "tag::eventtype",
])


def esc(text):
    # type: (str) -> str
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def is_visible_column(key):
    # type: (str) -> bool
    if key.startswith("_") or key in HIDDEN_SPLUNK_FIELDS:
        return False
    return not RUN_ID_PATTERN.match(key) and "{}" not in key


def cell_value(raw):
    # type: (Any) -> str
    if isinstance(raw, list):
        return " ".join(str(x) for x in raw)
    s = str(raw) if raw is not None else ""
    return s.replace("\n", " ")


_CONDITION_MAP = {
    "equals": lambda a, e: a == e,
    "equal_to": lambda a, e: a == e,
    "not_equals": lambda a, e: a != e,
    "contains": lambda a, e: e.lower() in a.lower(),
    "not_contains": lambda a, e: e.lower() not in a.lower(),
    "starts_with": lambda a, e: a.lower().startswith(e.lower()),
    "ends_with": lambda a, e: a.lower().endswith(e.lower()),
    "exists": lambda a, e: a != "",
    "not_exists": lambda a, e: a == "",
}


def _numeric_cmp(a, e, op):
    # type: (str, str, str) -> bool
    try:
        return float(a) > float(e) if op == "gt" else float(a) < float(e)
    except (ValueError, TypeError):
        return False


def evaluate_condition(condition, actual, expected):
    # type: (str, str, str) -> bool
    cond = condition.lower().replace(" ", "_")
    fn = _CONDITION_MAP.get(cond)
    if fn:
        return fn(actual, expected)
    if cond in ("greater_than", "gt"):
        return _numeric_cmp(actual, expected, "gt")
    if cond in ("less_than", "lt"):
        return _numeric_cmp(actual, expected, "lt")
    if cond == "matches_regex":
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False
    return True


def get_row_validation(row, validations):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> Tuple[bool, List[str]]
    notes = []  # type: List[str]
    all_passed = True
    for v in validations:
        field = v.get("field", "")
        if field.startswith("_"):
            continue
        actual = str(row.get(field, "") or "")
        expected = str(v.get("expected", "") or "")
        condition = str(v.get("condition", ""))
        if not evaluate_condition(condition, actual, expected):
            all_passed = False
            notes.append("{f}: expected {c} {e}, got \"{a}\"".format(
                f=field, c=condition.replace("_", " "),
                e=expected, a=actual or "(empty)",
            ))
    return all_passed, notes


def sort_rows_failed_first(rows, validations):
    # type: (List[Dict[str, Any]], List[Dict[str, Any]]) -> List[Dict[str, Any]]
    field_vals = [v for v in validations if not v.get("field", "").startswith("_")]
    if not field_vals:
        return rows
    return sorted(rows, key=lambda r: 1 if get_row_validation(r, field_vals)[0] else 0)


def format_result_rows_table(scenario):
    # type: (Dict[str, Any]) -> str
    """Render result rows as an Outlook-compatible HTML table."""
    result_rows = scenario.get("resultRows", [])
    if not result_rows:
        return ""
    cols = []  # type: List[str]
    seen = set()  # type: set
    for row in result_rows:
        for key in row:
            if key not in seen and is_visible_column(key):
                cols.append(key)
                seen.add(key)
    if not cols:
        return ""
    validations = scenario.get("validations", [])
    display = sort_rows_failed_first(result_rows, validations)[:MAX_EMAIL_ROWS]
    field_vals = [v for v in validations if not v.get("field", "").startswith("_")]
    header = _build_header(cols, validations)
    body = _build_body(display, cols, validations, field_vals)
    trunc = _build_truncation_row(len(result_rows), len(cols))
    return (
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr><td>'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        ' class="em-scen-border" style="border:1px solid #d1d5db;border-collapse:collapse">'
        "<thead>{0}</thead><tbody>{1}{2}</tbody></table></td></tr></table>"
    ).format(header, body, trunc)

_TH_BASE = ('padding:6px 10px;text-align:left;font-size:11px;font-weight:bold;'
            'border-bottom:2px solid #d1d5db;font-family:Arial,sans-serif')


def _build_header(columns, validations):
    # type: (List[str], List[Dict[str, Any]]) -> str
    hcells = '<th class="em-muted em-border" style="{0};color:#6b7280">#</th>'.format(_TH_BASE)
    for col in columns:
        fail = any(v.get("field") == col and not v.get("passed", True) for v in validations)
        color = "color:#dc2626" if fail else "color:#6b7280"
        cls = "" if fail else 'class="em-muted em-border"'
        hcells += '<th {0} style="{1};{2}">{3}</th>'.format(cls, _TH_BASE, color, esc(col))
    return "<tr>" + hcells + "</tr>"


_CELL_BORDER = "border-bottom:1px solid #e5e7eb;font-family:Arial,sans-serif"


def _build_body(display_rows, columns, validations, field_vals):
    # type: (List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]]) -> str
    rows_html = []
    for idx, row in enumerate(display_rows):
        row_passed = not field_vals or get_row_validation(row, field_vals)[0]
        if not row_passed:
            row_bg, row_cls = "#fef2f2", "em-row-fail"
        elif idx % 2 == 0:
            row_bg, row_cls = "#ffffff", "em-row-even"
        else:
            row_bg, row_cls = "#f9fafb", "em-row-odd"
        cells = (
            '<td class="em-muted em-border" style="padding:4px 10px;'
            'font-size:12px;color:#9ca3af;{b}">{n}</td>'
        ).format(b=_CELL_BORDER, n=idx + 1)
        for col in columns:
            val = cell_value(row.get(col))
            fail = any(v.get("field") == col and not v.get("passed", True)
                       for v in validations)
            tc = "color:#dc2626" if fail else "color:#374151"
            cls = "" if fail else 'class="em-text em-border"'
            cells += (
                '<td {cls} style="padding:4px 10px;font-size:12px;{c};{b}"'
                ' title="{t}">{v}</td>'
            ).format(cls=cls, c=tc, b=_CELL_BORDER, t=esc(val), v=esc(val[:80]))
        rows_html.append(
            '<tr class="{rc}" bgcolor="{bg}">{cells}</tr>'.format(
                rc=row_cls, bg=row_bg, cells=cells))
    return "\n".join(rows_html)


def _build_truncation_row(total, col_count):
    # type: (int, int) -> str
    if total <= MAX_EMAIL_ROWS:
        return ""
    return (
        '<tr><td colspan="{0}" class="em-muted" style="padding:6px 10px;'
        'font-size:11px;color:#9ca3af;font-family:Arial,sans-serif">'
        "Showing {1} of {2} rows (failed rows first)</td></tr>"
    ).format(col_count + 1, MAX_EMAIL_ROWS, total)
