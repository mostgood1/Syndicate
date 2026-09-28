"""Grade the live prop projection against real outcomes, by replaying ESPN pbp.

WHY. `wnba_live_prop_projection.project_live_player_stat` publishes a number and
prices nothing, because nobody has measured its error. `#481` set the pattern
for fixing that: replay the SHIPPED function over real games, score it against
what actually happened, and let the measurement decide the interval. This does
the same for the per-player projection.

**WHAT IT MEASURES, and why it is not the sd-scaling assumption.** The open
question was whether the sim's full-game distribution can be scaled to a
remainder (mean by `m/min_mean`, sd by `sqrt(m/min_mean)`). Grading that
assumption directly would test a parametric guess. Measuring the PROJECTION'S
OWN RESIDUAL -- `projected - actual_final`, bucketed by how much of the player's
game is left -- needs no assumption at all and yields the interval directly. It
is also the quantity a consumer actually needs: `prob_std_err` wants the spread
of the estimate, not the shape of a hypothesised remainder.

THE REPLAY IS SELF-CHECKED, and that check is the reason to trust any number
this prints. Replaying to the final buzzer must reproduce the OFFICIAL boxscore
exactly -- same points, same minutes, per player. `--reconcile-only` runs that
and nothing else. A residual computed from a replay that does not reconcile is
a number about a bug, and this project has published enough of those.

SCOPE, stated rather than discovered later: POINTS and MINUTES first. Points is
the highest-volume prop and both reconstruct unambiguously from `scoreValue` and
substitution events.

REBOUNDS AND ASSISTS `[2026-09-28, lane live-props-model-probability]` turned out
NOT to need text parsing: ESPN's plays carry them STRUCTURALLY. A rebound is a
play whose `type.text` contains "Rebound" with the rebounder as `participants[0]`
(team rebounds carry NO participant, and the box credits no player with them); an
assist is `participants[1]` on a made field goal (`scoringPlay` with two
participants -- a block is two participants on a MISS, so it never counts). Each
is admitted under the same gate as points: the replay must reproduce the official
box's `rebounds` / `assists` EXACTLY, per player, or the game is not graded for
that stat. THREES likewise: a made three is a scoring play worth 3, reconciled
against the made half of the box's made-attempted pair. `--stat` picks which
residual to measure.

    py -3 scripts/grade_wnba_live_prop_projection.py --events 401857158 --reconcile-only
    py -3 scripts/grade_wnba_live_prop_projection.py --date 2026-08-19
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
_PERIOD_MINUTES = 10.0
_OT_MINUTES = 5.0


def _get(url: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def elapsed_minutes(period: Any, clock_text: Any) -> float | None:
    """Total minutes elapsed since tip. Mirrors `_wnba_elapsed_minutes`'s
    convention (10-minute quarters, 5-minute OT) rather than re-deriving it."""
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
    # disproportionately free throws. Measured on event 401857158: the replay
    # reconciled 10/17 players on points, every miss UNDER the official box
    # (Mitchell 25 vs 37), while `sum(scoreValue)` over all scoring plays
    # equalled the official 176.0 exactly. The plays were all there; this parser
    # was throwing them away.
    #
    # `_wnba_elapsed_minutes` in production has the same MM:SS-only rule, but is
    # NOT exposed to this: `_infer_period_clock_from_status_text` already
    # matches the decimal-seconds form (`55.7 - 4th` -> period 4, `0:55`), so
    # the live lane survives the final minute. Checked before assuming a
    # production defect.
    try:
        if ":" in text:
            minutes_left, seconds_left = (int(part) for part in text.split(":", 1))
            remaining_raw = minutes_left + seconds_left / 60.0
        else:
            remaining_raw = float(text) / 60.0
    except ValueError:
        return None
    length = _PERIOD_MINUTES if period_number <= 4 else _OT_MINUTES
    remaining = max(0.0, min(length, remaining_raw))
    prior = ((period_number - 1) * _PERIOD_MINUTES if period_number <= 4
             else 4 * _PERIOD_MINUTES + (period_number - 5) * _OT_MINUTES)
    return prior + (length - remaining)


def _stat_at(stats: list[Any], index: int | None) -> float | None:
    if index is None or len(stats) <= index:
        return None
    try:
        return float(stats[index])
    except (TypeError, ValueError):
        return None


def _made_at(stats: list[Any], index: int | None) -> float | None:
    """`"3-7"` -> 3.0: the MADE half of a made-attempted pair."""
    if index is None or len(stats) <= index:
        return None
    try:
        return float(str(stats[index]).split("-", 1)[0])
    except (TypeError, ValueError):
        return None


def official_box(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """athlete id -> {name, starter, minutes, points, rebounds, assists} from the OFFICIAL box."""
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


def replay(summary: dict[str, Any]) -> dict[str, Any]:
    """Walk the plays, accumulating per-athlete points and minutes over time.

    Returns the end state plus every sample point, so the caller can both
    reconcile and grade from one pass.
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
    # the same sampling design as points (a sample at the scorer's scoring play),
    # so the three residual tables are comparable.
    stat_samples: dict[str, list[dict[str, Any]]] = {"rebounds": [], "assists": [], "threes": []}
    # CLOCK SAMPLES `[2026-09-28]`: every player who has played, at every whole game
    # minute, with counts AS OF that moment. The event samples above are taken right
    # after the player's own event -- when count/minutes (the pace the projection
    # extrapolates) is at its most inflated, worst for low-count stats. Production
    # prices on a clock tick, not after an event, so this is the design that matches it.
    clock_samples: list[dict[str, Any]] = []
    next_minute = 1.0
    # GAME STATE for a remaining-minutes model `[2026-09-28]`: the running score (a
    # blowout benches starters) and personal fouls (six and out).
    competitors = (((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or [])
    home_id = next((str(c.get("id")) for c in competitors if c.get("homeAway") == "home"), "")
    score = {"home": 0.0, "away": 0.0}
    fouls: dict[str, float] = {aid: 0.0 for aid in box}
    last_clock = 0.0

    plays = summary.get("plays") or []
    for play in plays:
        now = elapsed_minutes(play.get("period"), play.get("clock"))
        if now is None:
            continue
        # Credit every on-court player for the interval since the last event.
        while now >= next_minute:
            # Snapshot BEFORE this play's events: the state at the minute boundary.
            for aid in box:
                played = minutes.get(aid, 0.0) + (
                    max(0.0, next_minute - last_clock) if aid in on_court else 0.0)
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

        participants = [str(((p or {}).get("athlete") or {}).get("id") or "")
                        for p in (play.get("participants") or [])]
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
                    # A made three is a scoring play worth 3. Free throws are worth 1,
                    # so no other scoring play can carry that value.
                    threes[scorer] += 1.0
                    stat_samples["threes"].append({
                        "elapsed": round(now, 3), "athlete_id": scorer,
                        "value": threes[scorer], "minutes": round(minutes.get(scorer, 0.0), 3),
                    })
                samples.append({
                    "elapsed": round(now, 3),
                    "athlete_id": scorer,
                    "points": points[scorer],
                    "minutes": round(minutes.get(scorer, 0.0), 3),
                })

    # Final interval to the buzzer, so end-state minutes are complete.
    end = max((elapsed_minutes(p.get("period"), p.get("clock")) or 0.0) for p in plays) if plays else 0.0
    for aid in on_court:
        if aid in minutes:
            minutes[aid] += max(0.0, end - last_clock)

    return {"box": box, "points": points, "minutes": minutes,
            "rebounds": rebounds, "assists": assists, "threes": threes, "stat_samples": stat_samples,
            "clock_samples": clock_samples,
            "samples": samples, "end_elapsed": round(end, 3)}


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
            points_off.append(f'{row["name"]}: replay {state["points"].get(aid, 0.0):.0f} vs box {row["points"]:.0f}')
        if abs(state["minutes"].get(aid, 0.0) - row["minutes"]) <= minutes_tolerance:
            minutes_within += 1
        else:
            minutes_off.append(f'{row["name"]}: replay {state["minutes"].get(aid, 0.0):.1f} vs box {row["minutes"]:.1f}')
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
        "rebounds_exact": stat_exact["rebounds"],
        "rebounds_off": stat_off["rebounds"],
        "assists_exact": stat_exact["assists"],
        "assists_off": stat_off["assists"],
        "threes_exact": stat_exact["threes"],
        "threes_off": stat_off["threes"],
        "points_exact": points_exact,
        "points_off": points_off,
        "minutes_within_tolerance": minutes_within,
        "minutes_off": minutes_off,
        "minutes_tolerance": minutes_tolerance,
    }



def sim_anchor_index(date_str: str) -> dict[str, dict[str, Any]]:
    """`normalized player name -> {pts_mean, min_mean}` from that date's sim.

    Read through `read_json_file` so it works from a worker; falls back to the
    web export when run from a laptop. Returns {} rather than raising -- a date
    whose sim was never published must degrade to "no anchor", which the grader
    then counts by name instead of silently scoring fewer samples.
    """
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    relative = f"wnba_source/data/processed/cards_sim_detail_{date_str}.json"
    payload: Any = None
    try:
        from syndicate.features.shared.refresh_state_store import data_root, read_json_file

        payload = read_json_file(data_root() / relative)
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        try:
            # ENV FIRST, then `.env`. On Render `ADMIN_TOKEN` is an environment
            # variable; `.env` is gitignored, so a git WORKTREE has none and the
            # token silently came back empty -- the export then failed and the
            # anchor index returned {} with no error, which reads exactly like
            # "that date has no sim". Measured here: 0 anchors for 2026-08-19
            # while the export itself was fine.
            token = os.environ.get("ADMIN_TOKEN", "").strip()
            if not token:
                for candidate in (REPO_ROOT / ".env", Path.cwd() / ".env"):
                    if not candidate.exists():
                        continue
                    for line in candidate.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("ADMIN_TOKEN"):
                            token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if token:
                        break
            if not token:
                print("[grade] NO ADMIN_TOKEN -- cannot fetch the sim anchor; "
                      "set ADMIN_TOKEN or run from a tree with .env", flush=True)
                return {}
            # `/stream`, NOT `/export`: export reads on web have 502'd the board
            # under load (state_model.md, model-scorecard); stream sends the file.
            url = ("https://syndicate-an21.onrender.com/api/ops/artifacts/stream?"
                   + urllib.parse.urlencode({"path": relative}))
            request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            payload = None
    if not isinstance(payload, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for game in payload.get("games") or []:
        players = ((game or {}).get("sim") or {}).get("players")
        if not isinstance(players, dict):
            continue
        for side in ("home", "away"):
            for row in players.get(side) or []:
                if not isinstance(row, dict):
                    continue
                key = normalize_name(row.get("player_name"))
                if key and key not in out:
                    out[key] = {"pts_mean": row.get("pts_mean"),
                                "reb_mean": row.get("reb_mean"),
                                "ast_mean": row.get("ast_mean"),
                                "threes_mean": row.get("threes_mean"),
                                "min_mean": row.get("min_mean")}
    return out


_STAT_MEAN_KEY = {"points": "pts_mean", "rebounds": "reb_mean", "assists": "ast_mean",
                  "threes": "threes_mean"}


def grade_event(summary: dict[str, Any], anchors: dict[str, dict[str, Any]],
                stat: str = "points", sampling: str = "event") -> dict[str, Any]:
    """Residuals of the SHIPPED projection against the actual final, per sample."""
    from syndicate.features.shared.wnba_live_prop_projection import project_live_player_stat
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    state = replay(summary)
    box = state["box"]
    end = state["end_elapsed"] or 40.0
    rows: list[dict[str, Any]] = []
    no_anchor: set[str] = set()
    if sampling == "clock":
        samples = [dict(s, value=s[stat]) for s in state["clock_samples"]]
    elif stat == "points":
        samples = [dict(s, value=s["points"]) for s in state["samples"]]
    else:
        samples = state["stat_samples"][stat]
    mean_key = _STAT_MEAN_KEY[stat]
    for sample in samples:
        row = box.get(sample["athlete_id"])
        if row is None:
            continue
        anchor = anchors.get(normalize_name(row.get("name")))
        if not anchor:
            no_anchor.add(str(row.get("name")))
            continue
        verdict = project_live_player_stat(
            current_stat=sample["value"],
            minutes_played=sample["minutes"],
            pregame_stat=anchor.get(mean_key),
            pregame_minutes=anchor.get("min_mean"),
            game_minutes_remaining=max(0.0, end - sample["elapsed"]),
        )
        if verdict.get("projected") is None:
            continue
        rows.append({
            "player": row.get("name"),
            "elapsed": sample["elapsed"],
            "minutes_remaining": verdict.get("minutes_remaining"),
            "projected": verdict["projected"],
            "current": sample["value"],
            "minutes_played": sample.get("minutes"),
            "elapsed": sample.get("elapsed"),
            "game_clock_left": round(max(0.0, end - sample["elapsed"]), 3),
            "final_minutes": row.get("minutes"),
            "pregame_minutes": anchor.get("min_mean"),
            "pregame_stat": anchor.get(mean_key),
            "margin": sample.get("margin"),
            "fouls": sample.get("fouls"),
            "on_court": sample.get("on_court"),
            "actual": row[stat],
            "residual": verdict["projected"] - row[stat],
        })
    return {"rows": rows, "no_anchor": sorted(no_anchor)}



# ---------------------------------------------------------------- totals ----
#
# GRADING THE LIVE TOTALS ESTIMATOR. `_wnba_live_total_over_prob` still carries
# `8.0 + 0.50 * min_left`, a ported constant `#481` explicitly declined to refit
# because "refitting needs historical market totals, unavailable here". That was
# half right: retained `book_quotes` genuinely expire, but ESPN's own
# `pickcenter` carries the closing `overUnder` per past game, free. So the grade
# costs no OddsAPI credits and needs no backfill.
#
# METHOD MIRRORS `#481`'s: drive the SHIPPED functions over real games and score
# against outcomes, with a NEUTRAL pregame anchor so the LIVE transform is what
# is being measured rather than the quality of a pregame total projection. The
# market's own line stands in as the pregame projection (the honest neutral
# choice -- it is what the market thought before tip) and `p_total_over` starts
# at 0.5. `#481` recorded the same caveat for its own neutral anchor: it makes
# the pregame BLEND look worse than it is, and that is a property of the test
# setup, not a finding about the blend.


def grade_totals_event(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Score the shipped live-total transform at every scoring play."""
    from syndicate.features.wnba.cards import (
        _wnba_live_total_over_prob,
        _wnba_live_total_projection,
    )

    picks = summary.get("pickcenter") if isinstance(summary.get("pickcenter"), list) else []
    line = None
    for pick in picks:
        if isinstance(pick, dict) and pick.get("overUnder") is not None:
            try:
                line = float(pick["overUnder"])
            except (TypeError, ValueError):
                continue
            break
    if line is None:
        return None

    plays = summary.get("plays") or []
    samples: list[dict[str, Any]] = []
    final_total = None
    for play in plays:
        now = elapsed_minutes(play.get("period"), play.get("clock"))
        if now is None:
            continue
        try:
            running = float(play.get("homeScore")) + float(play.get("awayScore"))
        except (TypeError, ValueError):
            continue
        final_total = running
        if not play.get("scoringPlay"):
            continue
        projected = _wnba_live_total_projection(line, running, now)
        if projected is None:
            continue
        prob = _wnba_live_total_over_prob(0.5, projected, line, now)
        if prob is None:
            continue
        samples.append({
            "elapsed": round(now, 3),
            "minutes_left": round(max(0.0, 40.0 - now), 3),
            "current_total": running,
            "projected_total": round(float(projected), 3),
            "prob_over": float(prob),
        })
    if final_total is None or not samples:
        return None
    # PUSH IS EXCLUDED, not counted as a loss. A total landing exactly on the
    # line is neither over nor under, and scoring it either way biases the
    # calibration in a direction nobody chose.
    if abs(final_total - line) < 1e-9:
        return {"line": line, "final_total": final_total, "samples": [], "push": True}
    outcome = 1.0 if final_total > line else 0.0
    for sample in samples:
        sample["outcome"] = outcome
        sample["brier"] = (sample["prob_over"] - outcome) ** 2
    return {"line": line, "final_total": final_total, "samples": samples, "push": False}


def event_ids_for_date(date_str: str) -> list[str]:
    payload = _get(f"{_SCOREBOARD}?dates={date_str.replace('-', '')}")
    return [str(e.get("id")) for e in (payload.get("events") or []) if e.get("id")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", nargs="*", default=None, help="ESPN event ids")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; grades every game that day")
    parser.add_argument("--stat", choices=("points", "rebounds", "assists", "threes"), default="points",
                        help="which residual to grade; each is gated on ITS OWN exact reconcile")
    parser.add_argument("--sampling", choices=("event", "clock"), default="event",
                        help="event: at the player's own events (the original design); "
                             "clock: every player at every game minute (matches production)")
    parser.add_argument("--reconcile-only", action="store_true",
                        help="replay and check against the official box; grade nothing")
    args = parser.parse_args(argv)

    events = list(args.events or [])
    if args.date:
        events.extend(event_ids_for_date(args.date))
    if not events:
        print("no events given (--events or --date)", flush=True)
        return 1

    totals = {"games": 0, "players": 0, "points_exact": 0, "minutes_within": 0,
              "rebounds_exact": 0, "assists_exact": 0, "games_graded": 0}
    graded: list[dict[str, Any]] = []
    no_anchor_all: set[str] = set()
    anchor_cache: dict[str, dict[str, Any]] = {}
    for event_id in events:
        try:
            summary = _get(f"{_SUMMARY}?event={urllib.parse.quote(str(event_id))}")
        except Exception as exc:  # noqa: BLE001
            print(f"event={event_id} FETCH_FAILED {type(exc).__name__}: {exc}", flush=True)
            continue
        state = replay(summary)
        check = reconcile(state)
        stat_ok = check[f"{args.stat}_exact"] == check["players"]
        if not args.reconcile_only and check["points_exact"] == check["players"] and stat_ok:
            # GRADE ONLY A GAME WHOSE REPLAY RECONCILED. A residual from a
            # replay that disagrees with the official box measures the bug.
            date_for_anchor = args.date or str(((summary.get("header") or {}).get("competitions") or [{}])[0].get("date") or "")[:10]
            anchors = anchor_cache.get(date_for_anchor)
            if anchors is None:
                anchors = sim_anchor_index(date_for_anchor)
                anchor_cache[date_for_anchor] = anchors
            result = grade_event(summary, anchors, args.stat, args.sampling)
            totals["games_graded"] += 1
            graded.extend(result["rows"])
            no_anchor_all.update(result["no_anchor"])
        totals["games"] += 1
        totals["players"] += check["players"]
        totals["points_exact"] += check["points_exact"]
        totals["minutes_within"] += check["minutes_within_tolerance"]
        totals["rebounds_exact"] += check["rebounds_exact"]
        totals["assists_exact"] += check["assists_exact"]
        print(f"event={event_id} players={check['players']} "
              f"points_exact={check['points_exact']}/{check['players']} "
              f"minutes_within_{check['minutes_tolerance']}min="
              f"{check['minutes_within_tolerance']}/{check['players']} "
              f"rebounds_exact={check['rebounds_exact']}/{check['players']} "
              f"assists_exact={check['assists_exact']}/{check['players']} "
              f"samples={len(state['samples'])}", flush=True)
        for line in check[f"{args.stat}_off"][:5] if args.stat != "points" else ():
            print(f"    {args.stat.upper()}_OFF {line}", flush=True)
        for line in check["points_off"][:5]:
            print(f"    POINTS_OFF {line}", flush=True)
        for line in check["minutes_off"][:5]:
            print(f"    MINUTES_OFF {line}", flush=True)

    if not args.reconcile_only and graded:
        # BUCKETED BY MINUTES REMAINING, because the whole point is that the
        # interval SHRINKS as the game runs down -- a single sd over all samples
        # would describe neither end and would price both wrongly.
        print()
        print(f"RESIDUALS (projected - actual final {args.stat}), by minutes remaining:")
        print(f"  {'bucket':>12}  {'n':>5}  {'mean':>7}  {'sd':>6}  {'p90|err|':>8}")
        buckets = ((30.0, 99.0), (20.0, 30.0), (10.0, 20.0), (5.0, 10.0), (0.0, 5.0))
        for low, high in buckets:
            vals = [r["residual"] for r in graded if low <= (r["minutes_remaining"] or 0.0) < high]
            if len(vals) < 5:
                print(f"  {f'{low:g}-{high:g}':>12}  {len(vals):>5}  {'(too few)':>7}")
                continue
            sd = statistics.pstdev(vals)
            p90 = sorted(abs(v) for v in vals)[int(0.9 * (len(vals) - 1))]
            print(f"  {f'{low:g}-{high:g}':>12}  {len(vals):>5}  {statistics.fmean(vals):>7.2f}  {sd:>6.2f}  {p90:>8.2f}")
        allv = [r["residual"] for r in graded]
        print(f"  {'ALL':>12}  {len(allv):>5}  {statistics.fmean(allv):>7.2f}  "
              f"{statistics.pstdev(allv):>6.2f}")
        if no_anchor_all:
            print(f"  players with NO sim anchor (excluded): {len(no_anchor_all)} "
                  f"e.g. {sorted(no_anchor_all)[:4]}")

    print()
    print(f"TOTALS games={totals['games']} graded={totals['games_graded']} players={totals['players']} "
          f"points_exact={totals['points_exact']} rebounds_exact={totals['rebounds_exact']} "
          f"assists_exact={totals['assists_exact']} minutes_within={totals['minutes_within']}",
          flush=True)
    if totals["players"]:
        pct = 100.0 * totals["points_exact"] / totals["players"]
        print(f"  points reconcile: {pct:.1f}%", flush=True)
        if pct < 99.0:
            # The replay is the instrument. An instrument that does not agree
            # with the official record cannot be used to measure a residual.
            print("  REPLAY DOES NOT RECONCILE -- do not grade from this.", flush=True)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
