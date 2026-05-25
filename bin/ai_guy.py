# -*- coding: utf-8 -*-
"""
ai_guy.py — | aiguy — Splunk custom streaming command.
chunked=true + splunklib. All heavy imports deferred.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Defer splunklib import to module level (required by dispatch)
# but keep it as light as possible
from splunklib.searchcommands import (
    dispatch,
    StreamingCommand,
    Configuration,
    Option,
)

_ANALYSIS_MODES = {
    "summary", "anomaly", "trend", "compare", "alert", "health", "top"
}
_SPECIAL_MODES = {"extract", "enrich", "explain", "suggest", "dashboard"}
_ALL_MODES = _ANALYSIS_MODES | _SPECIAL_MODES


@Configuration()
class AiGuyCommand(StreamingCommand):

    prompt = Option(require=False, default=None)
    mode = Option(require=False, default=None)
    field = Option(require=False, default=None)
    value = Option(require=False, default=None)
    new_field_name = Option(require=False, default=None)

    def stream(self, records):
        t0 = time.time()

        session_key = ""
        full_spl = ""
        sid = ""
        try:
            full_spl = self._metadata.searchinfo.search or ""
            sid = self._metadata.searchinfo.sid or ""
            session_key = self._metadata.searchinfo.session_key or ""
        except Exception:
            pass

        mode = (self.mode or "").strip().lower()
        field = (self.field or "").strip()
        value = self.value
        prompt = (self.prompt or "").strip()
        new_field = (self.new_field_name or "").strip()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # ── Validate ────────────────────────────────────────────────
        err = ""
        if mode and mode not in _ALL_MODES:
            err = 'Unknown mode="{0}". Valid: {1}.'.format(
                mode, ", ".join(sorted(_ALL_MODES)))
        elif not mode and not prompt:
            err = 'Missing prompt= or mode=. Example: | aiguy prompt="..."'
        elif value is not None and not field:
            err = 'value= requires field=.'
        if err:
            for record in records:
                yield dict(record, ai_answer=err, aiguy_timestamp=ts, aiguy_source="error")
                break
            return

        # ── Rate limit (scheduled only) ─────────────────────────────
        if sid.startswith("scheduler__"):
            parts = sid.split("__")
            if len(parts) >= 2:
                from aiguy.llm import should_skip_scheduled
                if should_skip_scheduled(session_key, parts[1]):
                    first = True
                    for record in records:
                        row = dict(record)
                        if first:
                            row["ai_answer"] = "(aiguy skipped — last run < 10 min ago)"
                            first = False
                        row["aiguy_timestamp"] = ts
                        row["aiguy_source"] = "rate-limited"
                        yield row
                    return

        # ── LLM config ──────────────────────────────────────────────
        from aiguy.llm import get_llm_config, set_deadline
        set_deadline(t0)
        try:
            llm_cfg = get_llm_config(session_key)
        except Exception as exc:
            for record in records:
                yield dict(record, ai_answer="AI error: {0}".format(exc),
                           aiguy_timestamp=ts, aiguy_source="error")
                break
            return

        # ── Dispatch ────────────────────────────────────────────────
        if mode == "dashboard":
            from aiguy.dashboard import handle_dashboard
            gen = handle_dashboard(records, llm_cfg, prompt, t0)
        elif mode == "explain":
            from aiguy.handlers import handle_explain
            gen = handle_explain(records, llm_cfg, full_spl, field, prompt, t0)
        elif mode == "suggest":
            from aiguy.handlers import handle_suggest
            gen = handle_suggest(records, llm_cfg, full_spl, field, prompt, t0)
        elif mode == "enrich":
            from aiguy.handlers import handle_enrich
            gen = handle_enrich(records, llm_cfg, field, prompt, new_field, t0)
        elif mode == "extract":
            from aiguy.handlers import handle_extract
            gen = handle_extract(records, llm_cfg, field, prompt, new_field, t0)
        else:
            from aiguy.handlers import handle_analysis
            gen = handle_analysis(records, llm_cfg, full_spl, mode,
                                 field, value, prompt, self.mode or "", t0)

        for row in gen:
            yield row


dispatch(AiGuyCommand, sys.argv, sys.stdin, sys.stdout, __name__)
