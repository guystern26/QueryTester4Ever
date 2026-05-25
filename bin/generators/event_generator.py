# -*- coding: utf-8 -*-
"""
event_generator.py
Expand ParsedInput definitions into flat event lists for indexing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from logger import get_logger
from core.models import GeneratorConfig, GeneratorRule, ParsedInput
from generators import GENERATOR_REGISTRY, PREPARE_REGISTRY


logger = get_logger(__name__)


def build_events(inp: ParsedInput) -> List[Dict[str, Any]]:
    """Expand a ParsedInput into a list of event dicts to be indexed."""
    generator_config = inp.generator_config
    if not generator_config or not generator_config.enabled:
        return _filter_non_empty(inp.events)

    return _generate(inp.events, generator_config)


def _filter_non_empty(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []  # type: List[Dict[str, Any]]
    for event in events:
        if not isinstance(event, dict):
            logger.warning(
                "Skipping non-dict event of type %s in build_events.",
                type(event).__name__,
            )
            continue
        # Keep any event that has at least one field key, even if all values are empty.
        # An event like {"field": ""} is intentional — the user wants an empty value.
        if event:
            result.append(event)
    return result


def _generate(
    base_events: List[Dict[str, Any]], config: GeneratorConfig
) -> List[Dict[str, Any]]:
    template = dict(base_events[0]) if base_events else {}  # type: Dict[str, Any]

    # Pre-compile each rule ONCE before the hot loop.
    # For 10,000+ events this avoids redundant config parsing, weight
    # normalization, and type coercion on every single call.
    prepared_states = []  # type: List[Optional[Any]]
    for rule in config.rules:
        prep_fn = PREPARE_REGISTRY.get(rule.generation_type)
        prepared_states.append(prep_fn(rule) if prep_fn is not None else None)

    result = []  # type: List[Dict[str, Any]]
    for index in range(config.event_count):
        event = dict(template)
        for i, rule in enumerate(config.rules):
            event[rule.field_name] = _apply_rule(rule, index, prepared_states[i])
        result.append(event)
    return result


def _apply_rule(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Dispatch to the correct generator function with pre-compiled state."""
    fn = GENERATOR_REGISTRY.get(rule.generation_type)
    if fn is None:
        logger.warning(
            'Unknown generation_type "%s" -- returning empty string',
            rule.generation_type,
        )
        return ""
    return fn(rule, index, prepared)
