"""Replay-and-reconcile grading for live prop projections, across leagues.

WHY THIS IS SHARED `[2026-09-29, lane live-prop-grader-cross-sport]`. The
platform has FOUR different live-prop methodologies and exactly ONE of them has
ever been graded against real outcomes: WNBA's, by
`scripts/grade_wnba_live_prop_projection.py`. The other three publish a
probability from an ASSUMED distribution -- NBA's own sigma table says so in
`nba/cards.py:1687-1690` ("a principled starting point, NOT backtested against
real NBA outcomes"). Under the 2026-09-11 "Withhold, all sports" decision an
unmeasured model is exactly what gets withheld, so the grader -- not the
projector -- is the scarce part.

WHAT THIS MEASURES, and why it needs no distributional assumption. It scores a
shipped projection's OWN RESIDUAL (`projected - actual_final`), bucketed by how
much of the player's game is left. Grading a hypothesised remainder shape
instead would test a parametric guess; the residual yields the interval
directly, and it is the quantity a consumer actually needs -- `prob_std_err`
wants the spread of the ESTIMATE, not the shape of a supposed remainder.

Because it grades "whatever function produced this number", it is also the
instrument that can settle RE-SIM vs RESCALE. Score both over the same replayed
games and compare residuals; that is the comparison `nfl-ncaaf-live-props` ran
for NFL's live game line (re-sim MAE 9.596 vs a frozen baseline's 7.522, which
is why that lane chose RESCALE). Nothing here presumes which wins for any other
sport -- that is the point of having it.

THE RECONCILE GATE IS THE REASON TO TRUST ANY NUMBER THIS PRINTS. Replaying to
the final buzzer must reproduce the OFFICIAL boxscore exactly, per player, per
stat. A residual computed from a replay that does not reconcile is a number
about a bug, and this project has published enough of those. A game that fails
the gate is NOT graded for that stat.

SCOPE. ESPN-backed basketball leagues (WNBA, NBA) share a play-by-play and box
shape exactly, so they differ only in the constants in `LeagueSpec`: the league
path and the period lengths. `official_box`, `replay` and `reconcile` are the
same computation for both. Sports whose pbp is NOT this shape (MLB's
`feed_live`, NHL, football) need their own replay adapter feeding the same
`reconcile` / `residual_by_bucket` contract -- deliberately not faked here.

NOTE ON THE PERIOD CONSTANTS: they are self-checking. Wrong period lengths make
replayed MINUTES disagree with the official box, which the gate reports rather
than absorbs -- so a bad `LeagueSpec` fails loudly instead of quietly skewing
every residual.
"""
from __future__ import annotations

import json
import statistics
import urllib.request
from dataclasses import dataclass
from typing import Any

_SUMMARY_HOST = "https://site.web.api.espn.com/apis/site/v2/sports"
_SCOREBOARD_HOST = "https://site.api.espn.com/apis/site/v2/sports"


@dataclass(frozen=True)
class LeagueSpec:
    """The complete sport-specific surface of an ESPN basketball replay.

    `regulation_periods` is separate from `period_minutes` because the
    prior-time formula needs to know where OT starts, and a league that ever
    changed its quarter count would otherwise silently mis-time every overtime
    sample.
    """

    sport: str
    espn_path: str
    period_minutes: float
    ot_minutes: float
    regulation_periods: int = 4

    @property
    def summary_url(self) -> str:
        return f"{_SUMMARY_HOST}/{self.espn_path}/summary"

    @property
    def scoreboard_url(self) -> str:
        return f"{_SCOREBOARD_HOST}/{self.espn_path}/scoreboard"


#: WNBA plays 10-minute quarters, NBA 12-minute; both use 5-minute OT.
LEAGUES: dict[str, LeagueSpec] = {
    "wnba": LeagueSpec("wnba", "basketball/wnba", 10.0, 5.0, 4),
    "nba": LeagueSpec("nba", "basketball/nba", 12.0, 5.0, 4),
}


def league(sport: str) -> LeagueSpec:
    key = str(sport or "").strip().lower()
    if key not in LEAGUES:
        raise KeyError(f"no ESPN basketball LeagueSpec for {sport!r}; have {sorted(LEAGUES)}")
    return LEAGUES[key]


def get_json(url: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_summary(spec: LeagueSpec, event_id: str, timeout: int = 30) -> dict[str, Any]:
    return get_json(f"{spec.summary_url}?event={event_id}", timeout=timeout)


def event_ids_for_date(spec: LeagueSpec, date_str: str, timeout: int = 30) -> list[str]:
    """ESPN wants YYYYMMDD; callers hold YYYY-MM-DD."""
    compact = str(date_str or "").replace("-", "")
    payload = get_json(f"{spec.scoreboard_url}?dates={compact}", timeout=timeout)
    return [str(event.get("id")) for event in (payload.get("events") or []) if event.get("id")]


def elapsed_minutes(period: Any, clock_text: Any, spec: LeagueSpec) -> float | None:
    """Total minutes elapsed since tip, in `spec`'s period convention."""
    try:
        period_number = int((period or {}).get("number"))
    except (TypeError, ValueError):
        return None
    text = str((clock_text or {}).get("displayValue") or "").strip()
    if not text:
        return None
    # ESPN RENDERS SUB-MINUTE CLOCKS WITHOUT A COLON: "55.7", "14.9", "0.0".
    # Requiring `MM:SS` silently drops every play in the final minute of every
    # quarter, which is not a uniform loss -- end-of-quarter possessions are
    # disproportionately free throws. Measured on WNBA event 401857158: the
    # replay reconciled 10/17 players on points, every miss UNDER the official
    # box (Mitchell 25 vs 37), while the sum of scoreValue over all scoring
    # plays equalled the official 176.0 exactly. The plays were all there; the
    # parser was throwing them away. Carried over verbatim -- the same ESPN
    # renderer serves every league here.
    try:
        if ":" in text:
            minutes_left, seconds_left = (int(part) for part in text.split(":", 1))
            remaining_raw = minutes_left + seconds_left / 60.0
        else:
            remaining_raw = float(text) / 60.0
    except ValueError:
        return None
    regulation = spec.regulation_periods
    length = spec.period_minutes if period_number <= regulation else spec.ot_minutes
    remaining = max(0.0, min(length, remaining_raw))
    prior = (
        (period_number - 1) * spec.period_minutes
        if period_number <= regulation
        else regulation * spec.period_minutes + (period_number - regulation - 1) * spec.ot_minutes
    )
    return prior + (length - remaining)


def _stat_at(stats: list[Any], index: int | None) -> float | None:
    if index is None or len(stats) <= index:
        return None
    try:
        return float(stats[index])
    except (TypeError, ValueError):
        return None


def _made_at(stats: list[Any], index: int | None) -> float | None:
    """A "3-7" cell -> 3.0: the MADE half of a made-attempted pair."""
    if index is None or len(stats) <= index:
        return None
    try:
        return float(str(stats[index]).split("-", 1)[0])
    except (TypeError, ValueError):
        return None


def official_box(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """athlete id -> {name, starter, minutes, points, rebounds, assists, threes}."""
    out: dict[str, dict[str, Any]] = {}
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        team_id = str(((team_block.get("team") or {}).get("id")) or "")
        for stat_block in team_block.get("statistics") or []:
            keys = [str(k) for k in (stat_block.get("keys") or [])]
            try:
                minutes_at, points_at = keys.index("minutes"), keys.index("points")
            except ValueError:
                continue
            rebounds_at = keys.index("rebounds") if "rebounds" in keys else None
            assists_at = keys.index("assists") if "assists" in keys else None
            threes_key = "threePointFieldGoalsMade-threePointFieldGoalsAttempted"
            threes_at = keys.index(threes_key) if threes_key in keys else None
            for athlete in stat_block.get("athletes") or []:
                stats = athlete.get("stats") or []
                if len(stats) <= max(minutes_at, points_at):
                    continue
                info = athlete.get("athlete") or {}
                athlete_id = str(info.get("id") or "").strip()
                if not athlete_id:
                    continue
                try:
                    minutes = float(stats[minutes_at])
                    points = float(stats[points_at])
                except (TypeError, ValueError):
                    continue
                out[athlete_id] = {
                    "name": info.get("displayName"),
                    "starter": bool(athlete.get("starter")),
                    "minutes": minutes,
                    "points": points,
                    "rebounds": _stat_at(stats, rebounds_at),
                    "assists": _stat_at(stats, assists_at),
                    "threes": _made_at(stats, threes_at),
                    "team_id": team_id,
                }
    return out


def replay(summary: dict[str, Any], spec: LeagueSpec) -> dict[str, Any]:
    """Walk the plays, accumulating per-athlete counts and minutes over time.

    Returns the end state plus every sample point, so one pass serves both the
    reconcile gate and the residual grading.

    STRUCTURAL, NOT TEXT-PARSED, for everything except substitutions and fouls:
    a rebound is a play whose type text contains "Rebound" with the rebounder as
    `participants[0]` (team rebounds carry NO participant, and the box credits
    no player with them); an assist is `participants[1]` on a made field goal
    (a scoringPlay with two participants -- a block is two participants on a
    MISS, so it never counts); a made three is a scoring play worth exactly 3
    (free throws are 1, so no other scoring play carries that value).
    """
    box = official_box(summary)
    on_court = {aid for aid, row in box.items() if row.get("starter")}
    points: dict[str, float] = {aid: 0.0 for aid in box}
    rebounds: dict[str, float] = {aid: 0.0 for aid in box}
    assists: dict[str, float] = {aid: 0.0 for aid in box}
    threes: dict[str, float] = {aid: 0.0 for aid in box}
    minutes: dict[str, float] = {aid: 0.0 for aid in box}
    samples: list[dict[str, Any]] = []
    # Per-stat samples, taken at THAT stat's events for the credited player --
    # the same sampling design as points, so the residual tables are comparable.
    stat_samples: dict[str, list[dict[str, Any]]] = {"rebounds": [], "assists": [], "threes": []}
    # CLOCK SAMPLES: every player who has played, at every whole game minute,
    # with counts AS OF that moment. The event samples above are taken right
    # after the player's own event -- when count/minutes (the pace a projection
    # extrapolates) is at its most inflated, worst for low-count stats.
    # Production prices on a clock tick, not after an event, so this is the
    # design that matches it.
    clock_samples: list[dict[str, Any]] = []
    next_minute = 1.0
    # GAME STATE for a remaining-minutes model: the running score (a blowout
    # benches starters) and personal fouls (six and out).
    competitors = ((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
    home_id = next((str(c.get("id")) for c in competitors if c.get("homeAway") == "home"), "")
    score = {"home": 0.0, "away": 0.0}
    fouls: dict[str, float] = {aid: 0.0 for aid in box}
    last_clock = 0.0

    plays = summary.get("plays") or []
    for play in plays:
        now = elapsed_minutes(play.get("period"), play.get("clock"), spec)
        if now is None:
            continue
        while now >= next_minute:
            # Snapshot BEFORE this play's events: the state at the minute boundary.
            for aid in box:
                played = minutes.get(aid, 0.0) + (
                    max(0.0, next_minute - last_clock) if aid in on_court else 0.0
                )
                if played <= 0.0:
                    continue
                own_home = box[aid].get("team_id") == home_id
                margin = (score["home"] - score["away"]) * (1.0 if own_home else -1.0)
                clock_samples.append({
                    "elapsed": next_minute, "athlete_id": aid, "minutes": round(played, 3),
                    "points": points[aid], "rebounds": rebounds[aid],
                    "assists": assists[aid], "threes": threes[aid],
                    "margin": margin, "fouls": fouls.get(aid, 0.0),
                    "on_court": aid in on_court,
                })
            next_minute += 1.0
        delta = max(0.0, now - last_clock)
        if delta:
            for aid in on_court:
                if aid in minutes:
                    minutes[aid] += delta
        last_clock = now

        participants = [
            str(((p or {}).get("athlete") or {}).get("id") or "")
            for p in (play.get("participants") or [])
        ]
        type_text = str((play.get("type") or {}).get("text") or "").lower()
        for side, key in (("home", "homeScore"), ("away", "awayScore")):
            try:
                if play.get(key) is not None:
                    score[side] = float(play.get(key))
            except (TypeError, ValueError):
                pass
        if "personal foul" in type_text and participants and participants[0] in fouls:
            fouls[participants[0]] += 1.0

        if "substitution" in type_text and len(participants) >= 2:
            entering, leaving = participants[0], participants[1]
            if leaving in box:
                on_court.discard(leaving)
            if entering in box:
                on_court.add(entering)
            continue

        if "rebound" in type_text and participants and participants[0] in rebounds:
            rebounder = participants[0]
            rebounds[rebounder] += 1.0
            stat_samples["rebounds"].append({
                "elapsed": round(now, 3), "athlete_id": rebounder,
                "value": rebounds[rebounder], "minutes": round(minutes.get(rebounder, 0.0), 3),
            })

        if play.get("scoringPlay") and len(participants) >= 2 and participants[1] in assists:
            assister = participants[1]
            assists[assister] += 1.0
            stat_samples["assists"].append({
                "elapsed": round(now, 3), "athlete_id": assister,
                "value": assists[assister], "minutes": round(minutes.get(assister, 0.0), 3),
            })

        if play.get("scoringPlay") and participants:
            scorer = participants[0]
            try:
                value = float(play.get("scoreValue") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if scorer in points and value:
                points[scorer] += value
                if value == 3.0:
                    threes[scorer] += 1.0
                    stat_samples["threes"].append({
                        "elapsed": round(now, 3), "athlete_id": scorer,
                        "value": threes[scorer], "minutes": round(minutes.get(scorer, 0.0), 3),
                    })
                samples.append({
                    "elapsed": round(now, 3), "athlete_id": scorer,
                    "points": points[scorer], "minutes": round(minutes.get(scorer, 0.0), 3),
                })

    # Final interval to the buzzer, so end-state minutes are complete.
    end = (
        max((elapsed_minutes(p.get("period"), p.get("clock"), spec) or 0.0) for p in plays)
        if plays
        else 0.0
    )
    for aid in on_court:
        if aid in minutes:
            minutes[aid] += max(0.0, end - last_clock)

    return {
        "box": box, "points": points, "minutes": minutes, "rebounds": rebounds,
        "assists": assists, "threes": threes, "stat_samples": stat_samples,
        "clock_samples": clock_samples, "samples": samples, "end_elapsed": round(end, 3),
    }


def reconcile(state: dict[str, Any], *, minutes_tolerance: float = 2.0) -> dict[str, Any]:
    """Replayed end state vs the OFFICIAL box. The gate on trusting anything."""
    box = state["box"]
    points_exact = 0
    points_off: list[str] = []
    minutes_within = 0
    minutes_off: list[str] = []
    for aid, row in box.items():
        if abs(state["points"].get(aid, 0.0) - row["points"]) < 1e-6:
            points_exact += 1
        else:
            points_off.append(
                f'{row["name"]}: replay {state["points"].get(aid, 0.0):.0f} vs box {row["points"]:.0f}'
            )
        if abs(state["minutes"].get(aid, 0.0) - row["minutes"]) <= minutes_tolerance:
            minutes_within += 1
        else:
            minutes_off.append(
                f'{row["name"]}: replay {state["minutes"].get(aid, 0.0):.1f} vs box {row["minutes"]:.1f}'
            )
    stat_exact: dict[str, int] = {}
    stat_off: dict[str, list[str]] = {}
    for stat in ("rebounds", "assists", "threes"):
        exact = 0
        off: list[str] = []
        for aid, row in box.items():
            official = row.get(stat)
            replayed = state.get(stat, {}).get(aid, 0.0)
            if official is not None and abs(replayed - official) < 1e-6:
                exact += 1
            else:
                off.append(f'{row["name"]}: replay {replayed:.0f} vs box {official}')
        stat_exact[stat] = exact
        stat_off[stat] = off
    return {
        "players": len(box),
        "rebounds_exact": stat_exact["rebounds"], "rebounds_off": stat_off["rebounds"],
        "assists_exact": stat_exact["assists"], "assists_off": stat_off["assists"],
        "threes_exact": stat_exact["threes"], "threes_off": stat_off["threes"],
        "points_exact": points_exact, "points_off": points_off,
        "minutes_within_tolerance": minutes_within, "minutes_off": minutes_off,
        "minutes_tolerance": minutes_tolerance,
    }


def stat_reconciles(report: dict[str, Any], stat: str) -> bool:
    """Did EVERY player reconcile for this stat? The admission gate per game.

    A stat this replay does not track at all is NOT admitted -- an absent key
    reads as False rather than falling through to the permissive branch, because
    a failed lookup must never widen what gets graded.
    """
    key = f"{stat}_exact"
    if key not in report:
        return False
    return int(report.get(key) or 0) == int(report.get("players") or 0)


def residual_by_bucket(
    residuals: list[dict[str, Any]],
    *,
    bucket_key: str = "minutes_left",
    edges: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0, 40.0),
    min_n: int = 30,
) -> list[dict[str, Any]]:
    """Spread of (projected - actual_final), bucketed by game remaining.

    Reports the SPREAD (stdev) because that is what a consumer's `prob_std_err`
    needs, and the MEAN beside it because a non-zero mean is bias -- a different
    defect from a wide interval, and one a single summary number hides. A bucket
    under `min_n` is reported with its n and NO statistics rather than dropped,
    so thin coverage stays visible instead of looking like absence.
    """
    out: list[dict[str, Any]] = []
    for low, high in zip(edges, edges[1:]):
        rows = [r for r in residuals if low <= float(r.get(bucket_key) or 0.0) < high]
        entry: dict[str, Any] = {"bucket": f"[{low:g},{high:g})", "n": len(rows)}
        if len(rows) < min_n:
            entry["status"] = f"under-powered (<{min_n})"
            out.append(entry)
            continue
        errs = [float(r["residual"]) for r in rows]
        entry.update({
            "mean_residual": round(statistics.fmean(errs), 4),
            "stdev_residual": round(statistics.pstdev(errs), 4),
            "mean_abs_residual": round(statistics.fmean([abs(e) for e in errs]), 4),
        })
        out.append(entry)
    return out
