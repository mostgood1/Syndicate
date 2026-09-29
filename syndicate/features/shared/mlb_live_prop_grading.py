"""MLB replay-and-reconcile: the feed_live adapter for live prop grading.

WHY `[2026-09-29, lane mlb-live-prop-grader]`. MLB's live prop tier is the only
one on the platform actually putting live rows on the board (116 on 2026-09-29),
it is a 120-sim rest-of-game Monte Carlo living in VENDORED code
(`vendor/mlb_bettingv2/sim_engine/live_mc.py:estimate_live`), and it has never
been graded against a realised outcome. This is the replay half of fixing that:
the integrity gate that any MLB residual has to clear first.

It feeds the SAME contract as the basketball adapter in `live_prop_grading.py`
(`reconcile` shape, `stat_reconciles`, `residual_by_bucket`), so the two sports
produce comparable tables. It is a separate module because nothing else is
shared: MLB has no clock, no minutes, and a completely different play shape.

THE BUCKETING KEY IS OUTS REMAINING, NOT MINUTES. That is the honest analogue of
"how much game is left" here, and `residual_by_bucket(bucket_key="outs_left")`
already takes it. `count.outs` on a play is the count AFTER that play and RESETS
each half-inning (verified on 822896: plays 3/4/5 read 1/2/3, then the bottom
half restarts at 1), so cumulative outs is accumulated per half-inning rather
than read off any single field.

SCOPE IS THE PROP MARKETS, DELIBERATELY. Batter hits, total bases, home runs,
RBIs, runs and strikeouts; pitcher strikeouts and outs. At-bats and plate
appearances are NOT reconciled because nothing prices them -- reconciling a stat
you do not grade buys no confidence and creates a failure mode that withholds
games for an irrelevant reason.

NO TEXT PARSING. Every stat comes off structure: `result.eventType` for the
batting line, `result.rbi` for RBIs, `runners[].movement.end == "score"` with
`details.runner.id` for runs, `matchup.pitcher.id` for pitcher credit. A play
description is prose and changes without notice; an enum does not.

AN UNKNOWN eventType IS RECORDED, NOT SILENTLY DROPPED. `replay` returns
`unknown_events`, and a game carrying any is refused by `stat_reconciles` for the
batting stats it could have affected -- because an unrecognised event is exactly
the case where a silent zero looks like a clean reconcile.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

#: eventType -> (hits, total_bases, is_home_run, is_strikeout, is_at_bat)
#: Anything that is not here is UNKNOWN and is reported, never assumed harmless.
_BATTING_EVENTS: dict[str, tuple[int, int, bool, bool, bool]] = {
    "single": (1, 1, False, False, True),
    "double": (1, 2, False, False, True),
    "triple": (1, 3, False, False, True),
    "home_run": (1, 4, True, False, True),
    "strikeout": (0, 0, False, True, True),
    "strikeout_double_play": (0, 0, False, True, True),
    "strike_out": (0, 0, False, True, True),
    # Reached without a hit and without an at-bat charged.
    "walk": (0, 0, False, False, False),
    "intent_walk": (0, 0, False, False, False),
    "hit_by_pitch": (0, 0, False, False, False),
    "sac_fly": (0, 0, False, False, False),
    "sac_fly_double_play": (0, 0, False, False, False),
    "sac_bunt": (0, 0, False, False, False),
    "sac_bunt_double_play": (0, 0, False, False, False),
    "catcher_interf": (0, 0, False, False, False),
    # Outs in play: an at-bat, no hit.
    "field_out": (0, 0, False, False, True),
    "force_out": (0, 0, False, False, True),
    "grounded_into_double_play": (0, 0, False, False, True),
    "grounded_into_triple_play": (0, 0, False, False, True),
    "double_play": (0, 0, False, False, True),
    "triple_play": (0, 0, False, False, True),
    "fielders_choice": (0, 0, False, False, True),
    "fielders_choice_out": (0, 0, False, False, True),
    "field_error": (0, 0, False, False, True),
    "batter_interference": (0, 0, False, False, True),
    "bunt_group_out": (0, 0, False, False, True),
    "bunt_pop_out": (0, 0, False, False, True),
    "bunt_lineout": (0, 0, False, False, True),
}

#: Events that are not a completed plate appearance at all -- baserunning and
#: administrative plays. They can still SCORE a runner, which is why they are
#: walked for runners, but they credit the batter with nothing.
_NON_PA_EVENTS = frozenset({
    "stolen_base_2b", "stolen_base_3b", "stolen_base_home",
    "caught_stealing_2b", "caught_stealing_3b", "caught_stealing_home",
    "pickoff_1b", "pickoff_2b", "pickoff_3b",
    "pickoff_caught_stealing_2b", "pickoff_caught_stealing_3b",
    "pickoff_caught_stealing_home",
    "wild_pitch", "passed_ball", "balk", "other_advance", "defensive_indiff",
    "runner_double_play", "other_out", "game_advisory", "ejection",
    "defensive_substitution", "offensive_substitution", "pitching_substitution",
    "runner_placed", "injury", "stolen_base", "caught_stealing",
})

#: The stats this adapter grades. Each is a real prop market.
BATTING_STATS = ("hits", "totalBases", "homeRuns", "rbi", "runs", "strikeOuts")
PITCHING_STATS = ("strikeOuts", "outs")


def load_feed(path: str | Path) -> dict[str, Any]:
    """Read a feed_live capture, gzipped or plain."""
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(p.read_text(encoding="utf-8"))


def official_box(feed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """player id (int) -> {name, batting:{...}, pitching:{...}} from the box."""
    out: dict[str, dict[str, Any]] = {}
    teams = ((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    for side in ("home", "away"):
        for entry in ((teams.get(side) or {}).get("players") or {}).values():
            person = entry.get("person") or {}
            try:
                pid = int(person.get("id"))
            except (TypeError, ValueError):
                continue
            stats = entry.get("stats") or {}
            batting = stats.get("batting") or {}
            pitching = stats.get("pitching") or {}
            out[str(pid)] = {
                "name": person.get("fullName"),
                "side": side,
                "battingOrder": entry.get("battingOrder"),
                "batting": {k: batting.get(k) for k in BATTING_STATS},
                "pitching": {
                    "strikeOuts": pitching.get("strikeOuts"),
                    "outs": pitching.get("outs"),
                },
                "batted": bool(batting),
                "pitched": bool(pitching),
            }
    return out


def _blank_batting() -> dict[str, float]:
    return {k: 0.0 for k in BATTING_STATS}


def replay(feed: dict[str, Any]) -> dict[str, Any]:
    """Walk allPlays, accumulating per-player prop stats and outs over time.

    Emits a SAMPLE after every completed plate appearance, carrying each
    player's counts as of that moment plus `outs_left` -- the analogue of the
    basketball adapter's clock samples, and the granularity a live MLB price
    actually moves at.
    """
    live = feed.get("liveData") or {}
    plays = (live.get("plays") or {}).get("allPlays") or []
    box = official_box(feed)

    batting: dict[str, dict[str, float]] = {pid: _blank_batting() for pid in box}
    pitching: dict[str, dict[str, float]] = {
        pid: {"strikeOuts": 0.0, "outs": 0.0} for pid in box
    }
    unknown_events: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    total_outs = 0.0
    prev_half: tuple[Any, Any] | None = None
    outs_in_half = 0.0

    for play in plays:
        about = play.get("about") or {}
        result = play.get("result") or {}
        matchup = play.get("matchup") or {}
        event_type = str(result.get("eventType") or "").strip()

        half = (about.get("inning"), about.get("halfInning"))
        if half != prev_half:
            outs_in_half = 0.0
            prev_half = half
        try:
            outs_after = float((play.get("count") or {}).get("outs") or 0.0)
        except (TypeError, ValueError):
            outs_after = outs_in_half
        delta_outs = max(0.0, outs_after - outs_in_half)
        outs_in_half = outs_after
        total_outs += delta_outs

        batter_id = str((matchup.get("batter") or {}).get("id") or "")
        pitcher_id = str((matchup.get("pitcher") or {}).get("id") or "")

        # The pitcher is charged the outs recorded during this play regardless of
        # whether it was a plate appearance (a caught stealing is an out too).
        if pitcher_id in pitching:
            pitching[pitcher_id]["outs"] += delta_outs

        if event_type in _BATTING_EVENTS:
            hits, bases, is_hr, is_k, _is_ab = _BATTING_EVENTS[event_type]
            if batter_id in batting:
                line = batting[batter_id]
                line["hits"] += hits
                line["totalBases"] += bases
                line["homeRuns"] += 1.0 if is_hr else 0.0
                line["strikeOuts"] += 1.0 if is_k else 0.0
                try:
                    line["rbi"] += float(result.get("rbi") or 0.0)
                except (TypeError, ValueError):
                    pass
            if is_k and pitcher_id in pitching:
                pitching[pitcher_id]["strikeOuts"] += 1.0
        elif event_type and event_type not in _NON_PA_EVENTS:
            unknown_events[event_type] = unknown_events.get(event_type, 0) + 1

        # RUNS: credited to the RUNNER who scored, on whatever play scored them
        # -- including non-PA plays like a wild pitch, which is why this is
        # outside the batting branch.
        for runner in play.get("runners") or []:
            movement = runner.get("movement") or {}
            if str(movement.get("end") or "") != "score":
                continue
            rid = str(((runner.get("details") or {}).get("runner") or {}).get("id") or "")
            if rid in batting:
                batting[rid]["runs"] += 1.0

        if event_type in _BATTING_EVENTS:
            samples.append({
                "at_bat_index": about.get("atBatIndex"),
                "inning": about.get("inning"),
                "half": about.get("halfInning"),
                "outs_recorded": total_outs,
                "batting": {pid: dict(line) for pid, line in batting.items()},
                "pitching": {pid: dict(line) for pid, line in pitching.items()},
            })

    return {
        "box": box,
        "batting": batting,
        "pitching": pitching,
        "samples": samples,
        "total_outs": total_outs,
        "unknown_events": unknown_events,
        "plays": len(plays),
    }


def reconcile(state: dict[str, Any]) -> dict[str, Any]:
    """Replayed totals vs the OFFICIAL box. The gate on trusting any residual.

    Only players the box says actually BATTED (or PITCHED) are compared: a
    position player who never came to the plate has no official line, and
    counting him as a match would inflate every rate here with free agreement.
    """
    box = state["box"]
    report: dict[str, Any] = {"unknown_events": dict(state.get("unknown_events") or {})}

    batters = [pid for pid, row in box.items() if row.get("batted")]
    report["players"] = len(batters)
    for stat in BATTING_STATS:
        exact = 0
        off: list[str] = []
        for pid in batters:
            official = (box[pid]["batting"] or {}).get(stat)
            if official is None:
                continue
            replayed = state["batting"].get(pid, {}).get(stat, 0.0)
            if abs(float(replayed) - float(official)) < 1e-6:
                exact += 1
            else:
                off.append(f'{box[pid]["name"]}: replay {replayed:g} vs box {official}')
        report[f"{stat}_exact"] = exact
        report[f"{stat}_off"] = off

    pitchers = [pid for pid, row in box.items() if row.get("pitched")]
    report["pitchers"] = len(pitchers)
    for stat in PITCHING_STATS:
        exact = 0
        off: list[str] = []
        for pid in pitchers:
            official = (box[pid]["pitching"] or {}).get(stat)
            if official is None:
                continue
            replayed = state["pitching"].get(pid, {}).get(stat, 0.0)
            if abs(float(replayed) - float(official)) < 1e-6:
                exact += 1
            else:
                off.append(f'{box[pid]["name"]}: replay {replayed:g} vs box {official}')
        report[f"pitching_{stat}_exact"] = exact
        report[f"pitching_{stat}_off"] = off
    return report


def stat_reconciles(report: dict[str, Any], stat: str) -> bool:
    """Did EVERY relevant player reconcile for this stat?

    Mirrors `live_prop_grading.stat_reconciles`, with two MLB-specific refusals:

      * an UNKNOWN eventType in the game refuses every BATTING stat, because an
        unrecognised event credits nobody and a silent zero is indistinguishable
        from a clean reconcile;
      * a stat with no `<stat>_exact` key is one this replay never tracked, and
        reads False rather than falling through to the permissive branch.
    """
    pitching = stat.startswith("pitching_")
    key = f"{stat}_exact"
    if key not in report:
        return False
    if not pitching and report.get("unknown_events"):
        return False
    denominator = report.get("pitchers" if pitching else "players") or 0
    return int(report.get(key) or 0) == int(denominator)
