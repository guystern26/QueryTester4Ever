# -*- coding: utf-8 -*-
"""Shared test helpers — request/response builders, FakeKVStore."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


SESSION_KEY = "mock-session-key-12345"


def make_request(method="GET", payload=None, query=None, session_key=SESSION_KEY, path="", user="admin"):
    """Build a mock Splunk REST request dict."""
    req = {
        "method": method,
        "session": {"authtoken": session_key, "user": user},
        "rest_path": path,
    }
    if payload is not None:
        req["payload"] = json.dumps(payload) if isinstance(payload, dict) else payload
    if query is not None:
        req["query"] = query
    return json.dumps(req)


def parse_response(response):
    """Parse a handler JSON response dict."""
    assert "payload" in response
    return json.loads(response["payload"]), response.get("status", 200)


class FakeKVStore:
    """In-memory KVStore mock for testing handlers without Splunk."""

    def __init__(self):
        self._collections = {}  # type: Dict[str, Dict[str, Dict[str, Any]]]

    def get_all(self, collection):
        # type: (str) -> List[Dict[str, Any]]
        return list(self._collections.get(collection, {}).values())

    def get_by_id(self, collection, key):
        # type: (str, str) -> Dict[str, Any]
        store = self._collections.get(collection, {})
        if key not in store:
            raise ValueError("Record not found: {}".format(key))
        return dict(store[key])

    def upsert(self, collection, key, record):
        # type: (str, str, Dict[str, Any]) -> Dict[str, Any]
        if collection not in self._collections:
            self._collections[collection] = {}
        record["_key"] = key
        self._collections[collection][key] = dict(record)
        return record

    def delete(self, collection, key):
        # type: (str, str) -> None
        store = self._collections.get(collection, {})
        if key not in store:
            raise ValueError("Failed to delete {} from {}".format(key, collection))
        del store[key]

    def query(self, collection, query_dict):
        # type: (str, Dict[str, Any]) -> List[Dict[str, Any]]
        store = self._collections.get(collection, {})
        results = []
        for record in store.values():
            match = all(record.get(k) == v for k, v in query_dict.items())
            if match:
                results.append(dict(record))
        return results

    def seed(self, collection, records):
        # type: (str, list) -> None
        """Seed a collection with records (list of dicts, each must have 'id')."""
        for rec in records:
            self.upsert(collection, rec["id"], rec)
