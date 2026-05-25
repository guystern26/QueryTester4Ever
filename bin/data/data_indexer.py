# -*- coding: utf-8 -*-
"""
data_indexer.py
Index synthetic events into the temp Splunk index via HEC (HTTP Event Collector).
"""
from __future__ import annotations

import json
import ssl
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from logger import get_logger
from config import HEC_BATCH_SIZE, TEMP_INDEX
from splunk_connect import get_service
from data.hec_config import get_hec_config, get_hec_token, resolve_hec_context


logger = get_logger(__name__)

BATCH_SIZE = HEC_BATCH_SIZE


def index_events(
    events,       # type: List[Dict[str, Any]]
    run_id,       # type: str
    session_key,  # type: str
    hec_ctx=None, # type: Optional[Dict[str, Any]]
    input_idx=None,  # type: Optional[int]
):
    # type: (...) -> None
    """Index all events into the temp index via HEC, tagged with run_id.

    *input_idx* — when provided, adds an ``input_N`` field so events from
    different inputs can be distinguished during query injection.

    *hec_ctx* is a pre-resolved context dict from ``resolve_hec_context()``.
    When provided, skips runtime config lookup, URL formatting, and SSL
    context creation — useful when indexing across multiple scenarios.
    """
    if not events:
        logger.warning(
            "index_events called with empty list for run_id=%s — skipping",
            run_id,
        )
        return

    filtered_events = [
        event for event in events if isinstance(event, dict) and event
    ]  # type: List[Dict[str, Any]]
    if not filtered_events:
        logger.warning(
            "index_events received only empty or non-dict events "
            "for run_id=%s — skipping",
            run_id,
        )
        return

    ctx = hec_ctx if hec_ctx is not None else resolve_hec_context(session_key)

    for start in range(0, len(filtered_events), BATCH_SIZE):
        batch = filtered_events[start : start + BATCH_SIZE]
        _send_hec_batch(
            batch, run_id, ctx["hec_token"],
            hec_url=ctx["hec_url"], hec_timeout=ctx["hec_timeout"],
            ssl_ctx=ctx["ssl_ctx"], index=ctx["index"],
            sourcetype=ctx["sourcetype"],
            input_idx=input_idx,
        )
        logger.info(
            "Indexed batch %d-%d (%d events) for run_id=%s",
            start,
            start + len(batch),
            len(batch),
            run_id,
        )


def _run_id_field(run_id: str) -> str:
    """Return the unique run_id field name for this run, e.g. run_id_6d1f4ac7."""
    return "run_id_{0}".format(run_id)


def cleanup(run_id: str, session_key: str) -> None:
    """
    Delete all temp events for this run. Errors are logged, not raised.
    """
    field_name = _run_id_field(run_id)
    spl = 'search index={0} {1}="{2}" | delete'.format(
        TEMP_INDEX, field_name, run_id
    )
    try:
        _run_spl(session_key, spl)
        logger.info("Cleaned up events for run_id=%s", run_id)
    except Exception as exc:
        logger.warning("Cleanup failed for run_id=%s: %s", run_id, exc)


def _send_hec_batch(
    events,       # type: List[Dict[str, Any]]
    run_id,       # type: str
    hec_token,    # type: str
    hec_url,      # type: str
    hec_timeout,  # type: int
    ssl_ctx,      # type: Any
    index,        # type: str
    sourcetype,   # type: str
    input_idx=None,  # type: Optional[int]
):
    # type: (...) -> None
    """Send a batch of events to HEC in a single POST request."""
    lines = []  # type: List[str]
    for event in events:
        # Convert None values to empty strings so json.dumps doesn't produce "null"
        sanitized = {k: ("" if v is None else v) for k, v in event.items()}
        fields = {_run_id_field(run_id): run_id}
        if input_idx is not None:
            fields["input_{0}".format(input_idx)] = str(input_idx)
        envelope = {
            "event": sanitized,
            "index": index,
            "sourcetype": sourcetype,
            "fields": fields,
        }
        lines.append(json.dumps(envelope, ensure_ascii=False))

    body = "\n".join(lines).encode("utf-8")

    req = Request(hec_url, data=body, method="POST")
    req.add_header("Authorization", "Splunk {0}".format(hec_token))
    req.add_header("Content-Type", "application/json")

    try:
        response = urlopen(req, timeout=hec_timeout, context=ssl_ctx)
        response_body = response.read().decode("utf-8")
        response.close()
    except HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(
            "HEC request failed for run_id={0}: "
            "HTTP {1} — {2}".format(run_id, exc.code, error_body)
        )
    except URLError as exc:
        raise RuntimeError(
            "HEC connection failed for run_id={0}: {1}. "
            "Verify HEC is enabled at {2}.".format(
                run_id, exc.reason, hec_url
            )
        )

    # Verify HEC accepted the events
    try:
        result = json.loads(response_body)
    except (ValueError, TypeError):
        result = {}

    if result.get("code") != 0:
        raise RuntimeError(
            "HEC rejected events for run_id={0}: {1}".format(
                run_id, response_body
            )
        )


def _run_spl(session_key, spl):
    # type: (str, str) -> None
    """Execute SPL via splunklib — used only for cleanup deletes."""
    service = get_service(session_key, app="QueryTester", owner="nobody")
    job = service.jobs.create(spl)
    _ = job.results()
