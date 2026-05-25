# -*- coding: utf-8 -*-
"""
test_runner.py
Coordinate end-to-end execution of Splunk Query Tester scenarios.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from logger import get_logger
from core.models import ParsedScenario, ScenarioResult, TestPayload
from core.payload_parser import parse
from core.response_builder import build_error_response, build_response
from data.data_indexer import index_events
from data.hec_config import resolve_hec_context
from data.lookup_manager import create_temp_lookup, delete_temp_lookup, create_temp_kvstore_lookup, delete_temp_kvstore_lookup, set_session_key as _set_lookup_session_key
from data.sub_query_runner import run_sub_query
from generators.event_generator import build_events
from spl.preflight import get_blocked_commands_set
from spl.query_executor import QueryExecutor
from spl.query_injector import check_orphaned_filters, detect_strategy, inject
from spl.spl_analyzer import analyze as analyze_spl
from spl.spl_normalizer import normalize_spl
from validation.result_validator import validate

logger = get_logger(__name__)

INDEX_SETTLE_SECS = 3  # seconds for indexed data to become searchable


def _error_scenario(name, spl, exc):
    # type: (str, str, Exception) -> ScenarioResult
    return ScenarioResult(
        scenario_name=name, passed=False, execution_time_ms=0,
        result_count=0, injected_spl=spl, validations=[], error=str(exc),
    )


class TestRunner:
    """Parse payload, run each scenario independently, and build a response."""

    def __init__(self, session_key: str, config: Optional[Dict[str, Any]] = None) -> None:
        self._session_key = session_key
        self._executor = QueryExecutor(session_key)
        self._hec_ctx = (config or {}).get("hec_ctx")  # type: Optional[Dict[str, Any]]
        _set_lookup_session_key(session_key)

    def run_test(self, raw_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """
        Parse payload, run each scenario, and return response dict with HTTP status.
        """
        self._test_id = raw_payload.get("testId") or None  # type: Optional[str]
        self._cache_temp_lookups = []  # type: List[str]
        try:
            payload = parse(raw_payload)
            spl = self._resolve_spl(payload)

            # Pre-copy real lookups for non-testing cache macros (scheduled runs)
            self._prepare_cache_lookups(spl, payload.app)

            blocked_set = get_blocked_commands_set(self._session_key)
            analysis = analyze_spl(spl, blocked_commands=blocked_set)

            if analysis.unauthorized_commands:
                msg = "Blocked commands detected: {0}".format(
                    ", ".join(analysis.unauthorized_commands))
                return build_error_response(
                    payload, msg, "BLOCKED_COMMANDS", analysis=analysis,
                ), 400
        except ValueError as exc:
            logger.error("Client error: %s", exc, exc_info=True)
            return build_error_response(None, str(exc), "VALIDATION_ERROR"), 400
        except Exception as exc:
            logger.error("Fatal error: %s", exc, exc_info=True)
            msg = "Internal error while preparing test payload."
            return build_error_response(None, msg, "INTERNAL_ERROR"), 500

        scenario_results = []  # type: List[ScenarioResult]

        if payload.test_type == "query_only":
            # query_only: run the raw SPL as-is, no data indexing
            # Still apply cache macro lookup swap for safety
            from spl.query_injector import _swap_cache_lookups
            cache_run_id = uuid4().hex[:8]
            spl = _swap_cache_lookups(spl, cache_run_id, self._test_id)
            # Pre-create empty temp lookup CSVs so outputlookup inside
            # the cache macro has a valid target
            self._ensure_cache_lookup_files(spl, payload.app)
            try:
                result = self._run_query_only(payload, spl)
            except Exception as exc:
                logger.error("query_only failed: %s", str(exc), exc_info=True)
                result = _error_scenario("Query Only", spl, exc)
            scenario_results.append(result)
        else:
            strategy = detect_strategy(spl)
            for scenario in payload.scenarios:
                run_id = uuid4().hex[:8]
                injected_spl = inject(spl, run_id, strategy, scenario.inputs, test_id=self._test_id)
                self._ensure_cache_lookup_files(injected_spl, payload.app)
                orphan_warning = check_orphaned_filters(spl, injected_spl)
                if orphan_warning:
                    analysis.warnings.append(
                        {"message": orphan_warning, "severity": "warning"}
                    )
                try:
                    result = self._run_scenario(
                        payload, scenario, run_id, strategy, injected_spl,
                    )
                except Exception as exc:
                    logger.error(
                        'Scenario "%s" failed: %s', scenario.name, str(exc), exc_info=True
                    )
                    result = _error_scenario(scenario.name, injected_spl, exc)
                finally:
                    self._cleanup(run_id, strategy, payload.app)

                scenario_results.append(result)

        response = build_response(payload, analysis, scenario_results)
        # Clean up scheduled-run cache temp lookups (manual-run ones persist)
        if not self._test_id:
            self._cleanup_cache_lookups(payload.app)
        return response, 200

    def _run_scenario(
        self, payload: TestPayload, scenario: ParsedScenario,
        run_id: str, strategy: str, injected_spl: str,
    ) -> ScenarioResult:
        """Build events from all inputs, index them, and execute the injected SPL."""
        multi_input = len(scenario.inputs) > 1
        per_input_events = []  # type: List[tuple]
        scenario_warnings = []  # type: List[str]
        for idx, inp in enumerate(scenario.inputs):
            if inp.input_mode == "query_data" and inp.query_data_config is not None:
                # Run sub-query to fetch events as test data
                qd = inp.query_data_config
                sub_events, sub_warnings = run_sub_query(
                    spl=qd.spl,
                    session_key=self._session_key,
                    app=payload.app,
                    earliest_time=qd.earliest_time,
                    latest_time=qd.latest_time,
                )
                scenario_warnings.extend(sub_warnings)
                logger.info(
                    "query_data sub-query returned %d events for scenario '%s'",
                    len(sub_events),
                    scenario.name,
                )
                per_input_events.append((idx, sub_events))
            else:
                per_input_events.append((idx, build_events(inp)))

        all_events = []  # type: List[Dict[str, Any]]
        if payload.test_type != "query_only" and strategy not in ("tstats",):
            if self._hec_ctx is None:
                self._hec_ctx = resolve_hec_context(self._session_key)
            indexed_any = False
            for idx, events in per_input_events:
                if not events:
                    continue
                all_events.extend(events)
                # When multiple inputs exist, tag each with input_idx
                # so the injector can discriminate them in the query
                input_idx = idx if multi_input else None
                index_events(events, run_id, self._session_key,
                             hec_ctx=self._hec_ctx, input_idx=input_idx)
                indexed_any = True
            if indexed_any:
                logger.info("Waiting %ds for indexed data to become searchable.",
                            INDEX_SETTLE_SECS)
                time.sleep(INDEX_SETTLE_SECS)

        # Only create a temp lookup if the injected SPL actually references it
        temp_lookup_name = "temp_lookup_{0}".format(run_id)
        if temp_lookup_name in injected_spl and all_events:
            create_temp_lookup(run_id, all_events, payload.app)

        return self._execute_and_validate(
            payload, scenario, injected_spl, scenario.name,
            warnings=scenario_warnings,
        )

    def _run_query_only(self, payload, spl):
        # type: (TestPayload, str) -> ScenarioResult
        """Run the SPL as-is with no injection or data indexing."""
        dummy = ParsedScenario(name="Query Only", inputs=[])
        return self._execute_and_validate(payload, dummy, spl, "Query Only")

    def _execute_and_validate(
        self, payload: TestPayload, scenario: ParsedScenario,
        run_spl: str, name: str, warnings: Optional[List[str]] = None,
    ) -> ScenarioResult:
        """Execute SPL and validate results against the payload's validation config."""
        start_ms = int(time.time() * 1000)
        results = self._executor.run(
            run_spl, app=payload.app,
            earliest_time=payload.earliest_time, latest_time=payload.latest_time,
        )
        elapsed_ms = int(time.time() * 1000) - start_ms
        validations, passed = validate(payload.validation, scenario, results)
        return ScenarioResult(
            scenario_name=name, passed=passed, execution_time_ms=elapsed_ms,
            result_count=len(results), injected_spl=run_spl,
            validations=validations, result_rows=results,
            error=None, warnings=warnings or [],
        )

    def _resolve_spl(self, payload: TestPayload) -> str:
        """Normalize SPL from payload, raising ValueError if empty."""
        normalized = normalize_spl(payload.query)
        if not normalized:
            raise ValueError('Payload must include a non-empty "query" field.')
        return normalized

    def cancel(self) -> None:
        """Cancel the currently running search job."""
        self._executor.cancel()

    def _cleanup(self, run_id: str, strategy: str, app: str) -> None:
        """Remove temp lookup CSV. Indexed events rely on 24h index retention."""
        if strategy != "lookup":
            return
        try:
            delete_temp_lookup(run_id, app)
        except Exception as exc:
            logger.warning("Lookup cleanup failed for run_id=%s: %s", run_id, str(exc))

    def _get_lookup_fields(self, lookup_name, app):
        # type: (str, str) -> str
        """Run ``| inputlookup <name> | head 1`` to discover the field list."""
        try:
            from spl.query_executor import QueryExecutor
            executor = QueryExecutor(self._session_key)
            rows = executor.run(
                spl="| inputlookup {0} | head 1".format(lookup_name),
                app=app, earliest_time="0", latest_time="now",
            )
            if rows:
                fields = [f for f in rows[0].keys() if not f.startswith("_") or f == "_key"]
                if "_key" not in fields:
                    fields.insert(0, "_key")
                return ", ".join(fields)
        except Exception as exc:
            logger.warning("Failed to read fields from lookup '%s': %s", lookup_name, exc)
        return ""

    def _prepare_cache_lookups(self, spl: str, app: str) -> None:
        """Pre-step: nothing to do here now.

        KVStore creation is handled by ``_ensure_cache_lookup_files`` which
        creates the collection + transforms definition on demand.
        For manual runs the KVStore persists across reruns (stable name).
        For scheduled runs it's cleaned up after.
        """
        pass

    def _ensure_cache_lookup_files(self, spl: str, app: str) -> None:
        """Create KVStore collection + transforms definition for temp cache lookups.

        Reads the field list from the original lookup via ``| inputlookup | head 1``,
        then delegates to ``create_temp_kvstore_lookup`` which uses admin credentials.
        """
        try:
            from spl.spl_analyzer import parse_cache_macros

            macros = [
                info for info in parse_cache_macros(spl)
                if not info["is_testing"]
                and len(info["args"]) >= 6
                and info["lookup_name"]
                and info["lookup_name"].startswith("temp_cache_")
            ]
            if not macros:
                return

            for info in macros:
                lookup_name = info["lookup_name"]
                # Extract original lookup name: temp_cache_{key}_{original}
                parts = lookup_name.split("_", 3)
                original_lookup = parts[3] if len(parts) >= 4 else ""
                if not original_lookup:
                    continue

                fields_list = self._get_lookup_fields(original_lookup, app)
                if not fields_list:
                    logger.warning("Could not get fields from '%s' — skipping", original_lookup)
                    continue

                if create_temp_kvstore_lookup(lookup_name, fields_list, app):
                    self._cache_temp_lookups.append(lookup_name)
        except Exception as exc:
            logger.warning("Failed to create cache KVStore lookups: %s", exc)

    def _cleanup_cache_lookups(self, app: str) -> None:
        """Remove temp KVStore collections + transforms definitions for scheduled runs."""
        for name in self._cache_temp_lookups:
            delete_temp_kvstore_lookup(name, app)
