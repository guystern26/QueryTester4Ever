from __future__ import annotations

import json
import logging
import ssl
import time

from .constants import LLM_TIMEOUT_SECS, MAX_RESPONSE_TOKENS, MIN_INTERVAL_SECS, AIGUY_DEADLINE_SECS

_logger = logging.getLogger("aiguy")
_SSL_CTX = ssl._create_unverified_context()

# Persistent HTTPS connection (reused across batch calls)
_conn = None  # type: any
_conn_host = ""

# Track timing across ALL LLM calls
last_call_ms = 0
last_prompt_chars = 0
total_call_ms = 0
total_calls = 0

# Global deadline — set by ai_guy.py at command start
_deadline = 0.0  # type: float


class DeadlineExceeded(Exception):
    """Raised when the total command time budget is exhausted."""
    pass


def set_deadline(t_start):
    # type: (float) -> None
    """Set the global deadline from command start time."""
    global _deadline
    _deadline = t_start + AIGUY_DEADLINE_SECS


def _get_connection(endpoint):
    # type: (str) -> any
    """Get or create a persistent HTTPS connection to the LLM endpoint."""
    global _conn, _conn_host
    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse

    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host_key = "{0}:{1}".format(host, port)

    if _conn and _conn_host == host_key:
        return _conn, parsed.path

    # New connection
    if parsed.scheme == "https":
        import http.client
        _conn = http.client.HTTPSConnection(host, port, timeout=LLM_TIMEOUT_SECS, context=_SSL_CTX)
    else:
        import http.client
        _conn = http.client.HTTPConnection(host, port, timeout=LLM_TIMEOUT_SECS)
    _conn_host = host_key
    return _conn, parsed.path


def get_llm_config(_session_key):
    # type: (str) -> dict
    """Read LLM settings from config.py. No KVStore, no HTTP calls."""
    import config as cfg

    endpoint = getattr(cfg, "LLM_ENDPOINT", "").strip()
    api_key = getattr(cfg, "LLM_API_KEY", "").strip()
    model = getattr(cfg, "LLM_MODEL", "gpt-4o-mini").strip()
    max_tokens = int(getattr(cfg, "LLM_MAX_TOKENS", 1024) or 1024)

    if not endpoint:
        raise ValueError("LLM_ENDPOINT not set in config.py.")
    if not api_key:
        raise ValueError("LLM_API_KEY not set in config.py.")

    return {
        "endpoint": endpoint,
        "model": model,
        "max_tokens": min(max_tokens, MAX_RESPONSE_TOKENS),
        "api_key": api_key,
    }


def call_llm(llm_cfg, system_prompt, user_message):
    # type: (dict, str, str) -> str
    """HTTPS POST to LLM. Reuses connection. Respects deadline."""
    global last_call_ms, last_prompt_chars, total_call_ms, total_calls, _conn

    # Check deadline before making the call
    if _deadline and time.time() > _deadline:
        raise DeadlineExceeded("Time budget exceeded ({0}s)".format(AIGUY_DEADLINE_SECS))

    body = json.dumps({
        "model": llm_cfg["model"],
        "max_tokens": llm_cfg["max_tokens"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }).encode("utf-8")

    last_prompt_chars = len(system_prompt) + len(user_message)
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + llm_cfg["api_key"],
        "Connection": "keep-alive",
    }

    t0 = time.time()
    try:
        conn, path = _get_connection(llm_cfg["endpoint"])
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
        except Exception:
            # Connection stale — reconnect once
            _conn = None
            conn, path = _get_connection(llm_cfg["endpoint"])
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")

        if resp.status >= 400:
            raise ValueError("LLM HTTP {0}: {1}".format(resp.status, raw[:200]))
        data = json.loads(raw)
    except ValueError:
        raise
    except Exception as exc:
        _conn = None
        raise ValueError("Cannot reach LLM: {0}".format(exc))

    last_call_ms = int((time.time() - t0) * 1000)
    total_call_ms += last_call_ms
    total_calls += 1

    _logger.info(
        "aiguy llm_call prompt_chars=%d response_ms=%d",
        last_prompt_chars, last_call_ms,
    )

    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    if not content:
        content = data.get("content", "") or data.get("output", "") or ""
    if not content:
        content = (choice.get("delta") or {}).get("content", "")
    if not content:
        finish = choice.get("finish_reason", "unknown")
        _logger.warning(
            "aiguy empty LLM response: finish_reason=%s model=%s chars_sent=%d",
            finish, llm_cfg.get("model", "?"), last_prompt_chars,
        )
    if not content:
        finish = choice.get("finish_reason", "unknown")
        return "(empty AI response — finish_reason={0}, {1}ms, {2} chars sent)".format(
            finish, last_call_ms, last_prompt_chars)
    return content


def should_skip_scheduled(session_key, saved_search_name):
    # type: (str, str) -> bool
    """Check if this scheduled search ran less than 10 min ago."""
    if not saved_search_name or not session_key:
        return False
    try:
        import config as cfg
        import datetime
        from splunklib import client as splunk_client

        service = splunk_client.Service(
            token=session_key,
            host=cfg.SPLUNK_HOST,
            port=cfg.SPLUNK_PORT,
            scheme=cfg.SPLUNK_SCHEME,
            app="QueryTester",
            owner="nobody",
        )
        ss = service.saved_searches[saved_search_name]
        jobs = ss.history()
        if len(jobs) < 2:
            return False
        prev = jobs[1]
        try:
            dispatch_time = prev["published"] or ""
        except (KeyError, AttributeError):
            return False
        if not dispatch_time:
            return False
        clean = str(dispatch_time).split(".")[0].replace("T", " ")
        dt = datetime.datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        age_secs = (datetime.datetime.utcnow() - dt).total_seconds()
        if age_secs < MIN_INTERVAL_SECS:
            return True
    except Exception:
        pass
    return False


def log_usage(mode, field, prompt, source, row_count, t_start):
    # type: (str, str, str, str, int, float) -> None
    try:
        dur = int((time.time() - t_start) * 1000)
        _logger.info(
            "aiguy mode=%s field=%s source=%s rows=%d duration=%dms prompt=%s",
            mode or "prompt", field or "-", source,
            row_count, dur, (prompt or "-")[:100],
        )
    except Exception:
        pass
