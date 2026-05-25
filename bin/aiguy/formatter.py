from __future__ import annotations

from .constants import (
    MAX_ROWS_FOR_AI,
    MAX_COLS_FOR_AI,
    MAX_CELL_LEN,
    MAX_PROMPT_CHARS,
)


def clean_llm_response(raw):
    # type: (str) -> str
    """Strip markdown fences, quotes, and whitespace from LLM output."""
    clean = raw.strip().strip('"').strip("'")
    if clean.startswith("```"):
        inner = clean[3:]
        if inner.startswith("\n"):
            inner = inner[1:]
        elif "\n" in inner:
            inner = inner.split("\n", 1)[1]
        clean = inner.rsplit("```", 1)[0].strip()
    return clean.strip("`")


def _pick_columns(rows, focus_field):
    # type: (list, str) -> tuple
    """Pick columns: drop constants, drop _raw when many rows.
    Returns (keys, constants_note).
    """
    _KEEP = {"_time", "_raw"}
    all_keys = [
        k for k in rows[0].keys()
        if not k.startswith("_") or k in _KEEP
    ]
    if not all_keys:
        all_keys = list(rows[0].keys())

    # Detect constant columns (same value in every row)
    constants = {}  # type: dict
    varying = []
    sample = rows[:50]  # check first 50 for constants
    for k in all_keys:
        vals = set(str(r.get(k, "")) for r in sample)
        if len(vals) == 1 and len(sample) > 1:
            constants[k] = vals.pop()
        else:
            varying.append(k)

    # Drop _raw when many unique rows (it's huge and repetitive)
    unique_est = len(set(
        str(r.get(focus_field or varying[0] if varying else "", ""))
        for r in sample
    ))
    if unique_est > 5 and "_raw" in varying:
        varying.remove("_raw")

    keys = varying[:MAX_COLS_FOR_AI]
    # Build a note about constant columns
    note = ""
    if constants:
        parts = ["{0}={1}".format(k, v[:60]) for k, v in constants.items()]
        note = "All rows share: " + ", ".join(parts[:5])

    return keys, note


def format_table(rows, focus_field=None, char_budget=0):
    # type: (list, str, int) -> str
    """Format rows as a compact table for the LLM.

    - Drops constant-value columns (noted once above table)
    - Drops _raw when many rows
    - Deduplicates rows
    - Respects char budget
    - Dynamic cell length based on row count
    """
    if not rows:
        return "(no data)"
    budget = char_budget or MAX_PROMPT_CHARS

    keys, constants_note = _pick_columns(rows, focus_field)
    if not keys:
        keys = list(rows[0].keys())[:MAX_COLS_FOR_AI]

    # Dynamic cell length: fewer unique rows = more room per cell
    unique_est = len(set(
        str(r.get(focus_field or keys[0], "")) for r in rows[:50]
    ))
    if unique_est <= 3:
        cell_limit = 2000
    elif unique_est <= 10:
        cell_limit = 500
    else:
        cell_limit = MAX_CELL_LEN

    # Build table
    parts = []
    if constants_note:
        parts.append(constants_note)

    header = "| " + " | ".join(keys) + " |"
    sep = "| " + " | ".join("---" for _ in keys) + " |"
    parts.append(header)
    parts.append(sep)
    used = sum(len(p) for p in parts) + len(parts)

    seen = set()  # type: set
    for row in rows:
        if focus_field:
            dedup_key = str(row.get(focus_field, ""))
        else:
            dedup_key = "|".join(str(row.get(k, "")) for k in keys)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        cells = []
        for k in keys:
            val = str(row.get(k, ""))
            if len(val) > cell_limit:
                val = val[:cell_limit - 3] + "..."
            cells.append(val)
        line = "| " + " | ".join(cells) + " |"

        if used + len(line) + 1 > budget:
            break
        parts.append(line)
        used += len(line) + 1
        if len(seen) >= MAX_ROWS_FOR_AI:
            break

    return "\n".join(parts)


def trim_values_to_budget(values, budget=0):
    # type: (list, int) -> list
    """Trim a list of string values to fit within a char budget."""
    limit = budget or MAX_PROMPT_CHARS
    result = []
    used = 2  # for JSON brackets []
    for val in values:
        entry_len = len(val) + 4
        if used + entry_len > limit:
            break
        result.append(val)
        used += entry_len
    return result
