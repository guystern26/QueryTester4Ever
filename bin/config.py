# -*- coding: utf-8 -*-
"""
config.py — Deployment Configuration
=====================================
EDIT THIS FILE WHEN DEPLOYING TO A NEW SPLUNK INSTANCE.
This is the ONLY file you need to change for backend environment settings.
No other Python file should contain hardcoded environment-specific values.
"""
from __future__ import annotations

# ─── Splunk Instance Connection ──────────────────────────────────────────────

SPLUNK_HOST = "localhost"
SPLUNK_PORT = 8089            # splunkd management port
SPLUNK_SCHEME = "https"
SPLUNK_USERNAME = "admin"
SPLUNK_PASSWORD = ""

# ─── Endpoints ───────────────────────────────────────────────────────────────

ENDPOINT = "servicesNS/admin/playground/data/tester"
APPS_ENDPOINT = "http://splunk:8089/services/apps/local/?output_mode=json&count=1000"

# ─── HEC (HTTP Event Collector) ─────────────────────────────────────────────
# Used for indexing synthetic test data. HEC must be enabled on this instance.

HEC_HOST = "localhost"
HEC_PORT = 8088
HEC_SCHEME = "https"
HEC_TOKEN = "34b745fc-b8b8-4837-84ab-82402ea18d51"  # your HEC token
HEC_SSL_VERIFY = False        # set True if your instance uses a valid TLS cert
HEC_TIMEOUT = 30              # seconds

# ─── Temp Index ──────────────────────────────────────────────────────────────
# The index used for injected test data. Must exist in Splunk (see indexes.conf).

TEMP_INDEX = "temp_query_tester"
TEMP_SOURCETYPE = "query_tester_input"

# ─── Splunk Web URL ──────────────────────────────────────────────────────────
# Base URL of the Splunk web interface (no trailing slash).
# Used for building links in email notifications.

SPLUNK_WEB_URL = "http://localhost:8000"

# ─── SMTP / Email ────────────────────────────────────────────────────────────

SMTP_SERVER = "CASNLB"
SMTP_PORT = 25
MAIL_FROM = "svc_ijump@souf.org"
MAIL_PASSWORD = "Password1!"
MAIL_TO = "t_splunk@souf.org"
DEFAULT_ALERT_EMAIL = "t_splunk@souf.org"

# ─── Logging ─────────────────────────────────────────────────────────────────
# Log file path. Falls back to $SPLUNK_HOME/var/log/splunk/query_tester.log
# if left empty. Can also be overridden via QUERY_TESTER_LOG env var.

LOG_FILE = ""                 # e.g. "/opt/splunk/var/log/splunk/query_tester.log"
LOG_LEVEL = "INFO"            # DEBUG | INFO | WARNING | ERROR

# ─── Authorization ────────────────────────────────────────────────────────
# Roles considered "admin" for ownership bypass on PUT/DELETE.
# Add custom roles (e.g. from SAML role mapping) as needed.

ADMIN_ROLES = ["admin", "sc_admin", "query_tester_admin"]

# ─── LLM / AI ────────────────────────────────────────────────────────────────
# Used by the Extract Fields / Suggest Fields AI buttons.
# Set LLM_ENDPOINT to "" to disable AI features.

LLM_ENDPOINT = ""
LLM_API_KEY = ""
LLM_MODEL = "gpt-4o-mini"
LLM_MAX_TOKENS = 2048

# ─── Limits ──────────────────────────────────────────────────────────────────

MAX_QUERY_DATA_EVENTS = 10000  # max events from a Query Data sub-query
HEC_BATCH_SIZE = 1000          # events per HEC POST request
MAX_DEFINITION_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB — inside KVStore doc limit

# Run history retention (enforced by nightly saved search, not at write time)
MAX_RUN_HISTORY_PER_TEST = 20     # keep last N runs per scheduled test
MAX_RUN_HISTORY_TOTAL = 100000    # advisory cap on total run history records

# Scheduling concurrency
MAX_PARALLEL_TESTS = 5           # max concurrent scheduled test runs (1-10)
