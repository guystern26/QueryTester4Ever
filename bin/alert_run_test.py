# -*- coding: utf-8 -*-
"""alert_run_test.py — Custom alert action for scheduled test execution."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

_bin_dir = os.path.dirname(os.path.abspath(__file__))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

from logger import get_logger
from kvstore_client import KVStoreClient
from alerts.alert_email import (
    send_failure_emails, extract_scenario_results, build_result_summary,
)
from scheduling.spl_drift import check_spl_drift
from scheduling.scheduled_runner_helpers import build_test_payload

logger = get_logger(__name__)

COLLECTION_SCHEDULED_TESTS = "scheduled_tests"
COLLECTION_RUN_HISTORY = "test_run_history"


def _get_test_id_from_payload(payload_path):
    # type: (str) -> str
    with open(payload_path, "r") as fh:
        payload = json.load(fh)
    config = payload.get("configuration", {})
    test_id = config.get("test_id", "")
    if not test_id:
        raise ValueError("test_id not found in alert action payload.")
    return test_id


def _write_history_record(kv, test_id, ran_at, status, duration_ms,
                          spl_hash, spl_drift, summary, scenario_results):
    # type: (KVStoreClient, str, str, str, int, str, bool, str, List[Dict[str, Any]]) -> None
    try:
        record = {
            "id": str(uuid.uuid4()),
            "scheduledTestId": test_id,
            "ranAt": ran_at,
            "status": status,
            "durationMs": duration_ms,
            "splSnapshotHash": spl_hash,
            "splDriftDetected": spl_drift,
            "resultSummary": summary,
            "scenarioResults": json.dumps(scenario_results),
        }
        kv.upsert(COLLECTION_RUN_HISTORY, record["id"], record)
    except Exception as exc:
        logger.error("Failed to write history record for %s: %s", test_id, exc)


def run(payload_path, session_key):
    # type: (str, str) -> None
    test_id = ""
    kv = None  # type: Optional[KVStoreClient]
    start_ms = int(time.time() * 1000)

    try:
        test_id = _get_test_id_from_payload(payload_path)
        logger.info("Alert action triggered for test_id: %s", test_id)

        kv = KVStoreClient(session_key)

        try:
            scheduled = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, test_id)
        except (ValueError, Exception):
            logger.error("Scheduled test not found: %s", test_id)
            return

        if not scheduled.get("enabled", True):
            logger.info("Scheduled test %s is disabled, skipping.", test_id)
            return

        # Skip if scheduled_runner already claimed this test (queued/running)
        queue_status = scheduled.get("queueStatus", "idle")
        if queue_status in ("queued", "running"):
            logger.info("Skipping alert action for %s — scheduled_runner has it (%s).",
                        test_id, queue_status)
            return

        # O(1) dedup: skip if ran recently (covers the case where
        # scheduled_runner already finished before this alert fired)
        last_run = scheduled.get("lastRunAt", "")
        if last_run:
            try:
                import calendar
                ran_ts = calendar.timegm(time.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ"))
                if (time.time() - ran_ts) < 120:
                    logger.info("Skipping alert action for %s — ran %ds ago (dedup).",
                                test_id, int(time.time() - ran_ts))
                    return
            except (ValueError, OverflowError):
                pass

        # SPL drift check
        spl_drift = False
        spl_hash = ""
        saved_search_origin = scheduled.get("savedSearchOrigin")
        stored_hash = scheduled.get("splSnapshotHash", "")
        if saved_search_origin:
            spl_drift, _, spl_hash = check_spl_drift(
                session_key, saved_search_origin, stored_hash,
            )
        if not spl_hash:
            spl_hash = stored_hash

        # Fetch the saved test definition
        saved_test_id = scheduled.get("testId", "")
        try:
            saved_test = kv.get_by_id("saved_tests", saved_test_id)
        except ValueError:
            logger.error("Saved test not found: %s", saved_test_id)
            return
        definition = saved_test.get("definition", {})
        if isinstance(definition, str):
            definition = json.loads(definition)
        payload, _ = build_test_payload(definition, saved_test, scheduled)

        # Run the test
        from core.test_runner import TestRunner
        status = "error"
        result = {}  # type: Dict[str, Any]
        try:
            runner = TestRunner(session_key)
            result, _ = runner.run_test(payload)
            raw_status = result.get("status", "error")
            status = raw_status if raw_status in ("pass", "fail", "partial") else "error"
        except Exception as exc:
            logger.error("Test execution failed: %s", exc, exc_info=True)
            result = {"status": "error", "message": str(exc)}

        duration_ms = int(time.time() * 1000) - start_ms
        ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        scenario_results = extract_scenario_results(result)
        summary = build_result_summary(result)

        # Write history record (must never raise)
        _write_history_record(
            kv, test_id, ran_at, status, duration_ms,
            spl_hash, spl_drift, summary, scenario_results,
        )

        # Update scheduled test with last run info
        try:
            scheduled["lastRunAt"] = ran_at
            scheduled["lastRunStatus"] = status
            if spl_hash:
                scheduled["splSnapshotHash"] = spl_hash
            kv.upsert(COLLECTION_SCHEDULED_TESTS, test_id, scheduled)
        except Exception as exc:
            logger.error("Failed to update scheduled test %s: %s", test_id, exc)

        logger.info("Scheduled test %s completed: status=%s, duration=%dms",
                    test_id, status, duration_ms)

        # Send failure emails
        if status in ("fail", "error") and scheduled.get("alertOnFailure"):
            recipients = scheduled.get("emailRecipients", [])
            full_scenario_results = result.get(
                "scenarioResults", scenario_results,
            )
            send_failure_emails(
                recipients,
                scheduled.get("testName", test_id),
                ran_at, status, full_scenario_results, spl_drift,
                test_id=scheduled.get("testId", test_id),
                definition=definition if definition else None,
                full_results=result if result else None,
                session_key=session_key,
            )

    except Exception as exc:
        # Catch-all: always try to write an error history record
        logger.error("Unhandled error in alert action: %s", exc, exc_info=True)
        if test_id and kv is not None:
            duration_ms = int(time.time() * 1000) - start_ms
            ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _write_history_record(
                kv, test_id, ran_at, "error", duration_ms,
                "", False, "Unhandled error: {0}".format(exc), [],
            )
            # Update the scheduled test so Library shows error, not stale data
            try:
                sched = kv.get_by_id(COLLECTION_SCHEDULED_TESTS, test_id)
                sched["lastRunAt"] = ran_at
                sched["lastRunStatus"] = "error"
                kv.upsert(COLLECTION_SCHEDULED_TESTS, test_id, sched)
            except Exception as update_exc:
                logger.error(
                    "Failed to update scheduled test %s in catch-all: %s",
                    test_id, update_exc,
                )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("No payload path provided to alert action.")
        sys.exit(1)

    payload_file = sys.argv[1] if sys.argv[1] != "--execute" else sys.argv[2]

    try:
        stdin_data = sys.stdin.read()
        stdin_payload = json.loads(stdin_data)
        _session_key = stdin_payload.get("session_key", "")
    except Exception:
        _session_key = ""

    if not _session_key:
        logger.error("No session key available for alert action.")
        sys.exit(1)

    run(payload_file, _session_key)
