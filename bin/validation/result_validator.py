# -*- coding: utf-8 -*-
"""
result_validator.py
Validate Splunk query results against the configured validation rules.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from logger import get_logger
from core.models import (
    ParsedScenario,
    ValidationConfig,
    ValidationDetail,
)
from validation.condition_handlers import check_field_condition, check_result_count


logger = get_logger(__name__)


def validate(
    validation: ValidationConfig,
    scenario: ParsedScenario,
    results: List[Dict[str, Any]],
    fail_fast: bool = False,
) -> Tuple[List[ValidationDetail], bool]:
    """
    Validate result rows against all conditions. Returns (details, overall_passed).

    fail_fast=False (default): evaluates ALL conditions for the full report.
    fail_fast=True: stops on first failure, returns partial results (scheduled runs).
    """
    details = []  # type: List[ValidationDetail]
    all_passed = True

    if validation.result_count and validation.result_count.enabled:
        count_detail = check_result_count(len(results), validation.result_count)
        details.append(count_detail)
        if not count_detail.passed:
            all_passed = False
            if fail_fast:
                return details, False

    if not results and (not validation.result_count or not validation.result_count.enabled):
        no_result_detail = ValidationDetail(
            field="_results",
            operator="not_empty",
            expected="at least 1 result",
            actual="0 results",
            passed=False,
            message=(
                "No results returned. Check that indexed data matches your query filters."
            ),
        )
        return [no_result_detail], False

    scope = validation.validation_scope
    scope_n = validation.scope_n

    if validation.field_groups:
        passed = _validate_groups(
            validation, scenario, results, scope, scope_n, details, fail_fast,
        )
        if not passed:
            all_passed = False
    elif validation.field_conditions:
        passed = _validate_flat_conditions(
            validation, scenario, results, scope, scope_n, details, fail_fast,
        )
        if not passed:
            all_passed = False
    elif validation.expected_result:
        detail = _check_expected_result(validation.expected_result, results)
        details.append(detail)
        if not detail.passed:
            all_passed = False

    return details, all_passed


def _validate_groups(
    validation: ValidationConfig,
    scenario: ParsedScenario,
    results: List[Dict[str, Any]],
    scope: str,
    scope_n: Any,
    details: List[ValidationDetail],
    fail_fast: bool,
) -> bool:
    """Evaluate structured groups. Returns True if all groups pass."""
    group_results = []  # type: List[bool]
    for group in validation.field_groups:
        if not _scope_matches(group.scenario_scope, scenario.name):
            continue
        group_details = []  # type: List[ValidationDetail]
        for condition in group.conditions:
            detail = check_field_condition(condition, results, scope, scope_n)
            group_details.append(detail)
            if fail_fast and not detail.passed:
                details.extend(group_details)
                return False
        if not group_details:
            continue

        if group.condition_logic == "or":
            group_passed = any(d.passed for d in group_details)
            # For OR groups that passed, only show the passing branches
            if group_passed:
                details.extend([d for d in group_details if d.passed])
            else:
                details.extend(group_details)
        else:
            group_passed = all(d.passed for d in group_details)
            details.extend(group_details)
        group_results.append(group_passed)
        if fail_fast and not group_passed:
            return False

    if not group_results:
        return True
    if validation.field_logic == "or":
        return any(group_results)
    return all(group_results)


def _validate_flat_conditions(
    validation: ValidationConfig,
    scenario: ParsedScenario,
    results: List[Dict[str, Any]],
    scope: str,
    scope_n: Any,
    details: List[ValidationDetail],
    fail_fast: bool,
) -> bool:
    """Evaluate flat conditions (legacy / no groups). Returns True if all pass."""
    field_details = []  # type: List[ValidationDetail]
    for condition in validation.field_conditions:
        if not _scope_matches(condition.scenario_scope, scenario.name):
            continue
        detail = check_field_condition(condition, results, scope, scope_n)
        field_details.append(detail)
        if fail_fast and not detail.passed:
            details.extend(field_details)
            return False

    if validation.field_logic == "or":
        or_passed = bool(field_details) and any(d.passed for d in field_details)
        # For OR logic that passed, only show the passing branches
        if or_passed:
            details.extend([d for d in field_details if d.passed])
        else:
            details.extend(field_details)
        if field_details and not or_passed:
            return False
    else:
        details.extend(field_details)
        if any(not d.passed for d in field_details):
            return False
    return True


def _check_expected_result(
    expected: Dict[str, Any], results: List[Dict[str, Any]]
) -> ValidationDetail:
    if not results:
        message = "expected at least one row matching {0!r}, got 0 \u2717".format(
            expected
        )
        return ValidationDetail(
            field="_expected_result",
            operator="matches",
            expected=str(expected),
            actual="0 results",
            passed=False,
            message=message,
        )

    passed = any(_row_matches_expected(row, expected) for row in results)
    actual = str(results[0]) if results else ""
    if passed:
        message = "at least one row matched expected result \u2713"
    else:
        message = "no rows matched expected result {0!r} \u2717".format(expected)

    return ValidationDetail(
        field="_expected_result",
        operator="matches",
        expected=str(expected),
        actual=actual,
        passed=passed,
        message=message,
    )


def _row_matches_expected(row: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    for key, value in expected.items():
        if str(row.get(key)) != str(value):
            return False
    return True


def _scope_matches(scope: Any, scenario_name: str) -> bool:
    if scope == "all" or scope is None:
        return True
    if isinstance(scope, list):
        return scenario_name in scope
    return True
