# -*- coding: utf-8 -*-
"""
spl_analyzer_rules.py
Command classification sets used by the SPL analyzer.
"""
from __future__ import annotations

UNAUTHORIZED_COMMANDS = {
    "delete",
    "drop",
    "collect",
    "outputlookup",
    "outputcsv",
    "sendemail",
    "dbxquery",
    "rest",
    "script",
    "map",
    "localop",
    "dbinspect",
    "audit",
    "tscollect",
    "meventcollect",
}

UNUSUAL_COMMANDS = {
    "uniq",
    "transaction",
    "multisearch",
    "appendpipe",
    "join",
    "selfjoin",
    "gentimes",
    "loadjob",
    "savedsearch",
}
