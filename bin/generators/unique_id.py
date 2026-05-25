# -*- coding: utf-8 -*-
"""Unique ID generator — produces UUID, short hex, numeric, or alphanumeric IDs."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from core.models import GeneratorRule


PreparedUniqueId = Tuple[str, str, str, int]


def prepare(rule: GeneratorRule) -> Optional[PreparedUniqueId]:
    """Pre-parse variant config once. Returns (fmt, prefix, suffix, length) or None."""
    variants = rule.config.get("variants") or []
    if not variants or not isinstance(variants[0], dict):
        return None
    variant = variants[0]  # type: Dict[str, Any]
    fmt = variant.get("format", "uuid")
    prefix = str(variant.get("prefix", "") or "")
    suffix = str(variant.get("suffix", "") or "")
    length = variant.get("length", 32)
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 32
    if length < 1:
        length = 32
    return (fmt, prefix, suffix, length)


def generate(rule: GeneratorRule, index: int, prepared: Any = None) -> str:
    """Generate a unique ID string."""
    if prepared is None:
        prepared = prepare(rule)
        if prepared is None:
            return uuid4().hex
    fmt, prefix, suffix, length = prepared
    if fmt == "uuid":
        core = uuid4().hex
    elif fmt == "sequential":
        core = str(index + 1)
    elif fmt == "numeric":
        core = "".join(random.choices(string.digits, k=length))
    elif fmt == "hex":
        core = "".join(random.choices(string.hexdigits[:16], k=length))
    elif fmt == "alphanumeric":
        core = "".join(random.choices(string.ascii_letters + string.digits, k=length))
    else:
        core = uuid4().hex
    return prefix + core + suffix
