# -*- coding: utf-8 -*-
"""
spl_normalizer.py
Normalize user-pasted SPL before analysis and execution.
"""
from __future__ import annotations

import re
from typing import Optional


# Commands that should be stripped from SPL before test execution.
# These are action commands that have side effects (sending email, writing data).
STRIP_COMMANDS = re.compile(
    r'\|\s*(?:sendemail|outputlookup)\b[^|]*$',
    re.IGNORECASE | re.MULTILINE,
)


def normalize_spl(spl):
    # type: (Optional[str]) -> str
    """
    Normalize an SPL string for safe processing.

    - Returns empty string for None or empty input
    - Converts Windows line endings (\\r\\n) to \\n
    - Strips leading/trailing whitespace
    - Collapses runs of spaces/tabs within a line to single space
    - Strips side-effect commands (sendemail) from the end of the pipeline
    - Does NOT modify content inside quoted strings
    - Preserves meaningful newlines in multiline SPL
    """
    if not spl:
        return ""

    # Windows line endings → Unix
    result = spl.replace("\r\n", "\n").replace("\r", "\n")

    # Strip leading/trailing whitespace from the whole string
    result = result.strip()

    if not result:
        return ""

    # Remove side-effect commands (sendemail) from the pipeline
    result = STRIP_COMMANDS.sub('', result).rstrip()

    # Normalize internal whitespace line-by-line, preserving quoted content
    lines = result.split("\n")
    normalized_lines = []  # type: list
    for line in lines:
        normalized_lines.append(_normalize_line_whitespace(line))

    return "\n".join(normalized_lines)


def _normalize_line_whitespace(line):
    # type: (str) -> str
    """
    Collapse multiple spaces/tabs to single space within a line,
    but skip content inside single or double quotes.
    """
    result = []  # type: list
    i = 0
    in_space = False

    while i < len(line):
        ch = line[i]

        # Handle quoted strings — pass through verbatim
        if ch in ('"', "'"):
            if in_space:
                result.append(" ")
                in_space = False
            quote_char = ch
            result.append(ch)
            i += 1
            while i < len(line):
                c = line[i]
                result.append(c)
                if c == "\\" and i + 1 < len(line):
                    # Escaped character — include next char too
                    i += 1
                    result.append(line[i])
                elif c == quote_char:
                    break
                i += 1
            i += 1
            continue

        # Collapse whitespace (spaces and tabs)
        if ch in (" ", "\t"):
            in_space = True
            i += 1
            continue

        if in_space:
            result.append(" ")
            in_space = False

        result.append(ch)
        i += 1

    return "".join(result)
