# -*- coding: utf-8 -*-
"""
response_builder.py
Build the final JSON response dict from test results.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models import ScenarioResult, TestPayload, ValidationDetail
from spl.spl_analyzer import SplAnalysis


EMPTY_SPL_ANALYSIS = {
    "unauthorizedCommands": [],
    "unusualCommands": [],
    "uniqLimitations": None,
    "commandsUsed": [],
}  # type: Dict[str, Any]


def build_error_response(
    payload,       # type: Any
    message,       # type: str
    error_code,    # type: str
    analysis=None, # type: Any
):
    # type: (...) -> Dict[str, Any]
    """Build a TestResponse-shaped error dict with all required fields."""
    spl_analysis = EMPTY_SPL_ANALYSIS  # type: Dict[str, Any]
    warnings = []  # type: list
    if analysis is not None:
        spl_analysis = {
            "unauthorizedCommands": analysis.unauthorized_commands,
            "unusualCommands": analysis.unusual_commands,
            "uniqLimitations": analysis.uniq_limitations,
            "commandsUsed": analysis.commands_used,
        }
        warnings = analysis.warnings

    return {
        "status": "error",
        "message": message,
        "testName": payload.test_name if payload else "",
        "testType": payload.test_type if payload else "",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "totalScenarios": 0,
        "passedScenarios": 0,
        "errors": [{"code": error_code, "message": message, "severity": "error"}],
        "warnings": warnings,
        "splAnalysis": spl_analysis,
        "scenarioResults": [],
    }


def build_response(
    payload: TestPayload,
    analysis: SplAnalysis,
    scenario_results: List[ScenarioResult],
    max_result_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the top-level response dict returned to the frontend.

    *max_result_rows* truncates serialized result rows per scenario while
    keeping ``resultCount`` accurate. Avoids serializing thousands of rows
    when only a subset is displayed.
    """
    total = len(scenario_results)
    passed_count = sum(1 for s in scenario_results if s.passed)

    if passed_count == total and total > 0:
        status = "pass"
    elif passed_count == 0:
        status = "fail"
    else:
        status = "partial"

    return {
        "status": status,
        "message": "{0}/{1} scenarios passed".format(passed_count, total),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "testName": payload.test_name,
        "testType": payload.test_type,
        "totalScenarios": total,
        "passedScenarios": passed_count,
        "errors": [],
        "warnings": analysis.warnings,
        "splAnalysis": {
            "unauthorizedCommands": analysis.unauthorized_commands,
            "unusualCommands": analysis.unusual_commands,
            "uniqLimitations": analysis.uniq_limitations,
            "commandsUsed": analysis.commands_used,
        },
        "scenarioResults": [
            _scenario_result_to_dict(result, max_result_rows)
            for result in scenario_results
        ],
    }


def _scenario_result_to_dict(
    result: ScenarioResult, max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Serialize a ScenarioResult. Truncates result_rows if max_rows is set."""
    rows = result.result_rows
    if max_rows is not None and len(rows) > max_rows:
        rows = rows[:max_rows]
    return {
        "scenarioName": result.scenario_name,
        "passed": result.passed,
        "executionTimeMs": result.execution_time_ms,
        "resultCount": result.result_count,
        "injectedSpl": result.injected_spl,
        "validations": [
            _validation_detail_to_dict(v) for v in result.validations
        ],
        "resultRows": rows,
        "resultRowsTruncated": max_rows is not None and result.result_count > max_rows,
        "error": result.error,
        "warnings": result.warnings,
    }


def _validation_detail_to_dict(detail: ValidationDetail) -> Dict[str, Any]:
    result = {
        "field": detail.field,
        "condition": detail.operator,
        "expected": detail.expected,
        "actual": detail.actual,
        "passed": detail.passed,
        "message": detail.message,
    }
    if detail.error is not None:
        result["error"] = detail.error
    return result
