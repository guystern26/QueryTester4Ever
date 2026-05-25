# -*- coding: utf-8 -*-
"""
Live test: create a temp KVStore lookup, outputlookup to it, read it back, clean up.
Mimics exactly what the cache macro injection does.

Run manually:  py -m pytest tests/test_cache_kvstore_live.py -v -s
Requires a running local Splunk instance.
"""
from __future__ import annotations

import os
import sys
import time

_bin_dir = os.path.join(os.path.dirname(__file__), "..")
if _bin_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_bin_dir))

import splunklib.client as client
import splunklib.results as results
import pytest

SPLUNK_HOST = "localhost"
SPLUNK_PORT = 8089
SPLUNK_USER = "admin"
SPLUNK_PASS = "Password1!"
APP = "QueryTester"
LOOKUP_NAME = "temp_cache_livetest_mylu"
COLL_NAME = "temp_cache_livetest_mylu"


@pytest.fixture(scope="module")
def service():
    """Connect to local Splunk."""
    svc = client.connect(
        host=SPLUNK_HOST, port=SPLUNK_PORT,
        username=SPLUNK_USER, password=SPLUNK_PASS,
        app=APP, owner="nobody",
    )
    yield svc
    # Cleanup after all tests
    _cleanup(svc)


def _cleanup(svc):
    """Remove the temp collection + transforms definition."""
    try:
        svc.confs["transforms"].delete(LOOKUP_NAME)
    except Exception:
        pass
    try:
        svc.kvstore.delete(COLL_NAME)
    except Exception:
        pass


def _run_search(svc, spl, earliest="-1m", latest="now"):
    """Run a oneshot search and return result rows."""
    kwargs = {"earliest_time": earliest, "latest_time": latest}
    reader = results.JSONResultsReader(
        svc.jobs.oneshot(spl, output_mode="json", **kwargs)
    )
    rows = []
    for item in reader:
        if isinstance(item, dict):
            rows.append(item)
    return rows


class TestCacheKVStoreLive:

    def test_01_create_kvstore_collection(self, service):
        """Step 1: Create the KVStore collection."""
        _cleanup(service)  # start clean
        service.kvstore.create(COLL_NAME)
        colls = [c.name for c in service.kvstore]
        assert COLL_NAME in colls, "Collection not found after creation"

    def test_02_create_transforms_definition(self, service):
        """Step 2: Create transforms.conf lookup definition pointing to the collection."""
        service.confs["transforms"].create(
            LOOKUP_NAME,
            **{"collection": COLL_NAME, "external_type": "kvstore"}
        )
        stanza = service.confs["transforms"][LOOKUP_NAME]
        assert stanza["collection"] == COLL_NAME

    def test_03_outputlookup_writes_data(self, service):
        """Step 3: Run outputlookup to the temp KVStore — this is what the cache macro does."""
        spl = '| makeresults count=3 | eval src_ip="10.0.0." + tostring(random() % 255), score=random() % 100 | outputlookup ' + LOOKUP_NAME
        rows = _run_search(service, spl)
        # outputlookup returns the rows it wrote
        assert len(rows) == 3, "Expected 3 rows written, got {}".format(len(rows))

    def test_04_inputlookup_reads_data(self, service):
        """Step 4: Verify the data is readable via inputlookup."""
        time.sleep(1)  # small settle time
        spl = "| inputlookup " + LOOKUP_NAME
        rows = _run_search(service, spl)
        assert len(rows) == 3, "Expected 3 rows, got {}".format(len(rows))
        assert "src_ip" in rows[0], "Expected src_ip field in results"
        assert "score" in rows[0], "Expected score field in results"

    def test_05_lookup_command_works(self, service):
        """Step 5: Verify the lookup command works (read-side of cache)."""
        spl = '| makeresults | eval src_ip="10.0.0.1" | lookup ' + LOOKUP_NAME + ' src_ip'
        rows = _run_search(service, spl)
        assert len(rows) >= 1

    def test_06_outputlookup_append(self, service):
        """Step 6: Second outputlookup appends (simulates cache accumulation)."""
        spl = '| makeresults count=2 | eval src_ip="192.168.1." + tostring(random() % 255), score=50 | outputlookup append=true ' + LOOKUP_NAME
        _run_search(service, spl)
        time.sleep(1)
        spl2 = "| inputlookup " + LOOKUP_NAME + " | stats count"
        rows = _run_search(service, spl2)
        count = int(rows[0].get("count", 0))
        assert count == 5, "Expected 5 rows after append, got {}".format(count)

    def test_07_cleanup(self, service):
        """Step 7: Clean up — delete transforms + collection."""
        _cleanup(service)
        colls = [c.name for c in service.kvstore]
        assert COLL_NAME not in colls, "Collection should be deleted"
