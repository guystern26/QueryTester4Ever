# -*- coding: utf-8 -*-
"""
scheduled_runner.py — Scripted input that runs scheduled tests on their cron.

Runs every 60 seconds via inputs.conf. Uses a KVStore-backed queue so tests
that can't run immediately (pool full) persist until the next cycle instead
of being silently skipped.

Two-phase approach:
  Phase 1 — Enqueue: check cron matches, mark due tests as 'queued'.
  Phase 2 — Process: pick up to max_parallel_tests queued tests, run them.

Queue states on each scheduled_tests record:
  idle    — not running, waiting for next cron match
  queued  — due to run, waiting for a worker slot
  running — currently executing
"""
from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from logger import get_logger
from kvstore_client import KVStoreClient
from scheduling.cron_matcher import cron_matches, is_enabled
from scheduling.spl_drift import diff_spl, get_last_passed_spl
from scheduling.scheduled_runner_helpers import (
    write_history_record, build_scenario_results,
    build_summary, build_test_payload,
)

logger = get_logger("scheduled_runner")

COLLECTION_SCHEDULED_TESTS = "scheduled_tests"
COLLECTION_SAVED_TESTS = "saved_tests"

STATUS_VALID = ("pass", "fail", "partial")
TEST_TIMEOUT_SECONDS = 300    # 5 min max per individual test
DEDUP_WINDOW_SECONDS = 120    # skip if ran in last 2 min
STALE_RUNNING_SECONDS = 600   # reset 'running' after 10 min (crashed/timed-out worker)
MISSED_RUN_MULTIPLIER = 1.5   # consider missed if lastRunAt > interval * 1.5
SHC_DELAY_MIN = 10            # random delay before processing (seconds)
SHC_DELAY_MAX = 30            # spreads KVStore reads across SHs
LOCAL_HOSTNAME = platform.node()  # this search head's hostname

# Interval key → expected seconds between runs
INTERVAL_SECONDS = {
    "daily": 86400,
    "2d": 172800,
    "3d": 259200,
    "evening": 86400,
    "weekly": 604800,
    # Legacy keys (backward compat)
    "hourly": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
}

# Lock for KVStore writes to scheduled_tests (concurrent workers)
_kv_lock = threading.Lock()

# Flag: run sweep on first invocation after Splunk restart
_startup_sweep_done = False


# ── Helpers ─────────────────────────────────────────────────────────

def _parse_iso(iso_str):
    # type: (str) -> float
    """Parse ISO timestamp (UTC) to epoch seconds. Returns 0 on failure."""
    if not iso_str:
        return 0.0
    try:
        import calendar
        return calendar.timegm(time.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return 0.0


def _now_iso():
    # type: () -> str
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ran_recently(record):
    # type: (Dict[str, Any]) -> bool
    """O(1) dedup: check lastRunAt on the record itself."""
    last = record.get("lastRunAt", "")
    if not last:
        return False
    return (time.time() - _parse_iso(last)) < DEDUP_WINDOW_SECONDS


def _update_record(kv, sched_id, updates):
    # type: (KVStoreClient, str, Dict[str, Any]) -> None
    """Thread-safe read-modify-write on a scheduled_tests record."""
    if not sched_id:
        logger.warning("Skipping _update_record — empty sched_id")
        return
    with _kv_lock:
        try:
            fresh = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, sched_id)
            if isinstance(fresh, list):
                fresh = fresh[0] if fresh else {}
            fresh.update(updates)
            kv.upsert(COLLECTION_SCHEDULED_TESTS, sched_id, fresh)
        except Exception as exc:
            logger.error("Failed to update scheduled test %s: %s", sched_id, exc)


def _get_max_workers(session_key):
    # type: (str) -> int
    """Read max_parallel_tests from runtime config, clamped to 1-10."""
    try:
        from runtime_config import get_runtime_config
        cfg = get_runtime_config(session_key)
        val = int(cfg.get("max_parallel_tests", 5))
        return max(1, min(10, val))
    except Exception:
        return 5


# ── Missed-run sweep ──────────────────────────────────────────────

def _sweep_missed_runs(kv, all_tests, now_ts):
    # type: (KVStoreClient, List[Dict[str, Any]], float) -> int
    """Enqueue tests that should have run but didn't (missed cron window).

    Runs once at startup and hourly at :00. Catches gaps from Splunk
    restarts, crashes, or any period where scheduled_runner wasn't ticking.
    """
    enqueued = 0

    for rec in all_tests:
        if not is_enabled(rec):
            continue
        if rec.get("queueStatus", "idle") != "idle":
            continue

        sched_id = rec.get("_key") or rec.get("id", "")
        interval_key = rec.get("intervalKey", "")
        if not interval_key or interval_key not in INTERVAL_SECONDS:
            continue  # legacy record without intervalKey — skip

        expected_secs = INTERVAL_SECONDS[interval_key]
        last_run = rec.get("lastRunAt", "")

        if not last_run:
            # Never run before — enqueue it
            logger.warning("Missed run detected for test '%s' — never ran, "
                           "expected interval %s.", sched_id, interval_key)
        else:
            elapsed = now_ts - _parse_iso(last_run)
            threshold = expected_secs * MISSED_RUN_MULTIPLIER
            if elapsed <= threshold:
                continue  # within expected window, no miss
            logger.warning("Missed run detected for test '%s' — last ran "
                           "%.0fs ago, expected interval %s (%ds).",
                           sched_id, elapsed, interval_key, expected_secs)

        _update_record(kv, sched_id, {
            "queueStatus": "queued",
            "queuedAt": _now_iso(),
        })
        enqueued += 1

    if enqueued > 0:
        logger.info("Missed-run sweep enqueued %d test(s).", enqueued)
    return enqueued


# ── Phase 1: Enqueue ───────────────────────────────────────────────

def _enqueue_due_tests(kv, all_tests):
    # type: (KVStoreClient, List[Dict[str, Any]]) -> int
    """Mark cron-matched tests as 'queued'. Returns count enqueued."""
    now_local = time.localtime()
    cron_dow = (now_local.tm_wday + 1) % 7
    dt_tuple = (now_local.tm_min, now_local.tm_hour,
                now_local.tm_mday, now_local.tm_mon, cron_dow)
    now_ts = time.time()
    enqueued = 0

    for rec in all_tests:
        if not is_enabled(rec):
            continue
        sched_id = rec.get("_key") or rec.get("id", "")
        queue_status = rec.get("queueStatus", "idle")

        # Reset stale 'running' tests (crashed worker)
        if queue_status == "running":
            queued_at = _parse_iso(rec.get("queuedAt", ""))
            if queued_at and (now_ts - queued_at) > STALE_RUNNING_SECONDS:
                logger.warning("Resetting stale running test %s to idle.", sched_id)
                _update_record(kv, sched_id, {"queueStatus": "idle", "queuedAt": ""})
                queue_status = "idle"
            else:
                continue  # still running, leave it

        # Already queued — leave it
        if queue_status == "queued":
            continue

        # Check cron match
        cron_expr = rec.get("cronSchedule", "")
        if not cron_expr or not cron_matches(cron_expr, dt_tuple):
            continue

        # O(1) dedup: skip if lastRunAt is within 2 minutes
        if _ran_recently(rec):
            logger.info("Skipping %s — ran recently (dedup).", sched_id)
            continue

        # Enqueue
        _update_record(kv, sched_id, {
            "queueStatus": "queued",
            "queuedAt": _now_iso(),
        })
        enqueued += 1
        logger.info("Enqueued test %s", sched_id)

    return enqueued


# ── Phase 2: Process ───────────────────────────────────────────────

def _run_single_test(kv, session_key, scheduled):
    # type: (KVStoreClient, str, Dict[str, Any]) -> None
    """Run a single scheduled test and record the result."""
    sched_id = scheduled.get("_key") or scheduled.get("id", "")
    test_id = scheduled.get("testId", "")
    test_name = scheduled.get("testName", "")
    # runCycle: UTC minute timestamp — same across all SHs for the same cron trigger
    run_cycle = time.strftime("%Y%m%d_%H%M", time.gmtime())
    # Log tag for consistent structured fields across all messages
    tag = "runCycle=%s schedId=%s testId=%s testName=%s host=%s" % (
        run_cycle, sched_id, test_id, test_name, LOCAL_HOSTNAME)

    # Layer 1: Claim immediately — write our hostname before the delay
    _update_record(kv, sched_id, {"runningOnHost": LOCAL_HOSTNAME})

    # Layer 2: Random delay (10-30s) — gives KVStore time to replicate the claim
    delay = random.randint(SHC_DELAY_MIN, SHC_DELAY_MAX)
    logger.info("SHC stagger: waiting %ds — %s", delay, tag)
    time.sleep(delay)

    # Layer 3: Re-read after delay — check if we're still the owner + ran recently
    try:
        fresh = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, sched_id)
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else {}
        if _ran_recently(fresh):
            logger.info("Skipped (ran recently) — %s", tag)
            _update_record(kv, sched_id, {"queueStatus": "idle", "queuedAt": "", "runningOnHost": ""})
            return
        # Another SH overwrote our claim during the delay — they won
        owner = fresh.get("runningOnHost", "")
        if owner and owner != LOCAL_HOSTNAME:
            logger.info("Skipped (lost claim to %s) — %s", owner, tag)
            return
    except Exception:
        pass  # if re-read fails, proceed with the run

    start_ms = int(time.time() * 1000)

    logger.info("Running — %s", tag)

    status = "error"
    result = {}  # type: Dict[str, Any]
    scenario_results = []  # type: List[Dict[str, Any]]
    definition = {}  # type: Dict[str, Any]
    query_spl = ""

    try:
        try:
            saved_test = kv.get_by_id(COLLECTION_SAVED_TESTS, test_id)
        except Exception:
            logger.error("Saved test %s not found for scheduled test %s — disabling schedule.",
                         test_id, sched_id)
            _update_record(kv, sched_id, {
                "enabled": "0",
                "queueStatus": "idle",
                "queuedAt": "",
                "runningOnHost": "",
                "lastRunAt": _now_iso(),
                "lastRunStatus": "error",
            })
            return

        definition = saved_test.get("definition", {})
        if isinstance(definition, str):
            definition = json.loads(definition)

        payload, query_spl = build_test_payload(definition, saved_test, scheduled)

        # If linked to a saved search, fetch fresh SPL from Splunk
        origin = scheduled.get("savedSearchOrigin") or ""
        if origin:
            try:
                from scheduling.spl_drift import fetch_current_spl
                test_app = scheduled.get("app") or payload.get("app", "search")
                fresh_spl = fetch_current_spl(session_key, origin, app=test_app)
                if fresh_spl:
                    logger.info("Using fresh SPL from saved search '%s' for %s",
                                origin, sched_id)
                    payload["query"] = fresh_spl
                    query_spl = fresh_spl
                else:
                    logger.warning("Could not fetch saved search '%s' — using stored SPL.",
                                   origin)
            except Exception as exc:
                logger.warning("Failed to fetch saved search '%s': %s — using stored SPL.",
                               origin, exc)

        from core.test_runner import TestRunner
        runner = TestRunner(session_key)
        result, _ = runner.run_test(payload)
        raw_status = result.get("status", "error")
        status = raw_status if raw_status in STATUS_VALID else "error"
        scenario_results = build_scenario_results(result)
    except Exception as exc:
        logger.error("Test execution failed for %s: %s",
                     sched_id, exc, exc_info=True)

    duration_ms = int(time.time() * 1000) - start_ms
    ran_at = _now_iso()
    passed = result.get("passedScenarios", 0)
    total = result.get("totalScenarios", 0)
    summary = build_summary(passed, total, scenario_results)

    # SPL drift detection
    spl_drift = False
    spl_drift_details = ""
    if query_spl:
        last_passed_spl = get_last_passed_spl(kv, sched_id)
        if last_passed_spl and last_passed_spl.strip() != query_spl.strip():
            spl_drift = True
            spl_drift_details = diff_spl(last_passed_spl, query_spl)
            logger.info("SPL drift detected for %s: %s",
                        sched_id, spl_drift_details)

    # Layer 3 check: re-read to confirm we're still the owner
    is_owner = True
    try:
        final = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, sched_id)
        if isinstance(final, list):
            final = final[0] if final else {}
        owner = final.get("runningOnHost", "")
        if owner and owner != LOCAL_HOSTNAME:
            is_owner = False
            logger.info("Not the owner (owner=%s) — skipping post-run — %s", owner, tag)
    except Exception:
        pass  # if re-read fails, assume we're the owner

    if is_owner:
        write_history_record(
            kv, sched_id, ran_at, status, duration_ms, summary,
            scenario_results, current_spl=query_spl,
            spl_drift=spl_drift, spl_drift_details=spl_drift_details,
        )

    # Mark done: update lastRun + reset queue status + clear host claim
    _update_record(kv, sched_id, {
        "lastRunAt": ran_at,
        "lastRunStatus": status,
        "queueStatus": "idle",
        "queuedAt": "",
        "runningOnHost": "",
    })

    logger.info("Completed: status=%s duration=%dms owner=%s — %s",
                status, duration_ms, is_owner, tag)

    # Send failure emails — only if we're the owner
    if not is_owner:
        return
    alert_flag = scheduled.get("alertOnFailure", False)
    should_alert = alert_flag in (True, "1", "true", "True")
    if status in ("fail", "error") and should_alert:
        try:
            from alerts.alert_email import send_failure_emails
            recipients = scheduled.get("emailRecipients", [])
            full_scenario_results = result.get(
                "scenarioResults", scenario_results,
            )
            send_failure_emails(
                recipients,
                scheduled.get("testName", sched_id),
                ran_at, status, full_scenario_results, spl_drift,
                test_id=test_id,
                definition=definition,
                full_results=result if result else None,
                session_key=session_key,
            )
        except Exception as exc:
            logger.error("Failed to send failure emails: %s", exc)


def _process_queue(kv, session_key, all_tests, max_workers):
    # type: (KVStoreClient, str, List[Dict[str, Any]], int) -> None
    """Pick queued tests and run them in a thread pool."""
    # Re-fetch to see freshly-queued records
    try:
        all_tests = kv.get_all(COLLECTION_SCHEDULED_TESTS)
    except Exception as exc:
        logger.error("Failed to re-fetch scheduled tests: %s", exc)
        return

    queued = []  # type: List[Dict[str, Any]]
    for rec in all_tests:
        if rec.get("queueStatus") == "queued":
            queued.append(rec)

    if not queued:
        return

    # Sort by queuedAt so oldest-queued runs first
    queued.sort(key=lambda r: r.get("queuedAt", ""))

    # Take up to max_workers
    batch = queued[:max_workers]
    overflow = len(queued) - len(batch)
    if overflow > 0:
        logger.info("%d queued test(s) will wait for the next cycle.", overflow)

    logger.info("Processing %d queued test(s) with max_workers=%d",
                len(batch), max_workers)

    # Mark batch as 'running' before submitting
    for rec in batch:
        _update_record(kv, rec.get("_key") or rec.get("id", ""), {"queueStatus": "running"})

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}  # type: Dict[Any, str]
        for rec in batch:
            worker_kv = KVStoreClient(session_key)
            future = pool.submit(_run_single_test, worker_kv, session_key, rec)
            futures[future] = rec.get("_key") or rec.get("id", "unknown")

        for future in as_completed(futures):
            sched_id = futures[future]
            try:
                future.result(timeout=TEST_TIMEOUT_SECONDS)
            except Exception as exc:
                if "TimeoutError" in type(exc).__name__:
                    logger.error("Test %s timed out after %ds",
                                 sched_id, TEST_TIMEOUT_SECONDS)
                else:
                    logger.error("Unhandled error running scheduled test %s: %s",
                                 sched_id, exc, exc_info=True)
                # Reset to idle so it can be retried next cycle
                _update_record(kv, sched_id, {
                    "queueStatus": "idle", "queuedAt": "",
                })


# ── Main entry point ───────────────────────────────────────────────

def run(session_key):
    # type: (str) -> None
    """Main entry point called every 60 seconds by inputs.conf."""
    global _startup_sweep_done

    try:
        kv = KVStoreClient(session_key)
        all_tests = kv.get_all(COLLECTION_SCHEDULED_TESTS)
    except Exception as exc:
        logger.error("Failed to fetch scheduled tests: %s", exc)
        return

    if not all_tests:
        return

    now_ts = time.time()
    now_min = time.gmtime(now_ts).tm_min

    # Missed-run sweep: on first tick (startup catch-up) and hourly at :00
    if not _startup_sweep_done or now_min == 0:
        _startup_sweep_done = True
        _sweep_missed_runs(kv, all_tests, now_ts)

    # Phase 1: enqueue due tests (fast — just KVStore writes)
    _enqueue_due_tests(kv, all_tests)

    # Phase 2: process queued tests (slow — runs actual tests)
    max_workers = _get_max_workers(session_key)
    _process_queue(kv, session_key, all_tests, max_workers)


def _extract_session_key(raw_input):
    # type: (str) -> str
    """Extract session_key from Splunk scripted input stdin."""
    raw = raw_input.strip()
    if not raw:
        return ""
    if raw.startswith("<"):
        import re
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(raw)
            elem = root.find(".//session_key")
            if elem is not None and elem.text:
                return elem.text.strip()
        except Exception:
            pass
        match = re.search(
            r"<session_key>\s*(.*?)\s*</session_key>", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    return raw


if __name__ == "__main__":
    input_data = sys.stdin.read()
    _session_key = _extract_session_key(input_data)

    if not _session_key:
        logger.error("No session key found in scripted input stdin")
        sys.exit(1)

    run(_session_key)
