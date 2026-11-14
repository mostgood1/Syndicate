"""One answer per BUILD for lookups a build would otherwise repeat once per row (todo #790, lane
nba-grid-per-build-lookups).

WHY. Refresh-worker builds each sport's book grid on its main thread while the board loop runs, CPU-bound and
nearly back to back, on another thread of the same process. Every call that releases the GIL (a stat, an lstat,
an open) must then win it back from that thread, which can cost up to the 5 ms switch interval each time.
Measured on the fleet 2026-11-13 (lane book-grid-overlay-starvation, H3): one NBA grid build made 137,279
stat-like calls, and 135,090 of them were three lookups asked once per priced row at about 10 calls each --
the game's season phase (`nba_game_projections.season_phase_for_date`) and the game-line and prop book-blend
weights (`nba_prop_calibration.book_blend_weights`). Each one re-resolved the NBA data root and re-stat'ed the
same file. Under a busy thread the stage that makes them grew 5x (8-9 s -> 40-47 s) against 2-3x for the
CPU-only stages, and at the 11-13 peak NBA's grid took 85 s median (max 164 s) and NBA's own in-play overlay
went stale at web once (371 s).

WHAT. `lookup_scope()` opens a per-build memo; `scoped_lookup(namespace, key, compute)` returns the memo's
answer for (namespace, key), computing it on first ask. Outside a scope -- every caller that is not a grid
build -- `scoped_lookup` just calls `compute()`, exactly as before. The scope lives in a ContextVar, so it is
private to the thread that opened it: the board loop's own calls to the same lookups never see it.

FRESHNESS. The memo lives for one build (tens of seconds) and is dropped when the build returns or raises. The
next build looks every file up again, so a rewritten blend file or scoreboard is picked up by the next build,
as before. Inside a build, every row now sees the same answer; before, a file rewritten mid-build could give
the rows before and after the rewrite different answers.

OFF SWITCH: SYNDICATE_BUILD_LOOKUP_SCOPE=off makes `lookup_scope()` a no-op, so every lookup resolves on every
call, as before.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Hashable, Iterator, TypeVar

T = TypeVar("T")

FLAG = "SYNDICATE_BUILD_LOOKUP_SCOPE"

_SCOPE: ContextVar[dict[tuple[str, Hashable], Any] | None] = ContextVar("build_lookup_scope", default=None)


def lookup_scope_enabled() -> bool:
    return str(os.environ.get(FLAG) or "").strip().lower() not in {"0", "off", "false", "no"}


def lookup_scope_active() -> bool:
    """True while this thread is inside an enabled `lookup_scope()`."""
    return _SCOPE.get() is not None


@contextmanager
def lookup_scope() -> Iterator[None]:
    """Open a per-build memo for this thread. A nested scope shares the outer one's memo. No-op when off."""
    if _SCOPE.get() is not None or not lookup_scope_enabled():
        yield
        return
    token = _SCOPE.set({})
    try:
        yield
    finally:
        _SCOPE.reset(token)


def scoped_lookup(namespace: str, key: Hashable, compute: Callable[[], T]) -> T:
    """`compute()`'s answer, remembered for the rest of the enclosing scope; outside a scope, `compute()`."""
    memo = _SCOPE.get()
    if memo is None:
        return compute()
    slot = (namespace, key)
    if slot in memo:
        return memo[slot]
    value = compute()
    memo[slot] = value
    return value
