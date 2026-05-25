# -*- coding: utf-8 -*-
"""Tests for scheduled_tests_handler.py CRUD operations."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from helpers import make_request, parse_response, SESSION_KEY
from scheduled_tests_handler import ScheduledTestsHandler


SAMPLE_PAYLOAD = {
    "testId": "test-abc",
    "testName": "My Scheduled Test",
    "app": "search",
    "cronSchedule": "0 */6 * * *",
    "enabled": True,
    "alertOnFailure": False,
    "emailRecipients": [],
}


@pytest.fixture
def handler():
    return ScheduledTestsHandler()


@pytest.fixture
def mock_saved_search():
    """Mock scheduled_search_manager functions to prevent Splunk calls."""
    with patch("scheduled_tests_handler.create_saved_search") as create, \
         patch("scheduled_tests_handler.update_saved_search") as update, \
         patch("scheduled_tests_handler.delete_saved_search") as delete:
        yield {"create": create, "update": update, "delete": delete}


class TestGet:
    def test_returns_empty_list(self, handler, patch_kv, mock_saved_search):
        resp = handler.handle(make_request("GET"))
        data, status = parse_response(resp)
        assert status == 200
        assert data == []

    def test_returns_all_scheduled_tests(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "a", "testName": "A", "cronSchedule": "0 * * * *"},
            {"id": "b", "testName": "B", "cronSchedule": "0 6 * * *"},
        ])
        resp = handler.handle(make_request("GET"))
        data, _ = parse_response(resp)
        assert len(data) == 2


class TestPost:
    def test_creates_scheduled_test_with_uuid(self, handler, patch_kv, mock_saved_search):
        resp = handler.handle(make_request("POST", SAMPLE_PAYLOAD))
        data, status = parse_response(resp)
        assert status == 201
        assert data["testName"] == "My Scheduled Test"
        assert data["cronSchedule"] == "0 */6 * * *"
        assert data["version"] == 1
        assert len(data["id"]) == 36  # UUID

    def test_calls_create_saved_search(self, handler, patch_kv, mock_saved_search):
        handler.handle(make_request("POST", SAMPLE_PAYLOAD))
        mock_saved_search["create"].assert_called_once()
        call_args = mock_saved_search["create"].call_args
        record = call_args[0][1]  # second positional arg
        assert record["cronSchedule"] == "0 */6 * * *"

    def test_stores_in_kvstore(self, handler, patch_kv, mock_saved_search):
        handler.handle(make_request("POST", SAMPLE_PAYLOAD))
        records = patch_kv.get_all("scheduled_tests")
        assert len(records) == 1
        assert records[0]["testId"] == "test-abc"

    def test_missing_cron_returns_400(self, handler, patch_kv, mock_saved_search):
        payload = dict(SAMPLE_PAYLOAD)
        del payload["cronSchedule"]
        resp = handler.handle(make_request("POST", payload))
        _, status = parse_response(resp)
        assert status == 400


class TestPut:
    def test_updates_cron_schedule(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "u1", "testName": "T", "cronSchedule": "0 6 * * *", "enabled": True},
        ])
        resp = handler.handle(make_request("PUT", {"cronSchedule": "*/30 * * * *"}, query={"id": "u1"}))
        data, status = parse_response(resp)
        assert status == 200
        assert data["cronSchedule"] == "*/30 * * * *"

    def test_updates_enabled_flag(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "u2", "testName": "T", "enabled": True},
        ])
        resp = handler.handle(make_request("PUT", {"enabled": False}, query={"id": "u2"}))
        data, _ = parse_response(resp)
        assert data["enabled"] is False

    def test_calls_update_saved_search(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "u3", "testName": "T", "cronSchedule": "0 * * * *"},
        ])
        handler.handle(make_request("PUT", {"cronSchedule": "0 */2 * * *"}, query={"id": "u3"}))
        mock_saved_search["update"].assert_called_once()

    def test_missing_id_returns_400(self, handler, patch_kv, mock_saved_search):
        resp = handler.handle(make_request("PUT", {"enabled": False}))
        _, status = parse_response(resp)
        assert status == 400

    def test_version_conflict_returns_409(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "v1", "testName": "T", "cronSchedule": "0 6 * * *",
             "enabled": True, "version": 4},
        ])
        resp = handler.handle(make_request("PUT", {"enabled": False, "version": 3}, query={"id": "v1"}))
        data, status = parse_response(resp)
        assert status == 409
        assert data["error"] == "conflict"
        assert data["currentVersion"] == 4

    def test_version_match_succeeds_and_increments(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [
            {"id": "v2", "testName": "T", "cronSchedule": "0 6 * * *",
             "enabled": True, "version": 2},
        ])
        resp = handler.handle(make_request("PUT", {"enabled": False, "version": 2}, query={"id": "v2"}))
        data, status = parse_response(resp)
        assert status == 200
        assert data["enabled"] is False
        assert data["version"] == 3


class TestDelete:
    def test_deletes_and_removes_saved_search(self, handler, patch_kv, mock_saved_search):
        patch_kv.seed("scheduled_tests", [{"id": "d1", "testName": "Doomed"}])
        resp = handler.handle(make_request("DELETE", query={"id": "d1"}))
        data, status = parse_response(resp)
        assert status == 200
        assert data["deleted"] == "d1"
        assert len(patch_kv.get_all("scheduled_tests")) == 0
        mock_saved_search["delete"].assert_called_once_with(SESSION_KEY, "d1")

    def test_missing_id_returns_400(self, handler, patch_kv, mock_saved_search):
        resp = handler.handle(make_request("DELETE"))
        _, status = parse_response(resp)
        assert status == 400


class TestOwnership:
    """Ownership enforcement on PUT and DELETE."""

    @pytest.fixture(autouse=True)
    def _mock_search(self):
        with patch("scheduled_tests_handler.create_saved_search"), \
             patch("scheduled_tests_handler.update_saved_search"), \
             patch("scheduled_tests_handler.delete_saved_search"):
            yield

    def test_put_forbidden_for_non_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("scheduled_tests", [
                {"id": "o1", "testName": "T", "createdBy": "alice", "enabled": True},
            ])
            req = make_request("PUT", {"enabled": False}, query={"id": "o1"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 403

    def test_put_allowed_for_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("scheduled_tests", [
                {"id": "o2", "testName": "T", "createdBy": "bob", "enabled": True},
            ])
            req = make_request("PUT", {"enabled": False}, query={"id": "o2"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 200

    def test_delete_forbidden_for_non_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("scheduled_tests", [
                {"id": "o3", "testName": "T", "createdBy": "alice"},
            ])
            req = make_request("DELETE", query={"id": "o3"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 403


class TestPostValidation:
    @pytest.fixture(autouse=True)
    def _mock_search(self):
        with patch("scheduled_tests_handler.create_saved_search"), \
             patch("scheduled_tests_handler.update_saved_search"), \
             patch("scheduled_tests_handler.delete_saved_search"):
            yield

    def test_missing_test_id_returns_400(self, handler, patch_kv):
        payload = {"cronSchedule": "0 * * * *"}
        resp = handler.handle(make_request("POST", payload))
        data, status = parse_response(resp)
        assert status == 400
        assert "testId" in data["error"]

    def test_missing_cron_returns_400(self, handler, patch_kv):
        payload = {"testId": "t1", "cronSchedule": ""}
        resp = handler.handle(make_request("POST", payload))
        data, status = parse_response(resp)
        assert status == 400
        assert "cronSchedule" in data["error"]


class TestMethodNotAllowed:
    def test_patch_returns_405(self, handler, patch_kv, mock_saved_search):
        resp = handler.handle(make_request("PATCH"))
        _, status = parse_response(resp)
        assert status == 405
