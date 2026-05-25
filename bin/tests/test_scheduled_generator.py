# -*- coding: utf-8 -*-
"""
Tests that mimic the EXACT pipeline a scheduled test goes through,
specifically for generator rules — the path that caused KeyError on fieldName.

Pipeline: KVStore definition → build_test_payload → payload_parser → config_parser
"""
from __future__ import annotations

import json
import copy
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scheduling.scheduled_runner_helpers import build_test_payload
from generators.config_parser import parse_generator_config


# ─── Fixtures: what KVStore actually stores ─────────────────────────────────

def _kvstore_definition():
    """Mimics what the frontend saves to KVStore via saved_tests_handler.
    Keys are FRONTEND format: field, type (not fieldName, generationType).
    """
    return {
        "name": "License Usage Monitor",
        "app": "search",
        "testType": "standard",
        "query": {
            "spl": "index=_internal | stats count by sourcetype",
            "timeRange": {"earliest": "-24h", "latest": "now"},
            "savedSearchOrigin": None,
        },
        "scenarios": [
            {
                "id": "sc-1",
                "name": "Scenario 1",
                "description": "",
                "inputs": [
                    {
                        "id": "inp-1",
                        "rowIdentifier": "index=_internal",
                        "inputMode": "fields",
                        "events": [
                            {
                                "id": "evt-1",
                                "fieldValues": [
                                    {"id": "fv-1", "field": "sourcetype", "value": "splunkd"},
                                    {"id": "fv-2", "field": "count", "value": "100"},
                                ],
                            }
                        ],
                        "generatorConfig": {
                            "enabled": True,
                            "eventCount": 10,
                            "rules": [
                                {
                                    "id": "rule-1",
                                    "field": "sourcetype",       # ← Frontend key
                                    "type": "pick_list",         # ← Frontend key
                                    "config": {
                                        "values": ["splunkd", "scheduler"],
                                    },
                                },
                                {
                                    "id": "rule-2",
                                    "field": "count",            # ← Frontend key
                                    "type": "random_number",     # ← Frontend key
                                    "config": {
                                        "min": 1,
                                        "max": 1000,
                                    },
                                },
                            ],
                        },
                        "jsonContent": "",
                        "fileRef": None,
                        "queryDataConfig": {"spl": "", "timeRange": {"earliest": "", "latest": ""}},
                    }
                ],
            }
        ],
        "validation": {
            "validationType": "standard",
            "fieldGroups": [],
            "fieldLogic": "and",
            "validationScope": "all_events",
            "scopeN": None,
            "resultCount": {"enabled": False, "operator": "greater_than", "value": 0},
        },
    }


def _kvstore_definition_already_normalized():
    """Definition where generator rules already have fieldName/generationType.
    This happens if the definition was saved from a manual run payload.
    """
    d = _kvstore_definition()
    for rule in d["scenarios"][0]["inputs"][0]["generatorConfig"]["rules"]:
        rule["fieldName"] = rule.pop("field")
        rule["generationType"] = rule.pop("type")
    return d


def _kvstore_definition_no_generator():
    """Definition with no generator config."""
    d = _kvstore_definition()
    d["scenarios"][0]["inputs"][0]["generatorConfig"] = {
        "enabled": False,
        "eventCount": 0,
        "rules": [],
    }
    return d


def _kvstore_definition_generator_disabled():
    """Definition with generator config present but disabled."""
    d = _kvstore_definition()
    d["scenarios"][0]["inputs"][0]["generatorConfig"]["enabled"] = False
    return d


# ─── Tests ──────────────────────────────────────────────────────────────────

class TestScheduledGeneratorPipeline:
    """Mimics: KVStore → build_test_payload → payload_parser → config_parser"""

    def test_frontend_keys_get_normalized(self):
        """The main bug: KVStore has field/type, config_parser expects fieldName/generationType."""
        definition = _kvstore_definition()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, spl = build_test_payload(definition, saved_test, scheduled)

        # After build_test_payload, generator rules should be normalized
        gen = payload["scenarios"][0]["inputs"][0]["generatorConfig"]
        assert gen["enabled"] is True
        for rule in gen["rules"]:
            assert "fieldName" in rule, "fieldName missing after normalization"
            assert "generationType" in rule, "generationType missing after normalization"
            assert "field" not in rule, "'field' should have been renamed to 'fieldName'"
            assert "type" not in rule, "'type' should have been renamed to 'generationType'"

    def test_normalized_keys_pass_through_config_parser(self):
        """After normalization, config_parser should parse without KeyError."""
        definition = _kvstore_definition()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        gen_raw = payload["scenarios"][0]["inputs"][0]["generatorConfig"]

        # This is the call that was throwing KeyError
        gen_config = parse_generator_config(gen_raw)
        assert gen_config.enabled is True
        assert len(gen_config.rules) == 2
        assert gen_config.rules[0].field_name == "sourcetype"
        assert gen_config.rules[0].generation_type == "pick_list"
        assert gen_config.rules[1].field_name == "count"
        assert gen_config.rules[1].generation_type == "random_number"

    def test_already_normalized_keys_not_broken(self):
        """If keys are already fieldName/generationType, don't break them."""
        definition = _kvstore_definition_already_normalized()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        gen_raw = payload["scenarios"][0]["inputs"][0]["generatorConfig"]

        gen_config = parse_generator_config(gen_raw)
        assert gen_config.rules[0].field_name == "sourcetype"
        assert gen_config.rules[1].field_name == "count"

    def test_disabled_generator_skipped(self):
        """Disabled generator config should not crash normalization."""
        definition = _kvstore_definition_generator_disabled()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        gen_raw = payload["scenarios"][0]["inputs"][0]["generatorConfig"]

        # Rules still have frontend keys because normalization skips disabled generators
        # But config_parser should handle this since it won't be called for disabled configs
        assert gen_raw["enabled"] is False

    def test_no_generator_config(self):
        """Missing or empty generator should not crash."""
        definition = _kvstore_definition_no_generator()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        gen_raw = payload["scenarios"][0]["inputs"][0]["generatorConfig"]
        assert gen_raw["enabled"] is False

    def test_events_also_flattened(self):
        """Events should be flattened from fieldValues format to flat dicts."""
        definition = _kvstore_definition()
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        events = payload["scenarios"][0]["inputs"][0]["events"]

        assert len(events) == 1
        assert events[0]["sourcetype"] == "splunkd"
        assert events[0]["count"] == "100"
        assert "fieldValues" not in events[0]
        assert "id" not in events[0]

    def test_full_pipeline_end_to_end(self):
        """Full pipeline: KVStore def → build_payload → parse_generator_config.
        This is the EXACT path scheduled_runner.py takes.
        """
        definition = _kvstore_definition()
        saved_test = {"name": "License Monitor", "app": "search"}
        scheduled = {"testName": "License Monitor", "cronSchedule": "*/30 * * * *"}

        # Step 1: build_test_payload (what scheduled_runner_helpers does)
        payload, query_spl = build_test_payload(definition, saved_test, scheduled)

        assert query_spl == "index=_internal | stats count by sourcetype"
        assert payload["testName"] == "License Usage Monitor"
        assert payload["app"] == "search"

        # Step 2: parse each input's generator config (what payload_parser does)
        for scenario in payload["scenarios"]:
            for inp in scenario["inputs"]:
                gen_raw = inp.get("generatorConfig")
                if gen_raw and isinstance(gen_raw, dict) and gen_raw.get("enabled"):
                    gen_config = parse_generator_config(gen_raw)
                    assert gen_config.enabled is True
                    for rule in gen_config.rules:
                        assert rule.field_name, "field_name should not be empty"
                        assert rule.generation_type, "generation_type should not be empty"

    def test_multiple_inputs_multiple_generators(self):
        """Multiple inputs each with their own generator config."""
        definition = _kvstore_definition()
        # Add a second input with different generator rules
        second_input = copy.deepcopy(definition["scenarios"][0]["inputs"][0])
        second_input["id"] = "inp-2"
        second_input["rowIdentifier"] = "index=main"
        second_input["generatorConfig"]["rules"] = [
            {"id": "rule-3", "field": "host", "type": "pick_list",
             "config": {"values": ["web01", "web02"]}},
        ]
        definition["scenarios"][0]["inputs"].append(second_input)

        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)

        # Both inputs should have normalized generator rules
        for inp in payload["scenarios"][0]["inputs"]:
            gen = inp["generatorConfig"]
            if gen["enabled"]:
                for rule in gen["rules"]:
                    assert "fieldName" in rule
                    assert "generationType" in rule

        # Verify second input specifically
        second_gen = payload["scenarios"][0]["inputs"][1]["generatorConfig"]
        assert second_gen["rules"][0]["fieldName"] == "host"
        assert second_gen["rules"][0]["generationType"] == "pick_list"


class TestQueryDataConfigNormalization:
    """Tests for queryDataConfig.timeRange → earliestTime/latestTime conversion."""

    def test_timerange_converted_to_flat_keys(self):
        """Frontend stores timeRange nested, backend expects flat keys."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["inputMode"] = "query_data"
        definition["scenarios"][0]["inputs"][0]["queryDataConfig"] = {
            "spl": "index=main | stats count",
            "timeRange": {"earliest": "-7d@d", "latest": "now"},
        }
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        qd = payload["scenarios"][0]["inputs"][0]["queryDataConfig"]

        assert qd["earliestTime"] == "-7d@d"
        assert qd["latestTime"] == "now"
        assert "timeRange" not in qd

    def test_already_flat_keys_not_broken(self):
        """If keys are already earliestTime/latestTime, don't break them."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["inputMode"] = "query_data"
        definition["scenarios"][0]["inputs"][0]["queryDataConfig"] = {
            "spl": "index=main | stats count",
            "earliestTime": "-24h",
            "latestTime": "now",
        }
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        qd = payload["scenarios"][0]["inputs"][0]["queryDataConfig"]

        assert qd["earliestTime"] == "-24h"
        assert qd["latestTime"] == "now"

    def test_empty_query_data_config(self):
        """Empty SPL in queryDataConfig should not crash."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["queryDataConfig"] = {
            "spl": "",
            "timeRange": {"earliest": "", "latest": ""},
        }
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        # Empty SPL — should not be normalized (skipped)
        qd = payload["scenarios"][0]["inputs"][0]["queryDataConfig"]
        assert "timeRange" in qd  # not touched because spl is empty

    def test_missing_query_data_config(self):
        """Missing queryDataConfig entirely should not crash."""
        definition = _kvstore_definition()
        del definition["scenarios"][0]["inputs"][0]["queryDataConfig"]
        saved_test = {"name": "Test", "app": "search"}
        scheduled = {"testName": "Test"}

        payload, _ = build_test_payload(definition, saved_test, scheduled)
        assert "queryDataConfig" not in payload["scenarios"][0]["inputs"][0]


class TestEdgeCases:
    """Edge cases that could break the scheduled pipeline."""

    def test_empty_scenarios(self):
        """Definition with no scenarios."""
        definition = _kvstore_definition()
        definition["scenarios"] = []
        payload, _ = build_test_payload(definition, {}, {})
        assert payload["scenarios"] == []

    def test_empty_inputs(self):
        """Scenario with no inputs."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"] = []
        payload, _ = build_test_payload(definition, {}, {})
        assert payload["scenarios"][0]["inputs"] == []

    def test_empty_events(self):
        """Input with no events."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["events"] = []
        payload, _ = build_test_payload(definition, {}, {})
        assert payload["scenarios"][0]["inputs"][0]["events"] == []

    def test_already_flat_events(self):
        """Events already in flat dict format (not fieldValues)."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["events"] = [
            {"sourcetype": "splunkd", "count": "50"},
        ]
        payload, _ = build_test_payload(definition, {}, {})
        events = payload["scenarios"][0]["inputs"][0]["events"]
        assert events[0]["sourcetype"] == "splunkd"

    def test_generator_with_empty_rules(self):
        """Generator enabled but no rules."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["generatorConfig"] = {
            "enabled": True,
            "eventCount": 10,
            "rules": [],
        }
        payload, _ = build_test_payload(definition, {}, {})
        gen = payload["scenarios"][0]["inputs"][0]["generatorConfig"]
        assert gen["enabled"] is True
        assert gen["rules"] == []

    def test_generator_rule_missing_config(self):
        """Generator rule with no config dict."""
        definition = _kvstore_definition()
        definition["scenarios"][0]["inputs"][0]["generatorConfig"]["rules"] = [
            {"id": "r1", "field": "host", "type": "pick_list"},
        ]
        payload, _ = build_test_payload(definition, {}, {})
        rule = payload["scenarios"][0]["inputs"][0]["generatorConfig"]["rules"][0]
        assert rule["fieldName"] == "host"
        assert rule["generationType"] == "pick_list"

    def test_query_as_string(self):
        """Definition where query is a plain string (old format)."""
        definition = _kvstore_definition()
        definition["query"] = "index=main | stats count"
        payload, spl = build_test_payload(definition, {}, {})
        assert spl == "index=main | stats count"
        assert payload["earliestTime"] == "-24h"  # default

    def test_name_fallback_chain(self):
        """Test name falls back: definition → saved_test → scheduled."""
        definition = {"query": {"spl": "test", "timeRange": {}}, "scenarios": []}

        # No name anywhere
        payload, _ = build_test_payload(definition, {}, {})
        assert payload["testName"] == ""

        # Name in saved_test
        payload, _ = build_test_payload(definition, {"name": "From Saved"}, {})
        assert payload["testName"] == "From Saved"

        # Name in definition overrides
        definition["name"] = "From Definition"
        payload, _ = build_test_payload(definition, {"name": "From Saved"}, {})
        assert payload["testName"] == "From Definition"

    def test_validation_passes_through(self):
        """Validation object should pass through unchanged."""
        definition = _kvstore_definition()
        payload, _ = build_test_payload(definition, {}, {})
        v = payload["validation"]
        assert v["validationType"] == "standard"
        assert v["fieldLogic"] == "and"
        assert v["validationScope"] == "all_events"

    def test_mixed_inputs_all_normalized(self):
        """Multiple inputs with different modes all get normalized."""
        definition = _kvstore_definition()
        # Input 1: fields mode with generator (already in fixture)
        # Input 2: query_data mode
        qd_input = {
            "id": "inp-2",
            "rowIdentifier": "",
            "inputMode": "query_data",
            "events": [],
            "generatorConfig": {"enabled": False, "eventCount": 0, "rules": []},
            "queryDataConfig": {
                "spl": "index=firewall | stats count by src_ip",
                "timeRange": {"earliest": "-1h", "latest": "now"},
            },
            "jsonContent": "",
            "fileRef": None,
        }
        definition["scenarios"][0]["inputs"].append(qd_input)

        payload, _ = build_test_payload(definition, {}, {})
        inputs = payload["scenarios"][0]["inputs"]

        # Input 1: generator normalized
        gen = inputs[0]["generatorConfig"]
        assert gen["rules"][0]["fieldName"] == "sourcetype"

        # Input 2: queryDataConfig normalized
        qd = inputs[1]["queryDataConfig"]
        assert qd["earliestTime"] == "-1h"
        assert qd["latestTime"] == "now"
        assert "timeRange" not in qd

    def test_validation_defaults_when_missing(self):
        """Missing validation keys should get safe defaults."""
        definition = _kvstore_definition()
        definition["validation"] = {}
        payload, _ = build_test_payload(definition, {}, {})
        v = payload["validation"]
        assert v["validationType"] == "standard"
        assert v["fieldLogic"] == "and"
        assert v["validationScope"] == "any_event"
        assert v["fieldGroups"] == []

    def test_validation_null_becomes_dict(self):
        """None/null validation should not crash."""
        definition = _kvstore_definition()
        definition["validation"] = None
        payload, _ = build_test_payload(definition, {}, {})
        v = payload["validation"]
        assert isinstance(v, dict)
        assert v["fieldGroups"] == []

    def test_validation_fieldgroups_null_becomes_list(self):
        """Null fieldGroups should become empty list."""
        definition = _kvstore_definition()
        definition["validation"]["fieldGroups"] = None
        payload, _ = build_test_payload(definition, {}, {})
        assert payload["validation"]["fieldGroups"] == []

    def test_disabled_generator_with_frontend_keys_no_crash(self):
        """Enable generator → add rules → disable → scheduled run should not crash."""
        definition = _kvstore_definition()
        gen = definition["scenarios"][0]["inputs"][0]["generatorConfig"]
        gen["enabled"] = False
        # Rules still have frontend keys (field/type) from when it was enabled
        assert gen["rules"][0]["field"] == "sourcetype"
        assert gen["rules"][0]["type"] == "pick_list"

        payload, _ = build_test_payload(definition, {}, {})
        gen_out = payload["scenarios"][0]["inputs"][0]["generatorConfig"]

        # Rules should be normalized even though disabled
        assert gen_out["rules"][0]["fieldName"] == "sourcetype"
        assert gen_out["rules"][0]["generationType"] == "pick_list"
        assert gen_out["enabled"] is False

    def test_disabled_generator_not_parsed_by_payload_parser(self):
        """Disabled generator should be skipped by payload_parser — no KeyError."""
        from core.payload_parser import _parse_input

        raw_input = {
            "rowIdentifier": "index=main",
            "inputMode": "fields",
            "events": [{"host": "web01"}],
            "generatorConfig": {
                "enabled": False,
                "eventCount": 10,
                "rules": [
                    {"id": "r1", "field": "host", "type": "pick_list",
                     "config": {"values": ["web01"]}},
                ],
            },
        }
        # This should NOT crash even with frontend keys + disabled
        parsed = _parse_input(raw_input)
        assert parsed.generator_config is None  # disabled = not parsed

    def test_reenable_generator_after_disable(self):
        """Disable then re-enable: rules should still parse correctly."""
        definition = _kvstore_definition()
        gen = definition["scenarios"][0]["inputs"][0]["generatorConfig"]
        # Simulate: was enabled, got disabled, re-enabled
        gen["enabled"] = True
        # Rules still have frontend keys from original save

        payload, _ = build_test_payload(definition, {}, {})
        gen_out = payload["scenarios"][0]["inputs"][0]["generatorConfig"]

        gen_config = parse_generator_config(gen_out)
        assert gen_config.enabled is True
        assert gen_config.rules[0].field_name == "sourcetype"

    def test_kvstore_key_format(self):
        """KVStore returns _key, not id. build_test_payload should handle both."""
        definition = _kvstore_definition()
        saved_test = {"_key": "abc123", "name": "Test"}
        scheduled = {"_key": "sched456", "testName": "Test"}
        payload, _ = build_test_payload(definition, saved_test, scheduled)
        # Should not crash — _key is used internally, not in payload
