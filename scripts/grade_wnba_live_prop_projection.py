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

SCOPE, stated rather than discovered later: POINTS and MINUTES only. Points is
the highest-volume prop and both reconstruct unambiguously from `scoreValue` and
substitution events. Rebounds and assists need text parsing whose failure mode
is silent under-counting, so they are left out until they can be reconciled the
same way.

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


def official_box(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """athlete id -> {name, starter, minutes, points} from the OFFICIAL box."""
    out: dict[str, dict[str, Any]] = {}
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        for stat_block in team_block.get("statistics") or []:
            keys = [str(k) for k in (stat_block.get("keys") or [])]
            try:
                minutes_at, points_at = keys.index("minutes"), keys.index("points")
            except ValueError:
                continue
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
    minutes: dict[str, float] = {aid: 0.0 for aid in box}
    samples: list[dict[str, Any]] = []
    last_clock = 0.0

    plays = summary.get("plays") or []
    for play in plays:
        now = elapsed_minutes(play.get("period"), play.get("clock"))
        if now is None:
            continue
        # Credit every on-court player for the interval since the last event.
        delta = max(0.0, now - last_clock)
        if delta:
            for aid in on_court:
                if aid in minutes:
                    minutes[aid] += delta
        last_clock = now

        participants = [str(((p or {}).get("athlete") or {}).get("id") or "")
                        for p in (play.get("participants") or [])]
        type_text = str((play.get("type") or {}).get("text") or "").lower()

        if "substitution" in type_text and len(participants) >= 2:
            entering, leaving = participants[0], participants[1]
            if leaving in box:
                on_court.discard(leaving)
            if entering in box:
                on_court.add(entering)
            continue

        if play.get("scoringPlay") and participants:
            scorer = participants[0]
            try:
                value = float(play.get("scoreValue") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if scorer in points and value:
                points[scorer] += value
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
    return {
        "players": len(box),
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
            url = ("https://syndicate-an21.onrender.com/api/ops/artifacts/export?"
                   + urllib.parse.urlencode({"path": relative}))
            request = urllib.request.Request(url, headers={"X-Admin-Token": token})
            with urllib.request.urlopen(request, timeout=120) as response:
                envelope = json.loads(response.read().decode("utf-8"))
            body = (envelope.get("artifacts") or {}).get(relative)
            payload = json.loads(body) if body else None
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
                                "min_mean": row.get("min_mean")}
    return out


def grade_event(summary: dict[str, Any], anchors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Residuals of the SHIPPED projection against the actual final, per sample."""
    from syndicate.features.shared.wnba_live_prop_projection import project_live_player_stat
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    state = replay(summary)
    box = state["box"]
    end = state["end_elapsed"] or 40.0
    rows: list[dict[str, Any]] = []
    no_anchor: set[str] = set()
    for sample in state["samples"]:
        row = box.get(sample["athlete_id"])
        if row is None:
            continue
        anchor = anchors.get(normalize_name(row.get("name")))
        if not anchor:
            no_anchor.add(str(row.get("name")))
            continue
        verdict = project_live_player_stat(
            current_stat=sample["points"],
            minutes_played=sample["minutes"],
            pregame_stat=anchor.get("pts_mean"),
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
            "actual": row["points"],
            "residual": verdict["projected"] - row["points"],
        })
    return {"rows": rows, "no_anchor": sorted(no_anchor)}


def event_ids_for_date(date_str: str) -> list[str]:
    payload = _get(f"{_SCOREBOARD}?dates={date_str.replace('-', '')}")
    return [str(e.get("id")) for e in (payload.get("events") or []) if e.get("id")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", nargs="*", default=None, help="ESPN event ids")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; grades every game that day")
    parser.add_argument("--reconcile-only", action="store_true",
                        help="replay and check against the official box; grade nothing")
    args = parser.parse_args(argv)

    events = list(args.events or [])
    if args.date:
        events.extend(event_ids_for_date(args.date))
    if not events:
        print("no events given (--events or --date)", flush=True)
        return 1

    totals = {"games": 0, "players": 0, "points_exact": 0, "minutes_within": 0}
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
        if not args.reconcile_only and check["points_exact"] == check["players"]:
            # GRADE ONLY A GAME WHOSE REPLAY RECONCILED. A residual from a
            # replay that disagrees with the official box measures the bug.
            date_for_anchor = args.date or str(((summary.get("header") or {}).get("competitions") or [{}])[0].get("date") or "")[:10]
            anchors = anchor_cache.get(date_for_anchor)
            if anchors is None:
                anchors = sim_anchor_index(date_for_anchor)
                anchor_cache[date_for_anchor] = anchors
            result = grade_event(summary, anchors)
            graded.extend(result["rows"])
            no_anchor_all.update(result["no_anchor"])
        totals["games"] += 1
        totals["players"] += check["players"]
        totals["points_exact"] += check["points_exact"]
        totals["minutes_within"] += check["minutes_within_tolerance"]
        print(f"event={event_id} players={check['players']} "
              f"points_exact={check['points_exact']}/{check['players']} "
              f"minutes_within_{check['minutes_tolerance']}min="
              f"{check['minutes_within_tolerance']}/{check['players']} "
              f"samples={len(state['samples'])}", flush=True)
        for line in check["points_off"][:5]:
            print(f"    POINTS_OFF {line}", flush=True)
        for line in check["minutes_off"][:5]:
            print(f"    MINUTES_OFF {line}", flush=True)

    if not args.reconcile_only and graded:
        # BUCKETED BY MINUTES REMAINING, because the whole point is that the
        # interval SHRINKS as the game runs down -- a single sd over all samples
        # would describe neither end and would price both wrongly.
        print()
        print("RESIDUALS (projected - actual final points), by minutes remaining:")
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
    print(f"TOTALS games={totals['games']} players={totals['players']} "
          f"points_exact={totals['points_exact']} minutes_within={totals['minutes_within']}",
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
