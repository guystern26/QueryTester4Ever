# -*- coding: utf-8 -*-
"""
spl_drift.py — SPL drift detection for scheduled tests.
Compares current SPL against the last passed run, with human-readable diffs.
"""
from __future__ import annotations

import difflib
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from splunk_connect import get_service
from logger import get_logger

logger = get_logger(__name__)

COLLECTION_RUN_HISTORY = "test_run_history"


def compute_spl_hash(spl):
    # type: (str) -> str
    """Compute a short MD5 hash of SPL, stripping whitespace for consistency."""
    normalized = spl.strip().encode("utf-8")
    return hashlib.md5(normalized).hexdigest()[:12]


def fetch_current_spl(session_key, saved_search_name, app=None):
    # type: (str, str, Optional[str]) -> Optional[str]
    """Fetch the current SPL from a Splunk saved search.

    Tries the specified app first, then falls back to '-' (all apps).
    """
    apps_to_try = [app, "-"] if app else ["-"]
    for try_app in apps_to_try:
        try:
            service = get_service(session_key, app=try_app or "-", owner="-")
            search = service.saved_searches[saved_search_name]
            return search["search"]
        except Exception:
            continue
    logger.warning("Could not fetch saved search '%s' in any app.", saved_search_name)
    return None


def check_spl_drift(session_key, saved_search_origin, stored_hash):
    # type: (str, str, str) -> Tuple[bool, Optional[str], str]
    """Compare current SPL hash against stored hash.

    Returns (spl_drift_detected, current_spl, current_hash).
    """
    current_spl = fetch_current_spl(session_key, saved_search_origin)
    if current_spl is None:
        return False, None, stored_hash
    current_hash = compute_spl_hash(current_spl)
    drift = stored_hash != "" and current_hash != stored_hash
    if drift:
        logger.info("SPL drift detected for %s: stored=%s current=%s",
                     saved_search_origin, stored_hash, current_hash)
    return drift, current_spl, current_hash


def diff_spl(old_spl, new_spl):
    # type: (str, str) -> str
    """Produce a human-readable diff between two SPL strings.

    Splits by pipe segments so each command is a logical unit.
    Returns a compact description of what changed.
    """
    old_lines = [s.strip() for s in old_spl.split("|")]
    new_lines = [s.strip() for s in new_spl.split("|")]

    changes = []  # type: List[str]
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                old_part = old_lines[i1 + k] if (i1 + k) < i2 else ""
                new_part = new_lines[j1 + k] if (j1 + k) < j2 else ""
                if old_part and new_part:
                    changes.append("Changed: '| {0}' -> '| {1}'".format(
                        old_part, new_part))
                elif old_part:
                    changes.append("Removed: '| {0}'".format(old_part))
                else:
                    changes.append("Added: '| {0}'".format(new_part))
        elif tag == "delete":
            for k in range(i1, i2):
                changes.append("Removed: '| {0}'".format(old_lines[k]))
        elif tag == "insert":
            for k in range(j1, j2):
                changes.append("Added: '| {0}'".format(new_lines[k]))

    return "; ".join(changes) if changes else ""


def get_last_passed_spl(kv_client, sched_id):
    # type: (Any, str) -> Optional[str]
    """Get the SPL snapshot from the most recent passed run."""
    try:
        records = kv_client.query(COLLECTION_RUN_HISTORY, {
            "scheduledTestId": sched_id,
            "status": "pass",
        })
        if not records:
            return None
        records.sort(key=lambda r: r.get("ranAt", ""), reverse=True)
        return records[0].get("splSnapshot", "") or None
    except Exception as exc:
        logger.debug("Could not fetch last passed run for %s: %s", sched_id, exc)
        return None
