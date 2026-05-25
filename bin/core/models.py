# -*- coding: utf-8 -*-
"""
models.py
All dataclass definitions for the Splunk Query Tester backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Payload dataclasses ──────────────────────────────────────────────────────

@dataclass
class FieldCondition:
    """One field-level validation condition from the frontend payload."""

    field: str
    operator: str
    value: str
    scenario_scope: Any  # "all" or List[str] of scenario IDs


@dataclass
class ResultCount:
    """Configuration for validating overall result count."""

    enabled: bool
    operator: str
    value: int


@dataclass
class FieldConditionGroup:
    """A group of conditions on the same field, with intra-group logic (and/or)."""

    field: str
    conditions: List[FieldCondition]
    condition_logic: str  # "and" or "or"
    scenario_scope: Any  # "all" or List[str] of scenario IDs


@dataclass
class ValidationConfig:
    """Validation configuration shared across scenarios."""

    validation_type: str
    expected_result: Optional[Dict[str, Any]]
    field_conditions: Optional[List[FieldCondition]]
    field_groups: Optional[List[FieldConditionGroup]]
    field_logic: str
    validation_scope: str
    scope_n: Optional[int]
    result_count: Optional[ResultCount]


@dataclass
class GeneratorRule:
    """One rule describing how to generate values for a specific field."""

    id: str
    field_name: str
    generation_type: str
    config: Dict[str, Any]


@dataclass
class GeneratorConfig:
    """Generator configuration for synthesizing additional events."""

    enabled: bool
    event_count: int
    rules: List[GeneratorRule] = field(default_factory=list)


@dataclass
class QueryDataConfig:
    """Configuration for the query_data input mode (sub-query as test data)."""

    spl: str
    earliest_time: str = "-24h@h"
    latest_time: str = "now"


@dataclass
class ParsedInput:
    """One logical input row: base events plus optional generator configuration."""

    row_identifier: str
    input_mode: str = "fields"
    events: List[Dict[str, Any]] = field(default_factory=list)
    generator_config: Optional[GeneratorConfig] = None
    query_data_config: Optional[QueryDataConfig] = None


@dataclass
class ParsedScenario:
    """One scenario the test runner will execute independently."""

    name: str
    inputs: List[ParsedInput] = field(default_factory=list)


@dataclass
class TestPayload:
    """Top-level representation of the test definition received from the frontend."""

    test_name: str
    test_type: str
    app: str
    query: str
    scenarios: List[ParsedScenario] = field(default_factory=list)
    validation: ValidationConfig = field(default=None)  # type: ignore[assignment]
    earliest_time: str = "-24h@h"
    latest_time: str = "now"


# ─── Result dataclasses ───────────────────────────────────────────────────────

@dataclass
class ValidationDetail:
    """Result of evaluating one condition against the query results."""

    field: str
    operator: str
    expected: str
    actual: str
    passed: bool
    message: str
    error: Optional[str] = None


@dataclass
class ScenarioResult:
    """Result of running one scenario."""

    scenario_name: str
    passed: bool
    execution_time_ms: int
    result_count: int
    injected_spl: str
    validations: List[ValidationDetail] = field(default_factory=list)
    result_rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
