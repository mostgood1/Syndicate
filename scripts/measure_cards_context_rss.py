"""Peak-RSS measurement for the MLB overview hydration path (`#387`).

WHY RSS AND NOT `tracemalloc`. `docs/ai_context/handoff_refresh_worker_oom.md`
records the methodology failure that cost that incident a week: every local
measurement used `tracemalloc`, whose *peak* does not move when a loader parses
a large document and frees it before the next one starts -- while production
measures cgroup `memory.current`, which is RSS-like and ratchets, because
CPython's allocator does not reliably return that churn to the OS. A pass that
parses ten 20MB documents sequentially reads as ~20MB to `tracemalloc` and as
~200MB to the container. **Measure RSS when chasing this.**

WHAT IT MEASURES. The exact worker-side call chain `#387` names:

    build_intelligence_overview(skip_game_hydration=False)
      -> _build_sport_overview("mlb", ...)         syndicate/blueprints/home.py
        -> _load_home_games("mlb", ...)
          -> _MLBDataProvider.games()              home.py:5363
            -> build_cards_page_context()          mlb/cards.py:5535
            -> _enrich_games_with_tracked_market_lines()
            -> _mlb_game_market_recommendation_rows() per game

`_MLBDataProvider.games()` is the unit, not `build_cards_page_context` alone:
the ledger's standing finding is that the excursion sits in the UNMARKED gap
after `cards_context_end`, i.e. in the caller (`.syndicate/deploys.md`,
2026-08-16 04:5xZ). Measuring only the inner call reproduces the same blind
spot that entry describes.

LOCAL IS NOT PRODUCTION. 91.5MB locally against ~2-3.7GB in production is the
recorded gap, and three guesses built on local magnitudes have already been
wrong. This harness is for the RATIO between two code paths on the SAME slate
and the SAME interpreter -- never for a magnitude quoted about Render.

COVERAGE IS PART OF THE NUMBER, NOT A FOOTNOTE. `#387`'s retraction happened
because a run measured "the overview" on a mirror with no MLB games. This
script refuses to report unless the slate actually hydrated games, and prints
the game count next to every figure.

Usage (from a session worktree, whose data/ is excluded by design):

    py -3 scripts/measure_cards_context_rss.py --date 2026-06-14 --repeats 3

with SYNDICATE_MLB_SOURCE_ROOT pointed at a mirror that carries that date.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil


class _PeakSampler:
    """Samples process RSS on a thread so a transient inside one call is seen.

    A before/after pair cannot see a transient at all: the whole point of this
    measurement is the allocation that is freed before the call returns but was
    resident while it ran, which is exactly the shape that kills the worker.
    """

    def __init__(self, interval_sec: float = 0.01) -> None:
        self._proc = psutil.Process()
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_bytes = 0
        self.samples = 0

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                rss = self._proc.memory_info().rss
            except Exception:
                rss = 0
            if rss > self.peak_bytes:
                self.peak_bytes = rss
            self.samples += 1
            self._stop.wait(self._interval)

    def __enter__(self) -> "_PeakSampler":
        self.peak_bytes = self._proc.memory_info().rss
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def _reset_module_caches() -> None:
    """Drop the module-level caches so repeat N is not measuring repeat N-1.

    Both caches are keyed on artifact signatures that do not change locally, so
    without this every repeat after the first is a cache hit and the harness
    would report the cost of a `deepcopy` instead of the cost of a build. That
    is the local mirror of `cards_context_page_cache_hit`, and reporting it as
    the build cost is the same class of error as measuring a slate with no MLB
    games in it.
    """
    from syndicate.features.mlb import cards as mlb_cards
    from syndicate.blueprints import home as home_blueprint

    mlb_cards._MLB_CARDS_CONTEXT_CACHE.clear()
    mlb_cards._MLB_TODAY_CACHE.clear()
    home_blueprint._HOME_OVERVIEW_CACHE.clear()
    gc.collect()


def _run_once(date_value: str) -> tuple[int, float, float, float, float]:
    """One `_MLBDataProvider.games()` pass.

    Returns (games, peak_mb, before_mb, after_mb, seconds).
    """
    from syndicate.blueprints.home import _MLBDataProvider, SportContext

    _reset_module_caches()
    provider = _MLBDataProvider()
    context = SportContext(slug="mlb", context_label=date_value, season=None, week=None)

    before = _rss_mb()
    started = time.perf_counter()
    with _PeakSampler() as sampler:
        games = provider.games(context, is_active_today=False)
        game_count = len(games)
        # Drop the result before the sampler stops so `after` describes what the
        # pass RETAINED in module state, not what the caller is still holding.
        del games
    elapsed = time.perf_counter() - started
    gc.collect()
    after = _rss_mb()
    return game_count, sampler.peak_bytes / (1024 * 1024), before, after, elapsed


def _capture(expr: str, *, date_value: str, prune: str, dyno: str) -> str | None:
    """Serialise `expr` from a fresh interpreter under one flag combination.

    Subprocesses, not in-process toggling: the flag is read per loader call and
    the module-level context cache would otherwise let arm 2 serve arm 1's
    result -- a parity check that compares a value against itself.
    """
    import subprocess
    import tempfile

    # THE PAYLOAD GOES TO A FILE, NOT STDOUT, AND THAT IS LOAD-BEARING.
    #
    # This originally captured `sys.stdout`, which silently made the comparison
    # "the serialised object PLUS anything the code under test happened to
    # print". The moment `_daily_actual_by_game` gained its `FEED_LIVE_PRUNE`
    # line, parity reported DIFFERENT by 3 bytes -- `enabled=True/False` and
    # `pruned=15/0` -- on a change that is provably output-neutral. A harness
    # that fails when the subject adds a log line is measuring the wrong channel,
    # and the failure looks exactly like a real regression.
    #
    # The web arm stayed IDENTICAL throughout, because the emitter is worker-only
    # -- which is what identified the harness as the culprit rather than the code.
    root = str(Path(__file__).resolve().parents[1])
    handle, out_path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    code = (
        "import json,sys;"
        f"sys.path.insert(0, r'{root}');"
        f"{expr}"
        f"open(r'{out_path}','w',encoding='utf-8')"
        ".write(json.dumps(_v, sort_keys=True, default=str))"
    )
    env = dict(os.environ)
    env["SYNDICATE_MLB_FEED_LIVE_PRUNE"] = prune
    env["SYNDICATE_WEB_DYNO"] = dyno
    try:
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr[-3000:], flush=True)
            return None
        return Path(out_path).read_text(encoding="utf-8")
    finally:
        Path(out_path).unlink(missing_ok=True)


def _parity(date_value: str) -> int:
    """Byte parity between the pruned and unpruned paths, at three scopes.

    The unit tests assert parity per reader and per game. This asserts it over
    whole serialised objects, which is what catches a field nobody thought to
    enumerate:

      * the WORKER's games list -- what candidate collection is handed
      * the WHOLE page context, worker mode -- everything else the build returns
      * the WHOLE page context, WEB mode -- `blueprints/mlb.py:336` (`/mlb/cards`)
        calls the same builder, and `_render_web_dyno()` selects a different half
        of this module. Proving the worker arm alone would leave the served page
        unproven, which is the "isolate the thing you changed" gap.
    """
    scopes = (
        (
            "worker games list",
            "0",
            "from syndicate.blueprints.home import _MLBDataProvider, SportContext;"
            f"_v=_MLBDataProvider().games(SportContext(slug='mlb', context_label='{date_value}'), is_active_today=False);",
        ),
        (
            "worker page context",
            "0",
            "from syndicate.features.mlb.cards import build_cards_page_context as _b;"
            f"_v=_b('{date_value}');",
        ),
        (
            "web page context",
            "1",
            "from syndicate.features.mlb.cards import build_cards_page_context as _b;"
            f"_v=_b('{date_value}');",
        ),
    )

    failures = 0
    for label, dyno, expr in scopes:
        on = _capture(expr, date_value=date_value, prune="1", dyno=dyno)
        off = _capture(expr, date_value=date_value, prune="0", dyno=dyno)
        if on is None or off is None:
            return 1
        verdict = "IDENTICAL" if on and on == off else "DIFFERENT"
        print(f"{label:>20}  on={len(on):>9,} B  off={len(off):>9,} B  {verdict}")
        if verdict != "IDENTICAL":
            failures += 1

    if failures:
        print("\nthe prune is NOT output-neutral on this slate")
        return 1
    print("\nall scopes byte-identical -- the reduction is invisible above the loader")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json-out", default=None)
    parser.add_argument(
        "--parity",
        action="store_true",
        help="instead of measuring, assert the pruned and unpruned games lists are byte-identical",
    )
    parser.add_argument(
        "--label",
        default="",
        help="free text recorded with the result, e.g. the flag state under test",
    )
    args = parser.parse_args()

    if args.parity:
        return _parity(args.date)

    # The worker path is the subject. `_render_web_dyno()` decides which half of
    # this module runs, and on Render every service sets RENDER*, so the
    # explicit override is the only unambiguous way to select it -- see
    # `_render_web_dyno`'s own comment.
    os.environ["SYNDICATE_WEB_DYNO"] = "0"

    rows: list[dict[str, object]] = []
    for index in range(max(1, args.repeats)):
        game_count, peak_mb, before_mb, after_mb, elapsed = _run_once(args.date)
        rows.append(
            {
                "repeat": index + 1,
                "games": game_count,
                "rss_before_mb": round(before_mb, 1),
                "rss_peak_mb": round(peak_mb, 1),
                "rss_after_mb": round(after_mb, 1),
                "transient_mb": round(peak_mb - before_mb, 1),
                "retained_mb": round(after_mb - before_mb, 1),
                "seconds": round(elapsed, 2),
            }
        )
        print(
            f"repeat={index + 1} games={game_count} "
            f"before={before_mb:.1f}MB peak={peak_mb:.1f}MB after={after_mb:.1f}MB "
            f"transient=+{peak_mb - before_mb:.1f}MB retained=+{after_mb - before_mb:.1f}MB "
            f"{elapsed:.2f}s",
            flush=True,
        )

    games_seen = max(int(row["games"]) for row in rows)
    if not games_seen:
        print(
            "\nREFUSING TO REPORT: the slate hydrated ZERO games, so this run "
            "measured the path WITHOUT the sport that is the cost. That is "
            "exactly how `#387`'s 127MB retraction happened. Pick a date whose "
            "mirror carries a daily summary, or point "
            "SYNDICATE_MLB_SOURCE_ROOT at one that does.",
            flush=True,
        )
        return 2

    # Repeat 1 pays for cold imports and lru_caches that every later repeat
    # shares, so it is reported and then excluded -- a first-run figure quoted
    # as the steady-state cost is the local twin of the post-deploy confound
    # `#387` records ("only a cold process clears the bar").
    steady = rows[1:] or rows
    mean_transient = sum(float(row["transient_mb"]) for row in steady) / len(steady)
    mean_retained = sum(float(row["retained_mb"]) for row in steady) / len(steady)
    print(
        f"\nlabel={args.label or '(none)'} date={args.date} games={games_seen}\n"
        f"steady-state over {len(steady)} repeat(s): "
        f"transient mean +{mean_transient:.1f}MB, retained mean +{mean_retained:.1f}MB",
        flush=True,
    )
    print(
        "LOCAL RSS on a warm interpreter, not cgroup anon on Render. Use the "
        "RATIO between two labelled runs; do not quote the magnitude as a "
        "production figure.",
        flush=True,
    )

    if args.json_out:
        payload = {
            "label": args.label,
            "date": args.date,
            "games": games_seen,
            "rows": rows,
            "steady_transient_mb": round(mean_transient, 1),
            "steady_retained_mb": round(mean_retained, 1),
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
