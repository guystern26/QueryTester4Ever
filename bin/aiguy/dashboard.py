from __future__ import annotations

import json
import re
import ssl
import time
import xml.etree.ElementTree as ET

from .constants import MAX_PROMPT_CHARS
from .formatter import format_table
from .llm import call_llm, log_usage
from .prompts import SYSTEM_PROMPT


def _get_dashboard_xml(app, dashboard_name):
    # type: (str, str) -> str
    """Fetch dashboard XML via Splunk REST API using admin creds."""
    import config as cfg
    try:
        from urllib.request import Request, urlopen
    except ImportError:
        from urllib2 import Request, urlopen

    url = "{scheme}://{host}:{port}/servicesNS/nobody/{app}/data/ui/views/{name}?output_mode=json".format(
        scheme=cfg.SPLUNK_SCHEME, host=cfg.SPLUNK_HOST,
        port=cfg.SPLUNK_PORT, app=app, name=dashboard_name,
    )
    req = Request(url)
    # Basic auth
    import base64
    creds = base64.b64encode(
        "{0}:{1}".format(cfg.SPLUNK_USERNAME, cfg.SPLUNK_PASSWORD).encode()
    ).decode()
    req.add_header("Authorization", "Basic " + creds)

    ctx = ssl._create_unverified_context()
    resp = urlopen(req, timeout=10, context=ctx)
    data = json.loads(resp.read().decode("utf-8"))
    return data["entry"][0]["content"]["eai:data"]


def _extract_panel_searches(xml_str):
    # type: (str) -> list
    """Extract search queries and panel titles from dashboard XML."""
    panels = []
    root = ET.fromstring(xml_str)
    for panel_elem in root.iter("panel"):
        title_elem = panel_elem.find("title")
        title = title_elem.text if title_elem is not None else "Untitled"
        # Check chart, table, single, map, etc.
        for viz_type in ("chart", "table", "single", "map", "event", "viz"):
            viz = panel_elem.find(viz_type)
            if viz is None:
                continue
            search_elem = viz.find("search")
            if search_elem is None:
                continue
            query_elem = search_elem.find("query")
            if query_elem is not None and query_elem.text:
                spl = query_elem.text.strip()
                # Skip panels that reference base searches or tokens
                if spl.startswith("$") or not spl:
                    continue
                panels.append({"title": title, "spl": spl})
    return panels


def _run_panel_query(app, spl):
    # type: (str, str) -> list
    """Run a panel's SPL and return up to 10 result rows."""
    import config as cfg
    try:
        from splunklib import client as sc
        service = sc.connect(
            host=cfg.SPLUNK_HOST, port=cfg.SPLUNK_PORT,
            scheme=cfg.SPLUNK_SCHEME,
            username=cfg.SPLUNK_USERNAME,
            password=cfg.SPLUNK_PASSWORD,
            app=app, autologin=True,
        )
        # Run as oneshot (uses cache if available)
        import splunklib.results as results_mod
        result_stream = service.jobs.oneshot(
            spl, count=10, output_mode="json",
        )
        data = json.loads(result_stream.read().decode("utf-8"))
        rows = data.get("results", [])
        return rows[:10]
    except Exception:
        return []


def handle_dashboard(rows_unused, llm_cfg, prompt, t_start):
    """Fetch all panel results from a dashboard and summarize."""
    # prompt should be: "app/dashboard_name" or "app/dashboard_name: custom question"
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    if not prompt or "/" not in prompt:
        yield {
            "ai_answer": (
                'Dashboard mode requires: | aiguy mode="dashboard" '
                'prompt="app_name/dashboard_name" or '
                'prompt="app_name/dashboard_name: your question"'
            ),
            "aiguy_timestamp": ts,
            "aiguy_source": "error",
        }
        return

    # Split "app/dashboard: optional question"
    if ":" in prompt:
        path, question = prompt.split(":", 1)
        question = question.strip()
    else:
        path = prompt
        question = "Summarize the overall situation shown by this dashboard. What needs attention?"

    parts = path.strip().split("/", 1)
    app = parts[0].strip()
    dashboard_name = parts[1].strip() if len(parts) > 1 else ""

    if not app or not dashboard_name:
        yield {
            "ai_answer": 'Invalid format. Use: prompt="app_name/dashboard_name"',
            "aiguy_timestamp": ts,
            "aiguy_source": "error",
        }
        return

    # Fetch dashboard XML
    try:
        xml_str = _get_dashboard_xml(app, dashboard_name)
    except Exception as exc:
        yield {
            "ai_answer": "Cannot fetch dashboard: {0}".format(exc),
            "aiguy_timestamp": ts,
            "aiguy_source": "error",
        }
        return

    panels = _extract_panel_searches(xml_str)
    if not panels:
        yield {
            "ai_answer": "No panel searches found in dashboard.",
            "aiguy_timestamp": ts,
            "aiguy_source": "error",
        }
        return

    # Run each panel and collect results
    panel_summaries = []
    char_budget = MAX_PROMPT_CHARS
    used = 0
    for p in panels:
        result_rows = _run_panel_query(app, p["spl"])
        if not result_rows:
            panel_summaries.append(
                "Panel '{0}': (no results)".format(p["title"])
            )
            continue
        table = format_table(result_rows, char_budget=1500)
        entry = "Panel '{0}':\n{1}".format(p["title"], table)
        if used + len(entry) > char_budget:
            panel_summaries.append(
                "Panel '{0}': ({1} rows, skipped — budget full)".format(
                    p["title"], len(result_rows))
            )
            continue
        panel_summaries.append(entry)
        used += len(entry)

    user_msg = (
        "Dashboard: {app}/{name}\n"
        "Question: {q}\n\n"
        "{panels}"
    ).format(
        app=app, name=dashboard_name, q=question,
        panels="\n\n".join(panel_summaries),
    )

    try:
        answer = call_llm(llm_cfg, SYSTEM_PROMPT, user_msg)
        source = "live"
    except Exception as exc:
        answer = "AI error: {0}".format(exc)
        source = "error"

    yield {
        "ai_answer": answer,
        "aiguy_timestamp": ts,
        "aiguy_source": "{0} ({1} panels)".format(source, len(panels)),
        "dashboard": "{0}/{1}".format(app, dashboard_name),
        "panels_count": str(len(panels)),
    }

    log_usage("dashboard", "", prompt, source, len(panels), t_start)
