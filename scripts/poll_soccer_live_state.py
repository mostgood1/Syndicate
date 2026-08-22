"""Poll ESPN for in-progress matches and write a soccer live-lens snapshot.

For every league fixture ESPN currently reports as ``in`` progress, rebuilds
the current match state (score, cards, corners, shots-so-far per player --
via ``espn_live_state.build_live_state``) and projects it forward with the
resumed-match live lens (``features/soccer/features/live_lens.py``):
updated three-way/total/BTTS/corners, goal-in-the-next-10-minutes
probability, and live shot-prop projections for the players who have
appeared. Writes one artifact per league/date:

    data/soccer_source/{league}/api/live_state/live_state_{date}.json

``syndicate/features/soccer/live_lens.py`` (the UI feature module) reads
this directly -- no engine work happens in the request path.

Usage:
    python scripts/poll_soccer_live_state.py --league epl
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date as date_cls
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_soccer_artifacts import _fill_promoted
from scripts.build_soccer_artifacts import _load_player_rows
from scripts.build_soccer_artifacts import _load_team_ratings
from syndicate.features.soccer.ingestion.fotmob_momentum import fotmob_momentum_block
from syndicate.features.soccer.features.live_lens import goal_in_window_probability
from syndicate.features.soccer.features.live_lens import project_live_match
from syndicate.features.soccer.features.live_lens import project_live_player_props
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.ingestion.espn_live_state import build_live_state
from syndicate.features.soccer.ingestion.espn_match_box import build_match_box
from syndicate.features.soccer.sources import active_leagues_for_date

_GOAL_WINDOWS_SECONDS = {"next_10_min": 600.0, "next_5_min": 300.0}


def _as_of_seconds(event: dict[str, Any]) -> float | None:
    """ESPN's live match clock in seconds, or None if it did not report one."""
    value = event.get("status_clock_seconds")
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0.0 else None


def _team_player_rows(player_rows: list[dict[str, Any]], team_name: str) -> list[dict[str, Any]]:
    rows = []
    for row in player_rows:
        matched = match_team_name(str(row.get("team") or ""), [team_name])
        if matched is not None:
            rows.append(row)
    return rows


def _rating_for(ratings: dict[str, dict[str, float]], team_name: str) -> dict[str, float]:
    matched = match_team_name(team_name, list(ratings))
    if matched is None:
        return {"attack_rating": -0.18, "defense_rating": -0.18}
    return ratings[matched]


def _build_match_boxes(
    league: str,
    iso_date: str,
    *,
    out_path: Path,
    summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Per-match box scores for every `in` and `post` fixture on this date.

    Soccer's box tab rendered only sim squad projections -- no counterpart to
    MLB's real "Live / final box" -- while the numbers for one sat unused in
    the match summary this poller was already fetching. See
    `ingestion/espn_match_box.py`.

    A FINISHED MATCH IS FETCHED ONCE, EVER. `live_lens_loop` ticks this
    roughly every 60s across ten leagues, so re-deriving every completed
    fixture's box on every tick would add an ESPN summary call per finished
    match per minute, all day, to recompute a value that cannot change --
    exactly the "worker periodic work is never free" failure that caused a
    production restart loop under `#241`. A `post` box already carrying
    `final: true` in the artifact on disk is carried forward untouched.

    An in-progress match IS re-derived every tick, because its box is the
    thing that is moving.

    Failures are per-event and non-fatal: a box score is a display nicety and
    must never take down the live-lens projection, which is the product.
    """
    compact = iso_date.replace("-", "")
    window = f"{compact}-{compact}"
    try:
        events = fetch_events(league, date_windows=[window], statuses={"in", "post"})
    except Exception as error:
        print(
            f"[soccer_live_state] BOX_EVENTS_FAILED league={league} date={iso_date} "
            f"error={type(error).__name__}: {error}",
            flush=True,
        )
        return {}

    prior: dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            candidate = existing.get("match_box") if isinstance(existing, dict) else None
            if isinstance(candidate, dict):
                prior = candidate
        except Exception:
            prior = {}

    boxes: dict[str, Any] = {}
    reused = 0
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        is_final = str(event.get("status_state") or "") == "post"
        cached = prior.get(event_id)
        if is_final and isinstance(cached, dict) and cached.get("final"):
            boxes[event_id] = cached
            reused += 1
            continue
        summary = summaries.get(event_id)
        if summary is None:
            try:
                summary = fetch_match_summary(league, event_id)
            except Exception as error:
                print(
                    f"[soccer_live_state] BOX_SUMMARY_FAILED league={league} "
                    f"event={event_id} error={type(error).__name__}: {error}",
                    flush=True,
                )
                continue
        try:
            record = build_match_box(summary, event_id=event_id)
        except Exception as error:
            print(
                f"[soccer_live_state] BOX_BUILD_FAILED league={league} "
                f"event={event_id} error={type(error).__name__}: {error}",
                flush=True,
            )
            continue
        record["final"] = is_final
        record["status_state"] = event.get("status_state")
        record["status_detail"] = event.get("status_detail")
        record["status_display_clock"] = event.get("status_display_clock")
        record["status_period"] = event.get("status_period")
        # ESPN's scoreboard score, alongside the keyEvents-derived one in
        # `games`. For a FINAL match this is the only score that exists --
        # nothing writes a `games` entry for a finished fixture.
        record["score_home"] = event.get("home_score")
        record["score_away"] = event.get("away_score")
        record["home_team"] = event.get("home_team")
        record["away_team"] = event.get("away_team")
        boxes[event_id] = record
    if reused:
        print(
            f"[soccer_live_state] BOX_REUSED league={league} date={iso_date} "
            f"final_cached={reused} built={len(boxes) - reused}",
            flush=True,
        )
    return boxes


# The ESPN-commentary momentum proxy (`features/momentum.py`, formerly wired
# here as `_momentum_block`) was RETIRED as the production feed 2026-08-22.
# Swept across every half-life 30s-1800s against its own production weighting
# scheme, holdout, 699 matches: dAUC ran -0.0006 to +0.0002, monotonically
# WORSE as half-life grew -- the signature of no effect, not underpowered
# noise (`docs/ai_context/todo.md` #518). It is not reused as a fallback below:
# a confident-looking chart built on a disproven signal is worse than the
# panel simply not appearing, which is what `supported: False` already does
# on the card. The module and its tests remain in the repo -- unused in
# production, still an honest description of what it computes.


def poll_league(league: str, iso_date: str, *, source_root: Path, out_root: Path, simulations: int) -> dict[str, Any]:
    compact = iso_date.replace("-", "")
    window = f"{compact}-{compact}"
    live_events = fetch_events(league, date_windows=[window], statuses={"in"})
    api_root = out_root / league / "api"
    out_path = api_root / "live_state" / f"live_state_{iso_date}.json"

    games: dict[str, Any] = {}
    # Summaries fetched by the live-lens pass below, reused by the box pass so
    # an in-progress match costs ONE `fetch_match_summary`, not two.
    summaries: dict[str, dict[str, Any]] = {}
    if live_events:
        # `as_of` is REQUIRED and this call was missing it, which is the whole
        # live-lens outage. `_load_team_ratings(league, source_root, as_of)`
        # (build_soccer_artifacts.py:54) gained the third parameter with the
        # audit §7 #6 as-of work; that change updated its own module's caller
        # (:238) and missed this one.
        #
        # `iso_date`, matching :238's `iso_date`, because `as_of` is documented
        # there as "the date being built for" and live polling builds for the
        # in-progress fixture's own date.
        #
        # MEASURED ON PRODUCTION 2026-08-17 20:1x-20:3xZ (live-odds-worker):
        # this raised `TypeError: _load_team_ratings() missing 1 required
        # positional argument: 'as_of'` for la_liga, primeira_liga and
        # championship -- EXACTLY and only the three leagues with matches in
        # play -- while the other seven wrote `(0 live games)` and looked fine.
        # All three live-lens boards read "Live matches: 0 / Source: No data"
        # with three matches actually being played and scoring.
        #
        # THREE COVERS KEPT THIS HIDDEN, worth naming because only the first is
        # fixed here. (1) The call sits behind `if live_events:`, so it can only
        # fire for a league with a live match -- silent on a quiet slate, total
        # on a busy one. (2) `poll_active_leagues_for_tick`'s handler catches it
        # into an `errors` dict with no log line, and that dict reaches only
        # `data/live/soccer_live_lens.json`, which is not in the publisher
        # allowlist. (3) `tests/test_soccer_team_ratings_as_of.py:117` asserts
        # the literal call-site TEXT in `build_soccer_artifacts` alone, so it
        # stayed green while three other call sites were broken. A signature
        # change needs a caller census, not a spot-check of the caller you just
        # edited -- `validate_soccer_vs_market.py:316` and `:449` are still
        # wrong on the same footing and are NOT fixed here.
        ratings = _load_team_ratings(league, source_root, iso_date)
        team_names = [event["home_team"] for event in live_events] + [event["away_team"] for event in live_events]
        _fill_promoted(ratings, team_names)
        player_rows = _load_player_rows(league, source_root)

        for event in live_events:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            # THE REAL CLOCK, PASSED. `build_live_state`'s own docstring says
            # `as_of_seconds=None` means "full match" and is "the right default
            # for backtesting against a completed match", and that it is "**not**
            # a substitute for a true live clock" -- live callers "must source
            # the actual current clock from ESPN's live status and pass it
            # explicitly." This caller never did.
            #
            # WHAT THAT COST, measured 2026-08-20: with no `as_of_seconds`, the
            # cutoff is the nominal full-time 5400s, so
            # `_current_half_and_clock_remaining` returns `(2, 0.0)` for EVERY
            # live match -- half 2, nothing left to play. Those are the two
            # fields the card reads for its clock and period, which is why
            # `shared_game_state` carried `clock: ""` and `period: null` on
            # fixture 401882908 while it was genuinely in play. Passing ESPN's
            # `clock` (4200.0 at the 70th minute) returns `(2, 1200.0)`.
            #
            # It is NOT only a display bug. `project_live_match` and
            # `goal_in_window_probability` both project the REMAINDER of the
            # match from this state, so a live lens that believed every match
            # had 0 seconds left was projecting nothing forward at all.
            #
            # `None` when ESPN omits the clock, which restores the previous
            # behaviour for that event alone rather than inventing a position.
            as_of_seconds = _as_of_seconds(event)
            try:
                summary = fetch_match_summary(league, event_id)
                summaries[event_id] = summary
                live_state = build_live_state(
                    summary,
                    event_id=event_id,
                    home_team=event.get("home_team"),
                    away_team=event.get("away_team"),
                    as_of_seconds=as_of_seconds,
                )
            except Exception as error:
                print(f"skip {event_id}: {error}")
                continue

            home_rating = _rating_for(ratings, live_state["home_team"])
            away_rating = _rating_for(ratings, live_state["away_team"])
            projection = project_live_match(live_state, home_rating=home_rating, away_rating=away_rating, simulations=simulations)
            goal_windows = {
                label: goal_in_window_probability(live_state, home_rating=home_rating, away_rating=away_rating, window_seconds=seconds, simulations=simulations)
                for label, seconds in _GOAL_WINDOWS_SECONDS.items()
            }
            home_players = _team_player_rows(player_rows, live_state["home_team"])
            away_players = _team_player_rows(player_rows, live_state["away_team"])
            live_props = project_live_player_props(
                live_state,
                home_rating=home_rating,
                away_rating=away_rating,
                home_player_rows=home_players,
                away_player_rows=away_players,
                simulations=simulations,
            )
            games[event_id] = {
                "event_id": event_id,
                "home_team": live_state["home_team"],
                "away_team": live_state["away_team"],
                "half": live_state["half"],
                "clock_remaining": live_state["clock_remaining"],
                # ESPN's own rendering of the same instant, carried through
                # verbatim so the card shows "80'" rather than re-deriving a
                # minute from `half`+`clock_remaining` and disagreeing with
                # every scoreboard on the internet about stoppage time
                # (ESPN says "90'+7'"; the arithmetic would say "90'").
                "status_display_clock": event.get("status_display_clock"),
                "status_period": event.get("status_period"),
                "status_detail": event.get("status_detail"),
                "score_home": live_state["score_home"],
                "score_away": live_state["score_away"],
                "home_red_cards": live_state["home_red_cards"],
                "away_red_cards": live_state["away_red_cards"],
                "home_shots_so_far": live_state["home_shots_so_far"],
                "away_shots_so_far": live_state["away_shots_so_far"],
                "home_shots_on_target_so_far": live_state["home_shots_on_target_so_far"],
                "away_shots_on_target_so_far": live_state["away_shots_on_target_so_far"],
                "home_corners_so_far": live_state["home_corners_so_far"],
                "away_corners_so_far": live_state["away_corners_so_far"],
                "projection": projection.to_dict(),
                "goal_windows": goal_windows,
                # ATTACK MOMENTUM, from FotMob's own per-minute series
                # (`fotmob_momentum.py`), not computed from `summary` -- the
                # ESPN-derived proxy this used to call was retired 2026-08-22,
                # see the note above `poll_league`. One extra HTTP call per
                # live match per tick (FotMob has no bulk momentum endpoint);
                # never fatal, `supported: False` with a reason on any join or
                # fetch failure so the card hides the panel rather than
                # showing a stale or empty one.
                #
                # `as_of_seconds` bounds the series to the live clock, not
                # end-of-feed: reading the whole series would let a card show
                # pressure from after the moment it claims to describe.
                "momentum": fotmob_momentum_block(
                    league=league,
                    home_team=live_state["home_team"],
                    away_team=live_state["away_team"],
                    iso_date=iso_date,
                    as_of_seconds=as_of_seconds,
                ),
                "live_player_props": [row.to_dict() for row in sorted(live_props, key=lambda r: r.projected_final_shots, reverse=True)[:12]],
            }

    match_box = _build_match_boxes(league, iso_date, out_path=out_path, summaries=summaries)

    payload = {
        "league": league,
        "date": iso_date,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "count": len(games),
        "games": games,
        # A SEPARATE KEY FROM `games`, deliberately. `games` means "matches in
        # play" -- `syndicate/features/soccer/live_lens.py` reads it directly
        # and a finished match appearing there would present a settled result
        # as live. `match_box` spans `in` AND `post`, because the card needs a
        # box score in both states and the FINAL one is the case soccer has
        # never had at all.
        #
        # Carried inside this artifact rather than a new file because
        # `soccer_source/*/api/live_state/live_state_*.json` is ALREADY in
        # `HOT_ARTIFACT_PATTERNS`; a new path would need an allowlist entry in
        # `artifact_publisher.py`, which is claimed by two other open lanes,
        # and an unallowlisted artifact cannot reach web at all.
        "match_box": match_box,
        "match_box_count": len(match_box),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(games)} live games, {len(match_box)} box scores)", flush=True)
    return payload


def poll_active_leagues_for_tick(
    iso_date: str, *, source_root: Path, out_root: Path, simulations: int
) -> dict[str, Any]:
    # Fast-tick entrypoint for live_lens_loop.py (syndicate/features/shared/
    # live_lens_loop.py), which ticks MLB/NBA/WNBA every ~60s but had no
    # soccer entry at all -- soccer's only "live" refresh used to be this
    # same poll_league(), invoked once per league every 4h by
    # refresh_odds_sources.py's slow SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_
    # AUTORUN cadence. A 90-minute match could go an entire half with no
    # live-state update under that cadence.
    #
    # Unlike MLB/NBA/WNBA (one sport, one snapshot file), soccer is
    # multi-league -- this loops every currently-in-season league
    # (active_leagues_for_date, same month-window heuristic build_soccer_
    # artifacts.py's pregame path already uses) and calls the existing,
    # unmodified poll_league() per league, which writes that league's own
    # real live_state_{date}.json directly (soccer/sources.py's
    # live_state_payload() reads those per-league files already -- this
    # requires zero changes to the read side). The dict this function
    # returns is a flattened cross-league summary for live_lens_loop's own
    # bookkeeping/validation snapshot only, not a replacement for the real
    # per-league artifacts.
    #
    # Explicit loop (not a comprehension) so one league's exception doesn't
    # silently drop every other league's tick this cycle -- same reasoning
    # build_intelligence_overview (intelligence.py) already documents for
    # per-sport iteration.
    games: list[dict[str, Any]] = []
    leagues_checked: list[str] = []
    leagues_with_games: list[str] = []
    errors: dict[str, str] = {}
    for league in active_leagues_for_date(iso_date):
        leagues_checked.append(league)
        try:
            payload = poll_league(
                league, iso_date, source_root=source_root, out_root=out_root, simulations=simulations
            )
        except Exception as error:
            errors[league] = f"{type(error).__name__}: {error}"
            # A SWALLOWED LEAGUE WAS INDISTINGUISHABLE FROM AN INACTIVE ONE, and
            # on this path those are opposites.
            #
            # This is the handler that hid the 2026-08-17 outage. `poll_league`
            # raised `TypeError: _load_team_ratings() missing 1 required
            # positional argument: 'as_of'` (fixed in `6bdc50de`) and it was
            # caught here, recorded into `errors`, and never seen: that dict
            # reaches only `data/live/soccer_live_lens.json`, which is NOT in
            # `artifact_publisher`'s allowlist, so it is unreadable from web.
            #
            # WHY IT WAS TOTAL AND STILL INVISIBLE: everything expensive in
            # `poll_league` sits behind `if live_events:`, so only a league WITH a
            # match in play can reach the throwing code. Production wrote
            # `(0 live games)` for SEVEN leagues while `active_leagues_for_date`
            # returned TEN, and the three missing were exactly the three with
            # matches in play. The soccer live lens read "Live matches: 0 /
            # Source: No data" for all of them. Nothing in any log said why.
            #
            # The tick still reported `ok: true` throughout, because
            # `validate_live_lens_snapshot` accepts an EMPTY games list. Three
            # instruments read healthy while the feature was dead.
            #
            # print, not logger.info: `logger.info` does not reach Render's
            # collector (CLAUDE.md). flush=True because stdout is block-buffered
            # off a tty and an exception path is exactly where a buffered line is
            # lost. Traceback included because the exception message alone names
            # the callee, not the CALL SITE -- and the call site was the bug.
            print(
                f"[soccer_live_state] LEAGUE_POLL_FAILED league={league} "
                f"date={iso_date} error={type(error).__name__}: {error}",
                flush=True,
            )
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            continue
        league_games = payload.get("games") if isinstance(payload, dict) else None
        if isinstance(league_games, dict) and league_games:
            leagues_with_games.append(league)
            for event_id, game in league_games.items():
                if isinstance(game, dict):
                    games.append({"league": league, "event_id": event_id, **game})
    return {
        "date": iso_date,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "leagues_checked": leagues_checked,
        "leagues_with_games": leagues_with_games,
        "count": len(games),
        "games": games,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--date", default=None, help="ISO date, default today")
    parser.add_argument("--simulations", type=int, default=300)
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()
    iso_date = args.date or date_cls.today().isoformat()
    poll_league(args.league, iso_date, source_root=Path(args.source_root), out_root=Path(args.out_root), simulations=args.simulations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
