"""Publish the scoreboard chips on their OWN cadence, not the board build's. `#632`.

WHY THIS EXISTS, measured on refresh-worker 2026-09-08. The chips web serves are
written once per `build_layer2_shortlist`, so their cadence IS the heavy board
build's cadence. Consecutive `GAME_CHIPS_PUBLISHED` for the ONE date web reads
(`central_today_iso()`) ran a **24.1 minute median, range 12.6-32.2**, against
the endpoint's **120 s** freshness threshold -- 12x over. Per date matters: the
worker alternates today and tomorrow, so an all-dates gap understates what web
sees by ~2x.

The consequence is on web, and it is why this is worth new worker work at all:
`/api/board/game-chips` returned `source=inline_artifact_stale` on 5 of 5 probes,
so EVERY request ran the per-sport (and per-league x 2-matchday, for soccer)
fan-out inline at 5-9 s a build, and 20% of organic requests to that route
exceeded the 5 s health-check budget.

THE CHIPS DEPEND ON NONE OF THE BOARD BUILD. `layer2_shortlist.py` says so in its
own comment -- they are built from per-sport provider payloads, not from the
grid, the candidates or the cards. The coupling bought nothing and cost the
scoreboard ~24 minutes of staleness.

WHY NOT JUST RAISE THE THRESHOLD. `SYNDICATE_GAME_CHIP_ARTIFACT_MAX_AGE_SECONDS`
would make the endpoint accept a staler artifact and stop fanning out. `#564`'s
comment already names that trade -- "favour the worker and accept a staler
scoreboard". It hides the symptom (the scoreboard really would be ~24 min old),
so it is the fallback, not the fix.

THIS IS NEW PERIODIC WORK ON A 4 GB WORKER WITH AN OOM HISTORY, and `#241` is the
precedent where exactly that caused a restart loop. So it is bounded three ways,
and every refusal is NAMED rather than silent:

  1. An interval gate, default 120 s, floored at 60 s.
  2. A HEADROOM gate using the same `memory_headroom_snapshot` the odds-refresh
     and live-lens gates use. UNMEASURABLE HEADROOM COUNTS AS INSUFFICIENT --
     mapping "unknown" onto the permissive branch is how a failed read becomes a
     relaxed rule with nothing emitted.
  3. ONE date only (`central_today_iso()`), because that is the only date the
     endpoint reads. Publishing tomorrow's chips here would double the cost for a
     date nobody is serving yet.

It never raises. A failure must leave the board exactly as it found it -- web
still has its own inline build, so this degrades rather than breaks.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

# Enough headroom for one chip fan-out with room to spare. The chip build is far
# cheaper than the shortlist stage (14-27 s, +27..181 MB) that
# `_LAYER2_MIN_SAFE_HEADROOM_BYTES` is sized for, but this floor is deliberately
# NOT smaller: the failure being guarded is an OOM kill of the whole worker, and
# being generous costs a skipped publish while being tight costs the service.
_MIN_HEADROOM_BYTES = 600 * 1024 * 1024

_state: dict[str, Any] = {
    "last_publish_at": 0.0,
    "last_date": "",
    "publishes": 0,
    "skips": {},
}


def publish_interval_seconds() -> float:
    """Seconds between chip publishes. 120 s default, 60 s floor.

    120 s matches the endpoint's own `_game_chip_artifact_max_age_seconds`, so a
    publish lands inside the window the reader already treats as authoritative.
    The floor exists because this is WORKER work: lowering it to 5 s would be a
    duty-cycle change disguised as a config tweak.
    """
    raw = str(os.environ.get("SYNDICATE_GAME_CHIP_PUBLISH_SECONDS") or "").strip()
    if raw:
        try:
            return max(60.0, float(raw))
        except (TypeError, ValueError):
            pass
    return 120.0


def enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_GAME_CHIP_PUBLISH_ENABLED") or "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def _note_skip(reason: str) -> None:
    _state["skips"][reason] = int(_state["skips"].get(reason, 0)) + 1


def publisher_state() -> dict[str, Any]:
    """Counters for a reader. `skips` is per REASON, so a publisher that is
    skipping forever cannot look like one that is merely idle."""
    return {
        "last_publish_at": _state["last_publish_at"],
        "last_date": _state["last_date"],
        "publishes": _state["publishes"],
        "skips": dict(_state["skips"]),
        "interval_seconds": publish_interval_seconds(),
    }


def _default_sports() -> list[str]:
    from syndicate.features.shared.game_chip_scoreboard import GAME_CHIP_DEFAULT_SPORTS

    return sorted(set(GAME_CHIP_DEFAULT_SPORTS))


def maybe_publish_game_chips(
    *,
    now: float | None = None,
    force: bool = False,
    build: Callable[[str, list[str]], list] | None = None,
    write: Callable[[str, list], Any] | None = None,
    today: Callable[[], str] | None = None,
    headroom: Callable[[int], Any] | None = None,
    sports: list[str] | None = None,
) -> dict[str, Any] | None:
    """Publish today's chips if the interval has elapsed and memory allows.

    Returns a small result dict when it published, else None. NEVER RAISES.

    The collaborators are injectable so the tests can drive the gates without a
    provider registry, an artifact tree or a cgroup. The gates ARE the thing
    under test, and a test needing production wiring to reach them would not be
    run.
    """
    try:
        if not enabled():
            _note_skip("disabled")
            return None

        # WORKER ONLY, by the same authority the layer2 fast path uses rather
        # than a second copy of the test. Running this inside a web request
        # would reinstate exactly the request-path fan-out `#545` removed.
        try:
            from syndicate.features.shared.request_path_guard import (
                refuse_if_compute_in_request_path,
            )
        except ImportError:
            pass
        else:
            try:
                refuse_if_compute_in_request_path("game_chip_publish")
            except Exception:
                _note_skip("request_path")
                return None

        moment = float(now if now is not None else time.time())
        interval = publish_interval_seconds()
        last = float(_state.get("last_publish_at") or 0.0)
        if not force and last and (moment - last) < interval:
            _note_skip("interval")
            return None

        if headroom is None:
            from syndicate.features.shared.memory_observability import (
                memory_headroom_snapshot,
            )

            headroom = memory_headroom_snapshot
        snapshot = headroom(_MIN_HEADROOM_BYTES)
        # None means headroom COULD NOT BE MEASURED. That counts as insufficient.
        if not snapshot or not snapshot.get("sufficient", False):
            _note_skip("headroom")
            print(
                "[game_chip_publisher] CHIP_PUBLISH_SKIPPED reason=headroom "
                f"headroom_mb={'unmeasurable' if not snapshot else snapshot.get('headroom_mb')}",
                flush=True,
            )
            return None

        if today is None:
            from syndicate.features.shared.timezone import central_today_iso

            today = central_today_iso
        selected_date = str(today() or "").strip()
        if not selected_date:
            _note_skip("no_date")
            return None

        chip_sports = list(sports) if sports else _default_sports()
        if build is None:
            from syndicate.features.shared.game_chip_scoreboard import build_game_chips

            build = build_game_chips
        if write is None:
            from pipeline.intelligence_state import write_game_chips

            write = write_game_chips

        started = time.time()
        chips = build(selected_date, chip_sports) or []
        # AN EMPTY BUILD IS NOT PUBLISHED. Overwriting a good artifact with zero
        # chips blanks every sport's strip, and a chip-less strip is
        # indistinguishable from a sport with no games -- the exact confusion
        # `#545` called out. A stale scoreboard beats an empty one.
        if not chips:
            _note_skip("empty_build")
            print(
                "[game_chip_publisher] CHIP_PUBLISH_SKIPPED reason=empty_build "
                f"date={selected_date}",
                flush=True,
            )
            return None

        write(selected_date, chips)
        gap = (moment - last) if last else None
        _state["last_publish_at"] = moment
        _state["last_date"] = selected_date
        _state["publishes"] = int(_state["publishes"]) + 1
        print(
            f"[game_chip_publisher] CHIP_PUBLISH_TICK date={selected_date} "
            f"chips={len(chips)} build_ms={round((time.time() - started) * 1000.0, 1)} "
            f"gap_s={'first' if gap is None else round(gap, 1)} "
            f"interval_s={interval}",
            flush=True,
        )
        return {"date": selected_date, "chips": len(chips), "gap_seconds": gap}
    except Exception as exc:  # pragma: no cover - never costs the worker loop
        _note_skip(type(exc).__name__)
        print(
            f"[game_chip_publisher] CHIP_PUBLISH_FAILED error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


_thread_lock = threading.Lock()
_thread: threading.Thread | None = None
_thread_stop = threading.Event()


def _publisher_loop() -> None:
    """Own clock, because THE CALLER'S CLOCK IS THE PROBLEM.

    MEASURED before writing this: the worker's `LOOP_ITERATION` fires every
    **1-18 minutes, median ~15** -- it blocks on the board build and on its own
    condition wait. So calling `maybe_publish_game_chips()` from that tick would
    inherit exactly the cadence this exists to fix. A dedicated thread is the
    only way to reach a 120 s publish interval.

    It is deliberately dumb: sleep, try, repeat. Every real decision (interval,
    headroom, empty build) lives in `maybe_publish_game_chips`, so this loop
    cannot develop a second, divergent set of gates.
    """
    while not _thread_stop.is_set():
        try:
            maybe_publish_game_chips()
        except Exception:
            # `maybe_publish_game_chips` already swallows and names its own
            # failures; this is the belt for anything that escapes it. A dead
            # publisher thread would be silent forever.
            pass
        # Poll at half the interval so a publish lands close to when it is due
        # without the thread becoming its own duty-cycle problem. Bounded at 30 s
        # so a long interval does not make shutdown sluggish.
        _thread_stop.wait(timeout=min(30.0, max(5.0, publish_interval_seconds() / 2.0)))


def ensure_publisher_thread() -> bool:
    """Start the publisher thread once. Returns True if it is running.

    Idempotent and safe to call from every loop tick -- which is exactly how it
    is wired, so the existing tick bootstraps it and nothing else has to know
    about a new lifecycle.
    """
    global _thread
    if not enabled():
        return False
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _thread_stop.clear()
        _thread = threading.Thread(
            target=_publisher_loop, name="game-chip-publisher", daemon=True
        )
        _thread.start()
        print(
            "[game_chip_publisher] CHIP_PUBLISHER_THREAD_STARTED "
            f"interval_s={publish_interval_seconds()}",
            flush=True,
        )
        return True


def stop_publisher_thread(timeout: float = 5.0) -> None:
    """For tests and a clean shutdown."""
    global _thread
    _thread_stop.set()
    with _thread_lock:
        thread = _thread
        _thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)


def _reset_for_tests() -> None:
    _state["last_publish_at"] = 0.0
    _state["last_date"] = ""
    _state["publishes"] = 0
    _state["skips"] = {}
