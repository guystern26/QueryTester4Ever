# -*- coding: utf-8 -*-
"""
auth_utils.py — Authentication and authorization utilities.

Uses ``authentication/current-context`` via splunklib to read the
authenticated user's roles from the session token, without needing the
username separately.  This works correctly with SAML / SSO logins where
the username may be an email or UPN.
"""
from __future__ import annotations

from typing import List

from logger import get_logger

logger = get_logger(__name__)


def get_current_user_roles(session_key):
    # type: (str) -> List[str]
    """Return the list of roles for the user identified by *session_key*.

    Calls the ``authentication/current-context`` REST endpoint which
    returns information about the currently authenticated session —
    no username lookup required.
    """
    from splunk_connect import get_service

    service = get_service(session_key, app="QueryTester", owner="nobody")

    # GET /services/authentication/current-context
    response = service.get("authentication/current-context", output_mode="json")
    body = response.body.read()

    import json
    data = json.loads(body)
    logger.debug("authentication/current-context raw response: %s", data)

    # Response shape: { "entry": [ { "content": { "roles": [...], ... } } ] }
    entry = data.get("entry") or []
    if not entry:
        logger.warning("authentication/current-context returned no entries")
        return []

    content = entry[0].get("content") or {}
    roles = content.get("roles", [])

    if not isinstance(roles, list):
        logger.warning("Unexpected roles type: %s", type(roles).__name__)
        return []

    return roles


def is_admin(session_key):
    # type: (str) -> bool
    """Check whether the current session belongs to an admin user.

    Compares the user's roles against the configurable ``ADMIN_ROLES``
    list in ``config.py``.
    """
    from config import ADMIN_ROLES

    try:
        roles = get_current_user_roles(session_key)
    except Exception:
        logger.exception("Failed to read roles for admin check")
        return False

    admin_set = set(ADMIN_ROLES)
    return bool(admin_set.intersection(roles))
