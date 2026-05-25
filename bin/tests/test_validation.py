# -*- coding: utf-8 -*-
"""Comprehensive tests for the validation system: all operators, scopes, edge cases."""
from __future__ import annotations

import os
import sys

_bin_dir = os.path.join(os.path.dirname(__file__), "..")
if _bin_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_bin_dir))

import pytest
from validation.condition_handlers import CONDITION_HANDLERS, COUNT_OPS


# ═══════════════════════════════════════════════════════════════════════════════
# Equality operators
# ═══════════════════════════════════════════════════════════════════════════════

class TestEquals:
    def test_exact_match(self):
        assert CONDITION_HANDLERS["equals"]("hello", "hello") is True

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["equals"]("Hello", "hello") is True
        assert CONDITION_HANDLERS["equals"]("HELLO", "hello") is True

    def test_whitespace_trimmed(self):
        assert CONDITION_HANDLERS["equals"]("  hello  ", "hello") is True

    def test_mismatch(self):
        assert CONDITION_HANDLERS["equals"]("hello", "world") is False

    def test_empty_strings(self):
        assert CONDITION_HANDLERS["equals"]("", "") is True

    def test_numbers_as_strings(self):
        assert CONDITION_HANDLERS["equals"]("42", "42") is True
        assert CONDITION_HANDLERS["equals"]("42", "43") is False


class TestNotEquals:
    def test_different(self):
        assert CONDITION_HANDLERS["not_equals"]("hello", "world") is True

    def test_same(self):
        assert CONDITION_HANDLERS["not_equals"]("hello", "hello") is False

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["not_equals"]("Hello", "hello") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Text operators
# ═══════════════════════════════════════════════════════════════════════════════

class TestContains:
    def test_substring(self):
        assert CONDITION_HANDLERS["contains"]("hello world", "world") is True

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["contains"]("Hello World", "hello") is True

    def test_full_match(self):
        assert CONDITION_HANDLERS["contains"]("hello", "hello") is True

    def test_not_found(self):
        assert CONDITION_HANDLERS["contains"]("hello", "xyz") is False

    def test_empty_expected(self):
        assert CONDITION_HANDLERS["contains"]("hello", "") is True


class TestNotContains:
    def test_absent(self):
        assert CONDITION_HANDLERS["not_contains"]("hello", "xyz") is True

    def test_present(self):
        assert CONDITION_HANDLERS["not_contains"]("hello world", "world") is False


class TestStartsWith:
    def test_prefix(self):
        assert CONDITION_HANDLERS["starts_with"]("hello world", "hello") is True

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["starts_with"]("Hello", "hello") is True

    def test_no_match(self):
        assert CONDITION_HANDLERS["starts_with"]("hello", "world") is False

    def test_whitespace_trimmed(self):
        assert CONDITION_HANDLERS["starts_with"]("  hello", "hello") is True


class TestEndsWith:
    def test_suffix(self):
        assert CONDITION_HANDLERS["ends_with"]("hello world", "world") is True

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["ends_with"]("hello World", "world") is True

    def test_no_match(self):
        assert CONDITION_HANDLERS["ends_with"]("hello", "xyz") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Numeric operators
# ═══════════════════════════════════════════════════════════════════════════════

class TestGreaterThan:
    def test_greater(self):
        assert CONDITION_HANDLERS["greater_than"]("10", "5") is True

    def test_equal(self):
        assert CONDITION_HANDLERS["greater_than"]("5", "5") is False

    def test_less(self):
        assert CONDITION_HANDLERS["greater_than"]("3", "5") is False

    def test_float(self):
        assert CONDITION_HANDLERS["greater_than"]("10.5", "10.4") is True

    def test_non_numeric_returns_nan(self):
        # NaN comparisons always return False
        assert CONDITION_HANDLERS["greater_than"]("abc", "0") is False
        assert CONDITION_HANDLERS["greater_than"]("5", "abc") is False  # 5 > NaN = False


class TestLessThan:
    def test_less(self):
        assert CONDITION_HANDLERS["less_than"]("3", "5") is True

    def test_equal(self):
        assert CONDITION_HANDLERS["less_than"]("5", "5") is False

    def test_greater(self):
        assert CONDITION_HANDLERS["less_than"]("10", "5") is False


class TestGreaterOrEqual:
    def test_greater(self):
        assert CONDITION_HANDLERS["greater_or_equal"]("10", "5") is True

    def test_equal(self):
        assert CONDITION_HANDLERS["greater_or_equal"]("5", "5") is True

    def test_less(self):
        assert CONDITION_HANDLERS["greater_or_equal"]("3", "5") is False


class TestLessOrEqual:
    def test_less(self):
        assert CONDITION_HANDLERS["less_or_equal"]("3", "5") is True

    def test_equal(self):
        assert CONDITION_HANDLERS["less_or_equal"]("5", "5") is True

    def test_greater(self):
        assert CONDITION_HANDLERS["less_or_equal"]("10", "5") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Check operators (valueless)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsEmpty:
    def test_empty_string(self):
        assert CONDITION_HANDLERS["is_empty"]("", "") is True

    def test_whitespace_only(self):
        assert CONDITION_HANDLERS["is_empty"]("   ", "") is True

    def test_none(self):
        assert CONDITION_HANDLERS["is_empty"](None, "") is True

    def test_has_content(self):
        assert CONDITION_HANDLERS["is_empty"]("hello", "") is False


class TestIsNotEmpty:
    def test_has_content(self):
        assert CONDITION_HANDLERS["is_not_empty"]("hello", "") is True

    def test_empty(self):
        assert CONDITION_HANDLERS["is_not_empty"]("", "") is False

    def test_none(self):
        assert CONDITION_HANDLERS["is_not_empty"](None, "") is False

    def test_whitespace_only(self):
        assert CONDITION_HANDLERS["is_not_empty"]("   ", "") is False


class TestNotEmpty:
    """Legacy alias for is_not_empty."""
    def test_has_content(self):
        assert CONDITION_HANDLERS["not_empty"]("hello", "") is True

    def test_empty(self):
        assert CONDITION_HANDLERS["not_empty"]("", "") is False


class TestIsTimestamp:
    def test_epoch_seconds(self):
        assert CONDITION_HANDLERS["is_timestamp"]("1609459200", "") is True  # 2021-01-01

    def test_epoch_float(self):
        assert CONDITION_HANDLERS["is_timestamp"]("1609459200.123", "") is True

    def test_iso8601(self):
        assert CONDITION_HANDLERS["is_timestamp"]("2021-01-01T00:00:00", "") is True

    def test_iso8601_with_space(self):
        assert CONDITION_HANDLERS["is_timestamp"]("2021-01-01 12:30:45", "") is True

    def test_splunk_format(self):
        assert CONDITION_HANDLERS["is_timestamp"]("01/01/2021 00:00:00", "") is True

    def test_not_timestamp(self):
        assert CONDITION_HANDLERS["is_timestamp"]("hello", "") is False

    def test_empty(self):
        assert CONDITION_HANDLERS["is_timestamp"]("", "") is False

    def test_zero(self):
        assert CONDITION_HANDLERS["is_timestamp"]("0", "") is False

    def test_negative(self):
        assert CONDITION_HANDLERS["is_timestamp"]("-1", "") is False

    def test_far_future(self):
        # Year 2200 epoch — beyond 2100 cutoff
        assert CONDITION_HANDLERS["is_timestamp"]("9999999999", "") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Advanced operators
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegex:
    def test_simple_match(self):
        assert CONDITION_HANDLERS["regex"]("hello123", r"\d+") is True

    def test_no_match(self):
        assert CONDITION_HANDLERS["regex"]("hello", r"\d+") is False

    def test_full_pattern(self):
        assert CONDITION_HANDLERS["regex"]("192.168.1.1", r"^\d+\.\d+\.\d+\.\d+$") is True

    def test_invalid_regex(self):
        # Invalid pattern should return False, not crash
        assert CONDITION_HANDLERS["regex"]("hello", r"[invalid") is False

    def test_empty_actual(self):
        assert CONDITION_HANDLERS["regex"]("", r".+") is False

    def test_case_sensitive(self):
        # Regex is case-sensitive by default
        assert CONDITION_HANDLERS["regex"]("Hello", r"^hello$") is False
        assert CONDITION_HANDLERS["regex"]("hello", r"^hello$") is True


class TestInList:
    def test_in_list(self):
        assert CONDITION_HANDLERS["in_list"]("apple", "apple, banana, cherry") is True

    def test_not_in_list(self):
        assert CONDITION_HANDLERS["in_list"]("grape", "apple, banana, cherry") is False

    def test_case_insensitive(self):
        assert CONDITION_HANDLERS["in_list"]("Apple", "apple, banana") is True

    def test_whitespace_handling(self):
        assert CONDITION_HANDLERS["in_list"]("banana", "apple,banana,cherry") is True
        assert CONDITION_HANDLERS["in_list"]("banana", "apple , banana , cherry") is True

    def test_single_item(self):
        assert CONDITION_HANDLERS["in_list"]("apple", "apple") is True

    def test_empty_value(self):
        assert CONDITION_HANDLERS["in_list"]("", "apple, , cherry") is True


class TestNotInList:
    def test_absent(self):
        assert CONDITION_HANDLERS["not_in_list"]("grape", "apple, banana") is True

    def test_present(self):
        assert CONDITION_HANDLERS["not_in_list"]("apple", "apple, banana") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Result count operators
# ═══════════════════════════════════════════════════════════════════════════════

class TestCountOps:
    def test_equals(self):
        assert COUNT_OPS["equals"](5, 5) is True
        assert COUNT_OPS["equals"](5, 3) is False

    def test_greater_than(self):
        assert COUNT_OPS["greater_than"](10, 5) is True
        assert COUNT_OPS["greater_than"](5, 5) is False

    def test_less_than(self):
        assert COUNT_OPS["less_than"](3, 5) is True
        assert COUNT_OPS["less_than"](5, 5) is False

    def test_greater_or_equal(self):
        assert COUNT_OPS["greater_or_equal"](5, 5) is True
        assert COUNT_OPS["greater_or_equal"](3, 5) is False

    def test_less_or_equal(self):
        assert COUNT_OPS["less_or_equal"](5, 5) is True
        assert COUNT_OPS["less_or_equal"](10, 5) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Scope evaluation
# ═══════════════════════════════════════════════════════════════════════════════

class TestScopeEvaluation:
    """Test scope handlers via the evaluate function."""

    def test_all_events_pass(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([True, True, True], "all_events", None) is True

    def test_all_events_fail(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([True, False, True], "all_events", None) is False

    def test_any_event_pass(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([False, True, False], "any_event", None) is True

    def test_any_event_fail(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([False, False, False], "any_event", None) is False

    def test_exactly_n(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([True, True, False], "exactly_n", 2) is True
        assert evaluate_scope([True, True, True], "exactly_n", 2) is False

    def test_at_least_n(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([True, True, False], "at_least_n", 2) is True
        assert evaluate_scope([True, False, False], "at_least_n", 2) is False

    def test_at_most_n(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([True, False, False], "at_most_n", 2) is True
        assert evaluate_scope([True, True, True], "at_most_n", 2) is False

    def test_empty_results(self):
        from validation.scope_evaluator import evaluate_scope
        assert evaluate_scope([], "all_events", None) is False
        assert evaluate_scope([], "any_event", None) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_all_operators_registered(self):
        """Every operator from the frontend type should exist in backend."""
        expected = {
            "equals", "not_equals", "contains", "not_contains",
            "starts_with", "ends_with", "greater_than", "less_than",
            "greater_or_equal", "less_or_equal", "is_empty", "is_not_empty",
            "is_timestamp", "regex", "in_list", "not_in_list", "not_empty",
        }
        assert expected.issubset(set(CONDITION_HANDLERS.keys()))

    def test_none_safe_handlers(self):
        """Handlers that explicitly handle None should not crash."""
        none_safe = {"is_empty", "is_not_empty", "not_empty", "is_timestamp",
                     "greater_than", "less_than", "greater_or_equal", "less_or_equal"}
        for name in none_safe:
            handler = CONDITION_HANDLERS[name]
            try:
                handler(None, "test")
            except Exception as e:
                pytest.fail("Handler '{}' crashed with None: {}".format(name, e))

    def test_none_crashes_string_handlers(self):
        """String handlers (equals, contains, etc) crash on None — this is a known limitation.
        The result_validator wraps calls and handles missing fields before invoking handlers."""
        string_handlers = {"equals", "not_equals", "contains", "not_contains",
                           "starts_with", "ends_with", "in_list", "not_in_list"}
        for name in string_handlers:
            with pytest.raises((AttributeError, TypeError)):
                CONDITION_HANDLERS[name](None, "test")

    def test_empty_actual_value(self):
        """Empty string as actual should not crash."""
        for name, handler in CONDITION_HANDLERS.items():
            try:
                handler("", "test")
            except Exception as e:
                pytest.fail("Handler '{}' crashed with empty: {}".format(name, e))

    def test_unicode_values(self):
        assert CONDITION_HANDLERS["equals"]("\u00e9l\u00e8ve", "\u00e9l\u00e8ve") is True
        assert CONDITION_HANDLERS["contains"]("caf\u00e9 latte", "caf\u00e9") is True

    def test_numeric_string_edge(self):
        """Scientific notation, negative numbers."""
        assert CONDITION_HANDLERS["greater_than"]("1e5", "99999") is True
        assert CONDITION_HANDLERS["less_than"]("-5", "0") is True

    def test_multiline_value(self):
        assert CONDITION_HANDLERS["contains"]("line1\nline2\nline3", "line2") is True

    def test_special_chars_in_list(self):
        assert CONDITION_HANDLERS["in_list"]("a,b", "a,b, c,d") is False  # "a,b" is one value vs split
        assert CONDITION_HANDLERS["in_list"]("a", "a,b, c,d") is True
