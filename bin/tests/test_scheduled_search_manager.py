# -*- coding: utf-8 -*-
"""Tests for scheduled_search_manager.py — saved search creation and naming."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from scheduling.scheduled_search_manager import (
    saved_search_name, _is_enabled, _search_kwargs,
    create_saved_search, update_saved_search, delete_saved_search,
)


class TestSavedSearchName:
    def test_basic_name(self):
        record = {"testName": "Auth Check", "id": "abcd1234-5678-90ab-cdef-1234567890ab"}
        assert saved_search_name(record) == "QT - Auth Check [abcd1234]"

    def test_unnamed_fallback(self):
        record = {"id": "xyz12345"}
        assert saved_search_name(record) == "QT - Unnamed [xyz12345]"

    def test_short_id(self):
        record = {"testName": "T", "id": "abc"}
        assert saved_search_name(record) == "QT - T [abc]"


class TestIsEnabled:
    def test_bool_true(self):
        assert _is_enabled({"enabled": True}) is True

    def test_bool_false(self):
        assert _is_enabled({"enabled": False}) is False

    def test_string_1(self):
        assert _is_enabled({"enabled": "1"}) is True

    def test_string_0(self):
        assert _is_enabled({"enabled": "0"}) is False

    def test_string_true(self):
        assert _is_enabled({"enabled": "true"}) is True

    def test_string_false(self):
        assert _is_enabled({"enabled": "false"}) is False

    def test_missing_defaults_true(self):
        assert _is_enabled({}) is True


class TestSearchKwargs:
    def test_includes_schedule_fields(self):
        record = {"id": "test-123", "cronSchedule": "*/5 * * * *", "enabled": True}
        kwargs = _search_kwargs(record)
        assert kwargs["cron_schedule"] == "*/5 * * * *"
        assert kwargs["is_scheduled"] == "1"
        assert kwargs["disabled"] == "0"

    def test_disabled_record(self):
        record = {"id": "test-456", "enabled": False}
        kwargs = _search_kwargs(record)
        assert kwargs["disabled"] == "1"

    def test_default_cron(self):
        record = {"id": "test-789"}
        kwargs = _search_kwargs(record)
        assert kwargs["cron_schedule"] == "0 6 * * *"


class TestCreateSavedSearch:
    @patch("scheduling.scheduled_search_manager._find_saved_search", return_value=None)
    @patch("scheduling.scheduled_search_manager._connect")
    def test_creates_with_schedule_config(self, mock_connect, mock_find):
        service = MagicMock()
        mock_connect.return_value = service
        ss_mock = MagicMock()
        service.saved_searches.create.return_value = ss_mock

        record = {
            "id": "abc12345-6789",
            "testId": "test-001",
            "testName": "My Test",
            "cronSchedule": "0 */6 * * *",
            "enabled": True,
        }
        create_saved_search("session-key", record)

        service.saved_searches.create.assert_called_once()
        call_args = service.saved_searches.create.call_args
        name_arg = call_args[0][0]
        assert name_arg == "QT - My Test [abc12345]"
        kwargs = call_args[1]
        assert kwargs["cron_schedule"] == "0 */6 * * *"
        assert kwargs["is_scheduled"] == "1"

    @patch("scheduling.scheduled_search_manager._find_saved_search", return_value=None)
    @patch("scheduling.scheduled_search_manager._connect")
    def test_sets_app_level_acl(self, mock_connect, mock_find):
        service = MagicMock()
        mock_connect.return_value = service
        ss_mock = MagicMock()
        service.saved_searches.create.return_value = ss_mock

        create_saved_search("key", {"id": "t1", "testName": "T", "enabled": True})
        ss_mock.acl_update.assert_called_once()

    @patch("scheduling.scheduled_search_manager._find_saved_search", return_value=None)
    @patch("scheduling.scheduled_search_manager._connect")
    def test_handles_create_failure(self, mock_connect, mock_find):
        service = MagicMock()
        mock_connect.return_value = service
        service.saved_searches.create.side_effect = Exception("conflict")

        # Should not raise
        create_saved_search("key", {"id": "t2", "testName": "T"})

    @patch("scheduling.scheduled_search_manager._find_saved_search")
    def test_updates_existing_instead_of_creating(self, mock_find):
        existing = MagicMock()
        mock_find.return_value = existing

        record = {"id": "t3", "testId": "test-003", "testName": "T", "cronSchedule": "*/5 * * * *", "enabled": True}
        create_saved_search("key", record)

        existing.update.assert_called_once()


class TestUpdateSavedSearch:
    @patch("scheduling.scheduled_search_manager._find_saved_search")
    def test_updates_existing(self, mock_find):
        search_obj = MagicMock()
        mock_find.return_value = search_obj

        record = {"id": "u1", "testName": "T", "cronSchedule": "*/30 * * * *", "enabled": True}
        update_saved_search("key", record)

        search_obj.update.assert_called_once()
        kwargs = search_obj.update.call_args[1]
        assert kwargs["cron_schedule"] == "*/30 * * * *"

    @patch("scheduling.scheduled_search_manager._find_saved_search", return_value=None)
    @patch("scheduling.scheduled_search_manager.create_saved_search")
    def test_recreates_when_not_found(self, mock_create, mock_find):
        record = {"id": "u2", "testName": "T", "cronSchedule": "0 * * * *"}
        update_saved_search("key", record)

        mock_create.assert_called_once_with("key", record)


class TestDeleteSavedSearch:
    @patch("scheduling.scheduled_search_manager._find_saved_search")
    def test_deletes_found_search(self, mock_find):
        search_obj = MagicMock()
        search_obj.name = "QT - T [abc12345]"
        mock_find.return_value = search_obj

        delete_saved_search("key", "abc12345-6789")

        search_obj.delete.assert_called_once()

    @patch("scheduling.scheduled_search_manager._find_saved_search", return_value=None)
    def test_logs_when_not_found(self, mock_find):
        # Should not raise
        delete_saved_search("key", "nonexistent")
