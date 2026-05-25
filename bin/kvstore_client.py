# -*- coding: utf-8 -*-
"""
kvstore_client.py — Thin wrapper around splunklib KVStore.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import splunklib.client as splunk_client

from config import SPLUNK_HOST, SPLUNK_PORT
from logger import get_logger

logger = get_logger(__name__)


class KVStoreClient:
    """Provides CRUD operations against a Splunk KVStore collection."""

    def __init__(self, session_key):
        # type: (str) -> None
        self._service = splunk_client.connect(
            host=SPLUNK_HOST,
            port=SPLUNK_PORT,
            splunkToken=session_key,
            app="QueryTester",
            owner="nobody",
        )

    def get_all(self, collection):
        # type: (str) -> List[Dict[str, Any]]
        """Return all records from a KVStore collection."""
        coll = self._get_collection(collection)
        data = coll.data.query()
        return self._parse_response(data)

    def get_by_id(self, collection, key):
        # type: (str, str) -> Dict[str, Any]
        """Return a single record by _key. Raises ValueError if not found."""
        coll = self._get_collection(collection)
        try:
            data = coll.data.query_by_id(key)
        except Exception as exc:
            raise ValueError("Record not found: {0}".format(key)) from exc
        if isinstance(data, str):
            data = json.loads(data)
        return data

    def upsert(self, collection, key, record):
        # type: (str, str, Dict[str, Any]) -> Dict[str, Any]
        """Insert or update a record. Sets _key on the record."""
        coll = self._get_collection(collection)
        record["_key"] = key
        try:
            # Try update first
            self.get_by_id(collection, key)
            coll.data.update(key, json.dumps(record))
            logger.debug("Updated record %s in %s", key, collection)
        except ValueError:
            # Record doesn't exist — insert
            coll.data.insert(json.dumps(record))
            logger.debug("Inserted record %s in %s", key, collection)
        return record

    def delete(self, collection, key):
        # type: (str, str) -> None
        """Delete a record by _key. Raises ValueError if not found."""
        coll = self._get_collection(collection)
        try:
            coll.data.delete_by_id(key)
            logger.debug("Deleted record %s from %s", key, collection)
        except Exception as exc:
            raise ValueError(
                "Failed to delete {0} from {1}: {2}".format(key, collection, exc)
            ) from exc

    def query(self, collection, query_dict):
        # type: (str, Dict[str, Any]) -> List[Dict[str, Any]]
        """Query records with a MongoDB-style filter dict."""
        coll = self._get_collection(collection)
        query_str = json.dumps(query_dict)
        data = coll.data.query(query=query_str)
        return self._parse_response(data)

    def _get_collection(self, collection):
        # type: (str) -> Any
        """Get a KVStore collection object, raising ValueError if missing."""
        try:
            return self._service.kvstore[collection]
        except KeyError:
            raise ValueError("KVStore collection not found: {0}".format(collection))

    @staticmethod
    def _parse_response(data):
        # type: (Any) -> List[Dict[str, Any]]
        """Parse KVStore response into a list of dicts."""
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise ValueError("Unexpected KVStore response type: {0}".format(type(data)))
