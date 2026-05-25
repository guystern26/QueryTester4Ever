# -*- coding: utf-8 -*-
"""
condition_handlers.py
Condition handler registries and per-condition check functions.

Includes a compiled regex cache (capped at MAX_REGEX_CACHE entries)
and pre-compiled timestamp patterns to avoid recompilation per row.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from logger import get_logger
from core.helpers import safe_float
from core.models import FieldCondition, ResultCount, ValidationDetail
from validation.scope_evaluator import evaluate_scope, SCOPE_LABELS


logger = get_logger(__name__)

MAX_REGEX_CACHE = 100

# Module-level cache: persists across requests in Splunk's persistent handler.
_regex_cache = {}  # type: Dict[str, re.Pattern]


def _get_pattern(pattern: str) -> re.Pattern:
    """Return a compiled regex, using a capped LRU cache."""
    compiled = _regex_cache.get(pattern)
    if compiled is not None:
        return compiled
    # Evict oldest entries when cache is full (dict preserves insertion order in 3.7+)
    if len(_regex_cache) >= MAX_REGEX_CACHE:
        oldest = next(iter(_regex_cache))
        del _regex_cache[oldest]
    compiled = re.compile(pattern)
    _regex_cache[pattern] = compiled
    return compiled


# Pre-compiled timestamp patterns — compiled once at module load, not per row.
_TIMESTAMP_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),
    re.compile(r"^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}"),
    re.compile(r"^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),
]


def _is_timestamp(value: str) -> bool:
    """Check if a value looks like a timestamp (epoch, ISO 8601, or Splunk _time)."""
    if not value or not value.strip():
        return False
    stripped = value.strip()
    # Epoch seconds (with optional decimals)
    try:
        f = float(stripped)
        # Reasonable epoch range: 1970-01-01 to ~2100
        if 0 < f < 4102444800:
            return True
    except (ValueError, TypeError):
        pass
    for pat in _TIMESTAMP_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _safe_regex(actual: str, expected: str) -> bool:
    """Run regex match using compiled cache. Returns False on invalid pattern."""
    try:
        return bool(_get_pattern(expected).search(actual))
    except re.error as exc:
        logger.warning("Invalid regex pattern %r: %s", expected, exc)
        return False


ConditionHandler = Callable[[str, str], bool]

CONDITION_HANDLERS: Dict[str, ConditionHandler] = {
    "equals": lambda a, e: a.strip().lower() == e.strip().lower(),
    "not_equals": lambda a, e: a.strip().lower() != e.strip().lower(),
    "contains": lambda a, e: e.lower() in a.lower(),
    "not_contains": lambda a, e: e.lower() not in a.lower(),
    "starts_with": lambda a, e: a.strip().lower().startswith(e.strip().lower()),
    "ends_with": lambda a, e: a.strip().lower().endswith(e.strip().lower()),
    "regex": lambda a, e: _safe_regex(a, e),
    "greater_than": lambda a, e: safe_float(a) > safe_float(e),
    "less_than": lambda a, e: safe_float(a) < safe_float(e),
    "greater_or_equal": lambda a, e: safe_float(a) >= safe_float(e),
    "less_or_equal": lambda a, e: safe_float(a) <= safe_float(e),
    "is_empty": lambda a, _: a is None or a.strip() == "",
    "is_not_empty": lambda a, _: a is not None and a.strip() != "",
    "not_empty": lambda a, _: a is not None and a.strip() != "",
    "in_list": lambda a, e: a.strip().lower() in [v.strip().lower() for v in e.split(",")],
    "not_in_list": lambda a, e: a.strip().lower() not in [v.strip().lower() for v in e.split(",")],
    "is_timestamp": lambda a, _: _is_timestamp(a),
}

COUNT_OPS: Dict[str, Callable[[int, int], bool]] = {
    "equals": lambda a, e: a == e,
    "greater_than": lambda a, e: a > e,
    "less_than": lambda a, e: a < e,
    "greater_or_equal": lambda a, e: a >= e,
    "less_or_equal": lambda a, e: a <= e,
}


def check_field_condition(
    condition: FieldCondition,
    results: List[Dict[str, Any]],
    validation_scope: str = "any_event",
    scope_n: Optional[int] = None,
) -> ValidationDetail:
    """Evaluate one field condition against result rows, respecting validation scope."""
    handler = CONDITION_HANDLERS.get(condition.operator)
    if handler is None:
        logger.warning("Unknown condition operator: %s", condition.operator)
        return ValidationDetail(
            field=condition.field,
            operator=condition.operator,
            expected=condition.value,
            actual="unknown operator",
            passed=False,
            message='Unknown operator "{0}" \u2717'.format(condition.operator),
        )

    field = condition.field.strip()
    actual_values = [str(row.get(field, "")) for row in results]
    per_row = [handler(value, condition.value) for value in actual_values]

    match_count = sum(per_row)
    total_count = len(per_row)
    passed = evaluate_scope(per_row, validation_scope, scope_n)

    # Build display string
    if not actual_values:
        display = ""
    elif len(actual_values) == 1:
        display = actual_values[0]
    else:
        sample = actual_values[:3]
        display = ", ".join(sample)
        if len(actual_values) > 3:
            display = display + "..."

    scope_label = SCOPE_LABELS.get(validation_scope, validation_scope)
    if scope_n is not None:
        scope_label = scope_label.replace("{n}", str(scope_n))

    failed_count = total_count - match_count
    cond_human = condition.operator.replace("_", " ")

    if passed:
        message = "All {0} results matched: {1} {2} \u2713".format(
            total_count, condition.field, cond_human,
        )
    else:
        message = "{0} of {1} results failed: {2} was not {3} \u2014 expected {4} \u2717".format(
            failed_count, total_count, condition.field, cond_human, scope_label,
        )

    return ValidationDetail(
        field=condition.field,
        operator=condition.operator,
        expected=condition.value,
        actual=display,
        passed=passed,
        message=message,
    )


def check_result_count(actual: int, rc: ResultCount) -> ValidationDetail:
    """Evaluate a result count condition."""
    op = COUNT_OPS.get(rc.operator)
    if op is None:
        logger.warning("Unknown resultCount operator: %s", rc.operator)
        passed = False
    else:
        passed = op(actual, rc.value)

    if passed:
        message = "result count {0} {1}".format(rc.operator, rc.value)
    else:
        message = "expected result count {0} {1}, but got {2}".format(
            rc.operator, rc.value, actual
        )

    return ValidationDetail(
        field="_result_count",
        operator=rc.operator,
        expected=str(rc.value),
        actual=str(actual),
        passed=passed,
        message=message,
    )
