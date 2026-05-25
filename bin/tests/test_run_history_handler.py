# -*- coding: utf-8 -*-
"""Tests for run_history_handler.py."""
from __future__ import annotations

import json
import pytest

from helpers import make_request, parse_response
from run_history_handler import RunHistoryHandler


def make_run_record(test_id, ran_at, status="pass", scenario_results=None):
    """Build a run history record dict."""
    return {
        "id": "run-" + ran_at.replace(":", ""),
        "scheduledTestId": test_id,
        "ranAt": ran_at,
        "status": status,
        "durationMs": 1200,
        "splSnapshotHash": "abc",
        "splDriftDetected": False,
        "resultSummary": "OK",
        "scenarioResults": json.dumps(scenario_results or []),
    }


@pytest.fixture
def handler():
    return RunHistoryHandler()


class TestGet:
    def test_returns_empty(self, handler, patch_kv):
        resp = handler.handle(make_request("GET"))
        data, status = parse_response(resp)
        assert status == 200
        assert data == []

    def test_filters_by_scheduled_test_id(self, handler, patch_kv):
        patch_kv.seed("test_run_history", [
            make_run_record("st-1", "2026-03-15T10:00:00Z"),
            make_run_record("st-2", "2026-03-15T11:00:00Z"),
            make_run_record("st-1", "2026-03-15T12:00:00Z"),
        ])
        resp = handler.handle(make_request("GET", query={"scheduled_test_id": "st-1"}))
        data, _ = parse_response(resp)
        assert len(data) == 2
        assert all(r["scheduledTestId"] == "st-1" for r in data)

    def test_returns_sorted_descending(self, handler, patch_kv):
        patch_kv.seed("test_run_history", [
            make_run_record("st-1", "2026-03-15T08:00:00Z"),
            make_run_record("st-1", "2026-03-15T12:00:00Z"),
            make_run_record("st-1", "2026-03-15T10:00:00Z"),
        ])
        resp = handler.handle(make_request("GET", query={"scheduled_test_id": "st-1"}))
        data, _ = parse_response(resp)
        times = [r["ranAt"] for r in data]
        assert times == sorted(times, reverse=True)

    def test_limits_to_50(self, handler, patch_kv):
        records = [
            make_run_record("st-1", "2026-03-{:02d}T00:00:00Z".format(i))
            for i in range(1, 60)
        ]
        patch_kv.seed("test_run_history", records)
        resp = handler.handle(make_request("GET", query={"scheduled_test_id": "st-1"}))
        data, _ = parse_response(resp)
        assert len(data) == 50

    def test_deserializes_scenario_results(self, handler, patch_kv):
        scenarios = [{"scenarioId": "s1", "passed": True, "message": "OK"}]
        patch_kv.seed("test_run_history", [
            make_run_record("st-1", "2026-03-15T10:00:00Z", scenario_results=scenarios),
        ])
        resp = handler.handle(make_request("GET", query={"scheduled_test_id": "st-1"}))
        data, _ = parse_response(resp)
        assert isinstance(data[0]["scenarioResults"], list)
        assert data[0]["scenarioResults"][0]["passed"] is True

    def test_handles_malformed_scenario_results(self, handler, patch_kv):
        patch_kv.seed("test_run_history", [{
            "id": "r1", "scheduledTestId": "st-1", "ranAt": "2026-03-15",
            "scenarioResults": "not-valid-json{{{",
        }])
        resp = handler.handle(make_request("GET", query={"scheduled_test_id": "st-1"}))
        data, _ = parse_response(resp)
        assert data[0]["scenarioResults"] == []


class TestMethodNotAllowed:
    def test_post_returns_405(self, handler, patch_kv):
        resp = handler.handle(make_request("POST"))
        _, status = parse_response(resp)
        assert status == 405

    def test_delete_returns_405(self, handler, patch_kv):
        resp = handler.handle(make_request("DELETE"))
        _, status = parse_response(resp)
        assert status == 405
