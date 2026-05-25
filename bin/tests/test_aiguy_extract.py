# -*- coding: utf-8 -*-
"""
test_aiguy_extract.py — Tests for aiguy extract mode.
Compares regex approach vs dict-mapping approach on realistic Splunk data.
No LLM calls — uses hardcoded LLM responses to test the extraction logic.
"""
from __future__ import annotations

import re
import json
import pytest

# ── Test data: realistic Splunk field values ─────────────────────────────────

EMAIL_ROWS = [
    {"user": "john.smith@acme.com", "action": "login"},
    {"user": "jane.doe@acme.com", "action": "logout"},
    {"user": "admin@internal.corp.net", "action": "login"},
    {"user": "bob@gmail.com", "action": "failed_login"},
    {"user": "alice@yahoo.co.uk", "action": "login"},
    {"user": "svc-monitor@acme.com", "action": "api_call"},
    {"user": "root@localhost", "action": "sudo"},
    {"user": "noreply@notifications.acme.com", "action": "email"},
]

IP_ROWS = [
    {"src_ip": "192.168.1.100", "dest_ip": "10.0.0.1", "bytes": "4521"},
    {"src_ip": "192.168.1.101", "dest_ip": "10.0.0.2", "bytes": "8923"},
    {"src_ip": "10.50.30.22", "dest_ip": "172.16.0.5", "bytes": "102"},
    {"src_ip": "192.168.1.100", "dest_ip": "8.8.8.8", "bytes": "64"},
    {"src_ip": "10.50.30.22", "dest_ip": "10.0.0.1", "bytes": "7712"},
]

LOG_ROWS = [
    {"_raw": "2026-05-05T14:30:00 INFO  server=web01 action=GET path=/api/users status=200 duration=45ms"},
    {"_raw": "2026-05-05T14:30:01 ERROR server=web02 action=POST path=/api/login status=500 duration=1203ms"},
    {"_raw": "2026-05-05T14:30:02 WARN  server=web01 action=GET path=/api/health status=200 duration=12ms"},
    {"_raw": "2026-05-05T14:30:03 INFO  server=web03 action=DELETE path=/api/sessions/abc status=204 duration=89ms"},
    {"_raw": "2026-05-05T14:30:04 ERROR server=web02 action=GET path=/api/data status=503 duration=5001ms"},
]

NAME_ROWS = [
    {"full_name": "John Smith", "dept": "Engineering"},
    {"full_name": "Jane Doe", "dept": "Marketing"},
    {"full_name": "Bob", "dept": "Sales"},
    {"full_name": "Alice Marie Johnson", "dept": "Engineering"},
    {"full_name": "Dr. Robert Brown Jr.", "dept": "Executive"},
]

URL_ROWS = [
    {"url": "https://www.example.com/api/v2/users?page=1", "status": "200"},
    {"url": "https://api.internal.corp/health", "status": "200"},
    {"url": "http://legacy-app:8080/login.jsp", "status": "302"},
    {"url": "https://cdn.example.com/assets/main.js", "status": "200"},
    {"url": "https://www.example.com/api/v2/orders/123", "status": "404"},
]


# ── Extraction logic (same as what will go in ai_guy.py) ─────────────────────

MAX_UNIQUE_FOR_DICT = 100
MAX_SAMPLE_FOR_REGEX = 15

EXTRACT_REGEX_PROMPT = (
    "You are a regex generator. Given sample values from a data field and "
    "a user description of what to extract, return ONLY a Python-compatible "
    "regular expression with a single named capture group (?P<result>...). "
    "No explanation, no markdown, no code fences. ONLY the raw regex string."
)

EXTRACT_DICT_PROMPT = (
    "You are a data extraction engine. Given a list of field values and a "
    "description of what to extract from each, return ONLY a JSON object "
    "mapping each input value to its extracted result. "
    "No explanation, no markdown fences. ONLY valid JSON."
)


def _try_regex_extract(regex_str, rows, field_name):
    # type: (str, list, str) -> tuple
    """Apply a regex to all rows. Returns (results_dict, match_rate)."""
    clean = regex_str.strip().strip('"').strip("'")
    # Remove markdown fences if LLM wrapped it
    if clean.startswith("```"):
        # Handle ```regex\n...\n``` or ```\n...\n```
        inner = clean[3:]
        if inner.startswith("\n"):
            inner = inner[1:]
        elif "\n" in inner:
            inner = inner.split("\n", 1)[1]
        clean = inner.rsplit("```", 1)[0].strip()
    # Strip stray backticks
    clean = clean.strip('`')

    try:
        pattern = re.compile(clean)
    except re.error:
        return {}, 0.0

    results = {}  # type: dict
    matched = 0
    total = 0
    for row in rows:
        val = str(row.get(field_name, ""))
        if not val:
            continue
        total += 1
        m = pattern.search(val)
        if m:
            try:
                results[val] = m.group("result")
                matched += 1
            except IndexError:
                # No named group — try group(1)
                if m.lastindex and m.lastindex >= 1:
                    results[val] = m.group(1)
                    matched += 1

    rate = matched / total if total > 0 else 0.0
    return results, rate


def _apply_dict_extract(mapping, rows, field_name):
    # type: (dict, list, str) -> dict
    """Apply a dict mapping to rows. Returns val->extracted dict."""
    results = {}
    for row in rows:
        val = str(row.get(field_name, ""))
        if val in mapping:
            results[val] = mapping[val]
    return results


def _extract_field(rows, field_name, new_field, regex_response, dict_response):
    # type: (list, str, str, str, str) -> list
    """Full extract pipeline: try regex first, fall back to dict.
    Returns rows with new_field added.
    """
    # Strategy 1: Regex
    results, rate = _try_regex_extract(regex_response, rows, field_name)
    source = "regex"

    # Fall back to dict if regex failed or low match rate
    if rate < 0.5:
        try:
            clean = dict_response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            mapping = json.loads(clean)
            results = _apply_dict_extract(mapping, rows, field_name)
            source = "dict"
        except (json.JSONDecodeError, ValueError):
            source = "error"

    # Apply results to rows
    for row in rows:
        val = str(row.get(field_name, ""))
        row[new_field] = results.get(val, "")
        row["aiguy_extract_method"] = source

    return rows


# ── Tests ────────────────────────────────────────────────────────────────────

class TestRegexExtract:
    """Test the regex approach with realistic LLM regex responses."""

    def test_email_domain(self):
        regex = r"(?P<result>(?<=@)[\w.-]+)"
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 1.0
        assert results["john.smith@acme.com"] == "acme.com"
        assert results["admin@internal.corp.net"] == "internal.corp.net"
        assert results["alice@yahoo.co.uk"] == "yahoo.co.uk"
        assert results["root@localhost"] == "localhost"

    def test_email_username(self):
        regex = r"(?P<result>^[^@]+)"
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 1.0
        assert results["john.smith@acme.com"] == "john.smith"
        assert results["admin@internal.corp.net"] == "admin"

    def test_ip_first_octet(self):
        regex = r"(?P<result>^\d+)"
        results, rate = _try_regex_extract(regex, IP_ROWS, "src_ip")
        assert rate == 1.0
        assert results["192.168.1.100"] == "192"
        assert results["10.50.30.22"] == "10"

    def test_ip_subnet(self):
        regex = r"(?P<result>^\d+\.\d+\.\d+)"
        results, rate = _try_regex_extract(regex, IP_ROWS, "src_ip")
        assert rate == 1.0
        assert results["192.168.1.100"] == "192.168.1"

    def test_log_status_code(self):
        regex = r"status=(?P<result>\d+)"
        results, rate = _try_regex_extract(regex, LOG_ROWS, "_raw")
        assert rate == 1.0
        assert results[LOG_ROWS[0]["_raw"]] == "200"
        assert results[LOG_ROWS[1]["_raw"]] == "500"

    def test_log_duration(self):
        regex = r"duration=(?P<result>\d+)ms"
        results, rate = _try_regex_extract(regex, LOG_ROWS, "_raw")
        assert rate == 1.0
        assert results[LOG_ROWS[0]["_raw"]] == "45"
        assert results[LOG_ROWS[1]["_raw"]] == "1203"

    def test_log_server(self):
        regex = r"server=(?P<result>\w+)"
        results, rate = _try_regex_extract(regex, LOG_ROWS, "_raw")
        assert rate == 1.0
        assert results[LOG_ROWS[0]["_raw"]] == "web01"
        assert results[LOG_ROWS[1]["_raw"]] == "web02"

    def test_first_letter(self):
        regex = r"(?P<result>^.)"
        results, rate = _try_regex_extract(regex, NAME_ROWS, "full_name")
        assert rate == 1.0
        assert results["John Smith"] == "J"
        assert results["Bob"] == "B"
        assert results["Dr. Robert Brown Jr."] == "D"

    def test_first_word(self):
        regex = r"(?P<result>^\w+)"
        results, rate = _try_regex_extract(regex, NAME_ROWS, "full_name")
        assert rate == 1.0
        assert results["John Smith"] == "John"
        assert results["Alice Marie Johnson"] == "Alice"
        assert results["Dr. Robert Brown Jr."] == "Dr"

    def test_url_path(self):
        regex = r"https?://[^/]+(?P<result>/[^?]*)"
        results, rate = _try_regex_extract(regex, URL_ROWS, "url")
        assert rate == 1.0
        assert results[URL_ROWS[0]["url"]] == "/api/v2/users"
        assert results[URL_ROWS[2]["url"]] == "/login.jsp"

    def test_url_domain(self):
        regex = r"https?://(?P<result>[^/:]+)"
        results, rate = _try_regex_extract(regex, URL_ROWS, "url")
        assert rate == 1.0
        assert results[URL_ROWS[0]["url"]] == "www.example.com"
        assert results[URL_ROWS[2]["url"]] == "legacy-app"

    def test_bad_regex_returns_zero_rate(self):
        regex = r"(?P<result>[[[invalid"
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 0.0
        assert results == {}

    def test_non_matching_regex_low_rate(self):
        regex = r"(?P<result>ZZZNOMATCH)"
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 0.0

    def test_markdown_wrapped_regex(self):
        regex = "```\n(?P<result>(?<=@)[\\w.-]+)\n```"
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 1.0
        assert results["bob@gmail.com"] == "gmail.com"

    def test_quoted_regex(self):
        regex = '"(?P<result>(?<=@)[\\w.-]+)"'
        results, rate = _try_regex_extract(regex, EMAIL_ROWS, "user")
        assert rate == 1.0


class TestDictExtract:
    """Test the dict mapping approach."""

    def test_email_domain_dict(self):
        mapping = {
            "john.smith@acme.com": "acme.com",
            "jane.doe@acme.com": "acme.com",
            "admin@internal.corp.net": "internal.corp.net",
            "bob@gmail.com": "gmail.com",
            "alice@yahoo.co.uk": "yahoo.co.uk",
            "svc-monitor@acme.com": "acme.com",
            "root@localhost": "localhost",
            "noreply@notifications.acme.com": "notifications.acme.com",
        }
        results = _apply_dict_extract(mapping, EMAIL_ROWS, "user")
        assert len(results) == 8
        assert results["admin@internal.corp.net"] == "internal.corp.net"

    def test_first_name_semantic(self):
        """Dict handles semantic extraction that regex can't."""
        mapping = {
            "John Smith": "John",
            "Jane Doe": "Jane",
            "Bob": "Bob",
            "Alice Marie Johnson": "Alice",
            "Dr. Robert Brown Jr.": "Robert",  # Skips title — regex can't do this
        }
        results = _apply_dict_extract(mapping, NAME_ROWS, "full_name")
        assert results["Dr. Robert Brown Jr."] == "Robert"

    def test_missing_values_get_empty(self):
        mapping = {"john.smith@acme.com": "acme.com"}
        results = _apply_dict_extract(mapping, EMAIL_ROWS, "user")
        assert len(results) == 1  # only 1 matched
        assert "bob@gmail.com" not in results


def _clean_llm_response(raw):
    """Strip markdown fences, quotes, and whitespace from LLM output."""
    clean = raw.strip().strip('"').strip("'")
    if clean.startswith("```"):
        inner = clean[3:]
        if inner.startswith("\n"):
            inner = inner[1:]
        elif "\n" in inner:
            inner = inner.split("\n", 1)[1]
        clean = inner.rsplit("```", 1)[0].strip()
    return clean.strip("`")


def _parse_regex_response(raw):
    """Parse LLM regex response. Returns (regex_str, suggested_field_name)."""
    clean = _clean_llm_response(raw)
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            return (str(obj.get("regex", "")), str(obj.get("field_name", "")))
    except (json.JSONDecodeError, ValueError):
        pass
    return clean, ""


def _parse_dict_response(raw):
    """Parse LLM dict response. Returns (mapping_dict, suggested_field_name)."""
    clean = _clean_llm_response(raw)
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            field_name = str(obj.get("field_name", ""))
            mapping = obj.get("mapping", obj)
            if "mapping" in obj and isinstance(mapping, dict):
                return mapping, field_name
            mapping_copy = dict(obj)
            mapping_copy.pop("field_name", None)
            return mapping_copy, field_name
    except (json.JSONDecodeError, ValueError):
        pass
    return {}, ""


class TestResponseParsing:
    """Test parsing of JSON responses with field_name."""

    def test_parse_regex_json(self):
        raw = '{"regex": "(?P<result>(?<=@)[\\\\w.-]+)", "field_name": "domain"}'
        regex, name = _parse_regex_response(raw)
        assert "result" in regex
        assert name == "domain"

    def test_parse_regex_json_markdown_wrapped(self):
        raw = '```json\n{"regex": "(?P<result>\\\\d+)", "field_name": "count"}\n```'
        regex, name = _parse_regex_response(raw)
        assert name == "count"

    def test_parse_regex_fallback_raw(self):
        """If LLM returns raw regex (not JSON), fall back gracefully."""
        raw = "(?P<result>(?<=@)[\\w.-]+)"
        regex, name = _parse_regex_response(raw)
        assert "result" in regex
        assert name == ""  # no field name from raw regex

    def test_parse_dict_json(self):
        raw = json.dumps({
            "field_name": "first_name",
            "mapping": {"John Smith": "John", "Jane Doe": "Jane"},
        })
        mapping, name = _parse_dict_response(raw)
        assert name == "first_name"
        assert mapping["John Smith"] == "John"

    def test_parse_dict_legacy_format(self):
        """If LLM returns flat dict (no field_name/mapping keys), still works."""
        raw = json.dumps({"John Smith": "John", "Jane Doe": "Jane"})
        mapping, name = _parse_dict_response(raw)
        assert name == ""
        assert mapping["John Smith"] == "John"


class TestFullPipeline:
    """Test the full extract pipeline: regex first, dict fallback."""

    def test_regex_wins_when_good(self):
        regex_resp = r"(?P<result>(?<=@)[\w.-]+)"
        dict_resp = '{"john.smith@acme.com": "acme.com"}'
        rows = [dict(r) for r in EMAIL_ROWS]
        result = _extract_field(rows, "user", "domain", regex_resp, dict_resp)
        assert result[0]["domain"] == "acme.com"
        assert result[0]["aiguy_extract_method"] == "regex"

    def test_dict_fallback_on_bad_regex(self):
        regex_resp = "(?P<result>[[[invalid"
        dict_resp = json.dumps({
            "john.smith@acme.com": "acme.com",
            "jane.doe@acme.com": "acme.com",
            "admin@internal.corp.net": "internal.corp.net",
            "bob@gmail.com": "gmail.com",
            "alice@yahoo.co.uk": "yahoo.co.uk",
            "svc-monitor@acme.com": "acme.com",
            "root@localhost": "localhost",
            "noreply@notifications.acme.com": "notifications.acme.com",
        })
        rows = [dict(r) for r in EMAIL_ROWS]
        result = _extract_field(rows, "user", "domain", regex_resp, dict_resp)
        assert result[0]["domain"] == "acme.com"
        assert result[0]["aiguy_extract_method"] == "dict"

    def test_dict_fallback_on_low_match_rate(self):
        regex_resp = r"(?P<result>ZZZNOMATCH)"  # matches nothing
        dict_resp = json.dumps({
            "John Smith": "John",
            "Jane Doe": "Jane",
            "Bob": "Bob",
            "Alice Marie Johnson": "Alice",
            "Dr. Robert Brown Jr.": "Robert",
        })
        rows = [dict(r) for r in NAME_ROWS]
        result = _extract_field(rows, "full_name", "first_name", regex_resp, dict_resp)
        assert result[0]["first_name"] == "John"
        assert result[0]["aiguy_extract_method"] == "dict"

    def test_both_fail_gracefully(self):
        regex_resp = "(?P<result>[[[invalid"
        dict_resp = "not valid json at all"
        rows = [dict(r) for r in EMAIL_ROWS]
        result = _extract_field(rows, "user", "domain", regex_resp, dict_resp)
        assert result[0]["domain"] == ""
        assert result[0]["aiguy_extract_method"] == "error"

    def test_new_field_added_to_all_rows(self):
        regex_resp = r"status=(?P<result>\d+)"
        dict_resp = "{}"
        rows = [dict(r) for r in LOG_ROWS]
        result = _extract_field(rows, "_raw", "http_status", regex_resp, dict_resp)
        assert all("http_status" in r for r in result)
        assert result[0]["http_status"] == "200"
        assert result[1]["http_status"] == "500"
        assert result[4]["http_status"] == "503"

    def test_duplicate_values_handled(self):
        """Rows with same value get same extraction."""
        regex_resp = r"(?P<result>^\d+\.\d+\.\d+)"
        dict_resp = "{}"
        rows = [dict(r) for r in IP_ROWS]
        result = _extract_field(rows, "src_ip", "subnet", regex_resp, dict_resp)
        assert result[0]["subnet"] == "192.168.1"
        assert result[3]["subnet"] == "192.168.1"
        assert result[2]["subnet"] == "10.50.30"
        assert result[4]["subnet"] == "10.50.30"
