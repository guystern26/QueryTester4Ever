# -*- coding: utf-8 -*-
"""Numbered field generator — produces prefix_N values with optional padding."""
from __future__ import annotations

from typing import Any, Tuple

from core.models import GeneratorRule


def prepare(rule: GeneratorRule) -> Tuple[str, int, int]:
    """Pre-parse config once. Returns (prefix, start, padding)."""
    prefix = rule.config.get("prefix", rule.field_name)
    start = rule.config.get("start", 1)
    try:
        start = int(start)
    except (TypeError, ValueError):
        start = 1
    padding = rule.config.get("padding", 0)
    try:
        padding = int(padding)
    except (TypeError, ValueError):
        padding = 0
    return (prefix, start, padding)


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Generate prefix_N with optional zero-padding."""
    if prepared is None:
        prepared = prepare(rule)
    prefix, start, padding = prepared
    number = index + start
    num_str = str(number).zfill(padding) if padding > 0 else str(number)
    return "{0}_{1}".format(prefix, num_str)
