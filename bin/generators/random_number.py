# -*- coding: utf-8 -*-
"""Random number generator — produces random int or float in a range."""
from __future__ import annotations

import random
from typing import Any, Dict, List

from core.helpers import normalize_weights
from core.models import GeneratorRule


def _parse_variant(variant: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate numeric params from a variant config dict."""
    try:
        lo = float(variant.get("min", 0))
    except (TypeError, ValueError):
        lo = 0.0
    try:
        hi = float(variant.get("max", 100))
    except (TypeError, ValueError):
        hi = 100.0
    if lo > hi:
        lo, hi = hi, lo
    decimals = variant.get("decimals", 0)
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 0
    return {
        "lo": lo, "hi": hi, "decimals": decimals,
        "prefix": str(variant.get("prefix", "") or ""),
        "suffix": str(variant.get("suffix", "") or ""),
    }


def _generate_from_parsed(v: Dict[str, Any]) -> str:
    """Generate a random number string from pre-parsed variant params."""
    if v["decimals"] > 0:
        num = str(round(random.uniform(v["lo"], v["hi"]), v["decimals"]))
    else:
        num = str(random.randint(int(v["lo"]), int(v["hi"])))
    return v["prefix"] + num + v["suffix"]


def prepare(rule: GeneratorRule) -> Dict[str, Any]:
    """Pre-parse config for the generation loop. Called once per rule."""
    variants = rule.config.get("variants") or []

    # Legacy format: {min, max, float}
    if not variants and "min" in rule.config:
        lo = rule.config.get("min", 0)
        hi = rule.config.get("max", 100)
        try:
            lo_f, hi_f = float(lo), float(hi)
        except (TypeError, ValueError):
            lo_f, hi_f = 0.0, 100.0
        if lo_f > hi_f:
            lo_f, hi_f = hi_f, lo_f
        return {
            "mode": "legacy", "lo": lo_f, "hi": hi_f,
            "is_float": bool(rule.config.get("float", False)),
        }

    if not variants:
        return {"mode": "default"}

    parsed = [_parse_variant(v) for v in variants]
    if len(parsed) == 1:
        return {"mode": "single", "variant": parsed[0]}

    weights = []  # type: List[float]
    for v in variants:
        try:
            weights.append(float(v.get("weight", 1)))
        except (TypeError, ValueError):
            weights.append(1.0)
    return {"mode": "weighted", "variants": parsed, "weights": normalize_weights(weights)}


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Generate a random number as a string, with optional prefix/suffix."""
    if prepared is None:
        prepared = prepare(rule)
    mode = prepared["mode"]
    if mode == "legacy":
        if prepared["is_float"]:
            return str(round(random.uniform(prepared["lo"], prepared["hi"]), 2))
        return str(random.randint(int(prepared["lo"]), int(prepared["hi"])))
    if mode == "default":
        return str(random.randint(0, 100))
    if mode == "single":
        return _generate_from_parsed(prepared["variant"])
    # mode == "weighted": pick a variant then generate from its pre-parsed params
    chosen = random.choices(prepared["variants"], weights=prepared["weights"], k=1)[0]
    return _generate_from_parsed(chosen)
