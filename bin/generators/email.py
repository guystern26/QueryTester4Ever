# -*- coding: utf-8 -*-
"""Email generator — produces user@domain addresses with configurable local parts."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List

from core.helpers import normalize_weights
from core.models import GeneratorRule


def _generate_local_part(variant: Dict[str, Any], index: int) -> str:
    """Generate the local part of the email based on variant config."""
    comp_type = str(variant.get("componentType", "numeric") or "numeric")
    comp_length = variant.get("componentLength", 4)
    try:
        comp_length = int(comp_length)
    except (TypeError, ValueError):
        comp_length = 4
    if comp_length < 1:
        comp_length = 4

    local_part = str(variant.get("localPart", "user") or "user")

    if comp_type == "numeric":
        suffix = "".join(random.choices(string.digits, k=comp_length))
    elif comp_type == "string":
        suffix = "".join(random.choices(string.ascii_lowercase, k=comp_length))
    else:
        suffix = str(index + 1)

    return local_part + suffix


def prepare(rule: GeneratorRule) -> Dict[str, Any]:
    """Pre-parse email config. Pre-computes weights for multi-variant mode."""
    variants = rule.config.get("variants") or []

    # Legacy format: {domain: "example.com"}
    if not variants and "domain" in rule.config:
        return {"mode": "legacy", "domain": rule.config.get("domain", "example.com")}

    if not variants:
        return {"mode": "simple"}

    if len(variants) == 1:
        v = variants[0]
        return {
            "mode": "single",
            "domain": str(v.get("domain", "example.com") or "example.com"),
            "variant": v,
        }

    # Multi-variant: pre-compute normalized weights once
    weights = []  # type: List[float]
    for v in variants:
        try:
            weights.append(float(v.get("weight", 1)))
        except (TypeError, ValueError):
            weights.append(1.0)
    return {"mode": "weighted", "variants": variants, "weights": normalize_weights(weights)}


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Generate an email address."""
    if prepared is None:
        prepared = prepare(rule)
    mode = prepared["mode"]
    if mode == "legacy":
        return "user{0}@{1}".format(index + 1, prepared["domain"])
    if mode == "simple":
        return "user{0}@example.com".format(index + 1)
    if mode == "single":
        local = _generate_local_part(prepared["variant"], index)
        return "{0}@{1}".format(local, prepared["domain"])
    # mode == "weighted": pick variant, then generate
    chosen = random.choices(prepared["variants"], weights=prepared["weights"], k=1)[0]
    domain = str(chosen.get("domain", "example.com") or "example.com")
    return "{0}@{1}".format(_generate_local_part(chosen, index), domain)
