# -*- coding: utf-8 -*-
"""Pick-list generator — weighted random selection from a list of values."""
from __future__ import annotations

import random
from typing import Any, List, Optional, Tuple

from core.helpers import normalize_weights
from core.models import GeneratorRule


PreparedPickList = Tuple[List[str], List[float]]


def prepare(rule: GeneratorRule) -> Optional[PreparedPickList]:
    """Pre-compute values and normalized weights once. Returns None if no variants."""
    variants = rule.config.get("variants") or []
    if not variants:
        return None
    values = []  # type: List[str]
    weights_input = []  # type: List[float]
    for variant in variants:
        value = variant.get("value")
        # None means unconfigured — treat as empty string, not the literal "None"
        values.append(str(value) if value is not None else "")
        try:
            weights_input.append(float(variant.get("weight", 1)))
        except (TypeError, ValueError):
            weights_input.append(1.0)
    return (values, normalize_weights(weights_input))


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Pick a weighted-random value from the pre-computed list."""
    if prepared is None:
        prepared = prepare(rule)
        if prepared is None:
            return ""
    values, weights = prepared
    return random.choices(values, weights=weights, k=1)[0]
