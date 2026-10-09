"""Build the 2026 WNBA in-game CHECKPOINT corpus from ESPN play-by-play.

Lane `wnba-native-live-cutover` (P5 of `docs/ai_context/basketball_live_native_plan.md`),
prerequisite-free part: nothing here simulates. This produces the FIXED, PAIRED population that
P5's verification is scored on: the native re-sim and the current linear lens must be graded
on the SAME games at the SAME checkpoints, and that population is decided here, before either
side is run.

One row per (game, checkpoint). Checkpoints: end of Q1, end of Q2, end of Q3, 5:00 left in Q4
(the plan's P3 list). A row carries:

* ``state`` -- P2's typed ``LiveGameState`` (`syndicate/features/shared/basketball_live_state.py`)
  built from an AS-OF summary (plays cut at the checkpoint, header score = the running score, status
  in progress) -- the SAME parser production's live tick uses, so P3/P5 resume from exactly what the
  backtest grades. Its clock is the last play's (what a live tick sees), so the "5:00 Q4" cell is
  usually 5:0x-5:2x; ``checkpoint_secs_left_regulation`` keeps the nominal instant. Added beside it:
  per-player REB / AST / 3PM so far (P2 carries PTS and PF), ESPN's live WP at the cut, and, at an
  end-of-period cut only, the next period's possession (fixed by the alternating rule; basis
  ``quarter_start_rule_observed``). ``stints`` / ``notes`` are dropped for size;
  ``lineup_fill_by_final_box_minutes`` counts P2's one fallback that reads the FINAL box (0 of 1,376
  cells on the 2026 build).
* ``pregame`` -- ESPN pickcenter spread (home-relative) and total, when present.
* ``outcome`` -- final (incl. OT) and regulation scores, OT flag, and each player's final box.

WHY THE RECONCILIATION BLOCK IS THE GATE. A corpus whose state is parsed wrong grades both
models against a fiction, and they would agree with each other perfectly while doing it. Every
game is reconciled on P2's full-game reconstruction: the sum of the log's scoring plays must equal
the header score, and per-player PTS / REB / AST / PF must equal the box. A score failure EXCLUDES the game;
a stat failure keeps it for game lines and marks ``props_reconciled: false`` so a prop backtest
drops it. Both are COUNTED in the summary, never silent. Minutes from the stint
reconstruction are reported as a match rate (box minutes are rounded integers, and ESPN omits
period-start lineups), not gated.

Season types are kept separate (2 = regular, 3 = playoffs; anything else is reported and
excluded) -- they are different populations, and the verification reports them separately.

Fetching reuses `basketball_scenario_rates` (same ESPN endpoints and gz cache layout), so a
cache built by that script is reused as-is.

Usage (run at Idle priority -- the fleet shares this machine):
    py -3 scripts/build_wnba_live_checkpoint_corpus.py --out <dir> --start 2026-05-01 --end 2026-10-20
    py -3 scripts/build_wnba_live_checkpoint_corpus.py --out <dir> --offline   # cache only
"""
from __future__ import annotations

import argparse
import copy
import glob
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import basketball_scenario_rates as bsr  # noqa: E402
from syndicate.features.shared import basketball_live_state as bls  # noqa: E402
from syndicate.features.shared import basketball_pbp as pbp  # noqa: E402


LEAGUE = "wnba"
PERIOD_SECONDS = 600.0
REG_PERIODS = 4
# (label, period, seconds left in that period). State = every play at or before this instant.
CHECKPOINTS: Tuple[Tuple[str, int, float], ...] = (
    ("end_q1", 1, 0.0),
    ("end_q2", 2, 0.0),
    ("end_q3", 3, 0.0),
    ("q4_5min", 4, 300.0),
)
SEASON_TYPES = {2: "regular", 3: "playoffs"}

def _play_type(p: Dict[str, Any]) -> str:
    return str((p.get("type") or {}).get("text") or "").strip().lower()


def _period(p: Dict[str, Any]) -> int:
    return int(((p.get("period") or {}).get("number")) or 0)


def _game_sides(summary: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    out: Dict[str, Dict[str, Any]] = {}
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        team = c.get("team") or {}
        out[side] = {
            "id": str(team.get("id") or ""), "abbr": team.get("abbreviation"),
            "name": team.get("displayName"),
            "score": bsr._num(c.get("score")),
            "lines": [bsr._num(x.get("displayValue", x.get("value"))) for x in c.get("linescores") or []],
        }
    return out if set(out) == {"home", "away"} else None


def _box_players(summary: Dict[str, Any], team_side: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """athlete id -> {side, name, starter, min, pts, reb, ast, fg3m, pf}; DNPs kept with played False."""
    out: Dict[str, Dict[str, Any]] = {}
    for t in (summary.get("boxscore") or {}).get("players") or []:
        side = team_side.get(str((t.get("team") or {}).get("id") or ""))
        if side is None:
            continue
        stats = (t.get("statistics") or [{}])[0]
        ix = {k: i for i, k in enumerate(stats.get("keys") or [])}

        def val(vals: List[Any], key: str) -> Optional[float]:
            i = ix.get(key)
            return bsr._num(vals[i]) if i is not None and i < len(vals) else None

        for a in stats.get("athletes") or []:
            aid = str((a.get("athlete") or {}).get("id") or "")
            vals = a.get("stats") or []
            played = bool(vals) and not a.get("didNotPlay")
            fg3m, _ = bsr._pair(vals[ix["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]]) \
                if played and "threePointFieldGoalsMade-threePointFieldGoalsAttempted" in ix else (None, None)
            out[aid] = {
                "side": side, "name": (a.get("athlete") or {}).get("displayName"),
                "starter": bool(a.get("starter")), "played": played,
                "min": val(vals, "minutes") if played else 0.0,
                "pts": val(vals, "points") if played else 0.0,
                "reb": val(vals, "rebounds") if played else 0.0,
                "ast": val(vals, "assists") if played else 0.0,
                "fg3m": fg3m if played else 0.0,
                "pf": val(vals, "fouls") if played else 0.0,
            }
    return out


def _elapsed(period: int, secs_left: float) -> float:
    """Game seconds elapsed. OT periods are 5:00."""
    if period <= REG_PERIODS:
        return (period - 1) * PERIOD_SECONDS + (PERIOD_SECONDS - secs_left)
    return REG_PERIODS * PERIOD_SECONDS + (period - REG_PERIODS - 1) * 300.0 + (300.0 - secs_left)


def _cut_index(plays: List[Dict[str, Any]], cp_period: int, cp_secs: float) -> Optional[int]:
    """Index of the first play strictly AFTER the checkpoint instant (the feed's list order is
    chronological). None when the game never got past it."""
    for i, p in enumerate(plays):
        per = _period(p)
        secs = bsr._clock_seconds(p.get("clock"))
        if per > cp_period or (per == cp_period and secs is not None and secs < cp_secs):
            return i
    return None


def as_of_summary(summary: Dict[str, Any], cut: int) -> Dict[str, Any]:
    """The summary a LIVE tick would have fetched at the checkpoint: plays up to the cut, the
    header score = the score AT the cut, status in progress, no linescores.

    WHY THE HEADER IS REWRITTEN: `basketball_live_state.build_live_game_state` takes the team score
    from ESPN's HEADER (its documented choice, measured on 1,420 NBA games). A completed game's header
    holds the FINAL score, so passing the truncated plays alone would score every checkpoint with the
    final.

    WHY THE SCORE IS THE SUM OF SCORING PLAYS, NOT THE PLAYS' RUNNING `homeScore`: measured 2026-10-09
    on the 2026 WNBA season, the running field lags the sum of scoring plays on 36 of 347 games, for 1
    to 132 consecutive plays (a basket missing from the running field), while the play sum reaches the
    official final on every kept game. A live tick reads ESPN's official header, which the play sum
    tracks; the running field does not. (This script's first version read the running field, and a
    cross-check against its own tracker "agreed" on every cell -- because both read the same field.)
    """
    plays = list(summary.get("plays") or [])[:cut]
    header = copy.deepcopy(summary.get("header") or {})
    comp = (header.get("competitions") or [{}])[0]
    comp["status"] = {"type": {"state": "in", "completed": False, "name": "STATUS_IN_PROGRESS"}}
    out = {k: v for k, v in summary.items() if k not in ("plays", "header", "winprobability")}
    out["plays"] = plays
    out["header"] = header
    meta = pbp.game_meta(out, LEAGUE)
    score = pbp.reconstructed_score(pbp.normalize_plays(out, meta))
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        if side in score:
            c["score"] = str(score[side])
        c["linescores"] = []
    return out


def _player_counts(events: List[Any]) -> Dict[str, Dict[str, int]]:
    """REB / AST / 3PM per player so far, from P2's NORMALIZED events (P2's PlayerLiveState carries
    PTS and PF but not these; live props need them). Participant 0 is the actor, 1 the assister."""
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"reb": 0, "ast": 0, "fg3m": 0})
    for e in events:
        if not e.players:
            continue
        if e.kind in ("rebound_off", "rebound_def"):
            out[e.players[0]]["reb"] += 1
        elif e.kind == "shot" and e.made:
            if e.points_attempted == 3:
                out[e.players[0]]["fg3m"] += 1
            if len(e.players) >= 2 and "assist" in e.text.lower():
                out[e.players[1]]["ast"] += 1
    return out


def _quarter_start_possession(plays: List[Dict[str, Any]], cut: int, team_side: Dict[str, str]) -> Optional[str]:
    """At an end-of-period cut the log says nothing about who starts the next period (P2 returns
    None, basis `end_period`). That side is fixed by the alternating-possession rule, so reading it
    off the next period's first offensive action is the RULE's answer, not outcome leakage. Never
    used for a mid-period cut, where it WOULD leak (who won the next rebound)."""
    for p in plays[cut:]:
        t = _play_type(p)
        side = team_side.get(str((p.get("team") or {}).get("id") or ""))
        if not side:
            continue
        if (bool(p.get("shootingPlay")) and not t.startswith("free throw")) or "turnover" in t \
                or t in ("offensive foul", "offensive charge"):
            return side
    return None


_DROP_STATE_KEYS = ("stints", "notes")


def state_at(summary: Dict[str, Any], cp_period: int, cp_secs: float, team_side: Dict[str, str],
             date_str: str) -> Optional[Dict[str, Any]]:
    """P2's LiveGameState at the checkpoint, plus the per-player REB/AST/3PM P2 does not carry."""
    plays = list(summary.get("plays") or [])
    cut = _cut_index(plays, cp_period, cp_secs)
    if cut is None or cut == 0:
        return None
    s = as_of_summary(summary, cut)
    st = bls.build_live_game_state(s, LEAGUE, date=date_str, built_at="corpus")
    d = st.to_dict()
    notes = list(st.notes)
    for k in _DROP_STATE_KEYS:
        d.pop(k, None)
    d["lineup_fill_by_final_box_minutes"] = sum(1 for n in notes if "filled_by_minutes" in n)
    d["notes_n"] = len(notes)
    meta = pbp.game_meta(s, LEAGUE, date=date_str)
    counts = _player_counts(pbp.normalize_plays(s, meta))
    for pl in d["players"]:
        pl.update(counts.get(pl["player_id"], {"reb": 0, "ast": 0, "fg3m": 0}))
    if d.get("possession_side") is None and cp_secs == 0.0:
        d["possession_side"] = _quarter_start_possession(plays, cut, team_side)
        d["possession_basis"] = "quarter_start_rule_observed" if d["possession_side"] else d.get("possession_basis")
    last_run = next((q for q in reversed(plays[:cut]) if q.get("homeScore") is not None and q.get("awayScore") is not None), None)
    d["running_score_field_lagged"] = bool(last_run) and (
        int(last_run["homeScore"]), int(last_run["awayScore"])) != (d["home"]["score"], d["away"]["score"])
    last_id = str(plays[cut - 1].get("id") or "")
    wp = {str(w.get("playId")): w.get("homeWinPercentage") for w in summary.get("winprobability") or []}
    d["espn_home_wp"] = wp.get(last_id)
    d["checkpoint_secs_left_regulation"] = max(0.0, REG_PERIODS * PERIOD_SECONDS - _elapsed(cp_period, cp_secs))
    return d


def build_game(summary: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {"rows": [...], "recon": {...}}. rows is empty when reconciliation fails.

    State comes from P2 (`basketball_live_state.build_live_game_state`) on an AS-OF summary per
    checkpoint -- one parser for the corpus and for production's live tick. Cross-checked 2026-10-09
    against this script's former tracker over all 1,376 cells: score, team fouls, both on-floor
    fives and per-player PF/PTS/REB/AST/3PM identical on every cell."""
    sides = _game_sides(summary)
    if not sides:
        return {"rows": [], "recon": {"ok": False, "reason": "no_home_away"}}
    team_side = {sides["home"]["id"]: "home", sides["away"]["id"]: "away"}
    box = _box_players(summary, team_side)
    plays = list(summary.get("plays") or [])
    if not plays:
        return {"rows": [], "recon": {"ok": False, "reason": "no_plays"}}

    # ---- reconciliation, on P2's full-game reconstruction ---------------------------------------
    final = bls.build_live_game_state(summary, LEAGUE, date=event["date"], built_at="corpus")
    meta = pbp.game_meta(summary, LEAGUE, date=event["date"])
    counts = _player_counts(pbp.normalize_plays(summary, meta))
    p2 = {pl.player_id: pl for pl in final.players}
    h, a = sides["home"], sides["away"]
    score_ok = final.pbp_score == {"home": h["score"], "away": a["score"]}
    reg_lines_ok = len(h["lines"]) >= REG_PERIODS and len(a["lines"]) >= REG_PERIODS
    mism = Counter()
    min_close = min_n = 0
    for aid, b in box.items():
        if not b["played"]:
            continue
        mine = p2.get(aid)
        got = {"pts": mine.pts if mine else 0, "pf": mine.pf if mine else 0, **counts.get(aid, {"reb": 0, "ast": 0})}
        for k in ("pts", "reb", "ast", "pf"):
            if b[k] is not None and abs(float(got.get(k, 0)) - b[k]) > 1e-6:
                mism[k] += 1
        if b["min"] is not None:
            min_n += 1
            if abs((mine.seconds_played if mine else 0.0) / 60.0 - b["min"]) <= 1.0:
                min_close += 1
    snaps = {label: state_at(summary, per, secs, team_side, event["date"]) for label, per, secs in CHECKPOINTS}
    snaps = {k: v for k, v in snaps.items() if v is not None}
    # Game lines need the SCORE state; props need the per-player stats too. A game whose box and
    # pbp disagree by a stat correction stays in the game-line population, flagged for props.
    ok = score_ok and reg_lines_ok and len(snaps) == len(CHECKPOINTS)
    recon = {
        "ok": ok, "score_ok": score_ok, "props_ok": not mism, "stat_mismatches": dict(mism),
        "minutes_within_1": min_close, "minutes_n": min_n, "checkpoints_found": len(snaps),
        "p2_anomalies": final.anomalies,
    }
    if not ok:
        recon["reason"] = ("score" if not score_ok else
                           "linescores" if not reg_lines_ok else "checkpoints")
        return {"rows": [], "recon": recon}

    final_home, final_away = h["score"], a["score"]
    spread = total = None
    for pc in summary.get("pickcenter") or []:
        if spread is None and pc.get("spread") is not None:
            spread = bsr._num(pc.get("spread"))
        if total is None and pc.get("overUnder") is not None:
            total = bsr._num(pc.get("overUnder"))
    outcome = {
        "home": final_home, "away": final_away, "total": final_home + final_away,
        "margin": final_home - final_away, "home_win": final_home > final_away,
        "reg_home": sum(h["lines"][:REG_PERIODS]), "reg_away": sum(a["lines"][:REG_PERIODS]),
        "ot_periods": max(0, len(h["lines"]) - REG_PERIODS),
        "players": {aid: {k: b[k] for k in ("side", "name", "starter", "min", "pts", "reb", "ast", "fg3m", "pf")}
                    for aid, b in box.items() if b["played"]},
    }
    rows = []
    for label, _, _ in CHECKPOINTS:
        rows.append({
            "event_id": event["id"], "date": event["date"], "season_type": event["season_type"],
            "phase": SEASON_TYPES.get(event["season_type"], "other"),
            "home": h["abbr"], "away": a["abbr"], "checkpoint": label, "props_reconciled": not mism,
            "home_name": h["name"], "away_name": a["name"],
            "state": snaps[label], "pregame": {"spread_home": spread, "total": total},
            "outcome": outcome,
        })
    return {"rows": rows, "recon": recon}


def load_anchors(sim_dir: Optional[Path]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """(date, HOME code, AWAY code) -> the pregame anchors PRODUCTION's live lens reads.

    The lens reads `game["betting"]` (`wnba/cards.py:1365`), whose `p_home_win` / `p_home_cover` /
    `p_total_over` / `pred_total` / `pred_margin` are threaded into `game_cards` from the per-game
    `smart_sim_<date>_<HOME>_<AWAY>.json` by `scripts/refresh_wnba_oddsapi_props.py::
    _smart_sim_projection_index` -- which is CALLED here, not re-implemented. (The first build of this
    corpus read `predictions_<date>.csv` instead: a different estimate -- e.g. DAL v TOR 2026-08-12
    p_home_win 0.657 there vs 0.74 in the sim, total 165.8 vs 180.0 -- so its baseline was anchored on
    numbers production never served.) Source: the `wnba-lines-props-backtest` as-of re-run, today's
    pregame path per date (fleet `~/wnba_bt/archive/<d>/smart_sim_*.json`).

    The lines are the sim's OWN market inputs (`market_home_spread`, `market_total`): the line its
    cover / over probabilities were computed against. Production's lens prices against the card's
    book line, which at sim time is the same quote."""
    import refresh_wnba_oddsapi_props as producer

    out: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    if not sim_dir:
        return out
    dates = sorted({f.name[len("smart_sim_"):len("smart_sim_") + 10] for f in Path(sim_dir).glob("smart_sim_2026-*.json")})
    for d in dates:
        for (home, away), entry in producer._smart_sim_projection_index(processed_root=Path(sim_dir), date_str=d).items():
            out[(d, home, away)] = {**{k: entry.get(k) for k in (
                "p_home_win", "p_home_cover", "p_total_over", "pred_total", "pred_margin",
                "market_home_spread", "market_total")}, "file": f"smart_sim_{d}_{home}_{away}.json"}
    return out


def linear_lens(state: Dict[str, Any], anchors: Optional[Dict[str, Any]], market_total: Optional[float]) -> Dict[str, Any]:
    """The CURRENT native lens's prediction at this checkpoint, computed by the SHIPPED functions in
    `syndicate/features/wnba/cards.py` (imported, never re-implemented, so the baseline cannot drift
    from production). Same anchor precedence as the call site (:1429): pred_total, else the line."""
    from syndicate.features.wnba import cards

    anc = anchors or {}
    # P2's clock: the last play's, i.e. what a live tick sees (at "5:00 Q4" it is often 5:0x-5:2x).
    elapsed = min(float(state["elapsed"]), float(state["regulation_seconds"])) / 60.0
    margin = float(state["home"]["score"]) - float(state["away"]["score"])
    cur_total = float(state["home"]["score"]) + float(state["away"]["score"])
    line_total = anc.get("market_total") if anc.get("market_total") is not None else market_total
    pre_total = anc.get("pred_total") if anc.get("pred_total") is not None else line_total
    total_proj = cards._wnba_live_total_projection(pre_total, cur_total, elapsed) if elapsed else None
    return {
        "home_win_prob": cards._wnba_live_margin_win_prob(anc.get("p_home_win"), margin, elapsed),
        "home_cover_prob": cards._wnba_live_cover_prob(anc.get("p_home_cover"), margin, anc.get("market_home_spread"), elapsed),
        "total_proj": total_proj,
        "total_over_prob": cards._wnba_live_total_over_prob(anc.get("p_total_over"), total_proj, line_total, elapsed),
        "anchor_total_used": pre_total,
        "home_spread_line": anc.get("market_home_spread"),
        "total_line": line_total,
    }


def _iter_events(out: Path, start: date, end: date, offline: bool):
    cache = out / "cache" / LEAGUE
    if offline:
        for f in sorted(glob.glob(str(cache / "scoreboard_*.json.gz"))):
            ymd = Path(f).name[len("scoreboard_"):len("scoreboard_") + 8]
            d = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            if start.isoformat() <= d <= end.isoformat():
                yield from bsr._events_for_date(LEAGUE, d, out)
        return
    d = start
    while d <= end:
        yield from bsr._events_for_date(LEAGUE, d.isoformat(), out)
        d += timedelta(days=1)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-10-20")
    ap.add_argument("--offline", action="store_true", help="use cached scoreboards/summaries only")
    ap.add_argument("--sim-anchors", default=None, help="dir of as-of smart_sim_<date>_<HOME>_<AWAY>.json")
    args = ap.parse_args(argv)
    out = Path(args.out)
    cache = out / "cache" / LEAGUE
    rows: List[Dict[str, Any]] = []
    recon_fail = Counter()
    phase_games = Counter()
    excluded_types = Counter()
    min_close = min_n = games = props_bad = 0
    anchors = load_anchors(Path(args.sim_anchors) if args.sim_anchors else None)
    anchored_games = 0
    for ev in _iter_events(out, date.fromisoformat(args.start), date.fromisoformat(args.end), args.offline):
        if ev["season_type"] not in SEASON_TYPES:
            excluded_types[ev["season_type"]] += 1
            continue
        path = cache / f"summary_{ev['id']}.json.gz"
        if args.offline and not path.exists():
            recon_fail["not_cached"] += 1
            continue
        summary = bsr._cached(path, bsr.BASE.format(sport=LEAGUE, kind="summary") + f"?event={ev['id']}")
        games += 1
        res = build_game(summary, ev)
        rec = res["recon"]
        min_close += rec.get("minutes_within_1", 0)
        min_n += rec.get("minutes_n", 0)
        if not res["rows"]:
            recon_fail[rec.get("reason", "unknown")] += 1
            continue
        phase_games[res["rows"][0]["phase"]] += 1
        st0 = res["rows"][0]["state"]
        anc = anchors.get((ev["date"], st0["home"]["code"], st0["away"]["code"]))
        anchored_games += 1 if anc else 0
        for r in res["rows"]:
            r["anchors"] = anc
            r["linear_lens"] = linear_lens(r["state"], anc, r["pregame"]["total"])
        props_bad += 0 if rec["props_ok"] else 1
        rows.extend(res["rows"])
    dest = out / "wnba_live_checkpoints_2026.jsonl"
    with dest.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    summary = {
        "games_seen": games, "games_kept": sum(phase_games.values()),
        "games_excluded_recon": dict(recon_fail), "excluded_season_types": dict(excluded_types),
        "games_by_phase": dict(phase_games),
        "games_kept_props_unreconciled": props_bad,
        "anchor_games_available": len(anchors),
        "anchors_unjoined": len(set(anchors) - {(r["date"], r["state"]["home"]["code"], r["state"]["away"]["code"]) for r in rows}),
        "games_with_anchors": anchored_games,
        "games_with_anchors_by_phase": dict(Counter(r["phase"] for r in rows if r["checkpoint"] == "end_q1" and r.get("anchors"))),
        "rows_by_phase_checkpoint": dict(Counter(f"{r['phase']}/{r['checkpoint']}" for r in rows)),
        "minutes_within_1_rate": round(min_close / min_n, 4) if min_n else None,
        "minutes_n": min_n,
        "dates": [min((r["date"] for r in rows), default=None), max((r["date"] for r in rows), default=None)],
        "rows_with_pregame_total": sum(1 for r in rows if r["pregame"]["total"] is not None),
        "rows_with_espn_wp": sum(1 for r in rows if r["state"].get("espn_home_wp") is not None),
        "possession_basis": dict(Counter(f"{r['checkpoint']}/{r['state'].get('possession_basis')}" for r in rows)),
        "cells_running_score_field_lagged": sum(1 for r in rows if r["state"]["running_score_field_lagged"]),
        "cells_lineup_filled_by_final_box_minutes": sum(1 for r in rows if r["state"]["lineup_fill_by_final_box_minutes"]),
        "q4_5min_clock_left_seconds": {
            "min": min((r["state"]["clock_left"] for r in rows if r["checkpoint"] == "q4_5min"), default=None),
            "max": max((r["state"]["clock_left"] for r in rows if r["checkpoint"] == "q4_5min"), default=None)},
        "out": str(dest),
    }
    (out / "wnba_live_checkpoints_2026.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
