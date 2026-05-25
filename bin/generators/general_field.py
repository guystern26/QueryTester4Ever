# -*- coding: utf-8 -*-
"""General field generator — produces {prefix}{random_component}{suffix} values."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional, Tuple

from core.helpers import normalize_weights
from core.models import GeneratorRule


def _random_component(comp_type: str, length: int) -> str:
    """Generate a random string component based on type and length."""
    if length < 1:
        length = 6
    if comp_type == "numeric":
        return "".join(random.choices(string.digits, k=length))
    if comp_type == "alpha":
        return "".join(random.choices(string.ascii_letters, k=length))
    if comp_type == "hex":
        return "".join(random.choices(string.hexdigits[:16], k=length))
    # default: alphanumeric
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


ParsedVariant = Dict[str, Any]
PreparedGeneralField = Tuple[List[ParsedVariant], List[float]]


def prepare(rule: GeneratorRule) -> Optional[PreparedGeneralField]:
    """Pre-parse variant configs and normalize weights once."""
    variants = rule.config.get("variants") or []
    if not variants:
        return None
    parsed = []  # type: List[ParsedVariant]
    weights_input = []  # type: List[float]
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        comp_length = variant.get("componentLength", 6)
        try:
            comp_length = int(comp_length)
        except (TypeError, ValueError):
            comp_length = 6
        parsed.append({
            "prefix": str(variant.get("prefix", "") or ""),
            "suffix": str(variant.get("suffix", "") or ""),
            "comp_type": str(variant.get("componentType", "alphanumeric") or "alphanumeric"),
            "comp_length": comp_length,
        })
        try:
            weights_input.append(float(variant.get("weight", 1)))
        except (TypeError, ValueError):
            weights_input.append(1.0)
    if not parsed:
        return None
    return (parsed, normalize_weights(weights_input))


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Pick ONE variant via pre-computed weights, then generate its random component."""
    if prepared is None:
        prepared = prepare(rule)
        if prepared is None:
            return ""
    parsed, weights = prepared
    # Pick the variant FIRST, then generate only that variant's random component.
    # Previous implementation generated random components for ALL variants before
    # picking — wasting work proportional to variant count on every call.
    chosen = random.choices(parsed, weights=weights, k=1)[0]
    return chosen["prefix"] + _random_component(chosen["comp_type"], chosen["comp_length"]) + chosen["suffix"]
