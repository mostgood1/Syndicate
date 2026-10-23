"""Basketball scenario calibration -- the REAL side (lane `basketball-scenario-calibration`, 2026-10-06).

Per completed game (ESPN scoreboard season type 2 = regular, 3 = post, 5 = play-in), from the ESPN summary:
possessions, period points, margin entering the last regulation period, late-period FTA/3PA, OT, starters' minutes,
foul-outs, pregame spread/total (ESPN pickcenter), rest days. One row per game written to <out>/real_<league>.jsonl;
summaries are cached gzipped under <out>/cache/<league>/ so a re-run fetches nothing.

The scenario table, splits and decision rule are pre-registered in
.syndicate/findings_2026-10-06_basketball_scenario_calibration.md -- this script only extracts; `table` aggregates.

Usage:
  python scripts/basketball_scenario_rates.py real --league nba --start 2025-11-01 --end 2026-02-28 --out C:/tmp/bball_sc
  python scripts/basketball_scenario_rates.py table --league nba --out C:/tmp/bball_sc
"""
from __future__ import annotations

import argparse
import gzip
import dataclasses
import json
import math
import random
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SPORT = {"nba": "nba", "wnba": "wnba", "ncaab": "mens-college-basketball"}
BASE = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/{sport}/{kind}"
REG_PERIODS = {"nba": 4, "wnba": 4, "ncaab": 2}
FOUL_LIMIT = {"nba": 6, "wnba": 6, "ncaab": 5}
BLOWOUT = {"nba": 18, "wnba": 15, "ncaab": 18}
LATE_SECONDS = {"nba": 120, "wnba": 120, "ncaab": 240}


def _get(url: str, tries: int = 3) -> Dict[str, Any]:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def _cached(path: Path, url: str) -> Dict[str, Any]:
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    doc = _get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return doc


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _pair(v: Any) -> tuple:
    a, _, b = str(v or "").partition("-")
    return _num(a), _num(b)


def _team_box(team_stats: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    by = {str(s.get("name")): s.get("displayValue") for s in team_stats or []}
    fgm, fga = _pair(by.get("fieldGoalsMade-fieldGoalsAttempted"))
    tpm, tpa = _pair(by.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
    ftm, fta = _pair(by.get("freeThrowsMade-freeThrowsAttempted"))
    tov = _num(by.get("totalTurnovers") if by.get("totalTurnovers") is not None else by.get("turnovers"))
    # Makes, rebounds, blocks, steals and assists (Phase 2 #1d: the targets of the ported WNBA engine fixes).
    return {"fga": fga, "fg3a": tpa, "fta": fta, "oreb": _num(by.get("offensiveRebounds")), "tov": tov,
            "fgm": fgm, "fg3m": tpm, "ftm": ftm, "dreb": _num(by.get("defensiveRebounds")),
            "reb": _num(by.get("totalRebounds")), "blk": _num(by.get("blocks")), "stl": _num(by.get("steals")),
            "ast": _num(by.get("assists"))}


def _clock_seconds(clock: Any) -> Optional[float]:
    text = str((clock or {}).get("displayValue") if isinstance(clock, dict) else clock or "")
    if not text:
        return None
    try:
        if ":" in text:
            m, s = text.split(":", 1)
            return int(m) * 60 + float(s)
        return float(text)
    except ValueError:
        return None


def game_row(summary: Dict[str, Any], league: str, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    teams = {}
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        lines = [_num(x.get("displayValue", x.get("value"))) for x in c.get("linescores") or []]
        teams[side] = {"id": str((c.get("team") or {}).get("id") or ""), "abbr": (c.get("team") or {}).get("abbreviation"),
                       "score": _num(c.get("score")), "lines": lines}
    if set(teams) != {"home", "away"} or teams["home"]["score"] is None:
        return None
    reg = REG_PERIODS[league]
    h, a = teams["home"], teams["away"]
    if len(h["lines"]) < reg or len(a["lines"]) < reg or any(v is None for v in h["lines"][:reg] + a["lines"][:reg]):
        return None
    box = {}
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        tid = str((t.get("team") or {}).get("id") or "")
        side = "home" if tid == h["id"] else ("away" if tid == a["id"] else None)
        if side:
            box[side] = _team_box(t.get("statistics") or [])
    poss = {}
    for side, b in box.items():
        if None not in (b["fga"], b["fta"], b["tov"], b["oreb"]):
            poss[side] = b["fga"] + 0.44 * b["fta"] + b["tov"] - b["oreb"]
    # late-period FTA / 3PA and the last-regulation-period FTA share, from plays
    plays = summary.get("plays") or []
    last_p = reg
    fta_last = defaultdict(int)
    fta_late = defaultdict(int)
    fg3a_last = defaultdict(int)
    for p in plays:
        per = int(((p.get("period") or {}).get("number")) or 0)
        tid = str((p.get("team") or {}).get("id") or "")
        side = "home" if tid == h["id"] else ("away" if tid == a["id"] else None)
        if side is None:
            continue
        txt = str((p.get("type") or {}).get("text") or "").lower() + " " + str(p.get("text") or "").lower()
        is_ft = "free throw" in txt
        is_3 = bool(p.get("shootingPlay")) and (p.get("pointsAttempted") == 3 or "three point" in txt) and not is_ft
        if per == last_p:
            if is_ft:
                fta_last[side] += 1
                secs = _clock_seconds(p.get("clock"))
                if secs is not None and secs <= LATE_SECONDS[league]:
                    fta_late[side] += 1
            if is_3:
                fg3a_last[side] += 1
    # starters' minutes and foul-outs, from players
    starters_min = {}
    foulouts = 0
    players_n = 0
    for t in (summary.get("boxscore") or {}).get("players") or []:
        tid = str((t.get("team") or {}).get("id") or "")
        side = "home" if tid == h["id"] else ("away" if tid == a["id"] else None)
        stats = (t.get("statistics") or [{}])[0]
        keys = stats.get("keys") or stats.get("names") or []
        ix = {k: i for i, k in enumerate(keys)}
        smins = []
        for ath in stats.get("athletes") or []:
            vals = ath.get("stats") or []
            if not vals or ath.get("didNotPlay"):
                continue
            players_n += 1
            mins = _num(vals[ix["minutes"]]) if "minutes" in ix and ix["minutes"] < len(vals) else None
            pf = _num(vals[ix["fouls"]]) if "fouls" in ix and ix["fouls"] < len(vals) else None
            if pf is not None and pf >= FOUL_LIMIT[league]:
                foulouts += 1
            if ath.get("starter") and mins is not None:
                smins.append(mins)
        if side:
            starters_min[side] = smins
    spread = total = None
    for pc in summary.get("pickcenter") or []:
        if spread is None and pc.get("spread") is not None:
            spread = _num(pc.get("spread"))            # home-relative (negative = home favoured)
        if total is None and pc.get("overUnder") is not None:
            total = _num(pc.get("overUnder"))
    hq, aq = h["lines"], a["lines"]
    margin_entering_last = sum(hq[:reg - 1]) - sum(aq[:reg - 1])
    return {
        "league": league, "event_id": event["id"], "date": event["date"], "season_type": event["season_type"],
        "home": h["abbr"], "away": a["abbr"], "home_pts": h["score"], "away_pts": a["score"],
        "total": h["score"] + a["score"], "margin": h["score"] - a["score"],
        "period_totals": [hq[i] + aq[i] for i in range(reg)], "period_home": hq[:reg], "period_away": aq[:reg],
        "ot_periods": max(0, len(hq) - reg), "tied_after_reg": sum(hq[:reg]) == sum(aq[:reg]),
        "margin_entering_last": margin_entering_last,
        "possessions": poss, "box": box,
        "fta_last_period": dict(fta_last), "fta_late": dict(fta_late), "fg3a_last_period": dict(fg3a_last),
        "starters_min": starters_min, "foulouts": foulouts, "players_played": players_n,
        "spread_home": spread, "total_line": total,
    }


def _events_for_date(league: str, d: str, out: Path) -> List[Dict[str, Any]]:
    ymd = d.replace("-", "")
    extra = "&groups=50&limit=400" if league == "ncaab" else ""
    sb = _cached(out / "cache" / league / f"scoreboard_{ymd}.json.gz",
                 BASE.format(sport=SPORT[league], kind="scoreboard") + f"?dates={ymd}{extra}")
    evs = []
    for e in sb.get("events") or []:
        st = ((e.get("status") or {}).get("type")) or {}
        stype = int(((e.get("season") or {}).get("type")) or 0)
        if (st.get("completed") or str(st.get("state")) == "post") and stype in (2, 3, 5):
            evs.append({"id": str(e.get("id")), "date": d, "season_type": stype})
    return evs


def run_real(args) -> int:
    out = Path(args.out)
    d0, d1 = date.fromisoformat(args.start), date.fromisoformat(args.end)
    rows, fails = [], 0
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"real_{args.league}.jsonl"
    seen = set()
    if dest.exists():
        for ln in dest.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                seen.add(json.loads(ln)["event_id"])
    with dest.open("a", encoding="utf-8") as fh:
        d = d0
        while d <= d1:
            try:
                evs = _events_for_date(args.league, d.isoformat(), out)
            except Exception as exc:  # noqa: BLE001
                print(f"SCOREBOARD_FAIL {d} {exc}", flush=True)
                evs = []
            if args.sample and len(evs) > args.sample:
                evs = random.Random(d.toordinal()).sample(evs, args.sample)
            for ev in evs:
                if ev["id"] in seen:
                    continue
                try:
                    s = _cached(out / "cache" / args.league / f"summary_{ev['id']}.json.gz",
                                BASE.format(sport=SPORT[args.league], kind="summary") + f"?event={ev['id']}")
                    row = game_row(s, args.league, ev)
                except Exception as exc:  # noqa: BLE001
                    fails += 1
                    print(f"SUMMARY_FAIL {ev['id']} {exc}", flush=True)
                    continue
                if row:
                    fh.write(json.dumps(row) + "\n")
                    seen.add(ev["id"])
                    rows.append(row)
            d += timedelta(days=1)
    print(f"REAL league={args.league} new_rows={len(rows)} total_rows={len(seen)} fails={fails}", flush=True)
    return 0



_LEVER_CLS_CACHE: Dict[Any, Any] = {}


def _lever_cfg(cfg: Any, levers: Dict[str, float]) -> Any:
    """Copy of `cfg` (a frozen dataclass) with `levers` applied, adding any field the class lacks."""
    if cfg is None:
        raise SystemExit("LEVER_FAIL draw has no cfg to apply levers to")
    base = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cfg)}
    extra = tuple(sorted(k for k in levers if k not in base))
    key = (type(cfg), extra)
    cls = _LEVER_CLS_CACHE.get(key)
    if cls is None:
        cls = dataclasses.make_dataclass(f"{type(cfg).__name__}Lever", [(k, float, 0.0) for k in extra],
                                         bases=(type(cfg),), frozen=True)
        _LEVER_CLS_CACHE[key] = cls
    return cls(**{**base, **levers})

def _compact_draw(h_box: Dict[str, Any], a_box: Dict[str, Any], hq: Any, aq: Any, foul_limit: int) -> Dict[str, Any]:
    def team(b: Dict[str, Any]) -> List[int]:
        return [int(b.get(k) or 0) for k in ("team_total_fga", "team_total_fta", "team_total_tov", "team_total_fg3a", "team_total_pf")]

    def team_x(b: Dict[str, Any]) -> List[int]:
        # Phase 2 #1d: makes, rebounds, blocks, steals, assists (kept in a separate key so old draw files still read).
        return [int(b.get(k) or 0) for k in ("team_total_fgm", "team_total_threes", "team_total_ftm", "team_total_reb",
                                             "team_total_blk", "team_total_stl", "team_total_ast")]

    fo = sum(1 for b in (h_box, a_box) for p in (b.get("players") or []) if int(p.get("pf") or 0) >= foul_limit)
    out = {"hq": [int(x or 0) for x in list(hq or [])[:4]], "aq": [int(x or 0) for x in list(aq or [])[:4]],
           "hot": int(sum(int(x or 0) for x in (h_box.get("ot_pts") or []) if x is not None)),
           "aot": int(sum(int(x or 0) for x in (a_box.get("ot_pts") or []) if x is not None)),
           "h": team(h_box), "a": team(a_box), "hx": team_x(h_box), "ax": team_x(a_box), "fo": fo}
    # Phase 2 #3c: top fouler PF per side, and the engine's foul-out diagnosis rows when cfg.diag_foul_outs is on.
    out["pfmax"] = [max([int(p.get("pf") or 0) for p in (b.get("players") or [])] or [0]) for b in (h_box, a_box)]
    # P3 fouler-weight check: [PF of the top 5 by expected minutes, team PF] per side (real top-5 share 0.585).
    out["pft5"] = [[sum(int(p.get("pf") or 0) for p in sorted(b.get("players") or [], key=lambda p: -float(p.get("min") or 0))[:5]),
                    sum(int(p.get("pf") or 0) for p in (b.get("players") or []))] for b in (h_box, a_box)]
    if h_box.get("fo_diag") is not None:
        out["fod"] = h_box.get("fo_diag")
    if h_box.get("fo_t5") is not None:
        # #3d: [on-floor possessions, Q4 possessions] after a starter's 5th PF in Q4 with >= 240 s left; Q4 starters on floor.
        out["fot5"] = h_box.get("fo_t5")
        out["foq4"] = h_box.get("fo_q4st")
    if h_box.get("fo_cnt") is not None:
        # #3j: per-side possessions, bonus FT trips and end-game intentional trips (engine counters, not the capped event list).
        out["foc"] = h_box.get("fo_cnt")
    ev = h_box.get("events")
    if isinstance(ev, list) and ev:
        # Phase 2 #3: FTA by quarter from the engine's diagnostic events (cfg.record_events). Index 4 = overtime.
        # And-one free throws are NOT logged as FTA events (engine ~:1682 adds the FTA, the FGM event carries no flag),
        # so each side's and-ones (box FTA minus event FTA) are spread over quarters in proportion to its made shots.
        fq = {"H": [0.0] * 5, "A": [0.0] * 5}
        fgm = {"H": [0] * 5, "A": [0] * 5}
        ft3 = {"H": 0, "A": 0}
        ft2s = {"H": 0, "A": 0}
        ftb = {"H": 0, "A": 0}
        for e_ in ev:
            side_ = e_.get("off")
            if side_ not in fq:
                continue
            qi = min(int(e_.get("q") or 1), 5) - 1
            if e_.get("type") == "FTA":
                fq[side_][qi] += int(e_.get("fta") or 0)
                if int(e_.get("fta") or 0) == 3 and not e_.get("bonus") and not e_.get("intentional"):
                    ft3[side_] += 1   # R2-c: three-shot trips (fouled threes)
                elif int(e_.get("fta") or 0) == 2 and not e_.get("bonus") and not e_.get("intentional"):
                    ft2s[side_] += 1  # R2-c': shooting two-shot trips
                elif e_.get("bonus"):
                    ftb[side_] += 1
            elif str(e_.get("type") or "").startswith("FGM"):
                fgm[side_][qi] += 1
        andone = {}
        for side_, box_ in (("H", h_box), ("A", a_box)):
            extra = int(box_.get("team_total_fta") or 0) - int(sum(fq[side_]))
            andone[side_] = extra
            tot_fgm = sum(fgm[side_])
            if extra > 0 and tot_fgm > 0:
                for qi in range(5):
                    fq[side_][qi] += extra * fgm[side_][qi] / tot_fgm
        out["fq"] = [[round(x, 3) for x in fq["H"]], [round(x, 3) for x in fq["A"]]]
        out["and1"] = [andone["H"], andone["A"]]
        out["ft3"] = [ft3["H"], ft3["A"]]
        out["ft2s"] = [ft2s["H"], ft2s["A"]]
        out["ftb"] = [ftb["H"], ftb["A"]]
    return out


def run_sim(args) -> int:
    """SIM side: production's engine re-run as of each FIT date (scratch copy; roster mode forced pregame), with the
    per-draw recorder wrapped IN THIS PROCESS ONLY to keep each draw's quarter scores, OT, team volume and foul-outs.
    No engine file is modified. Run in WSL from a code copy (see resim_nba_availability.py for the scratch layout)."""
    import os
    import shutil
    import sys

    code, pristine, asof = Path(args.code), Path(args.pristine), Path(args.asof)
    out = Path(args.out) / f"sim_{args.league}"
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(args.scratch) / f"sc_w{args.worker}"
    sys.path[:0] = [str(code / "scripts"), str(code)]  # vendored src entry removed (lane vendor-dead-paths-cleanup): vendor/ is empty
    import backtest_nba_lines_props as bt
    import resim_nba_availability as rs

    class BtArgs:
        out = Path(args.bt_out)

    env = {"SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_NBA_SOURCE_ROOT": str(scratch / "nba_source"),
           "NBA_BETTING_DATA_ROOT": str(scratch / "nba_source" / "data"), "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1"}
    for k in ("ODDS_API_KEY", "ODDSAPI_KEY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    bpss._resolve_smart_sim_roster_mode_local = lambda **_k: "pregame"
    # A comma makes a tuple lever (endgame_foul_p_by_deficit=0.2,0.0,0.2; foul_trouble_thresholds=2,3,4,5).
    def _lever_value(v: str) -> Any:
        if "," in v:
            return tuple(float(x) for x in v.split(","))
        try:
            return float(v)
        except ValueError:
            return v  # a string field (quarter_targets_mode=mean)

    levers = {k: _lever_value(v) for k, v in (x.split("=", 1) for x in (args.lever or []))}
    games: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    orig_call, orig_rec = bpss._call_source_simulate_smart_game_local, bpss._recording_sim_draws_local

    def call(**kw):
        k = kw.get("kwargs") or {}
        cur.update(game={"date": str(k.get("date_str")), "home": str(k.get("home_tri")), "away": str(k.get("away_tri"))},
                   draws=[], minutes=None)
        result = orig_call(**kw)
        games.append({**cur["game"], "draws": cur["draws"], "minutes": cur["minutes"]})
        return result

    def rec(simulate_draw, recorded_draws):
        inner = orig_rec(simulate_draw, recorded_draws)

        def wrapped(**kw):
            if levers:
                # Phase 2 lever sweep. The cfg reaching here is Syndicate's FROZEN EventSimConfigLocal, which does not
                # carry the new vendor fields at all -- the first sweep's `hasattr`/`setattr` silently skipped L1/L2
                # (they ran the baseline) and crashed L3 (frozen). Rebuild the cfg with the levers instead.
                kw["cfg"] = _lever_cfg(kw.get("cfg"), levers)
            if oc_track:
                _oc_reset()
            res = inner(**kw)
            try:
                h_box, a_box, hq, aq = res
                cur["draws"].append(_compact_draw(h_box, a_box, hq, aq, FOUL_LIMIT[args.league]))
                if oc_track:
                    cur["draws"][-1].update(_oc_finish())
                if cur.get("minutes") is None:   # minutes are INPUTS (constant across draws): keep them once
                    cur["minutes"] = {side: [[str(p.get("player_name") or ""), float(p.get("min") or 0.0)]
                                             for p in (b.get("players") or [])] for side, b in (("home", h_box), ("away", a_box))}
            except Exception:  # noqa: BLE001
                pass
            return res
        return wrapped

    bpss._call_source_simulate_smart_game_local = call
    bpss._recording_sim_draws_local = rec

    # Phase 2 #4: SIMULATED playing time. The engine reports INPUT minutes only, so count, per draw, how often the
    # top-5 (by input minutes) are on court. Lineups come from two producers: the per-possession sampler (blowout /
    # late-game windows; wrapped -> observed) and the lineup pool (a nested engine function; not wrappable). Pool
    # picks do not depend on the score (fixed weights per game), so a pool possession contributes the pool's EXPECTED
    # top-5 count, computed exactly from the pool lineups and weights the engine received. Possession boundaries and
    # the index->input-minutes map come from `_contextual_minutes_weights`, called home then away once per possession.
    oc_track = bool(getattr(args, "track_oncourt", False))
    oc: Dict[str, Any] = {}

    def _oc_reset() -> None:
        oc.update(ctx_i=0, mins=[None, None], top5=[None, None], epool=[None, None], has_pool=[False, False],
                  buf=[], t5sum=[0.0, 0.0], poss=[0, 0], unknown=0, started=False)

    def _top5(m):
        order = sorted(range(len(m)), key=lambda i: -float(m[i]))
        return set(order[:5])

    def _expected_pool_top5(lineups, weights, top5, n):
        tot, acc = 0.0, 0.0
        for j, lu in enumerate(lineups or []):
            idx = [int(x) for x in (lu or []) if 0 <= int(x) < n]
            if len(idx) != 5:
                continue
            w = float(weights[j]) if weights is not None and j < len(weights) else 1.0
            if w <= 0:
                continue
            tot += w
            acc += w * len(set(idx) & top5)
        return acc / tot if tot > 0 else None

    def _oc_close_possession() -> None:
        if not oc.get("started"):
            return
        buf = oc["buf"]
        if len(buf) == 2:
            sides = [0, 1]
        elif len(buf) == 1:
            no_pool = [s for s in (0, 1) if not oc["has_pool"][s]]
            sides = [no_pool[0] if len(no_pool) == 1 else 0]
        else:
            sides = []
        sampled = dict(zip(sides, buf))
        for s in (0, 1):
            if oc["top5"][s] is None:
                continue
            if s in sampled:
                oc["t5sum"][s] += len(set(sampled[s]) & oc["top5"][s])
                oc["poss"][s] += 1
            elif oc["epool"][s] is not None:
                oc["t5sum"][s] += oc["epool"][s]
                oc["poss"][s] += 1
            else:
                oc["unknown"] += 1
        oc["buf"] = []

    def _oc_finish() -> Dict[str, Any]:
        _oc_close_possession()
        t5m = [round(oc["t5sum"][s] / (5.0 * oc["poss"][s]) * 48.0, 3) if oc["poss"][s] else None for s in (0, 1)]
        t5in = [round(sum(float(oc["mins"][s][i]) for i in oc["top5"][s]) / 5.0, 3) if oc["top5"][s] else None for s in (0, 1)]
        return {"t5m": t5m, "t5in": t5in, "ocposs": list(oc["poss"]), "ocunk": oc["unknown"]}

    if oc_track:
        from syndicate.features.basketball_engine import engine as _neng

        _oc_reset()
        orig_ctx = _neng._contextual_minutes_weights

        def ctx_w(base_weights, *a, **k):
            side = oc["ctx_i"] % 2
            if side == 0:
                _oc_close_possession()
                oc["started"] = True
            if oc["mins"][side] is None:
                m = [float(x) for x in list(base_weights)]
                oc["mins"][side] = m
                oc["top5"][side] = _top5(m)
                key = "home" if side == 0 else "away"
                kwg = oc.get("kw") or {}
                lus, ws = kwg.get(f"{key}_lineups"), kwg.get(f"{key}_lineup_weights")
                oc["has_pool"][side] = bool(lus)
                oc["epool"][side] = _expected_pool_top5(lus, ws, oc["top5"][side], len(m)) if lus else None
            oc["ctx_i"] += 1
            return orig_ctx(base_weights, *a, **k)

        _neng._contextual_minutes_weights = ctx_w
        eng_oc = bpss._engine_for_league_local(args.league)
        orig_samp = eng_oc.sample_lineup

        def samp_w(rng, players, *a, **k):
            res = orig_samp(rng, players, *a, **k)
            oc["buf"].append(list(res or []))
            return res

        eng_oc.sample_lineup = samp_w
        orig_entry = bpss._call_native_engine_local

        def entry_w(*, entrypoint_name, league_code, kwargs):
            oc["kw"] = kwargs
            return orig_entry(entrypoint_name=entrypoint_name, league_code=league_code, kwargs=kwargs)

        bpss._call_native_engine_local = entry_w
        print("ONCOURT_TRACK on (sampler observed; pool picks at their exact expected top-5 count)", flush=True)

    # Phase 2 #1f: keep each game's sim JOB (the inputs of the pre-sim raw total: points-derived ratings, def, pace,
    # outs, b2b, rest) so the raw can be decomposed offline. The jobs run in-process (smart_sim_workers=1).
    job_rec: List[Dict[str, Any]] = []
    orig_job = bpss._smart_sim_worker_run_local
    JOB_KEYS = ("home_tri", "away_tri", "market_total", "home_spread", "home_pace", "away_pace", "matchup_pace",
                "home_def_rtg", "away_def_rtg", "home_off_rtg", "away_off_rtg", "off_rtg_from_points", "home_outs",
                "away_outs", "home_b2b", "away_b2b", "home_rest_days", "away_rest_days")

    def job_wrapped(job):
        job_rec.append({k: job.get(k) for k in JOB_KEYS})
        return orig_job(job)

    bpss._smart_sim_worker_run_local = job_wrapped

    lever_seen = {"calls": 0, "with_levers": 0}
    flags: Dict[str, Any] = {}
    if levers or args.engine_flag:
        # FAIL LOUDLY on a lever the vendor engine does not read: an unknown name would otherwise be a silent no-op.
        pkg = "wnba_betting" if args.league == "wnba" else "nba_betting"
        # The engine that RUNS: the native Syndicate engine once lane basketball-native-engine switched the runtime
        # off vendor/ (its LeagueEngine carries the switches under the vendored names; assigning one swaps the league
        # params); the vendored events module before that. Whichever runs is the one the levers must reach.
        native = hasattr(bpss, "_engine_for_league_local") and hasattr(bpss, "_call_native_engine_local")
        if native:
            real_events = bpss._engine_for_league_local(args.league)
            entry_name, pkg = "_call_native_engine_local", f"native basketball_engine ({args.league})"
        else:
            real_events = bpss._import_real_events_module_local(package_name=pkg)
            entry_name = "_call_real_events_entrypoint_local"
        if real_events is None:
            raise SystemExit(f"LEVER_FAIL {pkg} engine not importable -- levers would not reach an engine")
        print(f"ENGINE {pkg} via bpss.{entry_name}", flush=True)
        vendor_fields = {f.name for f in dataclasses.fields(real_events.EventSimConfig)}
        unknown = sorted(set(levers) - vendor_fields)
        if unknown:
            raise SystemExit(f"LEVER_FAIL {unknown} are not fields of {pkg} EventSimConfig")
        # Module-level engine switches (Phase 2 #1d: the ported WNBA fixes are module constants, not cfg fields).
        for name, raw in (x.split("=", 1) for x in (args.engine_flag or [])):
            if not hasattr(real_events, name):
                raise SystemExit(f"LEVER_FAIL engine flag {name} is not an attribute of {pkg}.sim.events")
            current = getattr(real_events, name)   # NOT `cur`: that is the per-game recorder dict above
            if isinstance(current, bool):
                if raw.strip().lower() not in ("1", "0", "true", "false"):
                    raise SystemExit(f"LEVER_FAIL engine flag {name}={raw!r}: expected a boolean")
                val: Any = raw.strip().lower() in ("1", "true")
            else:
                val = type(current)(raw)
            setattr(real_events, name, val)
            flags[name] = val
        print(f"ENGINE_FLAGS {flags}", flush=True)
        # Reachability at the ENGINE boundary: count real-engine calls whose cfg carries every lever value AND whose
        # engine module carries every switch value at call time.
        orig_real = getattr(bpss, entry_name)

        dumped: set = set()

        def _dump_priors(kwargs) -> None:
            # Phase 2 #5c: the per-player shooting priors exactly as they reach the engine, one row set per distinct lineup frame.
            cols = ("_sim_min", "_prior_fga_pm", "_prior_fgm_pm", "_prior_threes_pm", "_prior_threes_att_pm", "_prior_fta_pm", "_prior_ftm_pm",
                    "_prior_ast_pm")  # #5b: assists
            for side in ("home_players", "away_players"):
                df = kwargs.get(side)
                if df is None or not hasattr(df, "columns") or "player_name" not in df.columns:
                    continue
                key = tuple(sorted(str(x) for x in df["player_name"]))
                if key in dumped:
                    continue
                dumped.add(key)
                rows = [{c: (float(r[c]) if c in df.columns and r[c] == r[c] else None) for c in cols} | {"player_name": str(r["player_name"])}
                        for _, r in df.iterrows()]
                qs = []
                for qr in kwargs.get("quarters") or []:
                    get = qr.get if isinstance(qr, dict) else (lambda k, _q=qr: getattr(_q, k, None))
                    qs.append([get("home_pts_mu"), get("away_pts_mu")])
                with open(args.dump_priors, "a", encoding="utf-8") as fh:
                    # R2-a: the per-quarter targets exactly as they reach the engine, beside the priors.
                    # #5b: the game, so a side's priors can be joined to its team.
                    fh.write(json.dumps({"side": side, "rows": rows, "quarters": qs, "game": dict(cur.get("game") or {})},
                                        default=float) + "\n")

        def real_probe(*, entrypoint_name, league_code, kwargs):
            lever_seen["calls"] += 1
            if getattr(args, "dump_priors", None):
                _dump_priors(kwargs)
            c = kwargs.get("cfg")
            cfg_ok = not levers or (c is not None and all(getattr(c, k, None) == v for k, v in levers.items()))
            if cfg_ok and all(getattr(real_events, k) == v for k, v in flags.items()):
                lever_seen["with_levers"] += 1
            return orig_real(entrypoint_name=entrypoint_name, league_code=league_code, kwargs=kwargs)

        setattr(bpss, entry_name, real_probe)

    all_dates = rs._dates(f"{args.start}..{args.end}", asof)
    if args.dates_file:
        keep = {ln.strip() for ln in Path(args.dates_file).read_text(encoding="utf-8").splitlines() if ln.strip()}
        all_dates = [d for d in all_dates if d in keep]
    dates = [d for i, d in enumerate(all_dates) if i % args.workers == args.worker]
    for d in dates:
        dest = out / f"{d}.jsonl"
        if dest.exists():
            continue
        # REUSE an existing snapshot: parallel sweep processes each rewriting the same shared file raced and left
        # truncated snapshots (2026-10-07: two sweep points simulated 0 games on every date). Pre-generate once.
        existing = Path(args.bt_out) / "asof" / "props_odds_hist" / f"{d}.csv"
        props_csv = existing if existing.exists() and existing.stat().st_size > 1000 else bt.hist_props_csv(BtArgs, d)
        if props_csv is None:
            print(f"SIM_SKIP {d} no props snapshot", flush=True)
            continue
        rs.prepare_scratch(pristine, scratch, d, asof, props_csv)
        for extra in args.copy_file or []:     # production switch files absent from the pristine copy
            shutil.copy2(extra, scratch / "nba_source" / "data" / "processed" / Path(extra).name)
        games.clear()
        job_rec.clear()
        src_root = scratch / "nba_source"
        try:
            export_props_predictions_local(
                source_root=src_root, date_str=d, out_path=src_root / "data" / "processed" / f"props_predictions_{d}.csv",
                calib_window=7, calibrate_player=True, player_calib_window=30, player_min_pairs=6, player_shrink_k=8,
                use_smart_sim=True, smart_sim_n_sims=args.n_sims, smart_sim_pbp=True, smart_sim_workers=1,
                smart_sim_overwrite=True, log_file=Path(args.out) / f"sim_{args.league}_{d}.log")
        except Exception as exc:  # noqa: BLE001
            print(f"SIM_FAIL {d} {exc!r}"[:300], flush=True)
        if levers or flags:
            print(f"LEVER_REACH {d} engine_calls={lever_seen['calls']} with_levers={lever_seen['with_levers']}", flush=True)
            if lever_seen["calls"] == 0 and games:
                raise SystemExit(f"LEVER_FAIL {d} games recorded but 0 real-engine calls: the levers reached nothing")
            if lever_seen["calls"] and lever_seen["with_levers"] != lever_seen["calls"]:
                raise SystemExit(f"LEVER_FAIL {d} only {lever_seen['with_levers']}/{lever_seen['calls']} engine calls saw the levers")
        if not games:
            print(f"SIM_EMPTY {d} -- nothing simulated; no output written (a 0-game file would read as a result)", flush=True)
            continue
        with dest.open("w", encoding="utf-8") as fh:
            for g in games:
                fh.write(json.dumps(g) + "\n")
        print(f"SIM {d} games={len(games)} draws={sum(len(g['draws']) for g in games)}", flush=True)
        # Per-game engine summary (the market-anchored TARGET vs the sim mean): the scratch is rebuilt per date, so keep
        # it now. Needed to read whether the event sim lands on the target it was given (Phase 2 #1c).
        jobs_out = Path(args.out) / f"smart_sim_jobs_{args.league}" / f"{d}.jsonl"
        jobs_out.parent.mkdir(parents=True, exist_ok=True)
        with jobs_out.open("w", encoding="utf-8") as fh:
            for jr in job_rec:
                fh.write(json.dumps({"date": d, **jr}, default=str) + "\n")
        summ = Path(args.out) / f"smart_sim_summary_{args.league}" / f"{d}.jsonl"
        summ.parent.mkdir(parents=True, exist_ok=True)
        with summ.open("w", encoding="utf-8") as fh:
            for f in sorted((src_root / "data" / "processed").glob(f"smart_sim_{d}_*.json")):
                try:
                    j = json.loads(f.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                sc = j.get("score") or {}
                fh.write(json.dumps({"date": d, "home": j.get("home"), "away": j.get("away"),
                                     "market_anchor": j.get("market_anchor"),
                                     "score": {k: sc.get(k) for k in ("home_mean", "away_mean", "margin_mean", "total_mean")},
                                     "team_advanced_priors_applied": ((j.get("context") or {}).get("team_advanced_priors") or {}).get("applied"),
                                     # VALID read: the served per-player means (the prop quantities), for minutes / prop MAE.
                                     "players": {side: [[p.get("player_name"), p.get("min_mean"), p.get("pts_mean"), p.get("reb_mean"),
                                                         p.get("ast_mean"), p.get("threes_mean")]
                                                        for p in ((j.get("players") or {}).get(side) or [])]
                                                 for side in ("home", "away")}}) + "\n")
    return 0


ESPN_TO_TRI = {"nba": {"GS": "GSW", "NO": "NOP", "NY": "NYK", "UTAH": "UTA", "WSH": "WAS", "SA": "SAS", "PHO": "PHX"},
               "wnba": {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL"}}


def _tri(league: str, abbr: Any) -> str:
    v = str(abbr or "").upper()
    return ESPN_TO_TRI.get(league, {}).get(v, v)


def _boot_mean(groups: List[List[float]], reps: int = 1000, seed: int = 7) -> tuple:
    """Mean over all values, with a GAME-clustered bootstrap 95% CI (each inner list is one game)."""
    groups = [g for g in groups if g]
    if not groups:
        return (float("nan"),) * 3
    sums = [sum(g) for g in groups]
    cnts = [len(g) for g in groups]
    point = sum(sums) / sum(cnts)
    rng = random.Random(seed)
    n = len(groups)
    stats = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        c = sum(cnts[i] for i in idx)
        stats.append(sum(sums[i] for i in idx) / c if c else point)
    stats.sort()
    return point, stats[int(0.025 * reps)], stats[int(0.975 * reps) - 1]


def _sd(values: List[float]) -> float:
    if len(values) < 2:
        return float("nan")
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _boot_sd(groups: List[List[float]], reps: int = 500, seed: int = 11) -> tuple:
    groups = [g for g in groups if g]
    flat = [v for g in groups for v in g]
    point = _sd(flat)
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        pick = [groups[rng.randrange(len(groups))] for _ in range(len(groups))]
        stats.append(_sd([v for g in pick for v in g]))
    stats.sort()
    return point, stats[int(0.025 * reps)], stats[int(0.975 * reps) - 1]


def _lines(league: str, dates: List[str], bt_out: Path) -> Dict[tuple, Dict[str, float]]:
    """(date, home, away) -> {'spread': home line, 'total': line} from the OddsAPI pre-tip backfill (NBA)."""
    out: Dict[tuple, Dict[str, float]] = {}
    if league != "nba":
        return out
    import sys
    repo = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(repo / "scripts"), str(repo)]
    import backtest_nba_lines_props as bt

    class A:
        out = bt_out

    for d in sorted(set(dates)):
        for (h, a), rec in bt.hist_game_book(A, d).items():
            row = {}
            if "spread" in rec:
                row["spread"] = rec["spread"]["line"]
            if "total" in rec:
                row["total"] = rec["total"]["line"]
            out[(d, h, a)] = row
    return out


def run_table(args) -> int:
    """Phase 1 real-vs-sim rows (pre-registered in the findings file). Pairs games present on BOTH sides."""
    lg = args.league
    out = Path(args.out)
    reg = REG_PERIODS[lg]
    thr = BLOWOUT[lg]
    real = {}
    for ln in (out / f"real_{lg}.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(ln)
        if args.start <= r["date"] <= args.end and r["season_type"] == 2:
            real[(r["date"], _tri(lg, r["home"]), _tri(lg, r["away"]))] = r
    sim = {}
    for f in sorted((out / f"sim_{lg}").glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            g = json.loads(ln)
            if g.get("draws"):
                sim[(g["date"], g["home"], g["away"])] = g
    keys = sorted(set(real) & set(sim))
    lines = _lines(lg, [k[0] for k in keys], Path(args.bt_out))
    print(f"TABLE league={lg} real={len(real)} sim={len(sim)} paired={len(keys)} with_line={sum(1 for k in keys if k in lines)}")

    def spread_bucket(k):
        ln = lines.get(k, {}).get("spread")
        if ln is None:
            return None
        a = abs(ln)
        return "0-4" if a <= 4 else ("4.5-8" if a <= 8 else "8.5+")

    def state_bucket(m):
        a = abs(m)
        return "close<=8" if a <= 8 else (f"9-{thr - 1}" if a < thr else f">={thr}")

    rows: List[Dict[str, Any]] = []

    def add(sid, name, bucket, r_groups, s_groups, unit, sd=False, pts_per_unit=None):
        f = _boot_sd if sd else _boot_mean
        rp, rlo, rhi = f(r_groups)
        sp, slo, shi = f(s_groups)
        gap = sp - rp
        outside = not (rlo <= sp <= rhi) if not math.isnan(rlo) else None
        rows.append({"id": sid, "scenario": name, "bucket": bucket, "n_real_games": sum(1 for g in r_groups if g),
                     "real": round(rp, 4), "real_ci": [round(rlo, 4), round(rhi, 4)], "sim": round(sp, 4),
                     "sim_ci": [round(slo, 4), round(shi, 4)], "gap": round(gap, 4), "unit": unit,
                     "sim_outside_real_ci": outside,
                     "pts_effect": None if pts_per_unit is None else round(gap * pts_per_unit, 3)})

    # per-game helpers
    def real_q(r):
        return r["period_totals"]

    def sim_q(d):
        return [d["hq"][i] + d["aq"][i] for i in range(reg)]

    mean_total = sum(sum(real[k]["period_totals"]) for k in keys) / max(1, len(keys))
    # S1 pace proxy per team-game: FGA + 0.44 FTA + TOV
    r_g, s_g = [], []
    for k in keys:
        b = real[k]["box"]
        r_g.append([b[s]["fga"] + 0.44 * b[s]["fta"] + b[s]["tov"] for s in ("home", "away")
                    if b.get(s) and None not in (b[s]["fga"], b[s]["fta"], b[s]["tov"])])
        s_g.append([d[s][0] + 0.44 * d[s][1] + d[s][2] for d in sim[k]["draws"] for s in ("h", "a")])
    add("S1", "pace proxy FGA+0.44FTA+TOV per team-game", "overall", r_g, [[sum(g) / len(g)] for g in s_g], "plays",
        pts_per_unit=mean_total / 100)
    # S2 quarter shares, overall and by state entering the last period
    for qi in range(reg):
        r_g = [[real_q(real[k])[qi] / sum(real_q(real[k]))] for k in keys]
        s_g = [[sum(sim_q(d)[qi] / max(1, sum(sim_q(d))) for d in sim[k]["draws"]) / len(sim[k]["draws"])] for k in keys]
        add("S2", f"share of regulation total in P{qi + 1}", "overall", r_g, s_g, "share", pts_per_unit=mean_total)
        for st in ("close<=8", f"9-{thr - 1}", f">={thr}"):
            r_g = [[real_q(real[k])[qi] / sum(real_q(real[k]))] for k in keys if state_bucket(real[k]["margin_entering_last"]) == st]
            s_g = []
            for k in keys:
                v = [sim_q(d)[qi] / max(1, sum(sim_q(d))) for d in sim[k]["draws"]
                     if state_bucket(sum(d["hq"][:reg - 1]) - sum(d["aq"][:reg - 1])) == st]
                if v:
                    s_g.append([sum(v) / len(v)])
            add("S2", f"share of regulation total in P{qi + 1}", f"entering last: {st}", r_g, s_g, "share", pts_per_unit=mean_total)
    # S3 quarter-total SD (pooled; sim pooled over draws)
    for qi in range(reg):
        add("S3", f"SD of P{qi + 1} total", "overall", [[real_q(real[k])[qi]] for k in keys],
            [[sim_q(d)[qi] for d in sim[k]["draws"]] for k in keys], "pts", sd=True, pts_per_unit=1.0)
    # S4 first-half share
    half = reg // 2
    add("S4", "H1 share of regulation total", "overall",
        [[sum(real_q(real[k])[:half]) / sum(real_q(real[k]))] for k in keys],
        [[sum(sum(sim_q(d)[:half]) / max(1, sum(sim_q(d))) for d in sim[k]["draws"]) / len(sim[k]["draws"])] for k in keys],
        "share", pts_per_unit=mean_total)
    # S5 blowout incidence entering the last period, by |spread| bucket
    for sb in ("0-4", "4.5-8", "8.5+", None):
        ks = [k for k in keys if (sb is None or spread_bucket(k) == sb)]
        add("S5", f"P(|margin| >= {thr} entering last period)", f"|spread| {sb or 'all'}",
            [[1.0 if abs(real[k]["margin_entering_last"]) >= thr else 0.0] for k in ks],
            [[sum(1 for d in sim[k]["draws"] if abs(sum(d["hq"][:reg - 1]) - sum(d["aq"][:reg - 1])) >= thr) / len(sim[k]["draws"])] for k in ks],
            "prob")
    # S6 FTA per team-game
    add("S6", "FTA per team-game", "overall",
        [[real[k]["box"][s]["fta"] for s in ("home", "away") if real[k]["box"].get(s) and real[k]["box"][s]["fta"] is not None] for k in keys],
        [[sum(d[s][1] for d in sim[k]["draws"] for s in ("h", "a")) / (2 * len(sim[k]["draws"]))] for k in keys], "FTA",
        pts_per_unit=0.78)
    # S7 tied after regulation, by |spread| bucket
    for sb in ("0-4", "4.5-8", "8.5+", None):
        ks = [k for k in keys if (sb is None or spread_bucket(k) == sb)]
        add("S7", "P(tied after regulation)", f"|spread| {sb or 'all'}",
            [[1.0 if real[k]["tied_after_reg"] else 0.0] for k in ks],
            [[sum(1 for d in sim[k]["draws"] if sum(d["hq"]) == sum(d["aq"])) / len(sim[k]["draws"])] for k in ks], "prob")
    # S8 SD of final total and margin around the pregame line (games with a line)
    kl = [k for k in keys if "total" in lines.get(k, {})]
    add("S8", "SD of (final total - total line)", "overall", [[real[k]["total"] - lines[k]["total"]] for k in kl],
        [[sum(d["hq"]) + sum(d["aq"]) + d["hot"] + d["aot"] - lines[k]["total"] for d in sim[k]["draws"]] for k in kl],
        "pts", sd=True, pts_per_unit=1.0)
    ks = [k for k in keys if "spread" in lines.get(k, {})]
    add("S8", "SD of (final margin + home spread)", "overall", [[real[k]["margin"] + lines[k]["spread"]] for k in ks],
        [[sum(d["hq"]) + d["hot"] - sum(d["aq"]) - d["aot"] + lines[k]["spread"] for d in sim[k]["draws"]] for k in ks],
        "pts", sd=True, pts_per_unit=1.0)
    # S9 3PA per team-game
    add("S9", "3PA per team-game", "overall",
        [[real[k]["box"][s]["fg3a"] for s in ("home", "away") if real[k]["box"].get(s) and real[k]["box"][s]["fg3a"] is not None] for k in keys],
        [[sum(d[s][3] for d in sim[k]["draws"] for s in ("h", "a")) / (2 * len(sim[k]["draws"]))] for k in keys], "3PA")
    # S10 top-5 minutes by final |margin| bucket (sim minutes are INPUTS: constant across draws)
    for mb, lo, hi in (("<=6", 0, 6), ("7-19", 7, 19), (">=20", 20, 999)):
        r_g, s_g = [], []
        for k in keys:
            if lo <= abs(real[k]["margin"]) <= hi:
                r_g.append([sum(sorted(real[k]["starters_min"].get(s) or [], reverse=True)[:5]) / 5
                            for s in ("home", "away") if len(real[k]["starters_min"].get(s) or []) >= 5])
            share = sum(1 for d in sim[k]["draws"]
                        if lo <= abs(sum(d["hq"]) + d["hot"] - sum(d["aq"]) - d["aot"]) <= hi) / len(sim[k]["draws"])
            mins = sim[k].get("minutes") or {}
            top = [sum(sorted((m for _, m in mins.get(s) or []), reverse=True)[:5]) / 5 for s in ("home", "away") if mins.get(s)]
            if share > 0 and top:
                s_g.append(top)
        add("S10", "mean minutes of top-5 (real: ESPN starters; sim: top-5 input minutes)", f"final |margin| {mb}", r_g, s_g, "min")
    # S11 foul-outs per game
    add("S11", f"foul-outs (>= {FOUL_LIMIT[lg]} PF) per game", "overall", [[float(real[k]["foulouts"])] for k in keys],
        [[sum(d["fo"] for d in sim[k]["draws"]) / len(sim[k]["draws"])] for k in keys], "players")
    dest = out / f"table_{lg}_{args.start}_{args.end}.json"
    dest.write_text(json.dumps({"league": lg, "paired_games": len(keys), "rows": rows}, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['id']:4} {r['scenario'][:46]:46} {r['bucket'][:22]:22} n={r['n_real_games']:4} real={r['real']:.4g} "
              f"[{r['real_ci'][0]:.4g},{r['real_ci'][1]:.4g}] sim={r['sim']:.4g} gap={r['gap']:+.4g} "
              f"outside={r['sim_outside_real_ci']} pts={r['pts_effect']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=("real", "sim", "table"))
    ap.add_argument("--league", choices=tuple(SPORT), required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", type=int, default=0, help="at most N games per date (NCAAB: deterministic sample)")
    # sim phase (WSL)
    ap.add_argument("--code", default="")
    ap.add_argument("--pristine", default="")
    ap.add_argument("--scratch", default="")
    ap.add_argument("--asof", default="/mnt/c/tmp/nba_bt/out/asof")
    ap.add_argument("--bt-out", default=("C:/tmp/nba_bt/out" if __import__("os").name == "nt" else "/mnt/c/tmp/nba_bt/out"))
    ap.add_argument("--n-sims", type=int, default=200)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--copy-file", action="append", help="extra production switch file copied into each scratch")
    ap.add_argument("--lever", action="append", help="EventSimConfig field=value applied to every draw (Phase 2 sweeps)")
    ap.add_argument("--engine-flag", action="append", help="module-level engine switch NAME=VALUE on the real events module (Phase 2 #1d)")
    ap.add_argument("--track-oncourt", action="store_true", help="record per-draw simulated minutes of the top-5 (Phase 2 #4)")
    ap.add_argument("--dump-priors", help="append the per-player shooting priors reaching the engine to this JSONL (Phase 2 #5c)")
    ap.add_argument("--dates-file", default="", help="only these dates (one per line)")
    args = ap.parse_args(argv)
    if args.phase == "table":
        return run_table(args)
    return run_sim(args) if args.phase == "sim" else run_real(args)


if __name__ == "__main__":
    raise SystemExit(main())
