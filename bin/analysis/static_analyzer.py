# -*- coding: utf-8 -*-
"""
static_analyzer.py — Rule-based static analysis of SPL queries.

Detects common performance, best-practice, and correctness issues without
calling any external service.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

from logger import get_logger

logger = get_logger(__name__)


def _note(severity, category, message, line=None, suggestion=None):
    # type: (str, str, str, int, str) -> Dict[str, Any]
    """Build an AnalysisNote dict."""
    return {
        "id": str(uuid.uuid4()),
        "severity": severity,
        "category": category,
        "message": message,
        "line": line,
        "suggestion": suggestion,
    }


def _strip_quoted(spl):
    # type: (str) -> str
    """Remove content inside single and double quotes to avoid false matches."""
    result = []  # type: List[str]
    i = 0
    while i < len(spl):
        ch = spl[i]
        if ch in ('"', "'"):
            quote = ch
            i += 1
            while i < len(spl):
                if spl[i] == "\\" and i + 1 < len(spl):
                    i += 2
                    continue
                if spl[i] == quote:
                    break
                i += 1
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


class StaticSplAnalyzer:
    """Rule-based SPL static analyzer."""

    def analyze(self, spl, app=""):
        # type: (str, str) -> Dict[str, Any]
        """Analyze SPL and return notes and field usage."""
        notes = []  # type: List[Dict[str, Any]]
        if not spl or not spl.strip():
            return {"notes": notes, "fieldUsage": _empty_field_usage()}

        safe = _strip_quoted(spl)
        lower = safe.lower()

        self._check_missing_time_range(lower, notes)
        self._check_wildcard_sourcetype(lower, notes)
        self._check_redundant_search(lower, notes)
        self._check_search_vs_where(lower, notes)
        self._check_stats_without_by(lower, notes)
        self._check_no_fields_command(lower, notes)
        self._check_join_command(lower, notes)

        field_usage = self._extract_field_usage(safe)
        return {"notes": notes, "fieldUsage": field_usage}

    def _check_missing_time_range(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag queries without explicit time bounds."""
        if "earliest=" not in lower and "latest=" not in lower:
            notes.append(_note(
                "info", "optimization",
                "No time range specified in the query. Unbounded searches scan all data and can be slow.",
                suggestion="Add earliest= and latest= to limit the search window.",
            ))

    def _check_wildcard_sourcetype(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag sourcetype=* which scans all sourcetypes."""
        if "sourcetype=*" in lower:
            notes.append(_note(
                "warning", "best_practice",
                "sourcetype=* scans all sourcetypes. This is usually unintentional and hurts performance.",
                suggestion="Specify a concrete sourcetype to narrow the search.",
            ))

    def _check_redundant_search(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag redundant leading 'search' command."""
        stripped = lower.lstrip()
        if stripped.startswith("| search ") or stripped.startswith("|search "):
            notes.append(_note(
                "info", "best_practice",
                "Leading '| search' is redundant. The implicit first command is already 'search'.",
                suggestion="Remove the leading '| search'.",
            ))

    def _check_search_vs_where(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag '| search field=' after the first pipe — suggest '| where'."""
        first_pipe = lower.find("|")
        if first_pipe == -1:
            return
        after = lower[first_pipe + 1:]
        if re.search(r"\|\s*search\s+\w+\s*=", after):
            notes.append(_note(
                "info", "optimization",
                "'| search field=value' after a pipe re-parses the data. '| where' is more efficient for mid-pipeline filtering.",
                suggestion="Replace '| search field=value' with '| where field=\"value\"'.",
            ))

    def _check_stats_without_by(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag '| stats count' without a 'by' clause."""
        match = re.search(r"\|\s*stats\s+count(?!\s+by\b)", lower)
        if match:
            notes.append(_note(
                "info", "best_practice",
                "'stats count' without a 'by' clause returns a single row. Add 'by field' to group results if needed.",
            ))

    def _check_no_fields_command(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag queries with stats/eval but no table/fields at the end."""
        has_transform = bool(re.search(r"\|\s*(stats|eval|chart|timechart)\b", lower))
        has_output = bool(re.search(r"\|\s*(table|fields)\b", lower))
        if has_transform and not has_output:
            notes.append(_note(
                "info", "best_practice",
                "Query has transforming commands but no '| table' or '| fields' to shape the output.",
                suggestion="Add '| table field1, field2' or '| fields field1, field2' to control output columns.",
            ))

    def _check_join_command(self, lower, notes):
        # type: (str, List[Dict[str, Any]]) -> None
        """Flag join command with optimization suggestion."""
        if re.search(r"\|\s*join\b", lower):
            notes.append(_note(
                "warning", "optimization",
                "'| join' is limited to 50,000 rows by default and is resource-intensive.",
                suggestion="Consider using '| stats' with 'values()' or '| lookup' as alternatives.",
            ))

    def _extract_field_usage(self, safe):
        # type: (str) -> Dict[str, List[str]]
        """Extract basic field usage from the SPL."""
        input_fields = []   # type: List[str]
        created_fields = [] # type: List[str]

        # Fields from by clauses
        for m in re.finditer(r"\bby\s+([\w,\s]+?)(?:\||$)", safe, re.IGNORECASE):
            for f in re.split(r"[,\s]+", m.group(1).strip()):
                clean = f.strip()
                if clean and clean not in input_fields:
                    input_fields.append(clean)

        # Fields from eval LHS
        for m in re.finditer(r"\beval\s+(\w+)\s*=", safe, re.IGNORECASE):
            name = m.group(1)
            if name not in created_fields:
                created_fields.append(name)

        # Fields from table/fields commands
        for m in re.finditer(r"\|\s*(?:table|fields)\s+([\w,\s\-]+?)(?:\||$)", safe, re.IGNORECASE):
            for f in re.split(r"[,\s]+", m.group(1).strip()):
                clean = f.strip().lstrip("-")
                if clean and clean not in input_fields and clean not in created_fields:
                    input_fields.append(clean)

        return {
            "input": input_fields,
            "created": created_fields,
            "available_unused": [],
        }


def _empty_field_usage():
    # type: () -> Dict[str, List[str]]
    """Return an empty field usage structure."""
    return {"input": [], "created": [], "available_unused": []}
