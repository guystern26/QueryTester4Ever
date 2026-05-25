# -*- coding: utf-8 -*-
"""Tests for savedsearch as a data source row identifier."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spl.query_injector import (
    detect_strategy,
    inject,
    SAVEDSEARCH_PATTERN,
)
from core.models import ParsedInput


def _make_input(row_identifier=""):
    return ParsedInput(
        row_identifier=row_identifier,
        input_mode="fields",
        events=[{"foo": "bar"}],
        generator_config=None,
        query_data_config=None,
    )


class TestSavedSearchDetection:
    def test_basic_savedsearch_detected(self):
        assert detect_strategy("| savedsearch my_search") == "savedsearch"

    def test_savedsearch_no_leading_pipe(self):
        assert detect_strategy("savedsearch my_search") == "savedsearch"

    def test_quoted_savedsearch_name(self):
        assert detect_strategy('| savedsearch "My Search"') == "savedsearch"

    def test_savedsearch_with_pipe_in_name(self):
        spl = '| savedsearch "category | details"'
        assert detect_strategy(spl) == "savedsearch"

    def test_savedsearch_with_followup_pipes(self):
        spl = '| savedsearch my_search | stats count'
        assert detect_strategy(spl) == "savedsearch"

    def test_inputlookup_still_takes_priority(self):
        spl = '| inputlookup users.csv | savedsearch foo'
        assert detect_strategy(spl) == "inputlookup"


class TestSavedSearchPattern:
    def test_matches_simple_name(self):
        m = SAVEDSEARCH_PATTERN.search("| savedsearch my_search | stats count")
        assert m is not None
        assert m.group(0).strip() == '| savedsearch my_search'.strip() or \
               'savedsearch my_search' in m.group(0)

    def test_matches_quoted_name_with_spaces(self):
        m = SAVEDSEARCH_PATTERN.search('| savedsearch "My Cool Search"')
        assert m is not None
        assert '"My Cool Search"' in m.group(0)

    def test_matches_quoted_name_with_pipes(self):
        spl = '| savedsearch "category | details" | stats count'
        m = SAVEDSEARCH_PATTERN.search(spl)
        assert m is not None
        # Must include the full quoted name with the pipe inside
        assert '"category | details"' in m.group(0)

    def test_single_quoted_name(self):
        m = SAVEDSEARCH_PATTERN.search("| savedsearch 'My Search'")
        assert m is not None
        assert "'My Search'" in m.group(0)


class TestSavedSearchInjection:
    def test_simple_replacement(self):
        spl = '| savedsearch my_search | stats count'
        result = inject(spl, "abc123", "savedsearch", [_make_input()])
        # The savedsearch should be REPLACED, not prepended
        assert 'savedsearch my_search' not in result
        assert 'index=temp_query_tester' in result
        assert 'run_id_abc123=abc123' in result
        # Should still have the stats command
        assert '| stats count' in result

    def test_quoted_name_with_pipe_replaced(self):
        spl = '| savedsearch "category | details" | stats count'
        result = inject(spl, "abc123", "savedsearch", [_make_input()])
        # The whole '| savedsearch "..."' clause should be gone
        assert 'savedsearch' not in result
        assert 'category | details' not in result
        assert 'index=temp_query_tester' in result
        assert '| stats count' in result

    def test_no_dangling_pipe(self):
        """After replacement, no '| index=...' (invalid SPL)."""
        spl = '| savedsearch foo | stats count'
        result = inject(spl, "abc123", "savedsearch", [_make_input()])
        # Should not start with '| index=' (that's invalid)
        stripped = result.lstrip()
        assert not stripped.startswith('|'), \
            "Result should not start with a pipe: {0}".format(result)

    def test_with_row_identifier_savedsearch(self):
        """When RI is 'savedsearch foo', it should be matched and replaced."""
        spl = '| savedsearch foo | where status=200'
        inp = _make_input(row_identifier='savedsearch foo')
        result = inject(spl, "abc123", "savedsearch", [inp])
        assert 'savedsearch foo' not in result
        assert 'index=temp_query_tester' in result
        # The leading pipe should be cleaned up
        assert not result.lstrip().startswith('|')

    def test_savedsearch_inside_pipeline(self):
        """savedsearch in the middle of a pipeline."""
        spl = 'index=main | join host [| savedsearch lookup_search] | stats count'
        # Not detected as savedsearch strategy (index= is in outer segment)
        strategy = detect_strategy(spl)
        # outer segment stops at '[' so savedsearch is in subsearch
        assert strategy == "standard"


class TestRegression:
    """Ensure we haven't broken other injection paths."""

    def test_inputlookup_still_works(self):
        spl = '| inputlookup users.csv | head 10'
        result = inject(spl, "xyz789", "inputlookup", [_make_input()])
        assert 'inputlookup' not in result
        assert 'index=temp_query_tester' in result

    def test_index_still_works(self):
        spl = 'index=main sourcetype=access | stats count'
        result = inject(spl, "xyz789", "standard", [_make_input()])
        assert 'temp_query_tester' in result

    def test_rest_still_works(self):
        spl = '| rest /services/apps/local | table title'
        result = inject(spl, "xyz789", "rest", [_make_input()])
        assert 'rest' not in result.split('|')[1]  # rest should be replaced
        assert 'index=temp_query_tester' in result
