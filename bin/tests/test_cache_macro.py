# -*- coding: utf-8 -*-
"""Tests for cache macro parsing, validation, and lookup swapping."""
from __future__ import annotations

import os
import sys

# Ensure bin/ is on the path
_bin_dir = os.path.join(os.path.dirname(__file__), "..")
if _bin_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_bin_dir))

import pytest
from spl.spl_analyzer import parse_cache_macros, check_cache_macros
from spl.query_injector import _swap_cache_lookups


# ═══════════════════════════════════════════════════════════════════════════════
# parse_cache_macros
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseCacheMacros:
    """Verify argument extraction from various cache macro formats."""

    def test_basic_testing_true(self):
        spl = '`cache(my_lookup, "id_field", "prop_field", "stack_field", true, 3600)`'
        result = parse_cache_macros(spl)
        assert len(result) == 1
        assert result[0]["lookup_name"] == "my_lookup"
        assert result[0]["is_testing"] is True

    def test_testing_false(self):
        spl = '`cache(my_lookup, "id_field", "prop_field", "stack_field", false, 3600)`'
        result = parse_cache_macros(spl)
        assert len(result) == 1
        assert result[0]["is_testing"] is False

    def test_testing_True_capitalized(self):
        spl = '`cache(my_lookup, id, prop, stack, True, 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is True

    def test_testing_true_quoted_double(self):
        spl = '`cache(my_lookup, id, prop, stack, "true", 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is True

    def test_testing_true_quoted_single(self):
        spl = "`cache(my_lookup, id, prop, stack, 'true', 3600)`"
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is True

    def test_testing_True_quoted(self):
        spl = '`cache(my_lookup, id, prop, stack, "True", 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is True

    def test_testing_1(self):
        spl = '`cache(my_lookup, id, prop, stack, 1, 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is True

    def test_testing_FALSE(self):
        """'FALSE' (uppercase) is not in the true set."""
        spl = '`cache(my_lookup, id, prop, stack, FALSE, 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is False

    def test_testing_0(self):
        spl = '`cache(my_lookup, id, prop, stack, 0, 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is False

    def test_testing_empty_string(self):
        spl = '`cache(my_lookup, id, prop, stack, "", 3600)`'
        result = parse_cache_macros(spl)
        assert result[0]["is_testing"] is False

    def test_multiple_id_fields_quoted(self):
        spl = '`cache(my_lookup, "id1 id2 id3", "prop1 prop2", "stack1", true, 7200)`'
        result = parse_cache_macros(spl)
        assert len(result) == 1
        assert result[0]["lookup_name"] == "my_lookup"
        assert result[0]["is_testing"] is True
        assert result[0]["args"][1] == "id1 id2 id3"

    def test_no_cache_macro(self):
        spl = "index=main sourcetype=access | stats count by src_ip"
        result = parse_cache_macros(spl)
        assert len(result) == 0

    def test_multiple_cache_macros(self):
        spl = (
            '| `cache(lookup_a, id, prop, stack, true, 3600)` '
            '| `cache(lookup_b, id, prop, stack, false, 7200)`'
        )
        result = parse_cache_macros(spl)
        assert len(result) == 2
        assert result[0]["lookup_name"] == "lookup_a"
        assert result[0]["is_testing"] is True
        assert result[1]["lookup_name"] == "lookup_b"
        assert result[1]["is_testing"] is False

    def test_too_few_args(self):
        spl = '`cache(my_lookup, id, prop)`'
        result = parse_cache_macros(spl)
        assert len(result) == 1
        assert result[0]["lookup_name"] == "my_lookup"
        assert result[0]["is_testing"] is False  # not enough args

    def test_spaces_around_args(self):
        spl = '`cache(  my_lookup ,  id_field , prop_field , stack_field ,  true  , 3600 )`'
        result = parse_cache_macros(spl)
        assert result[0]["lookup_name"] == "my_lookup"
        assert result[0]["is_testing"] is True

    def test_cache_in_middle_of_spl(self):
        spl = 'index=main | stats count by src_ip | `cache(ip_cache, "src_ip", "count", "", false, 86400)` | table src_ip count'
        result = parse_cache_macros(spl)
        assert len(result) == 1
        assert result[0]["lookup_name"] == "ip_cache"
        assert result[0]["is_testing"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# check_cache_macros (warnings)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckCacheMacros:
    """Verify warning messages for cache macro usage."""

    def test_testing_true_note(self):
        spl = '`cache(my_lookup, id, prop, stack, true, 3600)`'
        warnings = check_cache_macros(spl)
        assert len(warnings) == 1
        assert "safe to run" in warnings[0]
        assert "testing=false" in warnings[0]

    def test_testing_false_warns_swap(self):
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)`'
        warnings = check_cache_macros(spl)
        assert len(warnings) == 1
        assert "temporary lookup" in warnings[0]
        assert "persists" in warnings[0]
        assert "my_lookup" in warnings[0]

    def test_too_few_args_warns(self):
        spl = '`cache(my_lookup, id)`'
        warnings = check_cache_macros(spl)
        assert len(warnings) == 1
        assert "5 arguments" in warnings[0]

    def test_mixed_testing_values(self):
        spl = (
            '| `cache(a, id, prop, stack, true, 3600)` '
            '| `cache(b, id, prop, stack, false, 7200)`'
        )
        warnings = check_cache_macros(spl)
        assert len(warnings) == 2  # one note for true, one warning for false
        assert any("safe to run" in w for w in warnings)
        assert any("temporary lookup" in w and "b" in w for w in warnings)

    def test_no_cache_no_warnings(self):
        spl = "index=main | stats count"
        assert check_cache_macros(spl) == []


# ═══════════════════════════════════════════════════════════════════════════════
# _swap_cache_lookups (injection)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSwapCacheLookups:
    """Verify lookup name replacement in non-testing cache macros."""

    def test_false_gets_swapped(self):
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "abc123")
        assert "temp_cache_abc123_my_lookup" in result
        assert result.startswith("`cache(temp_cache_abc123_my_lookup,")

    def test_true_not_swapped(self):
        spl = '`cache(my_lookup, id, prop, stack, true, 3600)`'
        result = _swap_cache_lookups(spl, "abc123")
        assert result == spl  # unchanged

    def test_mixed_only_false_swapped(self):
        spl = (
            '| `cache(safe_lookup, id, prop, stack, true, 3600)` '
            '| `cache(real_lookup, id, prop, stack, false, 7200)`'
        )
        result = _swap_cache_lookups(spl, "x1")
        assert "safe_lookup" in result  # true — untouched
        assert "temp_cache_x1_real_lookup" in result  # false — swapped
        assert "`cache(safe_lookup," in result

    def test_no_cache_unchanged(self):
        spl = "index=main | stats count by src_ip"
        result = _swap_cache_lookups(spl, "abc")
        assert result == spl

    def test_quoted_fields_preserved(self):
        spl = '`cache(my_lookup, "id1 id2", "prop1 prop2", "stack1", false, 3600)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result
        # Verify other args are preserved
        assert "id1 id2" in result
        assert "prop1 prop2" in result
        assert "stack1" in result

    def test_spaces_preserved(self):
        spl = '`cache(  my_lookup , id , prop , stack , false , 3600 )`'
        result = _swap_cache_lookups(spl, "r2")
        assert "temp_cache_r2_my_lookup" in result

    def test_multiple_false_all_swapped(self):
        spl = (
            '| `cache(lookup_a, id, prop, stack, false, 3600)` '
            '| `cache(lookup_b, id, prop, stack, false, 7200)`'
        )
        result = _swap_cache_lookups(spl, "run1")
        assert "temp_cache_run1_lookup_a" in result
        assert "temp_cache_run1_lookup_b" in result

    def test_too_few_args_not_swapped(self):
        spl = '`cache(my_lookup, id, prop)`'
        result = _swap_cache_lookups(spl, "abc")
        assert result == spl  # malformed — skip

    def test_testing_True_capitalized_not_swapped(self):
        spl = '`cache(my_lookup, id, prop, stack, True, 3600)`'
        result = _swap_cache_lookups(spl, "abc")
        assert result == spl

    def test_testing_1_not_swapped(self):
        spl = '`cache(my_lookup, id, prop, stack, 1, 3600)`'
        result = _swap_cache_lookups(spl, "abc")
        assert result == spl

    def test_testing_quoted_true_not_swapped(self):
        spl = '`cache(my_lookup, id, prop, stack, "true", 3600)`'
        result = _swap_cache_lookups(spl, "abc")
        assert result == spl

    def test_in_full_spl_context(self):
        spl = (
            'index=firewall sourcetype=cisco:asa '
            '| stats count by src_ip dest_ip '
            '| `cache(ip_reputation, "src_ip dest_ip", "count", "", false, 86400)` '
            '| where count > 10'
        )
        result = _swap_cache_lookups(spl, "run99")
        assert "temp_cache_run99_ip_reputation" in result
        # Rest of SPL untouched
        assert "index=firewall" in result
        assert "stats count by src_ip dest_ip" in result
        assert "where count > 10" in result

    def test_0_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, 0, 3600)`'
        result = _swap_cache_lookups(spl, "abc")
        assert "temp_cache_abc_my_lookup" in result

    def test_empty_testing_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, "", 3600)`'
        result = _swap_cache_lookups(spl, "abc")
        assert "temp_cache_abc_my_lookup" in result

    # ── test_id (manual vs scheduled) ────────────────────────────────────

    def test_manual_run_uses_test_id(self):
        """Manual run: stable name from test_id, not run_id."""
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "run123", test_id="abcdefgh-1234-5678")
        assert "temp_cache_abcdefgh_my_lookup" in result  # first 8 chars of test_id
        assert "run123" not in result

    def test_scheduled_run_uses_run_id(self):
        """Scheduled run (no test_id): per-run name from run_id."""
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "run456", test_id=None)
        assert "temp_cache_run456_my_lookup" in result

    def test_manual_run_stable_across_calls(self):
        """Same test_id produces same temp name on repeated calls."""
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)`'
        r1 = _swap_cache_lookups(spl, "run1", test_id="test-uuid-1234")
        r2 = _swap_cache_lookups(spl, "run2", test_id="test-uuid-1234")
        assert r1 == r2  # same temp name regardless of run_id

    def test_testing_true_ignores_test_id(self):
        """testing=true macros are never swapped, even with test_id."""
        spl = '`cache(my_lookup, id, prop, stack, true, 3600)`'
        result = _swap_cache_lookups(spl, "run1", test_id="test-id")
        assert result == spl


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases — special characters, quoting, delimiters
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Stress-test parsing and swapping with tricky inputs."""

    # ── Empty strings / empty quotes ──────────────────────────────────────

    def test_empty_double_quotes_in_fields(self):
        """Fields can be empty strings in double quotes."""
        spl = '`cache(my_lookup, "", "", "", false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert parsed[0]["args"][1] == ""
        assert parsed[0]["args"][2] == ""
        assert parsed[0]["args"][3] == ""
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_empty_single_quotes_in_fields(self):
        spl = "`cache(my_lookup, '', '', '', false, 3600)`"
        parsed = parse_cache_macros(spl)
        assert parsed[0]["args"][1] == ""
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_all_empty_quote_args(self):
        spl = '`cache("", "", "", "", "", "")`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == ""
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_" in result

    # ── Underscores and special naming ────────────────────────────────────

    def test_lookup_with_underscores(self):
        spl = '`cache(my_big_lookup_v2, id_field, prop_field, stack_field, false, 3600)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_big_lookup_v2" in result

    def test_lookup_with_hyphens(self):
        spl = '`cache(my-lookup-name, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my-lookup-name" in result

    def test_lookup_with_dots(self):
        spl = '`cache(lookup.name.csv, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_lookup.name.csv" in result

    # ── Multiple fields with spaces inside quotes ─────────────────────────

    def test_multi_word_fields_double_quoted(self):
        spl = '`cache(my_lookup, "src_ip dest_ip host", "count bytes", "category type", false, 7200)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["args"][1] == "src_ip dest_ip host"
        assert parsed[0]["args"][2] == "count bytes"
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result
        assert "src_ip dest_ip host" in result

    def test_multi_word_fields_single_quoted(self):
        spl = "`cache(my_lookup, 'src_ip dest_ip', 'count', 'cat', false, 3600)`"
        parsed = parse_cache_macros(spl)
        assert parsed[0]["args"][1] == "src_ip dest_ip"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    # ── Commas inside quoted args (tricky — commas split args) ────────────

    def test_comma_in_double_quoted_field_splits(self):
        """Commas inside quotes still split args (regex doesn't parse nested quotes).
        This is a known limitation — document it, don't crash."""
        spl = '`cache(my_lookup, "id1,id2", prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        # The comma inside quotes causes an extra split
        assert len(parsed) == 1
        # It'll have 7 args instead of 6 because of the comma in "id1,id2"
        assert len(parsed[0]["args"]) == 7

    # ── Case sensitivity of testing value ─────────────────────────────────

    def test_testing_TRUE_uppercase_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, TRUE, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["is_testing"] is False  # only "true", "True", "1"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_testing_tRuE_mixed_case_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, tRuE, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_testing_False_capitalized_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, False, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["is_testing"] is False

    def test_testing_yes_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, yes, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["is_testing"] is False

    def test_testing_no_is_false(self):
        spl = '`cache(my_lookup, id, prop, stack, no, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["is_testing"] is False

    # ── Whitespace variations ─────────────────────────────────────────────

    def test_tabs_in_args(self):
        spl = '`cache(\tmy_lookup\t,\tid\t,\tprop\t,\tstack\t,\tfalse\t,\t3600\t)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my_lookup"
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_newlines_in_args(self):
        spl = '`cache(\nmy_lookup,\nid,\nprop,\nstack,\nfalse,\n3600\n)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my_lookup"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_no_spaces_at_all(self):
        spl = '`cache(my_lookup,id,prop,stack,false,3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my_lookup"
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_excessive_spaces(self):
        spl = '`cache(   my_lookup   ,   id   ,   prop   ,   stack   ,   true   ,   3600   )`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my_lookup"
        assert parsed[0]["is_testing"] is True
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl  # true — no swap

    # ── Vanish time variations ────────────────────────────────────────────

    def test_vanish_time_zero(self):
        spl = '`cache(my_lookup, id, prop, stack, false, 0)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_vanish_time_large(self):
        spl = '`cache(my_lookup, id, prop, stack, false, 999999)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_vanish_time_quoted(self):
        spl = '`cache(my_lookup, id, prop, stack, false, "3600")`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    # ── Multiple cache macros in complex SPL ──────────────────────────────

    def test_three_macros_mixed(self):
        spl = (
            'index=main | stats count by src_ip '
            '| `cache(lookup_a, "src_ip", "count", "", true, 3600)` '
            '| `cache(lookup_b, "src_ip", "count", "", false, 7200)` '
            '| `cache(lookup_c, src_ip, count, "", True, 86400)`'
        )
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 3
        assert parsed[0]["is_testing"] is True
        assert parsed[1]["is_testing"] is False
        assert parsed[2]["is_testing"] is True

        result = _swap_cache_lookups(spl, "x1")
        assert "lookup_a" in result  # true — kept
        assert "temp_cache_x1_lookup_b" in result  # false — swapped
        assert "lookup_c" in result  # True — kept
        assert "temp_cache_x1_lookup_a" not in result
        assert "temp_cache_x1_lookup_c" not in result

    def test_cache_inside_subsearch(self):
        spl = (
            'index=main [search index=threat '
            '| `cache(threat_intel, "ip", "score", "", false, 3600)` '
            '| fields ip] | stats count by src_ip'
        )
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert parsed[0]["lookup_name"] == "threat_intel"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_threat_intel" in result
        assert "index=main [search index=threat" in result

    # ── Not a cache macro (false positives) ───────────────────────────────

    def test_cache_word_in_spl_not_macro(self):
        """The word 'cache' in normal SPL should not be parsed as a macro."""
        spl = 'index=main sourcetype=cache_logs | stats count'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 0

    def test_backtick_comment_with_cache(self):
        """A Splunk comment containing cache should not trigger."""
        spl = '```This uses cache for performance``` index=main | stats count'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 0

    def test_cache_without_backticks(self):
        """cache(...) without backticks is not a macro call."""
        spl = 'cache(my_lookup, id, prop, stack, false, 3600)'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 0

    # ── Exactly 5 args (missing vanish_time) ──────────────────────────────

    def test_five_args_missing_vanish(self):
        """5 args (no vanish) — valid, should NOT produce a warning."""
        spl = '`cache(my_lookup, id, prop, stack, false)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert len(parsed[0]["args"]) == 5
        warnings = check_cache_macros(spl)
        # vanish is optional — 5 args is valid
        assert not any("arguments" in w for w in warnings)

    # ── Exactly 7+ args (extra args) ──────────────────────────────────────

    def test_seven_args_extra(self):
        """Extra args beyond 6 — should still work, testing is at index 4."""
        spl = '`cache(my_lookup, id, prop, stack, false, 3600, extra_arg)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 7
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        # 7 args >= 6, so swap happens
        assert "temp_cache_r1_my_lookup" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Malformed / garbage / typo inputs — must never attempt temp lookup creation
# ═══════════════════════════════════════════════════════════════════════════════

class TestMalformedCacheMacros:
    """Ensure garbage or incomplete cache calls are safely ignored."""

    def test_single_garbage_arg(self):
        """cache(sijfshjsh) — single garbage arg, no commas."""
        spl = '`cache(sijfshjsh)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert len(parsed[0]["args"]) == 1
        assert parsed[0]["is_testing"] is False
        # Should NOT swap — too few args
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_empty_cache(self):
        spl = '`cache()`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert len(parsed[0]["args"]) == 1
        assert parsed[0]["args"][0] == ""
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_just_lookup_name(self):
        spl = '`cache(my_lookup)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 1
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_two_args_only(self):
        spl = '`cache(my_lookup, some_field)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 2
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_three_args_only(self):
        spl = '`cache(my_lookup, id, prop)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 3
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_four_args_only(self):
        spl = '`cache(my_lookup, id, prop, stack)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 4
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl

    def test_five_args_no_vanish(self):
        """5 args — vanish_time optional. Should swap (testing=false)."""
        spl = '`cache(my_lookup, id, prop, stack, false)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 5
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup" in result

    def test_random_text_as_args(self):
        spl = '`cache(asdf, qwer, zxcv, poiu, lkjh, mnbv)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed[0]["args"]) == 6
        assert parsed[0]["lookup_name"] == "asdf"
        # testing="lkjh" is not true → swap happens
        assert parsed[0]["is_testing"] is False
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_asdf" in result

    def test_numbers_as_lookup_name(self):
        spl = '`cache(12345, id, prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "12345"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_12345" in result

    def test_spaces_only_in_args(self):
        spl = '`cache(   ,   ,   ,   ,   ,   )`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == ""
        assert parsed[0]["is_testing"] is False
        # 6 args but empty lookup name — swap still happens (produces temp_cache_r1_)
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_" in result

    def test_mixed_valid_and_garbage(self):
        """One valid cache + one garbage cache in same SPL."""
        spl = (
            '| `cache(real_lookup, id, prop, stack, false, 3600)` '
            '| `cache(garbage)`'
        )
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 2
        result = _swap_cache_lookups(spl, "r1")
        # Valid one gets swapped
        assert "temp_cache_r1_real_lookup" in result
        # Garbage one left as-is
        assert "`cache(garbage)`" in result

    def test_nested_parentheses_no_match(self):
        """Nested parens — regex [^)]* stops at the first ), so no valid match found.
        This is safe: the macro is silently ignored (no swap, no crash)."""
        spl = '`cache(my_lookup, eval(if(x>1, 1, 0)), prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 0  # no match — safe
        result = _swap_cache_lookups(spl, "r1")
        assert result == spl  # unchanged

    def test_special_chars_in_lookup_name(self):
        spl = '`cache(my@lookup!, id, prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my@lookup!"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my@lookup!" in result

    def test_unicode_in_args(self):
        spl = '`cache(lookup_\u00e9, id, prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "lookup_\u00e9"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_lookup_\u00e9" in result

    def test_warning_for_malformed(self):
        """Malformed cache calls should produce a warning about missing args."""
        spl = '`cache(sijfshjsh)`'
        warnings = check_cache_macros(spl)
        assert len(warnings) == 1
        assert "5 arguments" in warnings[0]
        assert "Found 1" in warnings[0]

    def test_warning_for_empty_cache(self):
        spl = '`cache()`'
        warnings = check_cache_macros(spl)
        assert len(warnings) == 1
        assert "5 arguments" in warnings[0]

    def test_no_warning_for_non_cache(self):
        """Normal SPL with no cache macro produces no cache warnings."""
        spl = 'index=main | lookup my_lookup src_ip OUTPUT threat_score'
        warnings = check_cache_macros(spl)
        assert warnings == []
        parsed = parse_cache_macros(spl)
        assert parsed == []

    def test_lookup_name_with_csv_extension(self):
        spl = '`cache(my_lookup.csv, id, prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == "my_lookup.csv"
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_my_lookup.csv" in result

    def test_backtick_inside_spl_comment(self):
        """Splunk triple-backtick comment should not interfere."""
        spl = '```this is a comment``` | stats count | `cache(real, id, prop, stack, false, 60)`'
        parsed = parse_cache_macros(spl)
        assert len(parsed) == 1
        assert parsed[0]["lookup_name"] == "real"

    def test_two_caches_same_lookup_different_testing(self):
        """Same lookup used twice: once testing=true, once false."""
        spl = (
            '| `cache(shared_lookup, id, prop, stack, true, 3600)` '
            '| `cache(shared_lookup, id, prop, stack, false, 3600)`'
        )
        result = _swap_cache_lookups(spl, "r1")
        # First (true) stays, second (false) gets swapped
        assert '`cache(shared_lookup,' in result
        assert 'temp_cache_r1_shared_lookup' in result

    def test_cache_at_very_start_of_spl(self):
        spl = '`cache(my_lookup, id, prop, stack, false, 3600)` | stats count'
        result = _swap_cache_lookups(spl, "r1")
        assert result.startswith('`cache(temp_cache_r1_my_lookup,')

    def test_cache_at_very_end_of_spl(self):
        spl = 'index=main | stats count | `cache(my_lookup, id, prop, stack, false, 3600)`'
        result = _swap_cache_lookups(spl, "r1")
        assert result.endswith('`cache(temp_cache_r1_my_lookup,id,prop,stack,false,3600)`')

    def test_only_whitespace_lookup_name(self):
        spl = '`cache(   , id, prop, stack, false, 3600)`'
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == ""
        # Empty name after strip — swap produces temp_cache_r1_
        result = _swap_cache_lookups(spl, "r1")
        # The swap still runs but with empty original name
        assert "temp_cache_r1_" in result

    def test_very_long_lookup_name(self):
        name = "a" * 200
        spl = '`cache({0}, id, prop, stack, false, 3600)`'.format(name)
        parsed = parse_cache_macros(spl)
        assert parsed[0]["lookup_name"] == name
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_" + name in result

    def test_pipe_before_cache(self):
        """Cache with explicit pipe before it."""
        spl = 'index=main | stats count by src_ip | `cache(ip_cache, src_ip, count, "", false, 86400)`'
        result = _swap_cache_lookups(spl, "r1")
        assert "temp_cache_r1_ip_cache" in result
        assert "stats count by src_ip" in result
