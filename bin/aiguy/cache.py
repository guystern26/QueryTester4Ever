from __future__ import annotations

import hashlib
import json
import os
import time

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".aiguy_cache",
)
_CACHE_TTL = 86400  # 24 hours

# Values containing these substrings are errors — never cache them
_ERROR_MARKERS = (
    "(no response from AI)",
    "(empty AI response",
    "AI error:",
    "LLM HTTP",
    "Cannot reach LLM",
)


def _is_error(val):
    # type: (str) -> bool
    """True if the value looks like a failed LLM response."""
    if not val:
        return True
    for marker in _ERROR_MARKERS:
        if marker in val:
            return True
    return False


def _cache_path(mode, field_name, prompt):
    # type: (str, str, str) -> str
    key = "{0}|{1}|{2}".format(mode, field_name, prompt).encode("utf-8")
    h = hashlib.md5(key).hexdigest()[:12]
    return os.path.join(_CACHE_DIR, "{0}_{1}.json".format(mode, h))


def load_cache(mode, field_name, prompt):
    # type: (str, str, str) -> dict
    path = _cache_path(mode, field_name, prompt)
    try:
        if not os.path.exists(path):
            return {}
        age = time.time() - os.path.getmtime(path)
        if age > _CACHE_TTL:
            return {}
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Strip any error entries that leaked into the cache
            return {k: v for k, v in data.items() if not _is_error(str(v))}
    except Exception:
        pass
    return {}


def save_cache(mode, field_name, prompt, mapping):
    # type: (str, str, str, dict) -> None
    # Filter out error values before saving
    clean = {k: v for k, v in mapping.items() if v and not _is_error(str(v))}
    if not clean:
        return  # nothing worth caching
    try:
        if not os.path.isdir(_CACHE_DIR):
            os.makedirs(_CACHE_DIR)
        path = _cache_path(mode, field_name, prompt)
        with open(path, "w") as f:
            json.dump(clean, f, ensure_ascii=False)
    except Exception:
        pass


def split_cached(unique_vals, cached):
    # type: (list, dict) -> tuple
    hit = {}   # type: dict
    miss = []  # type: list
    for val in unique_vals:
        if val in cached and cached[val] and not _is_error(str(cached[val])):
            hit[val] = cached[val]
        else:
            miss.append(val)
    return hit, miss
