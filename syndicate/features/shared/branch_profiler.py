"""An env-gated cProfile around one named region, for use on a REAL build.

WHY THIS EXISTS AS A SHARED MODULE `[2026-08-29]`

The first instance of this (in `blueprints/home.py`) settled in one run a
question that eight hand-placed log spans had failed to settle -- and then
immediately proved the region itself was the wrong one:

    soccer OVERVIEW_SPORT bracket   452.97s  ->  362.76s
    _build_sport_overview            10.95s  ->    3.22s   (2.4% -> 0.9%)

`_build_sport_overview` is ~1-2% of what soccer costs. The remaining ~99% is in
the CONSUMER (`intelligence_state._consume_sport`), which is a different file in
a different package. Copying eighty lines of profiler across that boundary to
find that out a second time is how a diagnostic becomes two diagnostics that
drift, so it lives here instead.

WHAT IT IS NOT: telemetry. cProfile costs roughly 1.3-2x on the profiled region.
Turn it on for a few builds, read it, turn it off.

THE OFF VALUE IS EXPLICIT, and that is not cosmetic: Render's env-var API
REJECTS an empty value (`HTTP 400 must provide a value or generateValue must be
set to true`), so "turn this back off" has to be a WORD. `off` previously
disabled the home.py profiler only by the coincidence that no sport is named
`off`.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any
from typing import Iterator


_OFF_VALUES = {"0", "off", "false", "no", "none", "disabled"}
_ALL_VALUES = {"1", "true", "yes", "on", "all"}

# One parked profiler per env var. cProfile permits a single active profiler per
# thread, so a region that RAISES before its exit would otherwise wedge the
# instrument for the life of the process -- the first exception silently
# disabling exactly the diagnostic you deployed to catch it.
_PARKED: dict[str, Any] = {}


def profile_keys(env_var: str) -> set[str]:
    raw = str(os.environ.get(env_var) or "").strip().lower()
    if not raw or raw in _OFF_VALUES:
        return set()
    if raw in _ALL_VALUES:
        return {"all"}
    return {part.strip() for part in raw.split(",") if part.strip()}


def profile_enabled_for(env_var: str, key: str) -> bool:
    wanted = profile_keys(env_var)
    if not wanted:
        return False
    return "all" in wanted or str(key).strip().lower() in wanted


def _report(profile: Any, *, env_var: str, key: str, label: str, elapsed_s: float) -> None:
    try:
        import io as _io
        import pstats

        raw = str(os.environ.get(f"{env_var}_TOP") or "").strip()
        try:
            top = max(5, min(60, int(raw))) if raw else 30
        except (TypeError, ValueError):
            top = 30
        stats = pstats.Stats(profile)
        # `tottime` FIRST and it is the one to read: self time names the leaf
        # burning the seconds, cumulative names the branch containing it. The
        # pair is what separates "one slow call" from "a million fast ones".
        for order in ("tottime", "cumulative"):
            buffer = _io.StringIO()
            stats.stream = buffer
            stats.sort_stats(order).print_stats(top)
            lines = [ln.rstrip() for ln in buffer.getvalue().splitlines() if ln.strip()]
            print(
                f"[profiler] {label} key={key} order={order} "
                f"elapsed_s={round(elapsed_s, 2)} rows={len(lines)}",
                flush=True,
            )
            for line in lines[: top + 6]:
                # One row per line: Render's collector truncates long lines, and
                # a cut-off table is unreadable exactly where it matters.
                print(f"[profiler] {label} | {line[:300]}", flush=True)
    except Exception as exc:
        print(f"[profiler] {label} REPORT_FAILED key={key} err={exc}", flush=True)


@contextmanager
def profile_branch(env_var: str, key: str, *, label: str, enabled: bool = True) -> "Iterator[None]":
    """Profile this block iff `env_var` names `key` (or `all`) and `enabled`.

    Never raises, and never changes control flow: if anything about the
    profiler fails, the body still runs exactly as it would have.
    """
    import time as _time

    profile = None
    if enabled and profile_enabled_for(env_var, key):
        try:
            import cProfile

            stale = _PARKED.get(env_var)
            if stale is not None:
                try:
                    stale.disable()
                except Exception:
                    pass
                print(f"[profiler] {label} STALE_CLEARED env={env_var}", flush=True)
            profile = cProfile.Profile()
            _PARKED[env_var] = profile
            profile.enable()
        except Exception as exc:
            profile = None
            print(f"[profiler] {label} BEGIN_FAILED key={key} err={exc}", flush=True)
    started = _time.monotonic()
    try:
        yield
    finally:
        if profile is not None:
            try:
                profile.disable()
            except Exception:
                pass
            _PARKED[env_var] = None
            _report(
                profile,
                env_var=env_var,
                key=key,
                label=label,
                elapsed_s=_time.monotonic() - started,
            )
