# -*- coding: utf-8 -*-
"""
sub_query_runner.py
Execute a sub-query SPL and return its results as events for test data injection.
Used by the 'query_data' input mode.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from logger import get_logger
from spl.query_executor import QueryExecutor

logger = get_logger(__name__)


def run_sub_query(
    spl,          # type: str
    session_key,  # type: str
    app,          # type: str
    earliest_time,  # type: str
    latest_time,    # type: str
):
    # type: (...) -> Tuple[List[Dict[str, Any]], List[str]]
    """
    Execute the sub-query SPL and return (events, warnings).

    All events are returned for indexing — no truncation.
    Internal Splunk fields (keys starting with '_') are stripped.
    """
    if not spl or not spl.strip():
        raise ValueError("query_data input has an empty sub-query SPL.")

    warnings = []  # type: List[str]

    executor = QueryExecutor(session_key)
    results = executor.run(
        spl,
        app=app,
        earliest_time=earliest_time,
        latest_time=latest_time,
    )

    logger.info("Sub-query returned %d rows.", len(results))

    # --- Non-tabular data warning ---
    if results and _is_raw_data(results):
        warnings.append(
            "The sub-query returned raw (non-tabular) events. "
            "For best results, add '| table *' or '| table field1, field2, ...' "
            "to the end of your query to produce structured fields."
        )

    # Strip Splunk internal fields — keep only user-visible data
    cleaned = []  # type: List[Dict[str, Any]]
    for row in results:
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        if clean:
            cleaned.append(clean)

    return cleaned, warnings


def _is_raw_data(results):
    # type: (List[Dict[str, Any]]) -> bool
    """Check if results look like raw events rather than tabular data.

    Heuristic: if most rows have '_raw' but very few non-internal fields,
    the user probably forgot to pipe through '| table'.
    """
    sample = results[:20]
    raw_count = 0
    low_field_count = 0
    for row in sample:
        if "_raw" in row:
            raw_count += 1
        user_fields = [k for k in row if not k.startswith("_")]
        if len(user_fields) <= 2:
            low_field_count += 1
    # If >50% of sampled rows have _raw AND >50% have very few user fields
    threshold = len(sample) / 2
    return raw_count > threshold and low_field_count > threshold
