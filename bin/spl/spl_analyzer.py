# -*- coding: utf-8 -*-
"""
spl_analyzer.py
Analyze SPL text for risky or unusual commands without modifying it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from logger import get_logger
from spl.spl_analyzer_rules import UNAUTHORIZED_COMMANDS, UNUSUAL_COMMANDS


logger = get_logger(__name__)


@dataclass
class SplAnalysis:
    """Summary of SPL commands and associated warnings."""

    unauthorized_commands: List[str] = field(default_factory=list)
    unusual_commands: List[str] = field(default_factory=list)
    uniq_limitations: Optional[str] = None
    commands_used: List[str] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)


def analyze(spl, blocked_commands=None):
    # type: (str, Optional[set]) -> SplAnalysis
    """Inspect SPL text and return an SplAnalysis describing detected commands and warnings.

    *blocked_commands* overrides the hardcoded UNAUTHORIZED_COMMANDS set when
    provided (e.g. from the command policy KVStore collection).
    """
    spl_clean = spl or ""
    unauthorized_set = blocked_commands if blocked_commands is not None else UNAUTHORIZED_COMMANDS

    # Extract commands from outer query (for general command listing)
    commands = _extract_commands(spl_clean)
    # Also extract commands from the FULL SPL (including subsearches) for safety checks
    all_commands = _extract_all_commands(spl_clean)
    unauthorized = [cmd for cmd in all_commands if cmd in unauthorized_set]
    unusual = [cmd for cmd in commands if cmd in UNUSUAL_COMMANDS]

    warnings = []  # type: List[Dict[str, Any]]
    uniq_message = None  # type: Optional[str]

    def _warn(msg: str, severity: str = "warning") -> None:
        warnings.append({"message": msg, "severity": severity})

    if "join" in commands:
        _warn(
            "join returns only 50,000 results. Consider using append "
            "+ stats values(*) by * instead."
        )
    if "append" in commands:
        _warn("append is limited to 1 million results.")
    if "transaction" in commands:
        _warn(
            "transaction is resource-intensive. Consider using stats "
            "with by/grouping fields when possible.",
            "caution",
        )
    if "uniq" in commands:
        uniq_message = (
            "uniq removes only consecutive duplicate events. Sort by the target field "
            "first, or use dedup for full deduplication."
        )
        _warn(uniq_message, "info")
    if _has_subsearch(spl_clean):
        _warn("Subsearches are limited to 50,000 results and a 60-second timeout.")
    if _has_tstats(spl_clean):
        _warn(
            "tstats queries cannot be injected with test data. "
            'Use testType="query_only" to run this query without injection.'
        )

    # Warn about cache macros — testing=false ones get lookup-swapped at injection time
    cache_warnings = check_cache_macros(spl_clean)
    for w in cache_warnings:
        _warn(w, "info")

    return SplAnalysis(
        unauthorized_commands=unauthorized,
        unusual_commands=unusual,
        uniq_limitations=uniq_message,
        commands_used=commands,
        warnings=warnings,
    )


def _strip_quoted_strings(spl: str) -> str:
    """Remove content inside single and double quotes to prevent false matches."""
    result = []  # type: List[str]
    i = 0
    while i < len(spl):
        ch = spl[i]
        if ch in ('"', "'"):
            quote_char = ch
            i += 1
            while i < len(spl):
                if spl[i] == "\\" and i + 1 < len(spl):
                    i += 2
                    continue
                if spl[i] == quote_char:
                    break
                i += 1
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _strip_subsearch_bodies(spl: str) -> str:
    parts = []  # type: List[str]
    depth = 0
    for char in spl:
        if char == "[":
            depth += 1
            continue
        if char == "]" and depth > 0:
            depth -= 1
            continue
        if depth == 0:
            parts.append(char)
    return "".join(parts)


def _extract_commands(spl: str) -> List[str]:
    base = _strip_subsearch_bodies(_strip_quoted_strings(spl))
    commands = []  # type: List[str]

    first_pipe = base.find("|")
    if first_pipe == -1:
        first_token = base.strip().split(" ", 1)[0]
        if re.match(r"^[a-zA-Z_]+$", first_token):
            commands.append(first_token.lower())
    else:
        pre = base[:first_pipe].strip().split(" ", 1)[0]
        if re.match(r"^[a-zA-Z_]+$", pre):
            commands.append(pre.lower())

    for match in re.finditer(r"\|\s*([a-zA-Z_]+)", base):
        cmd = match.group(1).lower()
        if cmd not in commands:
            commands.append(cmd)

    return commands


def _extract_all_commands(spl: str) -> List[str]:
    """Extract ALL commands from the full SPL including subsearches (for safety checks)."""
    commands = []  # type: List[str]

    # Strip quoted strings first to avoid false positives on commands inside strings
    safe = _strip_quoted_strings(spl)
    # Strip brackets but keep the content
    flat = safe.replace("[", " ").replace("]", " ")

    first_pipe = flat.find("|")
    if first_pipe == -1:
        first_token = flat.strip().split(" ", 1)[0]
        if re.match(r"^[a-zA-Z_]+$", first_token):
            commands.append(first_token.lower())
    else:
        pre = flat[:first_pipe].strip().split(" ", 1)[0]
        if re.match(r"^[a-zA-Z_]+$", pre):
            commands.append(pre.lower())

    for match in re.finditer(r"\|\s*([a-zA-Z_]+)", flat):
        cmd = match.group(1).lower()
        if cmd not in commands:
            commands.append(cmd)

    return commands


def _has_subsearch(spl: str) -> bool:
    return "[" in spl and "]" in spl


def _has_tstats(spl: str) -> bool:
    return bool(re.search(r"\|\s*tstats\b", spl, re.IGNORECASE))


# ── Cache macro validation ───────────────────────────────────────────────────

# Matches `cache(arg1, arg2, ..., testing_value, vanish_time)`
# The testing param is the 5th argument (index 4, zero-based).
_CACHE_MACRO_RE = re.compile(r"`cache\(([^)]*)\)`")
_TRUE_VALUES = {"true", "True", "1"}


def parse_cache_macros(spl):
    # type: (str) -> List[Dict[str, Any]]
    """Parse all `cache(...)` macro calls. Returns list of dicts with parsed args."""
    results = []  # type: List[Dict[str, Any]]
    for match in _CACHE_MACRO_RE.finditer(spl):
        args_raw = match.group(1)
        args = [a.strip().strip('"').strip("'") for a in args_raw.split(",")]
        entry = {
            "full_match": match.group(0),
            "start": match.start(),
            "end": match.end(),
            "args": args,
            "lookup_name": args[0] if len(args) > 0 else "",
            "testing": args[4].strip().strip('"').strip("'") if len(args) > 4 else "",
            "is_testing": False,
        }
        if len(args) > 4:
            entry["is_testing"] = entry["testing"] in _TRUE_VALUES
        results.append(entry)
    return results


def check_cache_macros(spl):
    # type: (str) -> List[str]
    """Return informational warnings about cache macros in the SPL."""
    warnings = []  # type: List[str]
    for info in parse_cache_macros(spl):
        if len(info["args"]) < 5:
            warnings.append(
                "cache macro requires at least 5 arguments "
                "(lookup_name, id_fields, prop_fields, stacking_fields, testing). "
                "vanish_time is optional. Found {0}.".format(len(info["args"]))
            )
        elif not info["is_testing"]:
            warnings.append(
                'cache macro lookup "{0}" will be replaced with a temporary lookup '
                "to protect production data. The temp lookup persists for the "
                "duration of your test session, so repeated runs will accumulate "
                "data in it.".format(info["lookup_name"])
            )
        else:
            warnings.append(
                'cache macro "{0}" is running with testing=true — safe to run. '
                "You can also run it with testing=false: Query Tester will "
                "automatically swap the lookup with a temporary copy so no "
                "production data is modified.".format(info["lookup_name"])
            )
    return warnings
