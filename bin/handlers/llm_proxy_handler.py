# -*- coding: utf-8 -*-
"""
llm_proxy_handler.py — Backend proxy for LLM API calls.

Reads endpoint/model/key from admin Setup config (KVStore + secrets).
The browser never talks to the LLM provider directly, avoiding CORS.
"""
from __future__ import annotations

import json
import ssl
from typing import Any, Dict

from logger import get_logger
from handler_utils import get_session_key, json_response, normalize_payload

logger = get_logger(__name__)


def _get_llm_config(session_key):
    # type: (str) -> Dict[str, Any]
    """Read LLM settings from runtime config + secrets."""
    from runtime_config import get_runtime_config
    cfg = get_runtime_config(session_key)

    endpoint = str(cfg.get("llm_endpoint") or "").strip()
    if not endpoint:
        raise ValueError(
            "AI features are disabled. Configure LLM endpoint in the admin Setup page."
        )

    model = str(cfg.get("llm_model") or "gpt-4o-mini").strip()
    max_tokens = int(cfg.get("llm_max_tokens") or 4096)

    # API key from secrets
    api_key = str(cfg.get("llm_api_key") or "").strip()
    if not api_key:
        raise ValueError(
            "LLM API key is not configured. Set it in the admin Setup page."
        )

    return {
        "endpoint": endpoint,
        "model": model,
        "max_tokens": max_tokens,
        "api_key": api_key,
    }


def _call_llm(llm_cfg, system_prompt, user_message):
    # type: (Dict[str, Any], str, str) -> str
    """POST to the LLM endpoint and return the assistant message content."""
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError
    except ImportError:
        from urllib2 import Request, urlopen, HTTPError, URLError

    body = json.dumps({
        "model": llm_cfg["model"],
        "max_tokens": llm_cfg["max_tokens"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }).encode("utf-8")

    req = Request(llm_cfg["endpoint"], data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + llm_cfg["api_key"])

    ctx = ssl._create_unverified_context()
    try:
        resp = urlopen(req, timeout=60, context=ctx)
        data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:200]
        logger.error("LLM HTTP %d: %s", exc.code, err_body)
        raise ValueError("LLM request failed ({0}): {1}".format(exc.code, err_body))
    except URLError as exc:
        logger.error("LLM connection error: %s", exc.reason)
        raise ValueError("Cannot reach LLM endpoint: {0}".format(exc.reason))

    # Try OpenAI-style response first, then common alternatives
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    if not content:
        content = (choice.get("delta") or {}).get("content", "")
    if not content:
        content = data.get("content", "") or data.get("output", "") or data.get("text", "")
    if not content:
        raw_resp = json.dumps(data)[:500]
        logger.error("LLM empty response. Raw: %s", raw_resp)
        raise ValueError("Empty response from LLM. Check query_tester.log for raw response.")
    return content


def _call_llm_chat(llm_cfg, system_prompt, messages):
    # type: (Dict[str, Any], str, list) -> str
    """POST multi-turn messages to the LLM endpoint. Returns assistant content."""
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError
    except ImportError:
        from urllib2 import Request, urlopen, HTTPError, URLError

    api_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = str(msg.get("content", ""))
        if role in ("user", "assistant") and content:
            api_messages.append({"role": role, "content": content})

    total_chars = sum(len(m["content"]) for m in api_messages)
    logger.info("LLM chat: %d messages, ~%d chars total", len(api_messages), total_chars)

    body = json.dumps({
        "model": llm_cfg["model"],
        "max_tokens": llm_cfg["max_tokens"],
        "messages": api_messages,
    }).encode("utf-8")

    req = Request(llm_cfg["endpoint"], data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + llm_cfg["api_key"])

    ctx = ssl._create_unverified_context()
    try:
        resp = urlopen(req, timeout=120, context=ctx)
        raw_resp = resp.read().decode("utf-8")
        data = json.loads(raw_resp)
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        logger.error("LLM chat HTTP %d: %s", exc.code, err_body)
        raise ValueError("LLM request failed ({0}): {1}".format(exc.code, err_body))
    except URLError as exc:
        logger.error("LLM chat connection error: %s", exc.reason)
        raise ValueError("Cannot reach LLM endpoint: {0}".format(exc.reason))

    # Try standard OpenAI format first, then common alternatives
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    if not content:
        # Some models use delta instead of message
        content = (choice.get("delta") or {}).get("content", "")
    if not content:
        # Some models put content at response root
        content = data.get("content", "")
    if not content:
        # Some models use output/text fields
        content = data.get("output", data.get("text", ""))
    if not content:
        logger.error("LLM chat empty response. Raw: %s", raw_resp[:500])
        raise ValueError("Empty response from LLM. Check query_tester.log for raw response.")
    return content


def handle_llm_proxy(request):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Handle POST /data/tester/llm — proxy an LLM call."""
    method = request.get("method", "GET").upper()
    if method != "POST":
        return json_response({"error": "Method not allowed"}, 405)

    try:
        session_key = get_session_key(request)
        payload = normalize_payload(request.get("payload"))

        system_prompt = str(payload.get("systemPrompt", "")).strip()
        messages = payload.get("messages")

        # Multi-turn chat mode: { systemPrompt, messages: [...] }
        if isinstance(messages, list) and len(messages) > 0:
            if not system_prompt:
                return json_response(
                    {"error": "systemPrompt is required for chat mode."}, 400,
                )
            llm_cfg = _get_llm_config(session_key)
            content = _call_llm_chat(llm_cfg, system_prompt, messages)
            return json_response({"content": content})

        # Single-shot mode: { systemPrompt, userMessage }
        user_message = str(payload.get("userMessage", "")).strip()
        if not system_prompt or not user_message:
            return json_response(
                {"error": "systemPrompt and userMessage are required."}, 400,
            )

        llm_cfg = _get_llm_config(session_key)
        content = _call_llm(llm_cfg, system_prompt, user_message)
        return json_response({"content": content})
    except ValueError as exc:
        logger.warning("LLM proxy client error: %s", exc)
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:
        logger.error("LLM proxy error: %s", exc, exc_info=True)
        return json_response({"error": "LLM proxy error: {0}".format(exc)}, 500)
