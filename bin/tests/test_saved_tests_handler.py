# -*- coding: utf-8 -*-
"""Tests for saved_tests_handler.py CRUD operations."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from helpers import make_request, parse_response, SESSION_KEY
from saved_tests_handler import SavedTestsHandler


SAMPLE_DEFINITION = {
    "id": "def-1",
    "name": "My Test",
    "app": "search",
    "testType": "standard",
    "scenarios": [],
    "query": {"spl": "index=main | stats count", "timeRange": {"earliest": "-1h", "latest": "now"}},
    "validation": {},
}


@pytest.fixture
def handler():
    return SavedTestsHandler()


class TestGet:
    def test_returns_empty_list(self, handler, patch_kv):
        resp = handler.handle(make_request("GET"))
        data, status = parse_response(resp)
        assert status == 200
        assert data == []

    def test_returns_saved_tests_sorted(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "a", "name": "Old", "updatedAt": "2026-01-01T00:00:00Z",
             "definition": json.dumps(SAMPLE_DEFINITION)},
            {"id": "b", "name": "New", "updatedAt": "2026-03-01T00:00:00Z",
             "definition": json.dumps(SAMPLE_DEFINITION)},
        ])
        resp = handler.handle(make_request("GET"))
        data, _ = parse_response(resp)
        assert len(data) == 2
        assert data[0]["name"] == "New"  # Most recent first

    def test_deserializes_definition_string(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "c", "definition": json.dumps({"app": "search"}), "updatedAt": ""},
        ])
        resp = handler.handle(make_request("GET"))
        data, _ = parse_response(resp)
        assert isinstance(data[0]["definition"], dict)
        assert data[0]["definition"]["app"] == "search"


class TestPost:
    def test_creates_test_with_uuid(self, handler, patch_kv):
        payload = {
            "name": "New Test",
            "app": "search",
            "description": "A test",
            "definition": SAMPLE_DEFINITION,
        }
        resp = handler.handle(make_request("POST", payload))
        data, status = parse_response(resp)
        assert status == 201
        assert data["name"] == "New Test"
        assert len(data["id"]) == 36  # UUID format
        assert data["createdBy"] == "admin"
        assert data["version"] == 1
        assert isinstance(data["definition"], dict)

    def test_stores_definition_as_json_string(self, handler, patch_kv):
        payload = {"name": "T", "definition": {"app": "search"}}
        handler.handle(make_request("POST", payload))
        stored = patch_kv.get_all("saved_tests")[0]
        # In KVStore, definition is stored as a JSON string
        assert isinstance(stored["definition"], str)


class TestPut:
    def test_updates_name_preserves_immutable(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "u1", "name": "Old", "createdAt": "2026-01-01", "createdBy": "bob",
             "definition": json.dumps(SAMPLE_DEFINITION), "updatedAt": "2026-01-01"},
        ])
        payload = {"name": "Updated"}
        req = make_request("PUT", payload, query={"id": "u1"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 200
        assert data["name"] == "Updated"
        assert data["createdAt"] == "2026-01-01"
        assert data["createdBy"] == "bob"
        assert data["updatedAt"] > "2026-01-01"

    def test_missing_id_returns_400(self, handler, patch_kv):
        resp = handler.handle(make_request("PUT", {"name": "x"}))
        data, status = parse_response(resp)
        assert status == 400
        assert "Missing record ID" in data["error"]

    def test_version_conflict_returns_409(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "v1", "name": "Versioned", "version": 3,
             "createdAt": "2026-01-01", "createdBy": "bob",
             "definition": json.dumps(SAMPLE_DEFINITION), "updatedAt": "2026-01-01"},
        ])
        payload = {"name": "Stale Update", "version": 2}
        req = make_request("PUT", payload, query={"id": "v1"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 409
        assert data["error"] == "conflict"
        assert data["currentVersion"] == 3

    def test_version_match_succeeds_and_increments(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "v2", "name": "Versioned", "version": 5,
             "createdAt": "2026-01-01", "createdBy": "bob",
             "definition": json.dumps(SAMPLE_DEFINITION), "updatedAt": "2026-01-01"},
        ])
        payload = {"name": "Fresh Update", "version": 5}
        req = make_request("PUT", payload, query={"id": "v2"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 200
        assert data["name"] == "Fresh Update"
        assert data["version"] == 6

    def test_legacy_record_without_version_allows_update(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [
            {"id": "v3", "name": "Legacy", "createdAt": "2026-01-01",
             "createdBy": "bob", "definition": json.dumps(SAMPLE_DEFINITION),
             "updatedAt": "2026-01-01"},
        ])
        payload = {"name": "Updated Legacy"}
        req = make_request("PUT", payload, query={"id": "v3"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 200
        assert data["name"] == "Updated Legacy"
        assert data["version"] == 1


class TestDelete:
    @pytest.fixture(autouse=True)
    def _mock_search(self):
        with patch("saved_tests_handler.delete_saved_search") as mock:
            self._mock_delete_search = mock
            yield

    def test_deletes_test(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [{"id": "d1", "name": "Doomed"}])
        req = make_request("DELETE", query={"id": "d1"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 200
        assert data["deleted"] == "d1"
        assert len(patch_kv.get_all("saved_tests")) == 0

    def test_cascade_deletes_schedule(self, handler, patch_kv):
        patch_kv.seed("saved_tests", [{"id": "d2", "name": "Scheduled"}])
        patch_kv.seed("scheduled_tests", [{"id": "s1", "testId": "d2"}])
        req = make_request("DELETE", query={"id": "d2"})
        resp = handler.handle(req)
        data, status = parse_response(resp)
        assert status == 200
        assert data["deleted"] == "d2"
        assert len(patch_kv.get_all("saved_tests")) == 0
        assert len(patch_kv.get_all("scheduled_tests")) == 0
        self._mock_delete_search.assert_called_once_with(SESSION_KEY, "s1")

    def test_missing_id_returns_400(self, handler, patch_kv):
        resp = handler.handle(make_request("DELETE"))
        _, status = parse_response(resp)
        assert status == 400


class TestOwnership:
    """Ownership enforcement on PUT and DELETE."""

    @pytest.fixture(autouse=True)
    def _mock_search(self):
        with patch("saved_tests_handler.delete_saved_search"):
            yield

    def test_put_forbidden_for_non_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("saved_tests", [
                {"id": "o1", "name": "Owned", "createdBy": "alice",
                 "createdAt": "2026-01-01", "definition": json.dumps(SAMPLE_DEFINITION),
                 "updatedAt": "2026-01-01"},
            ])
            req = make_request("PUT", {"name": "Hijack"}, query={"id": "o1"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 403

    def test_put_allowed_for_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("saved_tests", [
                {"id": "o2", "name": "Mine", "createdBy": "bob",
                 "createdAt": "2026-01-01", "definition": json.dumps(SAMPLE_DEFINITION),
                 "updatedAt": "2026-01-01"},
            ])
            req = make_request("PUT", {"name": "Updated"}, query={"id": "o2"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 200

    def test_put_admin_bypasses_ownership(self, handler, patch_kv):
        # is_admin_user returns True by default from conftest
        patch_kv.seed("saved_tests", [
            {"id": "o3", "name": "Others", "createdBy": "alice",
             "createdAt": "2026-01-01", "definition": json.dumps(SAMPLE_DEFINITION),
             "updatedAt": "2026-01-01"},
        ])
        req = make_request("PUT", {"name": "Admin Edit"}, query={"id": "o3"}, user="superuser")
        resp = handler.handle(req)
        _, status = parse_response(resp)
        assert status == 200

    def test_delete_forbidden_for_non_owner(self, handler, patch_kv):
        with patch("handler_utils.is_admin_user", return_value=False):
            patch_kv.seed("saved_tests", [{"id": "o4", "name": "Owned", "createdBy": "alice"}])
            req = make_request("DELETE", query={"id": "o4"}, user="bob")
            resp = handler.handle(req)
            _, status = parse_response(resp)
            assert status == 403


class TestPostValidation:
    def test_missing_name_returns_400(self, handler, patch_kv):
        payload = {"definition": SAMPLE_DEFINITION}
        resp = handler.handle(make_request("POST", payload))
        data, status = parse_response(resp)
        assert status == 400
        assert "name" in data["error"].lower()

    def test_empty_name_returns_400(self, handler, patch_kv):
        payload = {"name": "  ", "definition": SAMPLE_DEFINITION}
        resp = handler.handle(make_request("POST", payload))
        _, status = parse_response(resp)
        assert status == 400


class TestDefinitionSizeCap:
    def test_oversized_definition_on_post_returns_400(self, handler, patch_kv):
        with patch("saved_tests_handler.MAX_DEFINITION_SIZE_BYTES", 100):
            huge = {"data": "x" * 200}
            payload = {"name": "Big", "definition": huge}
            resp = handler.handle(make_request("POST", payload))
            data, status = parse_response(resp)
            assert status == 400
            assert "too large" in data["error"].lower()

    def test_oversized_definition_on_put_returns_400(self, handler, patch_kv):
        with patch("saved_tests_handler.MAX_DEFINITION_SIZE_BYTES", 100):
            patch_kv.seed("saved_tests", [
                {"id": "s1", "name": "Small", "createdBy": "admin",
                 "createdAt": "2026-01-01", "definition": "{}", "updatedAt": "2026-01-01"},
            ])
            huge = {"data": "x" * 200}
            req = make_request("PUT", {"definition": huge}, query={"id": "s1"})
            resp = handler.handle(req)
            data, status = parse_response(resp)
            assert status == 400
            assert "too large" in data["error"].lower()


class TestMethodNotAllowed:
    def test_patch_returns_405(self, handler, patch_kv):
        resp = handler.handle(make_request("PATCH"))
        _, status = parse_response(resp)
        assert status == 405
