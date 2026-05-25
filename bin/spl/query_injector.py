# -*- coding: utf-8 -*-
"""
query_injector.py
Rewrite SPL strings to target the temp query tester index.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from logger import get_logger
from config import TEMP_INDEX
from core.models import ParsedInput
logger = get_logger(__name__)

INDEX_PATTERN = re.compile(r'(?i)\bindex\s*=\s*["\']?[\w\*\-\.]+["\']?')
LOOKUP_PATTERN = re.compile(r"(?i)(\|\s*lookup\s+)([\w\-\.]+)")
INPUTLOOKUP_PATTERN = re.compile(
    r"(?i)(?:\|\s*)?inputlookup\s+[\w\-\.]+(?:\.csv)?"
)

_RE_INPUTLOOKUP = re.compile(r"(?:^|\|)\s*inputlookup\b", re.IGNORECASE)
_RE_TSTATS = re.compile(r"(?:^|\|)\s*tstats\b", re.IGNORECASE)
_RE_LOOKUP = re.compile(r"(?:^|\|)\s*lookup\s+\w", re.IGNORECASE)
_RE_REST = re.compile(r"(?:^|\|)\s*rest\b", re.IGNORECASE)
_RE_SAVEDSEARCH = re.compile(r"(?:^|\|)\s*savedsearch\b", re.IGNORECASE)
_RE_INDEX = re.compile(r"\bindex\s*=", re.IGNORECASE)

# Matches the full '| rest ...' clause up to the next pipe or end of string.
# Uses a non-greedy match and stops before trailing whitespace + pipe.
REST_PATTERN = re.compile(r"(?i)(?:\|\s*)?rest\s+[^|]+?(?=\s*\||$)")

# Matches '| savedsearch <name>' where <name> can be quoted (with spaces/pipes)
# or unquoted (word chars only). Quoted names are matched as one atomic token.
SAVEDSEARCH_PATTERN = re.compile(
    r'(?i)(?:\|\s*)?savedsearch\s+(?:"[^"]+"|\'[^\']+\'|[\w\-\.]+)'
)



def _outer_segment(spl: str) -> str:
    bracket_pos = spl.find("[")
    if bracket_pos == -1:
        return spl
    return spl[:bracket_pos]


def _run_id_field(run_id: str) -> str:
    return "run_id_{0}".format(run_id)


def _build_replacement(run_id: str, input_idx: Optional[int] = None) -> str:
    base = "index={0} {1}={2}".format(TEMP_INDEX, _run_id_field(run_id), run_id)
    if input_idx is not None:
        base += " input_{0}={0}".format(input_idx)
    return base


def _apply_row_identifiers(
    spl: str, inputs: List[ParsedInput], replacement: str,
) -> Optional[str]:
    """Apply all input row identifiers, replacing every match globally.
    Each input gets its own replacement with an input_idx discriminator
    so events from different inputs don't bleed into each other.
    Returns the modified SPL if any RI matched, or None if none matched.
    """
    current = spl
    run_id = _extract_run_id(replacement)
    for idx, parsed_input in enumerate(inputs):
        row_identifier = parsed_input.row_identifier.strip()
        if not row_identifier:
            continue
        # Build per-input replacement with input_idx discriminator
        if len(inputs) > 1:
            per_input_replacement = _build_replacement(run_id, input_idx=idx)
        else:
            per_input_replacement = replacement
        replaced = _replace_by_row_identifier(current, row_identifier, per_input_replacement)
        if replaced is not None:
            current = replaced
    if current != spl:
        return current
    return None


def _extract_run_id(replacement: str) -> str:
    """Extract the run_id value from a replacement string like
    'index=temp_query_tester run_id_abc123=abc123'.
    """
    for part in replacement.split():
        if part.startswith("run_id_"):
            eq = part.find("=")
            if eq != -1:
                return part[eq + 1:]
    return ""


def detect_strategy(spl: str) -> str:
    """Detect the injection strategy for the given SPL.

    Only inspects the outer segment (before first '[') so that inputlookup
    inside a subsearch does not override the primary strategy.
    Order: inputlookup, tstats, rest, lookup, standard, no_index.
    """
    spl_clean = (spl or "").strip()
    outer = _outer_segment(spl_clean)
    if _RE_INPUTLOOKUP.search(outer):
        return "inputlookup"
    if _RE_TSTATS.search(spl_clean):
        return "tstats"
    if _RE_REST.search(outer):
        return "rest"
    if _RE_SAVEDSEARCH.search(outer):
        return "savedsearch"
    if _RE_LOOKUP.search(spl_clean):
        return "lookup"
    if _RE_INDEX.search(outer):
        return "standard"
    return "no_index"


def inject(
    spl: str, run_id: str, strategy: str, inputs: List[ParsedInput],
    test_id: Optional[str] = None,
) -> str:
    """Apply the selected injection strategy, then replace any remaining
    inputlookup commands (e.g. inside subsearches) as a post-step.
    Swaps lookup names in non-testing cache macros with temp lookups.

    *test_id* — when provided (manual runs), the cache temp lookup uses a
    stable name so it persists across reruns within the session. When absent
    (scheduled runs), a per-run name is used.
    """
    handler = STRATEGY_HANDLERS.get(strategy)
    if handler is None:
        logger.warning('Unknown injection strategy "%s" — returning SPL unchanged.', strategy)
        return spl
    result = handler(spl, run_id, inputs)
    # Post-step: replace inputlookup commands in subsearches.
    # When explicit RIs are configured, only replace inputlookups that match
    # a configured RI. When no RIs are set, replace all (legacy behavior).
    if strategy != "tstats":
        has_explicit_ri = any(inp.row_identifier.strip() for inp in inputs)
        if has_explicit_ri:
            result = _replace_configured_inputlookups(result, run_id, inputs)
        else:
            result = _replace_all_inputlookups(result, run_id)
    pre_swap = result
    result = _swap_cache_lookups(result, run_id, test_id)
    if result != pre_swap:
        logger.info("Cache swap applied. Before: %.200s", pre_swap)
        logger.info("Cache swap applied. After:  %.200s", result)
    return result


def _inject_noop(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    # Even for tstats, try RI replacement — the user may have set index=X as the RI
    replacement = _build_replacement(run_id)
    result = _apply_row_identifiers(spl, inputs, replacement)
    if result is not None:
        return result
    return spl


def _inject_standard(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    replacement = _build_replacement(run_id)
    result = _apply_row_identifiers(spl, inputs, replacement)
    if result is not None:
        return result
    return _replace_outer_index(spl, replacement)


def _inject_no_index(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    prefix = _build_replacement(run_id) + " "
    stripped = spl.lstrip()
    leading = spl[: len(spl) - len(stripped)]
    return leading + prefix + stripped


def _inject_inputlookup(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    """Replace '| inputlookup <name>' with temp index reference.
    Must not produce '| index=...' which is invalid SPL.
    """
    replacement = _build_replacement(run_id)
    result = _apply_row_identifiers(spl, inputs, replacement)
    if result is not None:
        return result
    outer = _outer_segment(spl)
    match = INPUTLOOKUP_PATTERN.search(outer)
    if not match:
        logger.warning("inputlookup strategy but pattern not found — returning SPL unchanged.")
        return spl
    return spl[:match.start()] + replacement + spl[match.end():]


def _inject_rest(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    """Replace '| rest <args>' with temp index reference.
    The rest command queries Splunk REST endpoints, not indexes.
    Replace the entire rest clause (up to next pipe) with the temp index.
    """
    replacement = _build_replacement(run_id)
    result = _apply_row_identifiers(spl, inputs, replacement)
    if result is not None:
        return result
    outer = _outer_segment(spl)
    match = REST_PATTERN.search(outer)
    if not match:
        logger.warning("rest strategy but pattern not found — returning SPL unchanged.")
        return spl
    return spl[:match.start()] + replacement + spl[match.end():]


def _inject_savedsearch(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    """Replace '| savedsearch <name>' with the temp index.
    Handles quoted names with spaces and pipes inside them.
    """
    replacement = _build_replacement(run_id)
    result = _apply_row_identifiers(spl, inputs, replacement)
    if result is not None:
        return result
    outer = _outer_segment(spl)
    match = SAVEDSEARCH_PATTERN.search(outer)
    if not match:
        logger.warning("savedsearch strategy but pattern not found — returning SPL unchanged.")
        return spl
    return spl[:match.start()] + replacement + spl[match.end():]


_LOOKUP_RI_RE = re.compile(r'(?i)^(?:lookup|inputlookup)\s+([\w\-\.]+)')


def _inject_lookup(spl: str, run_id: str, inputs: List[ParsedInput]) -> str:
    """Handle lookup injection.

    If the RI starts with 'lookup <name>', swap only <name> with a temp
    lookup in the SPL. The test runner will create a temp KVStore lookup
    with the user's test data under that name.
    Otherwise, treat as standard index replacement — lookups untouched.
    """
    replacement = _build_replacement(run_id)
    result = spl
    ri_matched = False

    for inp in inputs:
        ri = inp.row_identifier.strip()
        if not ri:
            continue
        m = _LOOKUP_RI_RE.match(ri)
        if m:
            # RI is "lookup <name>" — swap <name> with temp lookup
            lookup_name = m.group(1).strip()
            temp_name = "temp_lookup_{0}".format(run_id)
            pattern = re.compile(r'\b' + re.escape(lookup_name) + r'\b')
            result = pattern.sub(temp_name, result)
            ri_matched = True
        else:
            # Standard RI (e.g. "index=main") — find-and-replace
            replaced = _replace_by_row_identifier(result, ri, replacement)
            if replaced is not None:
                result = replaced
                ri_matched = True

    if ri_matched:
        return result
    return _replace_outer_index(spl, replacement)


def _replace_by_row_identifier(
    spl: str, row_identifier: str, replacement: str,
) -> Optional[str]:
    """Replace ALL occurrences of the row identifier in the full SPL.

    For inputlookup/rest RIs (no leading pipe), also consume a leading
    ``| `` or ``|`` before the match so the result doesn't produce
    ``| index=...`` which is invalid SPL.
    """
    escaped = re.escape(row_identifier)
    ri_lower = row_identifier.strip().lower()
    needs_pipe_cleanup = (
        ri_lower.startswith("inputlookup ")
        or ri_lower.startswith("rest ")
        or ri_lower.startswith("savedsearch ")
    )
    if needs_pipe_cleanup:
        # Match optional leading pipe+whitespace before the RI
        pattern = re.compile(r"(?:\|\s*)?" + escaped, re.IGNORECASE)
    else:
        pattern = re.compile(escaped, re.IGNORECASE)
    result, count = pattern.subn(replacement, spl)
    if count == 0:
        return None
    return result


def _replace_outer_index(spl: str, replacement: str) -> str:
    """Find the outer index clause, then replace ALL occurrences of that
    exact index=<value> throughout the SPL. Other index values stay.
    """
    outer = _outer_segment(spl)
    match = INDEX_PATTERN.search(outer)
    if not match:
        return spl
    original_clause = match.group(0)
    exact_pattern = re.compile(re.escape(original_clause), re.IGNORECASE)
    return exact_pattern.sub(replacement, spl)


def _replace_all_inputlookups(spl: str, run_id: str) -> str:
    """Replace every inputlookup command in the SPL with the temp index."""
    return INPUTLOOKUP_PATTERN.sub(_build_replacement(run_id), spl)


def _replace_configured_inputlookups(
    spl: str, run_id: str, inputs: List[ParsedInput],
) -> str:
    """Replace inputlookup commands only if they match a configured row identifier.

    For each inputlookup in the SPL, check if any input's RI matches the
    inputlookup text (e.g. RI 'inputlookup users.csv'). Only replace matches.
    Inputlookup commands with no matching RI are left untouched.
    """
    replacement = _build_replacement(run_id)
    ri_set = set()
    for inp in inputs:
        ri = inp.row_identifier.strip().lower()
        if ri:
            ri_set.add(ri)
    if not ri_set:
        return spl

    def _check_and_replace(match):
        # type: (re.Match) -> str
        matched_text = match.group(0).strip().lower()
        # Check if any RI matches this inputlookup command text
        for ri in ri_set:
            if ri in matched_text or matched_text in ri:
                return replacement
        return match.group(0)

    return INPUTLOOKUP_PATTERN.sub(_check_and_replace, spl)


_ORPHAN_PATTERNS = [
    (re.compile(r"(?i)\bsourcetype\s*=\s*\S+"), "sourcetype="),
    (re.compile(r"(?i)\bsource\s*=\s*\S+"), "source="),
    (re.compile(r"(?i)\bhost\s*=\s*\S+"), "host="),
]


def check_orphaned_filters(original_spl: str, injected_spl: str) -> Optional[str]:
    """Check if filter clauses remain after injection that won't match temp data."""
    outer = _outer_segment(injected_spl)
    orphans = []  # type: List[str]
    for pattern, label in _ORPHAN_PATTERNS:
        if pattern.search(outer):
            orphans.append(label)
    if not orphans:
        return None
    return (
        "After injection the query still contains {0} in the outer segment. "
        "These filters don't apply to generated data and may cause zero results. "
        "Include them in the row identifier to avoid this.".format(
            ", ".join(orphans)
        )
    )


STRATEGY_HANDLERS: Dict[str, Callable[[str, str, List[ParsedInput]], str]] = {
    "standard": _inject_standard,
    "lookup": _inject_lookup,
    "inputlookup": _inject_inputlookup,
    "rest": _inject_rest,
    "savedsearch": _inject_savedsearch,
    "tstats": _inject_noop,
    "no_index": _inject_no_index,
}


# ── Cache macro lookup swap ──────────────────────────────────────────────────

def _swap_cache_lookups(spl, run_id, test_id=None):
    # type: (str, str, Optional[str]) -> str
    """Swap the lookup_name in non-testing cache macros with a temp lookup.

    `cache(lookup_name, id, prop, stack, testing, vanish)` — when testing is
    not true, replace lookup_name with a temp name so the macro writes to a
    disposable lookup instead of the real one.
    Testing=true macros are left untouched (safe by design).

    Naming:
    - Manual runs (test_id provided): ``temp_cache_{test_id[:8]}_{lookup}``
      — stable name so the temp lookup persists across reruns in the session.
    - Scheduled runs (no test_id): ``temp_cache_{run_id}_{lookup}``
      — unique per run. The caller should copy the real lookup into this
      temp before execution so the test validates against real data.
    """
    try:
        from spl.spl_analyzer import parse_cache_macros
    except ImportError as exc:
        logger.error("Failed to import parse_cache_macros: %s", exc)
        return spl

    parsed = parse_cache_macros(spl)
    logger.info("Cache macro scan: found %d macro(s) in SPL (len=%d)", len(parsed), len(spl))
    if not parsed:
        return spl

    key = test_id[:8] if test_id else run_id

    # Process in reverse order so string offsets stay valid
    result = spl
    for info in reversed(parsed):
        if info["is_testing"]:
            continue  # testing=true — safe, leave as-is
        if len(info["args"]) < 5:
            continue  # malformed — skip

        original_lookup = info["args"][0]
        temp_lookup = "temp_cache_{0}_{1}".format(key, original_lookup)

        # Rebuild the macro call with the temp lookup name
        new_args = list(info["args"])
        new_args[0] = temp_lookup
        new_macro = "`cache({0})`".format(",".join(new_args))

        result = result[:info["start"]] + new_macro + result[info["end"]:]
        logger.info(
            "Swapped cache lookup '%s' -> '%s' (key=%s)",
            original_lookup, temp_lookup, key,
        )

    return result
