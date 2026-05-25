from __future__ import annotations

MAX_ROWS_FOR_AI = 20           # unique rows sent to LLM
MAX_SCAN_FOR_SAMPLE = 10000    # scan this many rows to find unique ones
MAX_COLS_FOR_AI = 10           # columns sent to LLM
MAX_CELL_LEN = 80              # truncate cell values for LLM prompt
MAX_PROMPT_CHARS = 8000        # total char budget for data in LLM prompt
LLM_TIMEOUT_SECS = 15          # HTTP timeout per LLM call
AIGUY_DEADLINE_SECS = 25       # total time budget for entire command
MAX_RESPONSE_TOKENS = 1024     # cap LLM response length (analysis modes)
MAX_RESPONSE_TOKENS_ENRICH = 2000  # enrich needs more room for per-value explanations
ENRICH_BATCH_CHARS = 3000      # char budget per enrich LLM call (lower for weak models)
MIN_INTERVAL_SECS = 600        # 10 min — skip LLM if scheduled search ran recently
MAX_UNIQUE_FOR_DICT = 50       # max unique values sent to LLM for dict/enrich
MAX_SAMPLE_FOR_REGEX = 15      # sample values sent to LLM for regex generation
MIN_REGEX_MATCH_RATE = 0.5     # fall back to dict if regex matches < 50%
DICT_DIRECT_THRESHOLD = 8      # <= this many unique values: skip regex, use dict
