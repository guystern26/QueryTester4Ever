# -*- coding: utf-8 -*-
"""
config_secrets.py — Read/write secrets in Splunk storage/passwords.
Used by config_handler for sensitive configuration fields.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from logger import get_logger

logger = get_logger(__name__)

SECRET_REALM = "query_tester"

SECRET_FIELDS = frozenset([
    "hec_token", "splunk_password", "smtp_password",
    "oauth_client_secret", "email_api_key", "llm_api_key",
])


def get_splunk_service(session_key):
    # type: (str) -> Any
    """Connect to Splunk via splunklib for storage/passwords access.

    Uses static config directly (not splunk_connect) to avoid circular
    dependency: runtime_config -> config_secrets -> splunk_connect -> runtime_config.
    """
    import splunklib.client as splunk_client
    from config import SPLUNK_HOST, SPLUNK_PORT
    return splunk_client.connect(
        host=SPLUNK_HOST, port=int(SPLUNK_PORT),
        splunkToken=session_key, app="QueryTester", owner="nobody",
    )


def read_secret(service, field_name):
    # type: (Any, str) -> Optional[str]
    """Read a single secret from storage/passwords."""
    return read_all_secrets(service).get(field_name)


def read_all_secrets(service):
    # type: (Any) -> Dict[str, str]
    """Read all app secrets in a single pass over storage/passwords."""
    result = {}  # type: Dict[str, str]
    try:
        for cred in service.storage_passwords:
            if cred.realm == SECRET_REALM and cred.username in SECRET_FIELDS:
                result[cred.username] = cred.clear_password
    except Exception as exc:
        logger.debug("Failed to read secrets: %s", exc)
    return result


def write_secret(service, field_name, value):
    # type: (Any, str, str) -> None
    """Write or update a secret in storage/passwords."""
    # Try to update existing secret first
    try:
        for cred in service.storage_passwords:
            if cred.realm == SECRET_REALM and cred.username == field_name:
                cred.update(password=value)
                return
    except Exception as exc:
        logger.debug("Failed to scan existing secrets: %s", exc)

    # No existing secret — create new
    try:
        service.storage_passwords.create(value, field_name, SECRET_REALM)
    except Exception as exc:
        # If create fails with conflict, try delete + create
        logger.debug("Create secret failed, retrying with delete: %s", exc)
        try:
            service.storage_passwords.delete(field_name, SECRET_REALM)
            service.storage_passwords.create(value, field_name, SECRET_REALM)
        except Exception as exc2:
            logger.error("Failed to write secret '%s': %s", field_name, exc2)
            raise
