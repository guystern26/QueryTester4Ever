# -*- coding: utf-8 -*-
"""
scope_evaluator.py
Evaluate pass/fail based on per-row results and the validation scope.

Uses a SCOPE_HANDLERS registry dict — add new scopes by adding entries,
never with if/elif chains.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from logger import get_logger


logger = get_logger(__name__)


SCOPE_LABELS: Dict[str, str] = {
    "all_events": "all events",
    "any_event": "at least one event",
    "exactly_n": "exactly {n} event(s)",
    "at_least_n": "at least {n} event(s)",
    "at_most_n": "at most {n} event(s)",
}


def _resolve_n(scope_n: Optional[int], validation_scope: str) -> int:
    """Return scope_n or 0 with a warning when missing for N-based scopes."""
    if scope_n is not None:
        return scope_n
    logger.warning(
        "Scope %r requires scopeN but it was not provided; defaulting to 0.",
        validation_scope,
    )
    return 0


def _scope_all_events(per_row: List[bool], n: int) -> bool:
    return all(per_row)


def _scope_any_event(per_row: List[bool], n: int) -> bool:
    return any(per_row)


def _scope_exactly_n(per_row: List[bool], n: int) -> bool:
    return sum(per_row) == n


def _scope_at_least_n(per_row: List[bool], n: int) -> bool:
    return sum(per_row) >= n


def _scope_at_most_n(per_row: List[bool], n: int) -> bool:
    return sum(per_row) <= n


ScopeHandler = Callable[[List[bool], int], bool]

SCOPE_HANDLERS: Dict[str, ScopeHandler] = {
    "all_events": _scope_all_events,
    "any_event": _scope_any_event,
    "exactly_n": _scope_exactly_n,
    "at_least_n": _scope_at_least_n,
    "at_most_n": _scope_at_most_n,
}


def evaluate_scope(
    per_row: List[bool],
    validation_scope: str,
    scope_n: Optional[int],
) -> bool:
    """Decide pass/fail based on per-row results and the validation scope."""
    if not per_row:
        return False

    handler = SCOPE_HANDLERS.get(validation_scope)
    if handler is None:
        # Unknown scope — fall back to any_event
        return any(per_row)

    n = _resolve_n(scope_n, validation_scope)
    return handler(per_row, n)
