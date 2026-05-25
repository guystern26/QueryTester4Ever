# -*- coding: utf-8 -*-
"""
query_executor.py
Execute SPL queries via splunklib and return result rows.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import splunklib.client as splunk_client
import splunklib.results as splunk_results
from splunklib.binding import HTTPError

from logger import get_logger
from splunk_connect import get_service


logger = get_logger(__name__)

POLL_INTERVAL = 0.5  # seconds between job status checks


class QueryExecutor:
    """Execute SPL using a Splunk service connection."""

    def __init__(self, session_key: str) -> None:
        self._session_key = session_key
        self._current_job = None  # type: Optional[splunk_client.Job]
        self._cancelled = False

    def run(
        self,
        spl: str,
        app: str = "search",
        earliest_time: str = "0",
        latest_time: str = "now",
    ) -> List[Dict[str, Any]]:
        """
        Execute the given SPL and return a list of result rows as plain dicts.

        Uses an async search job (not oneshot) so it can be cancelled mid-flight
        via the cancel() method.

        Raises RuntimeError on Splunk HTTP errors or cancellation.
        """
        if not spl:
            return []

        # Splunk search requires SPL to start with a search command.
        # If it starts with a filter term (index=, source=, etc.) prepend "search ".
        stripped = spl.lstrip()
        if stripped and not stripped.startswith("|") and not stripped.lower().startswith("search "):
            first_word = stripped.split()[0].lower()
            if "=" in first_word or first_word.rstrip("=") in {
                "index", "source", "sourcetype", "host", "eventtype", "tag",
            }:
                spl = "search " + spl

        if "| tstats" in spl:
            logger.warning(
                'Executing SPL containing "| tstats" — data injection may not apply.'
            )

        self._cancelled = False
        start = time.time()
        try:
            service = get_service(self._session_key, app=app, owner="nobody")
            search_kwargs = {
                "earliest_time": earliest_time,
                "latest_time": latest_time,
                "exec_mode": "normal",
            }
            job = service.jobs.create(spl, **search_kwargs)
            self._current_job = job

            # Poll until the job is done or cancelled
            while not job.is_done():
                if self._cancelled:
                    self._finalize_job(job)
                    raise RuntimeError("Search cancelled by user.")
                time.sleep(POLL_INTERVAL)
                job.refresh()

            if self._cancelled:
                self._finalize_job(job)
                raise RuntimeError("Search cancelled by user.")

            reader = splunk_results.JSONResultsReader(
                job.results(output_mode="json", count=0)
            )

            rows = []  # type: List[Dict[str, Any]]
            for item in reader:
                if isinstance(item, splunk_results.Message):
                    logger.warning(
                        "Splunk message during query execution: %s", getattr(item, "message", item)
                    )
                    continue
                rows.append(dict(item))

            duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "Executed SPL in %d ms, returned %d rows.", duration_ms, len(rows)
            )
            return rows
        except HTTPError as exc:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(
                "Query execution failed after %d ms: %s", duration_ms, str(exc), exc_info=True
            )
            raise RuntimeError("Query execution failed: {0}".format(str(exc)))
        finally:
            self._current_job = None

    def cancel(self) -> None:
        """Cancel the currently running search job, if any."""
        self._cancelled = True
        job = self._current_job
        if job is not None:
            self._finalize_job(job)
            logger.info("Search job cancelled by user.")

    def _finalize_job(self, job: splunk_client.Job) -> None:
        """Cancel and clean up a Splunk job, ignoring errors."""
        try:
            job.cancel()
        except Exception as exc:
            logger.warning("Failed to cancel Splunk job: %s", str(exc))
