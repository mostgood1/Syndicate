"""Capture basketball attack momentum for the games currently in play.

**NOTHING SCHEDULES THIS YET.** It is a working entrypoint that must be invoked
-- by hand, or by the one-line wiring into the live-lens tick that Phase B
deliberately does not make (see `basketball_momentum_artifacts`'s docstring and
`.syndicate/scope_2026-08-22_basketball_live_momentum.md` section 7a). A
producer that exists is not a producer that runs, and this file existing is not
evidence that any momentum has ever been captured.

Shaped as a SCRIPT rather than as code inside `features/nba/` because that is
soccer's shape -- `scripts/poll_soccer_live_state.py` is a script the live-lens
loop imports -- and because `wnba/live_lens.py` and `live_lens_loop.py` are
both claimed by other open lanes.

    python scripts/poll_basketball_momentum.py --league wnba --date 2026-08-22
    python scripts/poll_basketball_momentum.py --league nba --dry-run

NETWORK. ESPN's site API is unauthenticated but soft-blocks datacenter egress
with a bot-shaped User-Agent: the request SUCCEEDS at the transport level and
returns an empty body, which is indistinguishable downstream from "no games
today". `#469` measured that as the difference between a real payload and
weeks of silently frozen data. The browser UA below is not decoration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_momentum_artifacts import append_momentum_artifact
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_payload_streamed
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path
from syndicate.features.shared.basketball_momentum_artifacts import strip_rows
from syndicate.features.shared.basketball_momentum_artifacts import write_momentum_events
from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path

_SPORT_PATH = {
    "nba": "sports/basketball/nba",
    "wnba": "sports/basketball/wnba",
    "ncaab": "sports/basketball/mens-college-basketball",
    "ncaabw": "sports/basketball/womens-college-basketball",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_json(url: str, *, timeout: int = 25, browser_ua: bool = False) -> dict[str, Any]:
    """Fetch JSON, and SAY SO when it fails.

    **`browser_ua=False` IS THE MEASURED DEFAULT AND MUST STAY THAT WAY FOR
    `site.api.espn.com`.** `scripts/fetch_espn_live_status_for_date.py` records
    the probe, run from Render itself on 2026-08-05 against a game confirmed
    genuinely live: the bare `Mozilla/5.0` UA returned **403**, a fuller
    realistic Chrome header set returned **403**, and NO custom headers at all
    -- urllib's own `Python-urllib/x.y` -- returned **200**. ESPN appears to
    fingerprint the browser-spoof pattern specifically. **Local testing cannot
    reproduce it; only Render's egress IP is blocked.**

    This module shipped with the browser UA on both calls, copied from
    `basketball_props_smart_sim._http_get_json_local`, whose comment argues the
    OPPOSITE for its own endpoint. Two comments in this repo give contradictory
    advice and only one of them was measured against the scoreboard from
    Render. Cost: the scoreboard 403'd on every tick of a live WNBA slate, the
    bare `except` swallowed it, and `live_events=0` was indistinguishable from
    "no games in play" for the whole evening.

    **THE SWALLOWED ERROR IS THE DEEPER DEFECT.** A 403 and an empty slate
    returned the same `{}`. Failures are now printed with their reason, so this
    can never again be silent.
    """
    headers = {"Accept": "application/json"}
    if browser_ua:
        headers["User-Agent"] = _BROWSER_UA
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                print(f"[basketball_momentum] FETCH_STATUS {response.status} url={url}", flush=True)
                return {}
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        print(f"[basketball_momentum] FETCH_FAILED {type(exc).__name__}: {exc} url={url}", flush=True)
        return {}


def scoreboard_url(league: str, date_str: str) -> str:
    """The scoreboard URL, built in ONE place.

    **`_SPORT_PATH` ALREADY CONTAINS `sports/`.** The season backfill rewrote
    this line by hand and prefixed `sports/` a second time, producing
    `.../v2/sports/sports/basketball/wnba/scoreboard` and HTTP 400 on every date
    of a season pull. Two callers, two spellings, one of them wrong.

    A URL that is known to work is reused, not retyped.
    """
    return (f"https://site.api.espn.com/apis/site/v2/{_SPORT_PATH[league]}"
            f"/scoreboard?dates={date_str.replace('-', '')}")


def live_event_ids(league: str, date_str: str) -> list[str]:
    """Event ids for games IN PROGRESS. Not scheduled, not final.

    A final game has a complete feed and would produce a full-match series that
    reads on a card as though the game were still being played. Soccer's
    `poll_soccer_live_state` keeps the same separation for the same reason.
    """
    ymd = date_str.replace("-", "")
    url = scoreboard_url(league, date_str)
    # NO browser UA: `site.api.espn.com` 403s on it from Render (see `_get_json`).
    scoreboard = _get_json(url)
    events = scoreboard.get("events")
    # Total vs in-play, because `live_events=0` alone cannot tell "3 games, none
    # tipped" from "the scoreboard call returned nothing" -- which is exactly
    # the ambiguity that hid the 403.
    print(
        f"[basketball_momentum] SCOREBOARD league={league} date={date_str} "
        f"events_total={len(events) if isinstance(events, list) else 'ABSENT'}",
        flush=True,
    )
    out: list[str] = []
    # **`events_total` vs `live_events` STILL LEAVES ONE AMBIGUITY, and it is
    # the one that matters on a slate that captured nothing.** `events_total=4
    # live_events=0` reads identically for "none have tipped yet", "all four
    # have finished", and "ESPN never advanced the state off `pre`" -- three
    # situations with three different owners: wait, nothing wrong, and a bug.
    # Counting the states separates them, in the same way `events_total`
    # separated "none tipped" from "the call returned nothing" and thereby
    # surfaced the 403.
    states: dict[str, int] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        status = ((event.get("status") or {}).get("type") or {})
        state = str(status.get("state") or "").strip().lower() or "ABSENT"
        states[state] = states.get(state, 0) + 1
        if state != "in":
            continue
        event_id = str(event.get("id") or "").strip()
        if event_id:
            out.append(event_id)
    if events:
        print(
            f"[basketball_momentum] SCOREBOARD_STATES league={league} date={date_str} "
            + " ".join(f"{k}={v}" for k, v in sorted(states.items())),
            flush=True,
        )
    return out


def fetch_summary(league: str, event_id: str) -> dict[str, Any]:
    """`site.web.api.espn.com` -- a DIFFERENT host from the scoreboard's.

    The browser UA is established for this host elsewhere in the repo
    (`basketball_props_smart_sim._espn_summary_local`,
    `grade_wnba_live_prop_projection`), so it is tried first. But the two hosts
    have already been shown to disagree about UA policy, so an empty result
    falls back to urllib's honest default rather than giving up -- the variant
    measured at 200 from Render for the sibling endpoint.
    """
    url = f"https://site.web.api.espn.com/apis/site/v2/{_SPORT_PATH[league]}/summary?event={event_id}"
    payload = _get_json(url, browser_ua=True)
    if not payload:
        print(f"[basketball_momentum] SUMMARY_RETRY_DEFAULT_UA event={event_id}", flush=True)
        payload = _get_json(url)
    return payload


# ---------------------------------------------------------------------------
# ONE-SHOT SEASON BACKFILL
# ---------------------------------------------------------------------------
# **GATED HERE RATHER THAN IN THE WORKER ENTRYPOINT, DELIBERATELY.**
# `scripts/run_refresh_worker.py` is the natural home and is CLAIMED by the OPEN
# lane `portfolio-ledger-service-split` (opened 2026-08-22). Editing a contested
# shared entrypoint to schedule my own lane's job is exactly what the lane
# protocol exists to stop, and this file is already the momentum subsystem's
# entry point on the worker.
#
# Set `SYNDICATE_WNBA_MOMENTUM_BACKFILL=<start>..<end>` to run once. It is:
#   - DAEMON-THREADED, so a live slate's capture is never blocked by it;
#   - RESUMABLE, so a restart re-scans and skips finished dates cheaply;
#   - SENTINEL-GUARDED, so a worker that restarts hourly does not re-run it;
#   - RATE-LIMITED at 0.25s between ESPN calls -- a WNBA season is ~286 requests
#     and there is no reason to go faster.
_BACKFILL_ENV = "SYNDICATE_WNBA_MOMENTUM_BACKFILL"
_VERIFY_ENV = "SYNDICATE_WNBA_MOMENTUM_VERIFY"
_SWEEP_ENV = "SYNDICATE_WNBA_MOMENTUM_SWEEP"
_INTERVAL_ENV = "SYNDICATE_WNBA_INTERVAL_PROJECTION"
_SITUATIONAL_ENV = "SYNDICATE_WNBA_SITUATIONAL_PACE"
_backfill_started = False
_verify_started = False
_sweep_started = False
_interval_started = False
_situational_started = False


def _backfill_sentinel(out_root: Path, league: str, spec: str) -> Path:
    safe = spec.replace("..", "_to_").replace("/", "-")
    return Path(out_root) / f"{league}_source" / "source_artifacts" / "data" / "live_lens" / f".backfill_{safe}.done"


def maybe_start_backfill(league: str, out_root: Path) -> bool:
    """Kick the one-shot backfill if requested and not already done."""
    global _backfill_started
    spec = str(os.environ.get(_BACKFILL_ENV) or "").strip()
    if not spec or _backfill_started:
        return False
    # **A MALFORMED SPEC IS NAMED, NOT IGNORED.** Dropping it into the same
    # silent `return False` as "unset" means someone who sets
    # `...BACKFILL=2026-05-01` and expects a season gets nothing, with nothing
    # said -- the exact ambiguity every diagnostic in this file exists to remove.
    start, sep, end = spec.partition("..")
    start, end = start.strip(), end.strip()
    if not sep or not start or not end:
        print(f"[basketball_momentum] BACKFILL_BAD_SPEC {spec!r} -- want <start>..<end>", flush=True)
        return False

    sentinel = _backfill_sentinel(out_root, league, spec)
    if sentinel.exists():
        # Said out loud. A silent skip is indistinguishable from a backfill that
        # never started, which is the ambiguity every diagnostic here exists to
        # remove.
        print(f"[basketball_momentum] BACKFILL_ALREADY_DONE spec={spec} "
              f"sentinel={sentinel}", flush=True)
        _backfill_started = True
        return False

    _backfill_started = True

    def _run() -> None:
        import threading  # noqa: F401 - imported for symmetry with the caller
        print(f"[basketball_momentum] BACKFILL_START league={league} spec={spec}", flush=True)
        try:
            from scripts.backfill_basketball_momentum_history import main as _backfill_main

            code = _backfill_main([
                "--league", league, "--start", start, "--end", end,
                "--data-root", str(out_root),
            ])
            print(f"[basketball_momentum] BACKFILL_DONE league={league} spec={spec} "
                  f"exit={code}", flush=True)
            if code == 0:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(spec, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - never kills the worker
            print(f"[basketball_momentum] BACKFILL_FAILED league={league} spec={spec} "
                  f"{type(exc).__name__}: {exc}", flush=True)

    import threading

    threading.Thread(target=_run, name="wnba-momentum-backfill", daemon=True).start()
    return True


def maybe_start_verify(league: str, out_root: Path) -> bool:
    """Run the projection-substrate check over a captured range, once.

    **THE LEAKAGE GUARD HAS ONLY EVER RUN ON FIXTURES**, which proved the logic
    and not the feed. This points it at real games before anything is fitted.
    Same one-shot shape as the backfill -- daemon-threaded, sentinel-guarded --
    but no sentinel is written on FAILURE, so a leak is re-reported on every
    restart rather than silently marked done.
    """
    global _verify_started
    spec = str(os.environ.get(_VERIFY_ENV) or "").strip()
    if not spec or _verify_started:
        return False
    start, sep, end = spec.partition("..")
    start, end = start.strip(), end.strip()
    if not sep or not start or not end:
        print(f"[basketball_momentum] VERIFY_BAD_SPEC {spec!r} -- want <start>..<end>", flush=True)
        return False

    sentinel = _backfill_sentinel(out_root, league, f"verify_{spec}")
    if sentinel.exists():
        print(f"[basketball_momentum] VERIFY_ALREADY_DONE spec={spec}", flush=True)
        _verify_started = True
        return False
    _verify_started = True

    def _run() -> None:
        print(f"[basketball_momentum] VERIFY_START league={league} spec={spec}", flush=True)
        try:
            from scripts.verify_momentum_projection_rows import main as _verify_main

            code = _verify_main([
                "--league", league, "--start", start, "--end", end,
                "--data-root", str(out_root),
            ])
            print(f"[basketball_momentum] VERIFY_DONE league={league} spec={spec} "
                  f"exit={code}", flush=True)
            # ONLY on a clean pass. A leak that gets marked done is a leak that
            # stops being reported, and this check exists to be noisy.
            if code == 0:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(spec, encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            print(f"[basketball_momentum] VERIFY_FAILED league={league} spec={spec} "
                  f"{type(exc).__name__}: {exc}", flush=True)

    import threading

    threading.Thread(target=_run, name="wnba-momentum-verify", daemon=True).start()
    return True



def maybe_start_sweep(league: str, out_root: Path) -> bool:
    """The pooled momentum sweep over a captured range, once.

    **THIS IS THE QUESTION THE WHOLE LANE WAS OPENED TO ANSWER**: does momentum
    lead scoring, at what half-life, on which axis, over the intervals that are
    actually traded. It has never been run on real data.

    Gated separately from the verify rather than chained to it, deliberately: a
    sweep that only runs when a check passes is a sweep whose absence is
    ambiguous between "clean but unrun" and "blocked". Two flags, two readings.
    """
    global _sweep_started
    spec = str(os.environ.get(_SWEEP_ENV) or "").strip()
    if not spec or _sweep_started:
        return False
    start, sep, end = spec.partition("..")
    start, end = start.strip(), end.strip()
    if not sep or not start or not end:
        print(f"[basketball_momentum] SWEEP_BAD_SPEC {spec!r} -- want <start>..<end>", flush=True)
        return False

    sentinel = _backfill_sentinel(out_root, league, f"sweep_{spec}")
    if sentinel.exists():
        print(f"[basketball_momentum] SWEEP_ALREADY_DONE spec={spec}", flush=True)
        _sweep_started = True
        return False
    _sweep_started = True

    def _run() -> None:
        print(f"[basketball_momentum] SWEEP_START league={league} spec={spec}", flush=True)
        try:
            from scripts.analyze_basketball_momentum import season_main

            code = season_main([
                "--league", league, "--start", start, "--end", end,
                "--data-root", str(out_root),
            ])
            print(f"[basketball_momentum] SWEEP_DONE league={league} spec={spec} "
                  f"exit={code}", flush=True)
            if code == 0:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(spec, encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            print(f"[basketball_momentum] SWEEP_FAILED league={league} spec={spec} "
                  f"{type(exc).__name__}: {exc}", flush=True)

    import threading

    threading.Thread(target=_run, name="wnba-momentum-sweep", daemon=True).start()
    return True



def maybe_start_interval(league: str, out_root: Path) -> bool:
    """Interval-final projection error, bucketed by time remaining. Once.

    A different question from the momentum sweep, and a better-founded one:
    projecting a quarter's final score from inside it is mostly ARITHMETIC, and
    the useful output is WHERE ON THE CLOCK the error becomes small enough that
    a stale line is beatable.
    """
    global _interval_started
    spec = str(os.environ.get(_INTERVAL_ENV) or "").strip()
    if not spec or _interval_started:
        return False
    start, sep, end = spec.partition("..")
    start, end = start.strip(), end.strip()
    if not sep or not start or not end:
        print(f"[basketball_momentum] INTERVAL_BAD_SPEC {spec!r} -- want <start>..<end>", flush=True)
        return False

    sentinel = _backfill_sentinel(out_root, league, f"interval_{spec}")
    if sentinel.exists():
        print(f"[basketball_momentum] INTERVAL_ALREADY_DONE spec={spec}", flush=True)
        _interval_started = True
        return False
    _interval_started = True

    def _run() -> None:
        print(f"[basketball_momentum] INTERVAL_START league={league} spec={spec}", flush=True)
        try:
            from scripts.analyze_interval_projection import main as _interval_main

            code = _interval_main([
                "--league", league, "--start", start, "--end", end,
                "--data-root", str(out_root),
            ])
            print(f"[basketball_momentum] INTERVAL_DONE league={league} spec={spec} "
                  f"exit={code}", flush=True)
            if code == 0:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(spec, encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            print(f"[basketball_momentum] INTERVAL_FAILED league={league} spec={spec} "
                  f"{type(exc).__name__}: {exc}", flush=True)

    import threading

    threading.Thread(target=_run, name="wnba-interval-projection", daemon=True).start()
    return True



def maybe_start_situational(league: str, out_root: Path) -> bool:
    """Measure whether pace and efficiency MOVE with game situation. Once.

    The interval projection multiplies remaining minutes by a game-to-date pace
    and PPP -- both whole-game averages, and both wrong in exactly the states a
    live bettor cares about: trailing teams speed up and foul, leading teams
    milk the clock, blowouts empty benches. A flat model is not merely imprecise
    there, it is BIASED, and biased hardest in close late games where the
    interval markets actually trade.

    This measures the effect before anyone models it. If the cells are flat, the
    simpler model wins and the layer is not built.
    """
    global _situational_started
    spec = str(os.environ.get(_SITUATIONAL_ENV) or "").strip()
    if not spec or _situational_started:
        return False
    start, sep, end = spec.partition("..")
    start, end = start.strip(), end.strip()
    if not sep or not start or not end:
        print(f"[basketball_momentum] SITUATIONAL_BAD_SPEC {spec!r} -- want <start>..<end>",
              flush=True)
        return False

    sentinel = _backfill_sentinel(out_root, league, f"situational_{spec}")
    if sentinel.exists():
        print(f"[basketball_momentum] SITUATIONAL_ALREADY_DONE spec={spec}", flush=True)
        _situational_started = True
        return False
    _situational_started = True

    def _run() -> None:
        print(f"[basketball_momentum] SITUATIONAL_START league={league} spec={spec}", flush=True)
        try:
            from scripts.analyze_situational_pace import main as _situational_main

            code = _situational_main([
                "--league", league, "--start", start, "--end", end,
                "--data-root", str(out_root),
            ])
            print(f"[basketball_momentum] SITUATIONAL_DONE league={league} spec={spec} "
                  f"exit={code}", flush=True)
            if code == 0:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(spec, encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            print(f"[basketball_momentum] SITUATIONAL_FAILED league={league} spec={spec} "
                  f"{type(exc).__name__}: {exc}", flush=True)

    import threading

    threading.Thread(target=_run, name="wnba-situational-pace", daemon=True).start()
    return True



def poll(league: str, date_str: str, *, out_root: Path, dry_run: bool = False) -> dict[str, Any]:
    # Fires at most once per process, and returns immediately -- the work runs
    # on a daemon thread so a live slate is never waiting on history.
    maybe_start_backfill(league, out_root)
    maybe_start_verify(league, out_root)
    maybe_start_sweep(league, out_root)
    maybe_start_interval(league, out_root)
    maybe_start_situational(league, out_root)

    event_ids = live_event_ids(league, date_str)
    print(f"[basketball_momentum] league={league} date={date_str} live_events={len(event_ids)}", flush=True)
    # **ONE SUMMARY IN MEMORY AT A TIME, not the whole slate.** The previous
    # form fetched every game first and held them all while blocks were built.
    # An ESPN basketball summary carries the full play-by-play plus box score,
    # so a late-game one is megabytes of parsed Python -- and this worker was
    # measured at 93.7% of its 2048MB with ~129MB headroom on a TWO-game slate.
    # Four games would have multiplied the peak for no benefit: each summary is
    # read once, reduced to a few dozen sampled points, and never needed again.
    missing: list[str] = []
    payload = build_momentum_payload_streamed(
        event_ids,
        lambda event_id: fetch_summary(league, event_id),
        league_code=league,
        date_str=date_str,
        on_missing=missing.append,
        include_rows=True,
    )
    fetched = int(payload.get("count") or 0)
    # **NAMED, NOT SILENTLY DROPPED.** On a one-game slate a failed fetch showed
    # up as `live_events=1 fetched=0`. With four games in play, three successes
    # would hide the fourth entirely unless the miss says which one.
    if missing:
        print(
            f"[basketball_momentum] SUMMARY_MISSING league={league} date={date_str} "
            f"events={','.join(missing)}",
            flush=True,
        )
    # `with_series` NOT `count`: a slate of games we fetched but could not read
    # and a slate with no games are both "0 charts", and only one of them is a
    # defect. Printing the pair is what makes them distinguishable in a log.
    print(
        f"[basketball_momentum] fetched={fetched} games={payload['count']} "
        f"with_series={payload['with_series']}",
        flush=True,
    )
    # **WHEN GAMES ARE PRESENT AND NONE CARRIED A SERIES, SAY WHY -- PER GAME.**
    #
    # `with_series=0` is ambiguous between "no live games" and "live games we
    # could not parse", and those need completely different responses. Without
    # this the two print the SAME line, which is the failure this repo names
    # repeatedly: a gate that fires silently cannot be told from a builder that
    # never ran.
    #
    # It matters most in exactly the window where it is least recoverable.
    # Every test of this taxonomy so far has run on hand-built fixtures, because
    # ESPN is 403 from a Claude Code sandbox -- so the first real payload is
    # also the first chance for `_team_index` or `_classify` to be wrong about
    # the feed's actual shape, and WNBA is the only basketball league in season.
    #
    # The three things printed are the three that can be wrong: a stated
    # `reason` from the block, whether `plays` arrived at all, and whether the
    # header yielded competitors (no competitors -> no home side -> every event
    # silently unsigned and dropped).
    # The summaries are gone by now -- deliberately, that is the whole point of
    # streaming -- so this reports what the BLOCK knows rather than re-reading a
    # feed we no longer hold. `plays`/`competitors` counts moved into the block's
    # own `reason`, which `build_momentum_block` already states.
    if fetched and not payload.get("with_series"):
        for event_id, block in (payload.get("games") or {}).items():
            print(
                f"[basketball_momentum] NO_SERIES event={event_id} "
                f"supported={block.get('supported')} reason={block.get('reason')!r} "
                f"events={block.get('events')}",
                flush=True,
            )

    if dry_run:
        print("[basketball_momentum] DRY RUN -- nothing written", flush=True)
        return payload

    if not payload.get("with_series"):
        # REFUSE TO STORE AN EMPTY CAPTURE. This appends once per live tick, so
        # a quiet slate would otherwise write a row every few minutes all day
        # and the backtest would have to learn to ignore them. The sibling
        # WNBA live-box capture in `live_lens_loop.py` takes the same position
        # for the same reason.
        #
        # `with_series`, not `count`: a slate we fetched but could not read is
        # also nothing worth storing, and it is the case that most needs
        # saying out loud rather than being written as a row of nulls.
        print(
            f"[basketball_momentum] NOTHING TO STORE league={league} date={date_str} "
            f"games={payload['count']} with_series=0 -- not appended",
            flush=True,
        )
        return payload

    # **TWO ARTIFACTS, AND THEY ARE NOT INTERCHANGEABLE.**
    #
    # The raw-event dump is OVERWRITTEN with the latest complete feed -- ESPN is
    # cumulative, so the newest write always holds the whole game and appending
    # would rewrite the same early plays every tick (~20x the bytes for a
    # four-game slate, no more complete). This is what the Phase C sweep reads,
    # and it means the sweep NEVER NEEDS ESPN AGAIN: a decayed series cannot be
    # inverted back into the events that made it, so re-fitting at another
    # half-life requires the rows themselves.
    events_path = momentum_events_path(out_root, league_code=league, date_str=date_str)
    rows_written = write_momentum_events(payload, path=events_path)
    print(
        f"[basketball_momentum] events_dump rows={rows_written} games={payload['count']} "
        f"path={events_path}",
        flush=True,
    )

    # The per-tick record stays APPEND-ONLY and row-free. It is the causal
    # evidence -- what a card actually showed at instant t -- which an
    # overwritten file can never reconstruct.
    path = momentum_artifact_path(out_root, league_code=league, date_str=date_str)
    append_momentum_artifact(strip_rows(payload), path=path)
    print(f"[basketball_momentum] appended {path}", flush=True)

    # **A SHAPE LINE PER CAPTURED GAME, because `with_series=1` says a series
    # was BUILT and nothing about whether its numbers are right.**
    #
    # The artifact itself cannot be read from a Claude Code session: the ops
    # export endpoint is on `syndicate-an21.onrender.com`, which the agent
    # proxy answers 403 to at CONNECT (an org policy denial, not an auth
    # failure -- an ADMIN_TOKEN does not change it). Logs are the one channel
    # that does reach out, so the check goes here rather than into a fetch.
    #
    # Deliberately a SHAPE, not a dump: series lengths, endpoint values, the
    # narrator's presence under its own name, and the clock. Enough to catch
    # an empty axis, a mis-signed series, a clock that does not track the game,
    # or a narrator that quietly vanished -- without putting a game's worth of
    # JSON through the log collector every 2.5 minutes.
    for event_id, block in (payload.get("games") or {}).items():
        if not block.get("pressure"):
            # ONE LINE PER GAME, INCLUDING THE ONES THAT FAILED. The
            # `NO_SERIES` block above only fires when the WHOLE slate is
            # empty, so on a mixed slate a game that failed to parse would
            # otherwise print nothing at all and hide behind its neighbour's
            # success -- `with_series=1` on a two-game slate reads as fine.
            print(
                f"[basketball_momentum] SHAPE event={event_id} "
                f"supported={block.get('supported')} reason={block.get('reason')!r} "
                f"events={block.get('events')} -- no series",
                flush=True,
            )
            continue
        pressure = block["pressure"]
        seconds = pressure.get("seconds") or {}
        possessions = pressure.get("possessions") or {}
        narrator = block.get("scoring_narrator") or {}
        print(
            f"[basketball_momentum] SHAPE event={event_id} "
            f"events={block.get('events')} "
            f"as_of_s={block.get('as_of_seconds')} as_of_poss={block.get('as_of_possessions')} "
            f"sec_pts={len(seconds.get('series') or [])} sec_now={seconds.get('current')} "
            f"poss_pts={len(possessions.get('series') or [])} poss_now={possessions.get('current')} "
            f"narrator={'yes' if narrator else 'NO'} narrator_events={narrator.get('events')}",
            flush=True,
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(_SPORT_PATH))
    parser.add_argument("--date", default=None, help="ISO date; defaults to today UTC")
    parser.add_argument("--out-root", default=None, help="artifact root; defaults to <repo>/data")
    parser.add_argument("--dry-run", action="store_true", help="fetch and build, write nothing")
    args = parser.parse_args(argv)

    date_str = args.date
    if not date_str:
        from datetime import datetime, timezone

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_root = Path(args.out_root) if args.out_root else (REPO_ROOT / "data")
    payload = poll(args.league, date_str, out_root=out_root, dry_run=bool(args.dry_run))
    # Exit 3, not 0, when nothing carried a series. A zero exit on an empty
    # capture is how an inert feature reads as healthy for weeks -- the same
    # discipline `scripts/verify_wnba_totals_pricing.py` adopted after a
    # pre-tip zero was indistinguishable from a broken one.
    return 0 if payload.get("with_series") else 3


if __name__ == "__main__":
    raise SystemExit(main())
