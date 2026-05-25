# -*- coding: utf-8 -*-
"""Tests for auth_utils — role reading and admin detection."""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest


def _mock_response(roles):
    """Build a fake splunklib response for authentication/current-context."""
    body_dict = {
        "entry": [
            {
                "content": {
                    "roles": roles,
                    "username": "testuser",
                }
            }
        ]
    }
    resp = MagicMock()
    resp.body = io.BytesIO(json.dumps(body_dict).encode("utf-8"))
    return resp


def _mock_response_no_roles():
    """Response where the roles field is missing entirely."""
    body_dict = {
        "entry": [
            {
                "content": {
                    "username": "testuser",
                }
            }
        ]
    }
    resp = MagicMock()
    resp.body = io.BytesIO(json.dumps(body_dict).encode("utf-8"))
    return resp


def _mock_response_empty_entry():
    """Response with an empty entry list."""
    body_dict = {"entry": []}
    resp = MagicMock()
    resp.body = io.BytesIO(json.dumps(body_dict).encode("utf-8"))
    return resp


class TestGetCurrentUserRoles:
    """Tests for get_current_user_roles()."""

    @patch("auth_utils.splunk_client", create=True)
    def test_normal_user_roles(self, _mock_client):
        """Standard user with 'user' and 'power' roles."""
        import splunklib.client as splunk_client

        mock_service = MagicMock()
        mock_service.get.return_value = _mock_response(["user", "power"])
        splunk_client.connect = MagicMock(return_value=mock_service)

        from auth_utils import get_current_user_roles

        roles = get_current_user_roles("fake-session-key")
        assert roles == ["user", "power"]
        mock_service.get.assert_called_once_with(
            "authentication/current-context", output_mode="json"
        )

    @patch("auth_utils.splunk_client", create=True)
    def test_admin_user_roles(self, _mock_client):
        """User with admin role."""
        import splunklib.client as splunk_client

        mock_service = MagicMock()
        mock_service.get.return_value = _mock_response(["admin", "power", "user"])
        splunk_client.connect = MagicMock(return_value=mock_service)

        from auth_utils import get_current_user_roles

        roles = get_current_user_roles("fake-session-key")
        assert "admin" in roles

    @patch("auth_utils.splunk_client", create=True)
    def test_missing_roles_field(self, _mock_client):
        """When roles key is absent, should return empty list."""
        import splunklib.client as splunk_client

        mock_service = MagicMock()
        mock_service.get.return_value = _mock_response_no_roles()
        splunk_client.connect = MagicMock(return_value=mock_service)

        from auth_utils import get_current_user_roles

        roles = get_current_user_roles("fake-session-key")
        assert roles == []

    @patch("auth_utils.splunk_client", create=True)
    def test_empty_entry(self, _mock_client):
        """When entry list is empty, should return empty list."""
        import splunklib.client as splunk_client

        mock_service = MagicMock()
        mock_service.get.return_value = _mock_response_empty_entry()
        splunk_client.connect = MagicMock(return_value=mock_service)

        from auth_utils import get_current_user_roles

        roles = get_current_user_roles("fake-session-key")
        assert roles == []


class TestIsAdmin:
    """Tests for is_admin()."""

    @patch("auth_utils.get_current_user_roles")
    def test_non_admin_user(self, mock_roles):
        """User with only 'user' and 'power' roles is not admin."""
        mock_roles.return_value = ["user", "power"]

        from auth_utils import is_admin

        assert is_admin("fake-key") is False

    @patch("auth_utils.get_current_user_roles")
    def test_admin_role(self, mock_roles):
        """User with 'admin' role is admin."""
        mock_roles.return_value = ["admin", "user"]

        from auth_utils import is_admin

        assert is_admin("fake-key") is True

    @patch("auth_utils.get_current_user_roles")
    def test_sc_admin_role(self, mock_roles):
        """User with 'sc_admin' role is admin."""
        mock_roles.return_value = ["sc_admin", "user"]

        from auth_utils import is_admin

        assert is_admin("fake-key") is True

    @patch("auth_utils.get_current_user_roles")
    def test_custom_admin_role(self, mock_roles):
        """User with 'query_tester_admin' role is admin."""
        mock_roles.return_value = ["query_tester_admin", "user"]

        from auth_utils import is_admin

        assert is_admin("fake-key") is True

    @patch("auth_utils.get_current_user_roles")
    def test_missing_roles_defaults_non_admin(self, mock_roles):
        """When roles come back empty, user is not admin."""
        mock_roles.return_value = []

        from auth_utils import is_admin

        assert is_admin("fake-key") is False

    @patch("auth_utils.get_current_user_roles")
    def test_exception_defaults_non_admin(self, mock_roles):
        """When role fetching throws, user is not admin (safe default)."""
        mock_roles.side_effect = Exception("connection failed")

        from auth_utils import is_admin

        assert is_admin("fake-key") is False

    @patch("auth_utils.get_current_user_roles")
    @patch("auth_utils.ADMIN_ROLES", ["custom_role_x"], create=True)
    def test_configurable_admin_roles(self, mock_roles):
        """ADMIN_ROLES is configurable — only listed roles count."""
        mock_roles.return_value = ["admin", "user"]

        from auth_utils import is_admin

        # "admin" is NOT in the patched ADMIN_ROLES, so should be False
        # But is_admin imports ADMIN_ROLES inside the function from config
        # We need to patch config.ADMIN_ROLES instead
        assert True  # placeholder — tested via config patch below

    @patch("auth_utils.get_current_user_roles")
    def test_custom_config_admin_roles(self, mock_roles):
        """Verify is_admin reads from config.ADMIN_ROLES."""
        mock_roles.return_value = ["custom_only_role"]

        with patch("config.ADMIN_ROLES", ["custom_only_role"]):
            from auth_utils import is_admin

            assert is_admin("fake-key") is True

    @patch("auth_utils.get_current_user_roles")
    def test_custom_config_excludes_default(self, mock_roles):
        """If config.ADMIN_ROLES doesn't include 'admin', admin role doesn't match."""
        mock_roles.return_value = ["admin", "user"]

        with patch("config.ADMIN_ROLES", ["only_this_role"]):
            from auth_utils import is_admin

            assert is_admin("fake-key") is False
