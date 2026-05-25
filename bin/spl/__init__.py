# -*- coding: utf-8 -*-
"""
spl — SPL analysis, injection, and execution.
"""
from __future__ import annotations

from spl.spl_analyzer import SplAnalysis, analyze
from spl.spl_normalizer import normalize_spl
from spl.query_injector import detect_strategy, inject
from spl.query_executor import QueryExecutor

__all__ = [
    "SplAnalysis",
    "analyze",
    "normalize_spl",
    "detect_strategy",
    "inject",
    "QueryExecutor",
]
