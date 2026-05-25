from __future__ import annotations

import json
import re

from .constants import (
    DICT_DIRECT_THRESHOLD,
    MAX_SAMPLE_FOR_REGEX,
    MAX_UNIQUE_FOR_DICT,
    MIN_REGEX_MATCH_RATE,
)
from .formatter import clean_llm_response, trim_values_to_budget
from .llm import call_llm
from .prompts import EXTRACT_DICT_PROMPT, EXTRACT_REGEX_PROMPT


def try_regex_extract(regex_str, rows, field_name):
    # type: (str, list, str) -> tuple
    """Apply a regex to all rows. Returns (val_to_extracted, match_rate)."""
    clean = clean_llm_response(regex_str)
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
        if val in results:
            matched += 1
            total += 1
            continue
        total += 1
        m = pattern.search(val)
        if m:
            try:
                results[val] = m.group("result")
                matched += 1
            except IndexError:
                if m.lastindex and m.lastindex >= 1:
                    results[val] = m.group(1)
                    matched += 1

    rate = matched / total if total > 0 else 0.0
    return results, rate


def try_dict_extract(dict_response, rows, field_name):
    # type: (str, list, str) -> dict
    """Parse a JSON dict response and map values."""
    clean = clean_llm_response(dict_response)
    try:
        mapping = json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(mapping, dict):
        return {}
    results = {}
    for row in rows:
        val = str(row.get(field_name, ""))
        if val in mapping:
            results[val] = str(mapping[val])
    return results


def parse_regex_response(raw):
    # type: (str) -> tuple
    """Parse LLM regex response. Returns (regex_str, suggested_field_name)."""
    clean = clean_llm_response(raw)
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            return str(obj.get("regex", "")), str(obj.get("field_name", ""))
    except (json.JSONDecodeError, ValueError):
        pass
    return clean, ""


def parse_dict_response(raw):
    # type: (str) -> tuple
    """Parse LLM dict response. Returns (mapping_dict, suggested_field_name)."""
    clean = clean_llm_response(raw)
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


def run_extract(llm_cfg, collected, field_name, user_prompt, user_field_name):
    # type: (dict, list, str, str, str) -> tuple
    """Run extract mode: regex first, dict fallback.
    Returns (collected_with_new_field, source_str, ai_answer_str).
    """
    unique_vals = []
    seen = set()  # type: set
    for row in collected:
        val = str(row.get(field_name, ""))
        if val and val not in seen:
            seen.add(val)
            unique_vals.append(val)

    if not unique_vals:
        new_field = user_field_name or "ai_answer"
        for row in collected:
            row[new_field] = ""
        return collected, "error", "No values found in field '{0}'".format(
            field_name
        )

    use_dict_direct = len(unique_vals) <= DICT_DIRECT_THRESHOLD

    results = {}  # type: dict
    source = "dict"
    match_rate = 0.0
    llm_field_name = ""
    regex_str = ""

    if not use_dict_direct:
        sample = trim_values_to_budget(unique_vals[:MAX_SAMPLE_FOR_REGEX])
        regex_msg = (
            "Field name: {field}\n"
            "User request: {prompt}\n"
            "Sample values:\n{values}"
        ).format(
            field=field_name,
            prompt=user_prompt,
            values="\n".join("- " + v for v in sample),
        )
        try:
            regex_response = call_llm(llm_cfg, EXTRACT_REGEX_PROMPT, regex_msg)
            regex_str, llm_field_name = parse_regex_response(regex_response)
        except Exception:
            pass

        source = "regex"
        if regex_str:
            results, match_rate = try_regex_extract(
                regex_str, collected, field_name
            )

    new_field = user_field_name or llm_field_name or "ai_answer"
    new_field = re.sub(r"[^\w]", "_", new_field).strip("_") or "ai_answer"
    # Never overwrite the source field
    if new_field == field_name:
        new_field = "ai_answer"

    if use_dict_direct or match_rate < MIN_REGEX_MATCH_RATE:
        dict_vals = trim_values_to_budget(unique_vals[:MAX_UNIQUE_FOR_DICT])
        dict_msg = (
            "Field name: {field}\n"
            "User request: {prompt}\n"
            "Values to extract from ({count}):\n{values}\n\n"
            "Return a JSON object with field_name and mapping."
        ).format(
            field=field_name,
            prompt=user_prompt,
            count=len(dict_vals),
            values=json.dumps(dict_vals),
        )
        try:
            dict_response = call_llm(llm_cfg, EXTRACT_DICT_PROMPT, dict_msg)
            mapping, dict_field_name = parse_dict_response(dict_response)
            dict_results = try_dict_extract(
                json.dumps(mapping), collected, field_name
            )
            if dict_results:
                results = dict_results
                source = "dict"
                if not user_field_name and dict_field_name and not llm_field_name:
                    new_field = re.sub(
                        r"[^\w]", "_", dict_field_name
                    ).strip("_") or "ai_answer"
        except Exception:
            pass

    if not results:
        source = "error"

    extracted_count = 0
    for row in collected:
        val = str(row.get(field_name, ""))
        extracted = results.get(val, "")
        row[new_field] = extracted
        if extracted:
            extracted_count += 1

    answer = "Extracted '{new}' from '{src}' using {method} ({n}/{total} rows)".format(
        new=new_field, src=field_name, method=source,
        n=extracted_count, total=len(collected),
    )
    if source == "regex" and regex_str:
        answer += " | pattern: " + clean_llm_response(regex_str)

    return collected, source, answer
