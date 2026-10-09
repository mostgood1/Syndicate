"""Build the 2026 WNBA in-game CHECKPOINT corpus from ESPN play-by-play.

Lane `wnba-native-live-cutover` (P5 of `docs/ai_context/basketball_live_native_plan.md`),
prerequisite-free part. P1 (native engine), P2 (native live state) and P3 (NBA live re-sim)
have not landed, so nothing here simulates. This produces the FIXED, PAIRED population that
P5's verification is scored on: the native re-sim and the current linear lens must be graded
on the SAME games at the SAME checkpoints, and that population is decided here, before either
side is run.

One row per (game, checkpoint). Checkpoints: end of Q1, end of Q2, end of Q3, 5:00 left in Q4
(the plan's P3 list). A row carries:

* ``state`` -- what a resume API needs, reconstructed from pbp only: period, seconds left in the
  period and in regulation, score, per-team box-so-far (FGA/3PA/FTA/OREB/TOV, possessions
  estimate), team fouls in the current period, per-player PF / PTS / REB / AST / 3PM so far,
  the five on the floor for each side, and the team that has the next possession.
* ``pregame`` -- ESPN pickcenter spread (home-relative) and total, when present.
* ``espn_home_wp`` -- ESPN's own live win probability at the checkpoint's last play, a free
  third comparator.
* ``outcome`` -- final (incl. OT) and regulation scores, OT flag, and each player's final box.

WHY THE RECONCILIATION BLOCK IS THE GATE. A corpus whose state is parsed wrong grades both
models against a fiction, and they would agree with each other perfectly while doing it. Every
game is reconciled: the pbp-reconstructed final score must equal the header score, and the
pbp-summed per-player PTS / REB / AST / PF must equal the box. A score failure EXCLUDES the game;
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
import csv
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

# Personal fouls (count toward a player's six). Technicals and defensive-3-second technicals do not.
_PERSONAL_FOUL_TYPES = {
    "personal foul", "shooting foul", "offensive foul", "loose ball foul", "offensive charge",
    "personal take foul", "away from play foul", "flagrant foul type 1", "flagrant foul type 2",
    "clear path foul", "transition take foul", "inbound foul", "personal block foul",
}
# Offensive fouls are personal fouls but not TEAM fouls for the bonus.
_OFFENSIVE_FOUL_TYPES = {"offensive foul", "offensive charge"}


def _play_type(p: Dict[str, Any]) -> str:
    return str((p.get("type") or {}).get("text") or "").strip().lower()


def _period(p: Dict[str, Any]) -> int:
    return int(((p.get("period") or {}).get("number")) or 0)


def _participants(p: Dict[str, Any]) -> List[str]:
    return [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants") or []]


def _is_turnover(t: str) -> bool:
    return "turnover" in t and not t.startswith("no turnover")


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


class _Tracker:
    """Replays plays in order; snapshot() returns the state after the last applied play."""

    def __init__(self, sides: Dict[str, Dict[str, Any]], box: Dict[str, Dict[str, Any]]):
        self.team_side = {sides["home"]["id"]: "home", sides["away"]["id"]: "away"}
        self.box = box
        self.score = {"home": 0.0, "away": 0.0}
        self.team = {s: Counter() for s in ("home", "away")}
        self.player: Dict[str, Counter] = defaultdict(Counter)
        self.team_fouls_period = {"home": 0, "away": 0}
        self.period = 1
        self.secs_left = PERIOD_SECONDS
        self.last_play_id: Optional[str] = None
        # on-floor: per side, a set; seeded from box starters, corrected per period (see _period_lineups)
        self.on_floor = {s: {a for a, b in box.items() if b["side"] == s and b["starter"]} for s in ("home", "away")}
        self.stint_start: Dict[str, float] = {a: 0.0 for s in self.on_floor.values() for a in s}
        self.minutes = Counter()

    def _side_of_player(self, aid: str) -> Optional[str]:
        b = self.box.get(aid)
        return b["side"] if b else None

    def set_period_lineup(self, period: int, lineups: Dict[str, set]) -> None:
        t0 = _elapsed(period, PERIOD_SECONDS if period <= REG_PERIODS else 300.0)
        for side in ("home", "away"):
            for a in list(self.on_floor[side]):
                self.minutes[a] += max(0.0, self.stint_start_close(a, t0))
            self.on_floor[side] = set(lineups.get(side) or self.on_floor[side])
            for a in self.on_floor[side]:
                self.stint_start[a] = t0

    def stint_start_close(self, aid: str, t: float) -> float:
        start = self.stint_start.pop(aid, None)
        return 0.0 if start is None else t - start

    def apply(self, p: Dict[str, Any]) -> None:
        per = _period(p)
        secs = bsr._clock_seconds(p.get("clock"))
        if per != self.period:
            self.team_fouls_period = {"home": 0, "away": 0}
            self.period = per
        if secs is not None:
            self.secs_left = secs
        t = _elapsed(per, self.secs_left)
        hs, as_ = bsr._num(p.get("homeScore")), bsr._num(p.get("awayScore"))
        if hs is not None and as_ is not None:
            self.score = {"home": hs, "away": as_}
        self.last_play_id = str(p.get("id") or "")
        typ = _play_type(p)
        txt = str(p.get("text") or "").lower()
        parts = _participants(p)
        side = self.team_side.get(str((p.get("team") or {}).get("id") or ""))
        actor = parts[0] if parts else None

        if typ == "substitution" and len(parts) >= 2:
            enters, leaves = parts[0], parts[1]
            s = self._side_of_player(enters) or self._side_of_player(leaves)
            if s:
                if leaves in self.on_floor[s]:
                    self.on_floor[s].discard(leaves)
                    self.minutes[leaves] += max(0.0, self.stint_start_close(leaves, t))
                self.on_floor[s].add(enters)
                self.stint_start[enters] = t
            return

        if bool(p.get("shootingPlay")) and side:
            is_ft = typ.startswith("free throw")
            made = bool(p.get("scoringPlay"))
            tc = self.team[side]
            if is_ft:
                tc["fta"] += 1
            else:
                tc["fga"] += 1
                if p.get("pointsAttempted") == 3:
                    tc["fg3a"] += 1
            if actor:
                if made:
                    self.player[actor]["pts"] += float(p.get("scoreValue") or 0)
                    if not is_ft and p.get("pointsAttempted") == 3:
                        self.player[actor]["fg3m"] += 1
                if made and not is_ft and len(parts) >= 2 and "assist" in txt:
                    self.player[parts[1]]["ast"] += 1
            return

        if typ in ("offensive rebound", "defensive rebound") and side:
            if typ == "offensive rebound":
                self.team[side]["oreb"] += 1
            if actor:
                self.player[actor]["reb"] += 1
            return

        if _is_turnover(typ) and side:
            self.team[side]["tov"] += 1
            return

        if typ in _PERSONAL_FOUL_TYPES and side:
            if actor:
                self.player[actor]["pf"] += 1
            if typ not in _OFFENSIVE_FOUL_TYPES:
                self.team_fouls_period[side] += 1

    def close_minutes(self, t_end: float) -> Counter:
        out = Counter(self.minutes)
        for side in ("home", "away"):
            for a in self.on_floor[side]:
                st = self.stint_start.get(a)
                if st is not None:
                    out[a] += max(0.0, t_end - st)
        return out

    def snapshot(self, period: int, secs_left: float) -> Dict[str, Any]:
        """State AT the checkpoint instant (period, secs_left), not at the last play's clock: the last
        play before 5:00 of Q4 can be at 5:12, and a quarter need not end on an End Period play."""
        teams = {}
        for s in ("home", "away"):
            c = self.team[s]
            teams[s] = {
                "pts": self.score[s], "fga": c["fga"], "fg3a": c["fg3a"], "fta": c["fta"],
                "oreb": c["oreb"], "tov": c["tov"],
                "poss_est": round(c["fga"] + 0.44 * c["fta"] + c["tov"] - c["oreb"], 2),
                "team_fouls_period": self.team_fouls_period[s],
                "on_floor": sorted(self.on_floor[s]),
            }
        players = {
            a: {k: float(v) for k, v in c.items()} for a, c in self.player.items() if any(c.values())
        }
        t = _elapsed(period, secs_left)
        mins = self.close_minutes(t)
        for a, m in mins.items():
            if m > 0:
                players.setdefault(a, {})["min"] = round(m / 60.0, 2)
        return {
            "period": period, "secs_left_period": secs_left,
            "secs_left_regulation": max(0.0, REG_PERIODS * PERIOD_SECONDS - t),
            "home_score": self.score["home"], "away_score": self.score["away"],
            "teams": teams, "players": players,
        }


def _period_lineups(plays: List[Dict[str, Any]], box: Dict[str, Dict[str, Any]]) -> Dict[int, Dict[str, set]]:
    """Five per side at the START of each period: players who act before (or without) entering,
    plus those who are subbed out before being subbed in. ESPN omits period-start lineups, so this
    is the standard inference; periods where it finds != 5 fall back to the carried-over five."""
    out: Dict[int, Dict[str, set]] = {}
    by_period: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for p in plays:
        by_period[_period(p)].append(p)
    for per, ps in by_period.items():
        entered: Dict[str, set] = {"home": set(), "away": set()}
        starters: Dict[str, set] = {"home": set(), "away": set()}
        for p in ps:
            typ = _play_type(p)
            parts = _participants(p)
            if typ == "substitution" and len(parts) >= 2:
                enters, leaves = parts[0], parts[1]
                for aid in (leaves,):
                    b = box.get(aid)
                    if b and aid not in entered[b["side"]]:
                        starters[b["side"]].add(aid)
                b = box.get(enters)
                if b:
                    entered[b["side"]].add(enters)
                continue
            if typ in ("jumpball",) or "timeout" in typ or "review" in typ or "challenge" in typ:
                continue
            for aid in parts[:2] if typ != "jumpball" else parts:
                b = box.get(aid)
                if b and aid not in entered[b["side"]]:
                    starters[b["side"]].add(aid)
        out[per] = {s: v for s, v in starters.items() if len(v) == 5}
    return out


def _next_possession(plays: List[Dict[str, Any]], start_idx: int, team_side: Dict[str, str]) -> Optional[str]:
    """Side of the first offensive action after the checkpoint (field-goal attempt, turnover, or an
    offensive foul). A derived field, labelled as such."""
    for p in plays[start_idx:]:
        typ = _play_type(p)
        side = team_side.get(str((p.get("team") or {}).get("id") or ""))
        if not side:
            continue
        if (bool(p.get("shootingPlay")) and not typ.startswith("free throw")) or _is_turnover(typ) \
                or typ in _OFFENSIVE_FOUL_TYPES:
            return side
    return None


def build_game(summary: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {"rows": [...], "recon": {...}}. rows is empty when reconciliation fails."""
    sides = _game_sides(summary)
    if not sides:
        return {"rows": [], "recon": {"ok": False, "reason": "no_home_away"}}
    team_side = {sides["home"]["id"]: "home", sides["away"]["id"]: "away"}
    box = _box_players(summary, team_side)
    # The feed's LIST order is chronological; `sequenceNumber` is not (sorting on it put the last
    # play mid-game on 27 of 218 games, measured 2026-10-09).
    plays = list(summary.get("plays") or [])
    if not plays:
        return {"rows": [], "recon": {"ok": False, "reason": "no_plays"}}
    lineups = _period_lineups(plays, box)
    tr = _Tracker(sides, box)
    wp_by_play = {str(w.get("playId")): w.get("homeWinPercentage") for w in summary.get("winprobability") or []}

    pending = list(CHECKPOINTS)
    snaps: Dict[str, Dict[str, Any]] = {}
    cur_period = 0
    for i, p in enumerate(plays):
        per = _period(p)
        secs = bsr._clock_seconds(p.get("clock"))
        # Close any checkpoint this play is strictly AFTER.
        while pending:
            label, cp_per, cp_secs = pending[0]
            after = per > cp_per or (per == cp_per and secs is not None and secs < cp_secs)
            if not after:
                break
            s = tr.snapshot(cp_per, cp_secs)
            s["next_possession"] = _next_possession(plays, i, team_side)
            s["espn_home_wp"] = wp_by_play.get(tr.last_play_id or "")
            snaps[label] = s
            pending.pop(0)
        if per != cur_period:
            if per in lineups:
                tr.set_period_lineup(per, lineups[per])
            cur_period = per
        tr.apply(p)

    h, a = sides["home"], sides["away"]
    reg_lines_ok = len(h["lines"]) >= REG_PERIODS and len(a["lines"]) >= REG_PERIODS
    final_home, final_away = h["score"], a["score"]
    reg_home = sum(h["lines"][:REG_PERIODS]) if reg_lines_ok else None
    reg_away = sum(a["lines"][:REG_PERIODS]) if reg_lines_ok else None

    # ---- reconciliation ------------------------------------------------------------------
    end_t = _elapsed(tr.period, tr.secs_left)
    pbp_min = tr.close_minutes(end_t)
    mism = Counter()
    min_close = min_n = 0
    for aid, b in box.items():
        if not b["played"]:
            continue
        pc = tr.player.get(aid, Counter())
        for k in ("pts", "reb", "ast", "pf"):
            if b[k] is not None and abs(float(pc.get(k, 0)) - b[k]) > 1e-6:
                mism[k] += 1
        if b["min"] is not None:
            min_n += 1
            if abs(pbp_min.get(aid, 0.0) / 60.0 - b["min"]) <= 1.0:
                min_close += 1
    score_ok = (tr.score["home"] == final_home and tr.score["away"] == final_away)
    # Game lines need the SCORE state; props need the per-player stats too. A game whose box and
    # pbp disagree by a stat correction stays in the game-line population, flagged for props.
    ok = score_ok and reg_lines_ok and len(snaps) == len(CHECKPOINTS)
    recon = {
        "ok": ok, "score_ok": score_ok, "props_ok": not mism, "stat_mismatches": dict(mism),
        "minutes_within_1": min_close, "minutes_n": min_n,
        "checkpoints_found": len(snaps), "lineup_periods_inferred": len(lineups),
    }
    if not ok:
        recon["reason"] = ("score" if not score_ok else
                           "linescores" if not reg_lines_ok else "checkpoints")
        return {"rows": [], "recon": recon}

    spread = total = None
    for pc in summary.get("pickcenter") or []:
        if spread is None and pc.get("spread") is not None:
            spread = bsr._num(pc.get("spread"))
        if total is None and pc.get("overUnder") is not None:
            total = bsr._num(pc.get("overUnder"))
    outcome = {
        "home": final_home, "away": final_away, "total": final_home + final_away,
        "margin": final_home - final_away, "home_win": final_home > final_away,
        "reg_home": reg_home, "reg_away": reg_away, "ot_periods": max(0, len(h["lines"]) - REG_PERIODS),
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


def load_anchors(anchor_dir: Optional[Path]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(date, home team display name) -> pregame anchors from production-schema
    `predictions_<date>.csv` files (the `wnba-lines-props-backtest` as-of re-run of today's pregame path,
    `.syndicate/findings_2026-10-02_wnba_lines_props_backtest.md`). Both the native re-sim and the
    linear lens must be given THESE anchors, so the comparison isolates the live mechanism."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if not anchor_dir:
        return out
    for f in sorted(Path(anchor_dir).glob("predictions_2026-*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                out[(str(r.get("date")), str(r.get("home_team")))] = {
                    "p_home_win": bsr._num(r.get("home_win_prob")),
                    "pred_margin": bsr._num(r.get("spread_margin")),
                    "pred_total": bsr._num(r.get("totals")),
                    "book_home_spread": bsr._num(r.get("home_spread")),
                    "book_total": bsr._num(r.get("total")),
                    "visitor_team": r.get("visitor_team"),
                    "file": f.name,
                }
    return out


def linear_lens(state: Dict[str, Any], anchors: Optional[Dict[str, Any]], market_total: Optional[float]) -> Dict[str, Any]:
    """The CURRENT native lens's prediction at this checkpoint, computed by the SHIPPED functions in
    `syndicate/features/wnba/cards.py` (imported, never re-implemented, so the baseline cannot drift
    from production). Same anchor precedence as the call site: pred_total, else the market total."""
    from syndicate.features.wnba import cards

    elapsed = 40.0 - float(state["secs_left_regulation"]) / 60.0
    margin = float(state["home_score"]) - float(state["away_score"])
    cur_total = float(state["home_score"]) + float(state["away_score"])
    p_pre = (anchors or {}).get("p_home_win")
    pre_total = (anchors or {}).get("pred_total")
    if pre_total is None:
        pre_total = (anchors or {}).get("book_total")
    if pre_total is None:
        pre_total = market_total
    return {
        "home_win_prob": cards._wnba_live_margin_win_prob(p_pre, margin, elapsed),
        "total_proj": cards._wnba_live_total_projection(pre_total, cur_total, elapsed) if elapsed else None,
        "anchor_total_used": pre_total,
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
    ap.add_argument("--anchors", default=None, help="dir of production-schema predictions_<date>.csv")
    args = ap.parse_args(argv)
    out = Path(args.out)
    cache = out / "cache" / LEAGUE
    rows: List[Dict[str, Any]] = []
    recon_fail = Counter()
    phase_games = Counter()
    excluded_types = Counter()
    min_close = min_n = games = props_bad = 0
    anchors = load_anchors(Path(args.anchors) if args.anchors else None)
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
        anc = anchors.get((ev["date"], str(res["rows"][0]["home_name"])))
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
        "anchor_files": len({a["file"] for a in anchors.values()}),
        "games_with_anchors": anchored_games,
        "games_with_anchors_by_phase": dict(Counter(r["phase"] for r in rows if r["checkpoint"] == "end_q1" and r.get("anchors"))),
        "rows_by_phase_checkpoint": dict(Counter(f"{r['phase']}/{r['checkpoint']}" for r in rows)),
        "minutes_within_1_rate": round(min_close / min_n, 4) if min_n else None,
        "minutes_n": min_n,
        "dates": [min((r["date"] for r in rows), default=None), max((r["date"] for r in rows), default=None)],
        "rows_with_pregame_total": sum(1 for r in rows if r["pregame"]["total"] is not None),
        "rows_with_espn_wp": sum(1 for r in rows if r["state"].get("espn_home_wp") is not None),
        "out": str(dest),
    }
    (out / "wnba_live_checkpoints_2026.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
