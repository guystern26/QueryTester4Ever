# -*- coding: utf-8 -*-
"""
config_parser.py
Parse generator configuration from raw payload dicts.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from logger import get_logger
from core.models import GeneratorConfig, GeneratorRule


logger = get_logger(__name__)


def parse_generator_config(raw: Dict[str, Any]) -> GeneratorConfig:
    """Parse a generatorConfig block into a GeneratorConfig dataclass."""
    enabled = bool(raw.get("enabled", False))
    event_count_raw = raw.get("eventCount", 0)
    if isinstance(event_count_raw, bool):
        event_count = int(event_count_raw)
    elif isinstance(event_count_raw, (int, float)):
        event_count = int(event_count_raw)
    else:
        try:
            event_count = int(str(event_count_raw))
        except (TypeError, ValueError):
            logger.warning(
                'Expected "generatorConfig.eventCount" to be numeric; '
                "received %s. Coercing to 0.",
                type(event_count_raw).__name__,
            )
            event_count = 0

    rules_raw = raw.get("rules") or []
    if not isinstance(rules_raw, list):
        logger.warning(
            'Expected "generatorConfig.rules" to be a list; '
            "received %s. Treating as empty.",
            type(rules_raw).__name__,
        )
        rules_raw = []

    rules = []  # type: List[GeneratorRule]
    for rule_obj in rules_raw:
        if not isinstance(rule_obj, dict):
            logger.warning(
                "Skipping non-object generator rule of type %s.",
                type(rule_obj).__name__,
            )
            continue
        rules.append(_parse_generator_rule(rule_obj))

    return GeneratorConfig(enabled=enabled, event_count=event_count, rules=rules)


def _parse_generator_rule(raw: Dict[str, Any]) -> GeneratorRule:
    rule_id = _get_str(raw, "id", "")
    field_name = raw["fieldName"]
    if not isinstance(field_name, str):
        raise ValueError(
            'Expected "fieldName" to be a string but received %s.'
            % type(field_name).__name__
        )
    generation_type = raw["generationType"]
    if not isinstance(generation_type, str):
        raise ValueError(
            'Expected "generationType" to be a string but received %s.'
            % type(generation_type).__name__
        )
    config_raw = raw.get("config") or {}
    if not isinstance(config_raw, dict):
        logger.warning(
            'Expected "generatorConfig.rules[].config" to be an object; '
            "received %s. Using empty object.",
            type(config_raw).__name__,
        )
        config_raw = {}

    config_normalized = _normalize_config(generation_type, config_raw)

    return GeneratorRule(
        id=rule_id,
        field_name=field_name,
        generation_type=generation_type,
        config=config_normalized,
    )


def _normalize_pick_list(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Frontend sends {items: [...]}; backend expects {variants: [...]}."""
    items = raw.get("items") or raw.get("variants") or []
    return {"variants": items}


def _normalize_general_field(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Variant list pass-through — accepts either 'variants' or 'items' key."""
    variants = raw.get("variants") or raw.get("items") or []
    return {"variants": variants}


def _normalize_numbered(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Frontend sends {pattern, rangeStart, padLength}; backend expects {prefix, start, padding}."""
    prefix = raw.get("pattern") or raw.get("prefix", "")
    start = raw.get("rangeStart", raw.get("start", 1))
    padding = raw.get("padLength", raw.get("padding", 0))
    return {"prefix": prefix, "start": start, "padding": padding}


def _normalize_variants_passthrough(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Pass through variants list unchanged — used by types with matching frontend/backend shape."""
    variants = raw.get("variants") or []
    return {"variants": variants}


ConfigNormalizer = Callable[[Dict[str, Any]], Dict[str, Any]]

CONFIG_NORMALIZERS: Dict[str, ConfigNormalizer] = {
    "pick_list": _normalize_pick_list,
    "general_field": _normalize_general_field,
    "numbered": _normalize_numbered,
    "random_number": _normalize_variants_passthrough,
    "email": _normalize_variants_passthrough,
    "unique_id": _normalize_variants_passthrough,
    "ip_address": _normalize_variants_passthrough,
}


def _normalize_config(gen_type: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map frontend camelCase config keys to what each backend generator expects."""
    normalizer = CONFIG_NORMALIZERS.get(gen_type)
    if normalizer is None:
        return raw
    return normalizer(raw)


def _get_str(obj: Dict[str, Any], key: str, default: str) -> str:
    value = obj.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return default
