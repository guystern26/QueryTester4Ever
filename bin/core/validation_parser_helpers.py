# -*- coding: utf-8 -*-
"""
validation_parser_helpers.py
Helper functions for parsing validation sub-structures.
"""
from __future__ import annotations

from typing import Any, Dict, List

from logger import get_logger
from core.models import FieldCondition, FieldConditionGroup, ResultCount


logger = get_logger(__name__)


def get_str(obj: Dict[str, Any], key: str, default: str) -> str:
    """Get a string value from a dict, with a default fallback."""
    value = obj.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        logger.warning(
            'Could not convert value for key "%s" to string; using default "%s".',
            key,
            default,
        )
        return default


def parse_field_condition(raw: Dict[str, Any]) -> FieldCondition:
    """Parse a single field condition dict into a FieldCondition dataclass."""
    for key in ("field", "operator", "value"):
        if key not in raw:
            raise ValueError(
                'Missing required key "{0}" in fieldCondition: {1}'.format(key, raw)
            )

    field = raw["field"]
    if not isinstance(field, str):
        raise ValueError(
            'Expected "field" to be a string but received %s.'
            % type(field).__name__
        )
    operator = raw["operator"]
    if not isinstance(operator, str):
        raise ValueError(
            'Expected "operator" to be a string but received %s.'
            % type(operator).__name__
        )
    value = raw["value"]
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            raise ValueError(
                'Expected "value" to be a string but received %s.'
                % type(value).__name__
            )
    scenario_scope = raw.get("scenarioScope", "all")
    return FieldCondition(
        field=field,
        operator=operator,
        value=value,
        scenario_scope=scenario_scope,
    )


def parse_field_group(raw: Dict[str, Any]) -> FieldConditionGroup:
    """Parse a field group dict into a FieldConditionGroup dataclass."""
    field_name = raw.get("field")
    if not field_name or not isinstance(field_name, str):
        raise ValueError(
            'Missing or non-string "field" in fieldGroup: {0}'.format(raw)
        )
    condition_logic = get_str(raw, "conditionLogic", "and")
    scenario_scope = raw.get("scenarioScope", "all")

    conditions_raw = raw.get("conditions") or []
    if not isinstance(conditions_raw, list):
        raise ValueError(
            'Expected "conditions" to be a list in fieldGroup: {0}'.format(raw)
        )

    conditions = []  # type: List[FieldCondition]
    for cond_obj in conditions_raw:
        if not isinstance(cond_obj, dict):
            continue
        operator = cond_obj.get("operator")
        if not operator or not isinstance(operator, str):
            continue
        value = cond_obj.get("value", "")
        if not isinstance(value, str):
            try:
                value = str(value)
            except Exception:
                value = ""
        conditions.append(FieldCondition(
            field=field_name,
            operator=operator,
            value=value,
            scenario_scope=scenario_scope,
        ))

    return FieldConditionGroup(
        field=field_name,
        conditions=conditions,
        condition_logic=condition_logic,
        scenario_scope=scenario_scope,
    )


def parse_result_count(raw: Dict[str, Any]) -> ResultCount:
    """Parse a result count dict into a ResultCount dataclass."""
    enabled = bool(raw.get("enabled", True))
    operator = get_str(raw, "operator", "equals")
    value_raw = raw.get("value", 0)
    if isinstance(value_raw, bool):
        value = int(value_raw)
    elif isinstance(value_raw, (int, float)):
        value = int(value_raw)
    else:
        try:
            value = int(str(value_raw))
        except (TypeError, ValueError):
            logger.warning(
                'Expected "validation.resultCount.value" to be numeric; '
                "received %s. Coercing to 0.",
                type(value_raw).__name__,
            )
            value = 0

    return ResultCount(enabled=enabled, operator=operator, value=value)
