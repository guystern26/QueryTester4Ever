# -*- coding: utf-8 -*-
"""Tests for handler_utils.py shared utilities."""
from __future__ import annotations

import json
import pytest

from handler_utils import (
    get_session_key, get_username, json_response,
    normalize_payload, extract_id, get_query_param, now_iso,
)


class TestGetSessionKey:
    def test_extracts_from_authtoken(self):
        req = {"session": {"authtoken": "abc123"}}
        assert get_session_key(req) == "abc123"

    def test_extracts_from_sessionKey(self):
        req = {"session": {"sessionKey": "xyz789"}}
        assert get_session_key(req) == "xyz789"

    def test_falls_back_to_system_authtoken(self):
        req = {"session": {}, "system_authtoken": "sys-token"}
        assert get_session_key(req) == "sys-token"

    def test_raises_when_missing(self):
        with pytest.raises(ValueError, match="Missing session key"):
            get_session_key({"session": {}})

    def test_handles_none_session(self):
        with pytest.raises(ValueError, match="Missing session key"):
            get_session_key({})


class TestGetUsername:
    def test_extracts_user(self):
        req = {"session": {"user": "admin"}}
        assert get_username(req) == "admin"

    def test_defaults_to_unknown(self):
        assert get_username({}) == "unknown"


class TestJsonResponse:
    def test_default_200(self):
        resp = json_response({"ok": True})
        assert resp["status"] == 200
        assert json.loads(resp["payload"]) == {"ok": True}
        assert resp["headers"]["Content-Type"] == "application/json"

    def test_custom_status(self):
        resp = json_response({"error": "bad"}, 400)
        assert resp["status"] == 400

    def test_serializes_list(self):
        resp = json_response([1, 2, 3])
        assert json.loads(resp["payload"]) == [1, 2, 3]


class TestNormalizePayload:
    def test_none_returns_empty(self):
        assert normalize_payload(None) == {}

    def test_empty_string_returns_empty(self):
        assert normalize_payload("") == {}
        assert normalize_payload("  ") == {}

    def test_json_string(self):
        assert normalize_payload('{"a": 1}') == {"a": 1}

    def test_bytes(self):
        assert normalize_payload(b'{"b": 2}') == {"b": 2}

    def test_dict_passthrough(self):
        d = {"c": 3}
        assert normalize_payload(d) is d

    def test_list_unwraps_first(self):
        assert normalize_payload(['{"d": 4}']) == {"d": 4}

    def test_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported payload type"):
            normalize_payload(42)


class TestExtractId:
    def test_from_query_dict(self):
        req = {"query": {"id": "abc"}}
        assert extract_id(req) == "abc"

    def test_from_query_list(self):
        req = {"query": [["id", "def"]]}
        assert extract_id(req) == "def"

    def test_from_form_dict(self):
        req = {"query": {}, "form": {"id": "ghi"}}
        assert extract_id(req) == "ghi"

    def test_from_form_list(self):
        req = {"query": [], "form": [["id", "jkl"]]}
        assert extract_id(req) == "jkl"

    def test_from_rest_path(self):
        req = {"query": {}, "rest_path": "/servicesNS/admin/QueryTester/data/saved_tests/xyz"}
        assert extract_id(req) == "xyz"

    def test_returns_none_when_missing(self):
        assert extract_id({}) is None


class TestGetQueryParam:
    def test_from_dict(self):
        req = {"query": {"scheduled_test_id": "st1"}}
        assert get_query_param(req, "scheduled_test_id") == "st1"

    def test_from_list(self):
        req = {"query": [["scheduled_test_id", "st2"]]}
        assert get_query_param(req, "scheduled_test_id") == "st2"

    def test_missing_returns_empty(self):
        assert get_query_param({}, "x") == ""

    def test_wrong_param_returns_empty(self):
        req = {"query": {"a": "1"}}
        assert get_query_param(req, "b") == ""


class TestNowIso:
    def test_format(self):
        result = now_iso()
        assert result.endswith("Z")
        assert "T" in result
        assert len(result) == 20  # YYYY-MM-DDTHH:MM:SSZ
