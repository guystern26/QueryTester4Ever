# -*- coding: utf-8 -*-
"""
scheduled_search_manager.py — Create/update/delete backing saved searches
for scheduled tests.

Saved searches serve dual purpose: UI visibility in Splunk and backup alert
action execution (Path A). Primary execution is via scheduled_runner.py (Path B).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from splunk_connect import get_service
from logger import get_logger

logger = get_logger(__name__)

SAVED_SEARCH_PREFIX = "QT - "

# Connection cache: keyed by (session_key, owner) -> splunklib Service object.
# Reusing connections avoids the ~1-2s HTTPS handshake on every call.
_conn_cache = {}  # type: Dict[tuple, Any]
_conn_lock = threading.Lock()


def _connect(session_key, owner="nobody"):
    # type: (str, str) -> Any
    cache_key = (session_key, owner)
    with _conn_lock:
        cached = _conn_cache.get(cache_key)
        if cached is not None:
            return cached
    # Build connection outside lock to avoid blocking other threads
    service = get_service(session_key, app="QueryTester", owner=owner)
    with _conn_lock:
        _conn_cache[cache_key] = service
    return service


def _invalidate_connection(session_key, owner="nobody"):
    # type: (str, str) -> None
    """Remove a cached connection (e.g. after a connection error)."""
    cache_key = (session_key, owner)
    with _conn_lock:
        _conn_cache.pop(cache_key, None)


def _is_enabled(record):
    # type: (Dict[str, Any]) -> bool
    from scheduling.cron_matcher import is_enabled
    return is_enabled(record)


def saved_search_name(record):
    # type: (Dict[str, Any]) -> str
    test_name = record.get("testName", "Unnamed")
    record_id = record.get("id", "unknown")
    return "{prefix}{name} [{short_id}]".format(
        prefix=SAVED_SEARCH_PREFIX,
        name=test_name,
        short_id=record_id[:8],
    )


def _search_kwargs(record):
    # type: (Dict[str, Any]) -> Dict[str, str]
    """Saved search kwargs — UI visibility only, alert action disabled.

    Primary execution is via scheduled_runner.py (Path B).
    Alert action (Path A) is disabled by default to avoid race conditions.
    Admin can manually enable action.query_tester_run_test on a saved search
    if they want backup execution for a specific test.
    """
    cron = record.get("cronSchedule", "0 6 * * *")
    disabled = "0" if _is_enabled(record) else "1"
    return {
        "cron_schedule": cron,
        "is_scheduled": "1",
        "disabled": disabled,
        "dispatch.earliest_time": "-1m",
        "dispatch.latest_time": "now",
    }


def _find_saved_search(session_key, record):
    # type: (str, Dict[str, Any]) -> Optional[Any]
    """Find saved search across all owners.

    Strategy: try direct name lookups first (fast). Only fall back to
    scanning all saved searches if both direct lookups miss — this avoids
    iterating hundreds of saved searches on every call.
    """
    try:
        service = _connect(session_key, owner="-")
    except Exception as exc:
        _invalidate_connection(session_key, owner="-")
        logger.warning("Connection failed in _find_saved_search: %s", exc)
        return None

    name = saved_search_name(record)
    record_id = record.get("id", "")

    # 1. Direct lookup — new naming convention
    try:
        return service.saved_searches[name]
    except KeyError:
        pass
    except Exception as exc:
        logger.debug("Error looking up saved search %s: %s", name, exc)
        _invalidate_connection(session_key, owner="-")

    # 2. Direct lookup — old naming convention
    old_name = "QueryTester_Scheduled_" + record_id
    try:
        return service.saved_searches[old_name]
    except KeyError:
        pass
    except Exception as exc:
        logger.debug("Error looking up saved search %s: %s", old_name, exc)

    # 3. Last resort: scan all saved searches by short ID suffix
    logger.debug("Direct lookups missed for %s, scanning all saved searches", record_id)
    try:
        short_id = "[{0}]".format(record_id[:8])
        for search in service.saved_searches:
            sname = search.name
            if sname.startswith(SAVED_SEARCH_PREFIX) and sname.endswith(short_id):
                return search
            if sname.startswith("QueryTester_Scheduled_") and record_id in sname:
                return search
    except Exception as exc:
        logger.warning("Scan failed: %s", exc)
        _invalidate_connection(session_key, owner="-")

    return None


def create_saved_search(session_key, record):
    # type: (str, Dict[str, Any]) -> None
    name = saved_search_name(record)
    spl = '| makeresults | eval test_id="{0}", scheduled_test="{1}"'.format(
        record.get("testId", ""), record["id"],
    )

    # Check if one already exists
    existing = _find_saved_search(session_key, record)
    if existing is not None:
        try:
            existing.update(search=spl, **_search_kwargs(record))
            logger.info("Updated existing saved search: %s", existing.name)
            return
        except Exception as exc:
            logger.warning("Failed to update existing %s: %s", existing.name, exc)
            try:
                existing.delete()
            except Exception:
                pass

    try:
        service = _connect(session_key)
    except Exception as exc:
        _invalidate_connection(session_key)
        logger.warning("Connection failed in create_saved_search: %s", exc)
        return
    try:
        ss = service.saved_searches.create(name, search=spl, **_search_kwargs(record))
        try:
            ss.acl_update(sharing="app", **{"perms.read": "*", "perms.write": "admin,power"})
        except Exception as acl_exc:
            logger.warning("Failed to set ACL on %s: %s", name, acl_exc)
        logger.info("Created saved search: %s", name)
    except Exception as exc:
        logger.warning("Failed to create saved search %s: %s", name, exc)


def update_saved_search(session_key, record):
    # type: (str, Dict[str, Any]) -> None
    existing = _find_saved_search(session_key, record)

    if existing is not None:
        try:
            existing.update(**_search_kwargs(record))
            logger.info("Updated saved search: %s", existing.name)
        except Exception as exc:
            logger.warning("Failed to update saved search %s: %s", existing.name, exc)
        return

    logger.info("Saved search not found for %s, creating.", record.get("id", ""))
    create_saved_search(session_key, record)


def delete_saved_search(session_key, record_id):
    # type: (str, str) -> None
    dummy = {"id": record_id, "testName": ""}
    existing = _find_saved_search(session_key, dummy)
    if existing is not None:
        try:
            existing.delete()
            logger.info("Deleted saved search: %s", existing.name)
        except Exception as exc:
            logger.warning("Failed to delete saved search %s: %s", existing.name, exc)
        return

    logger.warning("No saved search found to delete for record %s", record_id)
