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

THE IN-PLAY OVERLAY TOO (lane nba-overlay-card-cost, 2026-11-16). The overlay is built on the same main thread
right after the grid is written, outside the grid's scope, so it now opens its own (`build_inplay_overlay`). Its
card builder checks files once per card or per side rather than once per row: measured offline on the 11-16 NBA
grid, a warm 2,000-card build made 47,565 stat and 2,376 scandir calls -- the data root's `resolve()` behind the
calibration profile path (24,280), the closing-line index stat (7,664), the NBA odds root's `resolve()` (6,776),
the calibration profile's stat signature (4,856), the team-results glob and stat (2,376 + 2,376). Beside one busy
thread that build took 139.9 s against 3.6 s alone; answering each path once per build took it to 6.1 s, with the
same cards. `scoped_stat_signature` is the shared once-per-build stat; `scope_counts` reports how many asks a scope
computed and how many it answered from the memo, which the INPLAY_OVERLAY line prints.

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


class _Memo(dict):
    """A scope's answers, plus how many asks it computed (`misses`) and answered from memory (`hits`)."""

    __slots__ = ("hits", "misses")

    def __init__(self) -> None:
        super().__init__()
        self.hits = 0
        self.misses = 0


_SCOPE: ContextVar[_Memo | None] = ContextVar("build_lookup_scope", default=None)


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
    token = _SCOPE.set(_Memo())
    try:
        yield
    finally:
        _SCOPE.reset(token)


def scope_counts() -> tuple[int, int] | None:
    """(computed, answered from memory) so far in this thread's scope; None outside one (or when off)."""
    memo = _SCOPE.get()
    return None if memo is None else (memo.misses, memo.hits)


def scoped_lookup(namespace: str, key: Hashable, compute: Callable[[], T]) -> T:
    """`compute()`'s answer, remembered for the rest of the enclosing scope; outside a scope, `compute()`."""
    memo = _SCOPE.get()
    if memo is None:
        return compute()
    slot = (namespace, key)
    if slot in memo:
        memo.hits += 1
        return memo[slot]
    value = compute()
    memo[slot] = value
    memo.misses += 1
    return value


def _stat_signature_now(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def scoped_stat_signature(path: Any) -> tuple[int, int] | None:
    """`(st_mtime_ns, st_size)` of `path`, or None when it cannot be stat'ed (absent counts: an absent file stays
    absent for the rest of the build). Once per path per build inside a scope; a fresh `os.stat` outside one."""
    key = os.fspath(path)
    return scoped_lookup("stat_signature", key, lambda: _stat_signature_now(key))
