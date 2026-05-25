# -*- coding: utf-8 -*-
"""
payload_parser.py
Parse raw JSON payloads from the frontend into typed Python dataclasses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from logger import get_logger
from core.models import (
    ParsedInput,
    ParsedScenario,
    QueryDataConfig,
    TestPayload,
)
from core.validation_parser import parse_validation
from generators.config_parser import parse_generator_config


logger = get_logger(__name__)


def parse(raw: Dict[str, Any]) -> TestPayload:
    """
    Parse a raw payload dictionary into a TestPayload instance.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "Payload root must be a JSON object (dict). "
            "Received type: {0}".format(type(raw).__name__)
        )

    try:
        test_name = _require_str(raw, "testName")
        app = _require_str(raw, "app")
        test_type = _require_str(raw, "testType")
        query = _require_str(raw, "query")
    except KeyError as exc:
        raise ValueError(
            "Missing required top-level key in payload: {0}".format(str(exc))
        )

    # Fail fast: check time range before parsing scenarios/validation (cheap fatal check)
    earliest_time = raw.get("earliestTime", "0")
    latest_time = raw.get("latestTime", "now")
    if not isinstance(earliest_time, str):
        earliest_time = "0"
    if not isinstance(latest_time, str):
        latest_time = "now"
    if earliest_time.strip() == "0":
        raise ValueError(
            '"All time" is not allowed. Please select a specific time range.'
        )

    validation_raw = raw.get("validation") or {}
    if not isinstance(validation_raw, dict):
        raise ValueError("validation must be an object when provided.")
    validation = parse_validation(validation_raw)

    scenarios_raw = raw.get("scenarios")
    scenarios = []  # type: List[ParsedScenario]
    if scenarios_raw is None:
        scenarios_raw = []
    if not isinstance(scenarios_raw, list):
        logger.warning(
            'Expected "scenarios" to be a list but received %s; treating as empty.',
            type(scenarios_raw).__name__,
        )
        scenarios_raw = []
    for scenario_obj in scenarios_raw:
        if not isinstance(scenario_obj, dict):
            logger.warning(
                "Skipping non-object scenario entry of type %s.",
                type(scenario_obj).__name__,
            )
            continue
        scenarios.append(_parse_scenario(scenario_obj))

    return TestPayload(
        test_name=test_name,
        test_type=test_type,
        app=app,
        query=query,
        scenarios=scenarios,
        validation=validation,
        earliest_time=earliest_time,
        latest_time=latest_time,
    )


def _require_str(obj: Dict[str, Any], key: str) -> str:
    value = obj[key]
    if not isinstance(value, str):
        raise ValueError(
            'Expected "%s" to be a string but received %s.'
            % (key, type(value).__name__)
        )
    return value


def _parse_scenario(raw: Dict[str, Any]) -> ParsedScenario:
    name = _get_str_with_default(raw, "name", "Unnamed Scenario")
    inputs_raw = raw.get("inputs") or []
    if not isinstance(inputs_raw, list):
        logger.warning(
            'Expected "scenario.inputs" to be a list; received %s. Treating as empty.',
            type(inputs_raw).__name__,
        )
        inputs_raw = []

    inputs = []  # type: List[ParsedInput]
    for input_obj in inputs_raw:
        if not isinstance(input_obj, dict):
            logger.warning(
                "Skipping non-object input entry of type %s.",
                type(input_obj).__name__,
            )
            continue
        inputs.append(_parse_input(input_obj))

    return ParsedScenario(name=name, inputs=inputs)


def _parse_input(raw: Dict[str, Any]) -> ParsedInput:
    row_identifier = _get_str_with_default(raw, "rowIdentifier", "")
    input_mode = _get_str_with_default(raw, "inputMode", "fields")

    events_raw = raw.get("events") or []
    events = []  # type: List[Dict[str, Any]]
    if not isinstance(events_raw, list):
        logger.warning(
            'Expected "input.events" to be a list; received %s. Treating as empty.',
            type(events_raw).__name__,
        )
        events_raw = []

    for event in events_raw:
        if not isinstance(event, dict):
            logger.warning(
                "Skipping non-object event entry of type %s.",
                type(event).__name__,
            )
            continue
        if not event:
            continue
        events.append(event)

    generator_config_raw = raw.get("generatorConfig")
    generator_config = None  # type: Optional[Any]
    if generator_config_raw is None:
        pass
    elif not isinstance(generator_config_raw, dict):
        logger.warning(
            'Expected "generatorConfig" to be an object or null; '
            "received %s. Treating as disabled.",
            type(generator_config_raw).__name__,
        )
    elif generator_config_raw.get("enabled"):
        generator_config = parse_generator_config(generator_config_raw)

    # Parse query_data config if present
    query_data_config = None  # type: Optional[QueryDataConfig]
    qd_raw = raw.get("queryDataConfig")
    if isinstance(qd_raw, dict) and qd_raw.get("spl"):
        query_data_config = QueryDataConfig(
            spl=str(qd_raw.get("spl", "")),
            earliest_time=str(qd_raw.get("earliestTime", "0")),
            latest_time=str(qd_raw.get("latestTime", "now")),
        )

    return ParsedInput(
        row_identifier=row_identifier,
        input_mode=input_mode,
        events=events,
        generator_config=generator_config,
        query_data_config=query_data_config,
    )


def _get_str_with_default(obj: Dict[str, Any], key: str, default: str) -> str:
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
