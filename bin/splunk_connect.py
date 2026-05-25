# -*- coding: utf-8 -*-
"""
splunk_connect.py — Centralized Splunk connection factory.

All modules that need a splunklib Service should call ``get_service()``
instead of importing SPLUNK_HOST/PORT from config and calling
``splunk_client.connect()`` directly.

Always connects to localhost via static config.py values. Session tokens
are bound to the local splunkd — connecting to a different hostname
(e.g. the auto-detected FQDN) causes "not logged in" errors.

The ``splunk_host`` from the Setup page is for display/URL purposes
only (e.g. email links), not for API connections.
"""
from __future__ import annotations

from typing import Any

import splunklib.client as splunk_client

from config import SPLUNK_HOST, SPLUNK_PORT


def get_service(session_key, app="QueryTester", owner="nobody"):
    # type: (str, str, str) -> Any
    """Create a splunklib Service connected to the local Splunk instance."""
    return splunk_client.connect(
        host=SPLUNK_HOST,
        port=int(SPLUNK_PORT),
        splunkToken=session_key,
        app=app,
        owner=owner,
    )
