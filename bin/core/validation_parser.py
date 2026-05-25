# -*- coding: utf-8 -*-
"""
validation_parser.py
Parse the validation section of the frontend payload into typed dataclasses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from logger import get_logger
from core.models import (
    FieldCondition,
    FieldConditionGroup,
    ResultCount,
    ValidationConfig,
)
from core.validation_parser_helpers import (
    get_str,
    parse_field_condition,
    parse_field_group,
    parse_result_count,
)


logger = get_logger(__name__)


def parse_validation(raw: Dict[str, Any]) -> ValidationConfig:
    """Parse the validation block of a payload into a ValidationConfig."""
    validation_type = get_str(raw, "validationType", "standard")
    expected_result = raw.get("expectedResult")
    if expected_result is not None and not isinstance(expected_result, dict):
        logger.warning(
            'Expected "validation.expectedResult" to be an object or null; '
            "received %s. Coercing to None.",
            type(expected_result).__name__,
        )
        expected_result = None

    field_conditions_raw = raw.get("fieldConditions")
    if field_conditions_raw is None:
        field_conditions = None  # type: Optional[List[FieldCondition]]
    else:
        if not isinstance(field_conditions_raw, list):
            logger.warning(
                'Expected "validation.fieldConditions" to be a list or null; '
                "received %s. Treating as no field conditions.",
                type(field_conditions_raw).__name__,
            )
            field_conditions = None
        else:
            field_conditions = []
            for condition_obj in field_conditions_raw:
                if not isinstance(condition_obj, dict):
                    logger.warning(
                        "Skipping non-object field condition of type %s.",
                        type(condition_obj).__name__,
                    )
                    continue
                try:
                    field_conditions.append(parse_field_condition(condition_obj))
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed field condition: %s", str(exc)
                    )

    # Parse fieldGroups (structured, with per-group conditionLogic)
    field_groups_raw = raw.get("fieldGroups")
    field_groups = None  # type: Optional[List[FieldConditionGroup]]
    if field_groups_raw is not None:
        if not isinstance(field_groups_raw, list):
            logger.warning(
                'Expected "validation.fieldGroups" to be a list or null; '
                "received %s. Ignoring.",
                type(field_groups_raw).__name__,
            )
        else:
            field_groups = []
            for group_obj in field_groups_raw:
                if not isinstance(group_obj, dict):
                    logger.warning(
                        "Skipping non-object field group of type %s.",
                        type(group_obj).__name__,
                    )
                    continue
                try:
                    field_groups.append(parse_field_group(group_obj))
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed field group: %s", str(exc)
                    )

    field_logic = get_str(raw, "fieldLogic", "and")
    validation_scope = get_str(raw, "validationScope", "any_event")

    scope_n_raw = raw.get("scopeN")
    scope_n = None  # type: Optional[int]
    if scope_n_raw is not None:
        try:
            scope_n = int(scope_n_raw)
        except (TypeError, ValueError):
            logger.warning(
                'Expected "validation.scopeN" to be numeric; '
                "received %s. Ignoring.",
                type(scope_n_raw).__name__,
            )

    result_count_raw = raw.get("resultCount")
    if result_count_raw is None:
        result_count = None  # type: Optional[ResultCount]
    else:
        if not isinstance(result_count_raw, dict):
            logger.warning(
                'Expected "validation.resultCount" to be an object or null; '
                "received %s. Skipping result count check.",
                type(result_count_raw).__name__,
            )
            result_count = None
        else:
            result_count = parse_result_count(result_count_raw)

    return ValidationConfig(
        validation_type=validation_type,
        expected_result=expected_result,
        field_conditions=field_conditions,
        field_groups=field_groups,
        field_logic=field_logic,
        validation_scope=validation_scope,
        scope_n=scope_n,
        result_count=result_count,
    )
