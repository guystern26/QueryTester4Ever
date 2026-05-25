# -*- coding: utf-8 -*-
"""Shared fixtures and Splunk module stubs for handler tests."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add bin/ to sys.path so handlers can be imported
_bin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _bin_dir not in sys.path:
    sys.path.insert(0, _bin_dir)

# Add tests/ to sys.path so helpers can be imported
_tests_dir = os.path.dirname(os.path.abspath(__file__))
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

# Stub Splunk modules before any handler import
_splunk_mock = MagicMock()
sys.modules.setdefault("splunk", _splunk_mock)
sys.modules.setdefault("splunk.persistconn", _splunk_mock.persistconn)
sys.modules.setdefault("splunk.persistconn.application", _splunk_mock.persistconn.application)
sys.modules.setdefault("splunklib", MagicMock())
sys.modules.setdefault("splunklib.client", MagicMock())
sys.modules.setdefault("splunklib.results", MagicMock())

# Make PersistentServerConnectionApplication a plain base class
_splunk_mock.persistconn.application.PersistentServerConnectionApplication = object

# Break circular import: spl/__init__ -> query_injector -> core.models ->
# core/__init__ -> core.test_runner -> spl.query_injector.
# Pre-register lightweight package stubs so submodule imports (e.g.
# "from core.models import X") resolve directly without __init__.py.
import types as _types
import importlib as _il

for _pkg_name, _pkg_dir in [("spl", "spl"), ("core", "core")]:
    if _pkg_name not in sys.modules:
        _pkg = _types.ModuleType(_pkg_name)
        _pkg.__path__ = [os.path.join(_bin_dir, _pkg_dir)]
        _pkg.__package__ = _pkg_name
        sys.modules[_pkg_name] = _pkg

from helpers import FakeKVStore


@pytest.fixture
def fake_kv():
    return FakeKVStore()


@pytest.fixture
def patch_kv(fake_kv):
    """Patch KVStoreClient in every handler module that imports it."""
    targets = [
        "saved_tests_handler.KVStoreClient",
        "scheduled_tests_handler.KVStoreClient",
        "run_history_handler.KVStoreClient",
    ]
    patches = [patch(t, return_value=fake_kv) for t in targets]
    # Default is_admin_user to True so ownership checks pass (admin bypass)
    admin_patches = [
        patch("handler_utils.is_admin_user", return_value=True),
    ]
    for p in patches + admin_patches:
        p.start()
    yield fake_kv
    for p in patches + admin_patches:
        p.stop()
