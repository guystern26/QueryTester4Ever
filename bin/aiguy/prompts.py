from __future__ import annotations

# Injected into prompts that take user instructions
_UP = (
    " Follow the user's prompt= LITERALLY — single-line answer, "
    "no newlines, no extra context."
)

SYSTEM_PROMPT = (
    "You are an AI analyst in a Splunk pipeline. "
    "1-3 sentences, reference specific values. "
    "Plain text, under 80 words, no markdown." + _UP
)

EXPLAIN_PROMPT = (
    "Explain this SPL query in plain English. "
    "2-4 sentences, under 80 words."
)

SUGGEST_PROMPT = (
    "Suggest ONE follow-up SPL query. "
    "Line 1: raw SPL. Line 2: why. No markdown."
)

ENRICH_PROMPT = (
    "You receive numbered values and a user instruction." + _UP + "\n"
    "Return ONLY JSON: "
    '{"field_name": "snake_case_name", "mapping": {"1": "answer", "2": "answer"}}\n'
    "Use the NUMBER as key. Every number must appear. No markdown."
)

EXTRACT_REGEX_PROMPT = (
    "Generate a Python 3.7 regex to extract what the user asked for." + _UP + "\n"
    'Return ONLY JSON: {"regex": "(?P<result>...)", "field_name": "name"}\n'
    "Use precise classes: digits=\\d, letters=[a-zA-Z]. No . as catch-all."
)

EXTRACT_DICT_PROMPT = (
    "Extract what the user asked from each value." + _UP + "\n"
    'Return ONLY JSON: {"field_name": "name", "mapping": {"input": "extracted"}}\n'
    "If user says 'only digits', return only digits — not 'code=400' but '400'."
)

MODE_PROMPTS = {
    "summary": "Summarize key findings. What are the main takeaways?",
    "anomaly": "Identify outliers or unusual patterns. What stands out?",
    "trend": "Describe trends over time. Increasing, decreasing, or stable?",
    "compare": "Compare the groups. What are the main differences?",
    "alert": "Should an alert be triggered? Yes or no, and why briefly.",
    "health": "Assess overall health. Any concerns?",
    "top": "What are the top items and why are they significant?",
}

SPECIAL_MODES = {"extract", "enrich", "explain", "suggest", "dashboard"}
