# -*- coding: utf-8 -*-
"""Tests for scheduled_runner.py cron matching logic."""
from __future__ import annotations

import pytest

from scheduling.cron_matcher import cron_matches as _cron_matches, _field_matches


class TestFieldMatches:
    def test_star_matches_all(self):
        assert _field_matches("*", 0, 0, 59) is True
        assert _field_matches("*", 30, 0, 59) is True

    def test_exact_match(self):
        assert _field_matches("5", 5, 0, 59) is True
        assert _field_matches("5", 6, 0, 59) is False

    def test_range(self):
        assert _field_matches("1-5", 3, 0, 59) is True
        assert _field_matches("1-5", 6, 0, 59) is False

    def test_step(self):
        assert _field_matches("*/5", 0, 0, 59) is True
        assert _field_matches("*/5", 5, 0, 59) is True
        assert _field_matches("*/5", 3, 0, 59) is False

    def test_comma_list(self):
        assert _field_matches("1,3,5", 3, 0, 59) is True
        assert _field_matches("1,3,5", 4, 0, 59) is False

    def test_range_with_step(self):
        assert _field_matches("0-30/10", 0, 0, 59) is True
        assert _field_matches("0-30/10", 10, 0, 59) is True
        assert _field_matches("0-30/10", 15, 0, 59) is False
        assert _field_matches("0-30/10", 40, 0, 59) is False


class TestCronMatches:
    def test_every_minute(self):
        assert _cron_matches("* * * * *", (30, 12, 15, 3, 6)) is True

    def test_specific_time(self):
        # 6:00 AM every day
        assert _cron_matches("0 6 * * *", (0, 6, 15, 3, 0)) is True
        assert _cron_matches("0 6 * * *", (0, 7, 15, 3, 0)) is False
        assert _cron_matches("0 6 * * *", (1, 6, 15, 3, 0)) is False

    def test_every_5_minutes(self):
        assert _cron_matches("*/5 * * * *", (0, 12, 15, 3, 0)) is True
        assert _cron_matches("*/5 * * * *", (5, 12, 15, 3, 0)) is True
        assert _cron_matches("*/5 * * * *", (3, 12, 15, 3, 0)) is False

    def test_hourly(self):
        assert _cron_matches("0 * * * *", (0, 14, 15, 3, 0)) is True
        assert _cron_matches("0 * * * *", (30, 14, 15, 3, 0)) is False

    def test_midnight(self):
        assert _cron_matches("0 0 * * *", (0, 0, 15, 3, 0)) is True
        assert _cron_matches("0 0 * * *", (0, 12, 15, 3, 0)) is False

    def test_every_6_hours(self):
        assert _cron_matches("0 */6 * * *", (0, 0, 15, 3, 0)) is True
        assert _cron_matches("0 */6 * * *", (0, 6, 15, 3, 0)) is True
        assert _cron_matches("0 */6 * * *", (0, 12, 15, 3, 0)) is True
        assert _cron_matches("0 */6 * * *", (0, 3, 15, 3, 0)) is False

    def test_weekday_only(self):
        # Monday-Friday (1-5 in cron)
        assert _cron_matches("0 9 * * 1-5", (0, 9, 15, 3, 1)) is True   # Monday
        assert _cron_matches("0 9 * * 1-5", (0, 9, 15, 3, 0)) is False  # Sunday

    def test_invalid_cron(self):
        assert _cron_matches("bad", (0, 0, 1, 1, 0)) is False
        assert _cron_matches("", (0, 0, 1, 1, 0)) is False

    def test_every_minute_specific_test(self):
        # "* * * * *" should match minute=0 on March 15 2026 at 21:00
        assert _cron_matches("* * * * *", (0, 21, 15, 3, 0)) is True
