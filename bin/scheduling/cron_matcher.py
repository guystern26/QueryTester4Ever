# -*- coding: utf-8 -*-
"""
cron_matcher.py — 5-field cron expression matching.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple


def cron_matches(cron_expr, dt_tuple):
    # type: (str, Tuple[int, int, int, int, int]) -> bool
    """Check if a 5-field cron expression matches (min, hour, dom, month, dow)."""
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return False

    fields = [
        (parts[0], dt_tuple[0], 0, 59),     # minute
        (parts[1], dt_tuple[1], 0, 23),      # hour
        (parts[2], dt_tuple[2], 1, 31),      # day of month
        (parts[3], dt_tuple[3], 1, 12),      # month
        (parts[4], dt_tuple[4], 0, 6),       # day of week (0=Sunday)
    ]

    for field, current, low, high in fields:
        if not _field_matches(field, current, low, high):
            return False
    return True


def _field_matches(field, current, low, high):
    # type: (str, int, int, int) -> bool
    """Check if a single cron field matches the current value."""
    if field == "*":
        return True

    for part in field.split(","):
        if "/" in part:
            base, step_str = part.split("/", 1)
            try:
                step = int(step_str)
            except ValueError:
                continue
            if base == "*":
                if current % step == 0:
                    return True
            elif "-" in base:
                rng = base.split("-", 1)
                try:
                    rng_low, rng_high = int(rng[0]), int(rng[1])
                    if rng_low <= current <= rng_high and (current - rng_low) % step == 0:
                        return True
                except ValueError:
                    continue
        elif "-" in part:
            rng = part.split("-", 1)
            try:
                rng_low, rng_high = int(rng[0]), int(rng[1])
                if rng_low <= current <= rng_high:
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(part) == current:
                    return True
            except ValueError:
                continue

    return False


def is_enabled(record):
    # type: (Dict[str, Any]) -> bool
    """Normalize the enabled flag from KVStore (handles bool/string variants)."""
    val = record.get("enabled", True)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes")
    return bool(val)
