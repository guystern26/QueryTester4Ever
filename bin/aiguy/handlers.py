from __future__ import annotations

import json
import re
import time

from .constants import (
    ENRICH_BATCH_CHARS,
    MAX_RESPONSE_TOKENS_ENRICH,
    MAX_ROWS_FOR_AI,
    MAX_SCAN_FOR_SAMPLE,
    MAX_UNIQUE_FOR_DICT,
)
from .prompts import (
    SYSTEM_PROMPT,
    EXPLAIN_PROMPT,
    SUGGEST_PROMPT,
    ENRICH_PROMPT,
    MODE_PROMPTS,
)
from . import llm as llm_mod
from .llm import call_llm, log_usage, DeadlineExceeded
from .formatter import format_table, trim_values_to_budget
from .extract import run_extract, parse_dict_response


def _batch_values(values, char_budget):
    # type: (list, int) -> list
    """Split values into batches that each fit within char_budget."""
    batches = []
    current = []
    used = 2  # JSON brackets []
    for val in values:
        entry_len = len(val) + 4  # quotes + comma + space
        if current and used + entry_len > char_budget:
            batches.append(current)
            current = []
            used = 2
        current.append(val)
        used += entry_len
    if current:
        batches.append(current)
    return batches or [[]]


def _error_row(record, msg, ts):
    # type: (dict, str, str) -> dict
    record["ai_answer"] = msg
    record["aiguy_timestamp"] = ts
    record["aiguy_source"] = "error"
    return record


def _yield_one_error(records, msg, ts):
    # type: (object, str, str) -> list
    """Return a list with one error row from the iterator."""
    for record in records:
        return [_error_row(dict(record), msg, ts)]
    return []


def handle_explain(records, llm_cfg, full_spl, field, prompt, t_start):
    """Explain the SPL query itself — no results needed."""
    try:
        answer = call_llm(
            llm_cfg, EXPLAIN_PROMPT,
            "SPL query:\n" + (full_spl or "(not available)"),
        )
        source = "live"
    except Exception as exc:
        answer = "AI error: {0}".format(str(exc))
        source = "error"
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    yielded = False
    for record in records:
        row = dict(record)
        if not yielded:
            row["ai_answer"] = answer
            yielded = True
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source
        yield row
        break
    if not yielded:
        yield {"ai_answer": answer, "aiguy_timestamp": ts,
               "aiguy_source": source}
    log_usage("explain", field, prompt, source, 1, t_start)


def handle_suggest(records, llm_cfg, full_spl, field, prompt, t_start):
    """Suggest a follow-up SPL query based on results."""
    sample = []
    for record in records:
        sample.append(dict(record))
        if len(sample) >= MAX_ROWS_FOR_AI:
            break
    table = format_table(sample) if sample else "(no data)"
    spl_short = (full_spl or "")[:500]
    user_msg = "SPL: {0}\n\nResults ({1} rows):\n{2}".format(
        spl_short or "(not available)", len(sample), table)
    try:
        answer = call_llm(llm_cfg, SUGGEST_PROMPT, user_msg)
        source = "live"
    except Exception as exc:
        answer = "AI error: {0}".format(str(exc))
        source = "error"
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    for row in (sample[:1] or [{}]):
        row["ai_answer"] = answer
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source
        yield row
    log_usage("suggest", field, prompt, source, len(sample), t_start)


def handle_enrich(records, llm_cfg, field_name, user_prompt,
                  new_field_name, t_start):
    """Per-row AI classification/labeling (streaming)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if not field_name:
        msg = (
            "Enrich mode requires field= parameter. "
            'Example: | aiguy mode="enrich" field="status" '
            'prompt="classify as success or failure"'
        )
        for row in _yield_one_error(records, msg, ts):
            yield row
        log_usage("enrich", field_name, user_prompt, "error", 1, t_start)
        return

    # Scan all rows and collect ALL unique values (batching handles LLM size)
    scanned = []
    unique_vals = []
    seen = set()  # type: set
    for record in records:
        row = dict(record)
        scanned.append(row)
        val = str(row.get(field_name, ""))
        if val and val not in seen:
            seen.add(val)
            unique_vals.append(val)
        if len(scanned) >= MAX_SCAN_FOR_SAMPLE:
            break

    if not scanned:
        return

    if field_name not in scanned[0]:
        available = [k for k in scanned[0].keys() if not k.startswith("_")]
        msg = 'Field "{0}" not found. Available: {1}'.format(
            field_name, ", ".join(available[:15]))
        yield _error_row(scanned[0], msg, ts)
        log_usage("enrich", field_name, user_prompt, "error", 1, t_start)
        return

    # Send all unique values to LLM (in numbered batches)
    mapping = {}  # type: dict
    llm_field_name = ""
    source = "dict"
    enrich_cfg = dict(llm_cfg)
    enrich_cfg["max_tokens"] = MAX_RESPONSE_TOKENS_ENRICH
    batches = _batch_values(unique_vals, ENRICH_BATCH_CHARS)

    timed_out = False
    for batch in batches:
        numbered = "\n".join(
            "{0}: {1}".format(i + 1, v) for i, v in enumerate(batch)
        )
        enrich_msg = (
            "Field name: {field}\n"
            "User request: {prompt}\n"
            "Values ({count}):\n{numbered}"
        ).format(
            field=field_name,
            prompt=user_prompt or "classify each value",
            count=len(batch),
            numbered=numbered,
        )
        try:
            response = call_llm(enrich_cfg, ENRICH_PROMPT, enrich_msg)
            idx_mapping, batch_field = parse_dict_response(response)
            for i, val in enumerate(batch):
                key = str(i + 1)
                if key in idx_mapping:
                    mapping[val] = str(idx_mapping[key])
            if not llm_field_name and batch_field:
                llm_field_name = batch_field
        except DeadlineExceeded:
            source = "partial"
            timed_out = True
            break
        except Exception:
            source = "error"

    new_field = new_field_name or llm_field_name or "ai_answer"
    new_field = re.sub(r"[^\w]", "_", new_field).strip("_") or "ai_answer"
    # Never overwrite the source field
    if new_field == field_name:
        new_field = "ai_answer"
    if timed_out:
        source = "partial (deadline exceeded — returning {0} of {1} values)".format(
            len(mapping), len(unique_vals))

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    source_info = source
    row_count = len(scanned)
    for row in scanned:
        val = str(row.get(field_name, ""))
        row[new_field] = str(mapping.get(val, ""))
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source_info
        yield row

    for record in records:
        row = dict(record)
        val = str(row.get(field_name, ""))
        row[new_field] = str(mapping.get(val, ""))
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source_info
        row_count += 1
        yield row

    log_usage("enrich", field_name, user_prompt, source, row_count, t_start)


def handle_extract(records, llm_cfg, field_name, user_prompt,
                   new_field_name, t_start):
    """AI-powered field extraction (streaming)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if not field_name:
        msg = (
            "Extract mode requires field= parameter. "
            'Example: | aiguy mode="extract" field="email" '
            'prompt="extract the domain" new_field_name="domain"'
        )
        for row in _yield_one_error(records, msg, ts):
            yield row
        log_usage("extract", field_name, user_prompt, "error", 1, t_start)
        return

    scanned = []
    for record in records:
        scanned.append(dict(record))
        if len(scanned) >= MAX_SCAN_FOR_SAMPLE:
            break

    if not scanned:
        return

    if field_name not in scanned[0]:
        available = [k for k in scanned[0].keys() if not k.startswith("_")]
        msg = 'Field "{0}" not found. Available: {1}'.format(
            field_name, ", ".join(available[:15]))
        yield _error_row(scanned[0], msg, ts)
        log_usage("extract", field_name, user_prompt, "error", 1, t_start)
        return

    new_field = (new_field_name or "extracted").strip()
    try:
        scanned, source, answer = run_extract(
            llm_cfg, scanned, field_name, user_prompt, new_field
        )
    except Exception as exc:
        answer = "Extract error: {0}".format(str(exc))
        source = "error"

    # Build lookup from scanned for streaming remaining rows
    extract_map = {}  # type: dict
    resolved_field = new_field
    for row in scanned:
        if resolved_field not in row:
            for k in row:
                if k not in ("ai_answer", "aiguy_timestamp",
                             "aiguy_source") and k != field_name:
                    if k not in scanned[0] or k == new_field:
                        resolved_field = k
                        break
        val = str(row.get(field_name, ""))
        extracted = str(row.get(resolved_field, ""))
        if val and extracted:
            extract_map[val] = extracted

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    row_count = len(scanned)
    for idx, row in enumerate(scanned):
        if idx == 0 and source == "error":
            row["ai_answer"] = answer
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source
        yield row

    for record in records:
        row = dict(record)
        val = str(row.get(field_name, ""))
        row[resolved_field] = extract_map.get(val, "")
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source
        row_count += 1
        yield row

    log_usage("extract", field_name, user_prompt, source, row_count, t_start)


def handle_analysis(records, llm_cfg, full_spl, mode_key,
                    field, value, prompt, mode_raw, t_start):
    """Default analysis mode — summary, anomaly, trend, etc."""
    focus_field = field.strip() if field else None
    scanned = []
    sample = []
    seen_keys = set()  # type: set

    for record in records:
        row = dict(record)
        scanned.append(row)
        if len(sample) < MAX_ROWS_FOR_AI:
            if focus_field:
                key = str(row.get(focus_field, ""))
            else:
                key = "|".join(
                    str(row.get(k, "")) for k in row
                    if not k.startswith("_") or k in ("_time", "_raw")
                )
            if key not in seen_keys:
                seen_keys.add(key)
                sample.append(row)
        if len(scanned) >= MAX_SCAN_FOR_SAMPLE:
            break

    if not sample:
        return

    effective_prompt = prompt or ""
    if mode_key:
        effective_prompt = MODE_PROMPTS.get(
            mode_key, "Analyze the data with focus on: " + (mode_raw or ""))
    if not effective_prompt:
        effective_prompt = MODE_PROMPTS["summary"]

    focus_note = ""
    if field and value is not None:
        focus_note = "The user is focused on rows where {0}={1}.".format(
            field.strip(), value.strip())
    elif field:
        focus_note = "The user is specifically interested in the '{0}' field.".format(
            field.strip())

    table = format_table(sample, focus_field=focus_field)
    msg_parts = ["Question: " + effective_prompt]
    if focus_note:
        msg_parts.append("Focus: " + focus_note)
    spl_trimmed = (full_spl or "")[:500]
    if spl_trimmed:
        msg_parts.append("SPL: " + spl_trimmed)
    msg_parts.append(
        "Query results ({0} unique rows sampled):\n{1}".format(
            len(sample), table))
    user_msg = "\n\n".join(msg_parts)

    try:
        answer = call_llm(llm_cfg, SYSTEM_PROMPT, user_msg)
        source = "live"
    except Exception as exc:
        answer = "AI error: {0}".format(str(exc))
        source = "error"

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    row_count = len(scanned)
    source_info = "{0} ({1} unique of {2} scanned, {3}ms llm, {4} chars sent)".format(
        source, len(sample), row_count,
        llm_mod.last_call_ms, llm_mod.last_prompt_chars)
    for idx, row in enumerate(sample):
        if idx == 0:
            row["ai_answer"] = answer
        row["aiguy_timestamp"] = ts
        row["aiguy_source"] = source_info
        yield row

    log_usage(mode_key or "prompt", field, prompt,
              source, row_count, t_start)
