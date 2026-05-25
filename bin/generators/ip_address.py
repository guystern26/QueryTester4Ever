# -*- coding: utf-8 -*-
"""IP address generator — produces IPs from subnet or custom octets."""
from __future__ import annotations

import random
from typing import Any, Dict, List

from core.helpers import normalize_weights
from core.models import GeneratorRule

_SUBNET_MAP = {
    "private_a": "10.0.0",
    "private_b": "172.16.0",
    "private_c": "192.168.1",
    "ipv4": "10.0.0",
}


def _generate_ip(variant: Dict[str, Any]) -> str:
    """Generate a single IP from a variant config."""
    custom = variant.get("customOctets")
    if custom and isinstance(custom, list) and len(custom) >= 4:
        octets = []
        for octet in custom[:4]:
            if octet == "" or octet is None:
                octets.append(str(random.randint(1, 254)))
            else:
                try:
                    octets.append(str(int(octet)))
                except (TypeError, ValueError):
                    octets.append(str(random.randint(1, 254)))
        return ".".join(octets)

    ip_type = variant.get("ipType", "private_c")
    subnet = _SUBNET_MAP.get(str(ip_type), "10.0.0")
    prefix = str(variant.get("prefix", "") or "")
    suffix = str(variant.get("suffix", "") or "")
    ip = "{0}.{1}".format(subnet, random.randint(1, 254))
    return prefix + ip + suffix


def prepare(rule: GeneratorRule) -> Dict[str, Any]:
    """Pre-parse IP config. Pre-computes weights for multi-variant mode."""
    # Legacy format: {subnet: "10.0.0"}
    if "subnet" in rule.config and "variants" not in rule.config:
        return {"mode": "legacy", "subnet": rule.config.get("subnet", "10.0.0")}

    variants = rule.config.get("variants") or []
    if not variants:
        return {"mode": "default"}

    if len(variants) == 1:
        return {"mode": "single", "variant": variants[0]}

    # Multi-variant: pre-compute normalized weights once
    weights = []  # type: List[float]
    for v in variants:
        try:
            weights.append(float(v.get("weight", 1)))
        except (TypeError, ValueError):
            weights.append(1.0)
    return {"mode": "weighted", "variants": variants, "weights": normalize_weights(weights)}


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Generate an IP address string."""
    if prepared is None:
        prepared = prepare(rule)
    mode = prepared["mode"]
    if mode == "legacy":
        return "{0}.{1}".format(prepared["subnet"], random.randint(1, 254))
    if mode == "default":
        return "10.0.0.{0}".format(random.randint(1, 254))
    if mode == "single":
        return _generate_ip(prepared["variant"])
    # mode == "weighted": pick variant, then generate
    chosen = random.choices(prepared["variants"], weights=prepared["weights"], k=1)[0]
    return _generate_ip(chosen)
