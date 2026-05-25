#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Standalone live test: KVStore temp lookup for cache macro injection.
Run from bin/:  py test_cache_live.py
"""
from __future__ import annotations

import sys
import time

import splunklib.client as client
import splunklib.results as results

SPLUNK_HOST = "localhost"
SPLUNK_PORT = 8089
SPLUNK_USER = "admin"
SPLUNK_PASS = "Password1!"
APP = "QueryTester"
LOOKUP_NAME = "temp_cache_livetest_mylu"
COLL_NAME = "temp_cache_livetest_mylu"


def connect():
    return client.connect(
        host=SPLUNK_HOST, port=int(SPLUNK_PORT),
        username=SPLUNK_USER, password=SPLUNK_PASS,
        app=APP, owner="nobody",
    )


def run_search(svc, spl):
    job = svc.jobs.create(spl, earliest_time="-1m", latest_time="now")
    while not job.is_done():
        time.sleep(0.3)
        job.refresh()
    reader = results.JSONResultsReader(
        job.results(output_mode="json", count=0)
    )
    rows = []
    for item in reader:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def cleanup(svc):
    try:
        svc.confs["transforms"].delete(LOOKUP_NAME)
    except Exception:
        pass
    try:
        svc.kvstore.delete(COLL_NAME)
    except Exception:
        pass


def main():
    ok = 0
    fail = 0

    print("Connecting to Splunk...")
    svc = connect()
    cleanup(svc)

    # Step 1: Create KVStore collection
    print("\n[1] Create KVStore collection:", COLL_NAME)
    try:
        svc.kvstore.create(COLL_NAME)
        colls = [c.name for c in svc.kvstore]
        assert COLL_NAME in colls, "Collection not found"
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 2: Create transforms.conf lookup definition
    # In real flow, fields_list comes from inputlookup on the original lookup.
    # Here we hardcode the fields we'll use in the test.
    print("\n[2] Create transforms definition:", LOOKUP_NAME)
    try:
        svc.confs["transforms"].create(
            LOOKUP_NAME,
            **{
                "collection": COLL_NAME,
                "external_type": "kvstore",
                "fields_list": "_key, src_ip, score",
            }
        )
        stanza = svc.confs["transforms"][LOOKUP_NAME]
        assert stanza["collection"] == COLL_NAME
        print("    fields_list: _key, src_ip, score")
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 2b: Seed the collection with a dummy record
    print("\n[2b] Seed KVStore with dummy record")
    try:
        coll = svc.kvstore[COLL_NAME]
        coll.data.insert('{"_key": "__seed__", "src_ip": "", "score": ""}')
        data = coll.data.query()
        print("    Seeded, collection has", len(data), "record(s)")
        assert len(data) >= 1
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 3: outputlookup to KVStore
    print("\n[3] outputlookup to temp KVStore")
    try:
        spl = ('| makeresults count=3 '
               '| eval src_ip="10.0.0." + tostring(random() % 255), score=random() % 100 '
               '| outputlookup ' + LOOKUP_NAME)
        run_search(svc, spl)
        time.sleep(2)
        verify = run_search(svc, "| inputlookup " + LOOKUP_NAME)
        print("    Wrote and verified", len(verify), "rows")
        assert len(verify) >= 3, "Expected >= 3, got {}".format(len(verify))
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    time.sleep(1)

    # Step 4: inputlookup reads back
    print("\n[4] inputlookup reads data back")
    try:
        rows = run_search(svc, "| inputlookup " + LOOKUP_NAME)
        print("    Read", len(rows), "rows")
        assert len(rows) == 3, "Expected 3"
        assert "src_ip" in rows[0], "Missing src_ip"
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 5: lookup command works
    print("\n[5] lookup command enrichment")
    try:
        spl = '| makeresults | eval src_ip="10.0.0.1" | lookup ' + LOOKUP_NAME + ' src_ip'
        rows = run_search(svc, spl)
        print("    Got", len(rows), "rows")
        assert len(rows) >= 1
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 6: outputlookup append
    print("\n[6] outputlookup append (accumulation)")
    try:
        spl = ('| makeresults count=2 '
               '| eval src_ip="192.168.1." + tostring(random() % 255), score=50 '
               '| outputlookup append=true ' + LOOKUP_NAME)
        run_search(svc, spl)
        time.sleep(1)
        rows = run_search(svc, "| inputlookup " + LOOKUP_NAME + " | stats count")
        count = int(rows[0].get("count", 0))
        print("    Total rows after append:", count)
        assert count == 5, "Expected 5"
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    # Step 7: Cleanup
    print("\n[7] Cleanup")
    try:
        cleanup(svc)
        colls = [c.name for c in svc.kvstore]
        assert COLL_NAME not in colls
        print("    PASS")
        ok += 1
    except Exception as e:
        print("    FAIL:", e)
        fail += 1

    print("\n" + "=" * 40)
    print("Results: {} passed, {} failed".format(ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
