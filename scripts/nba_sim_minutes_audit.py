"""How the NBA SmartSim spends a side's 240 minutes, against the box score and the market (lane nba-sim-minutes-allocation).

For every date with BOTH production sims (``smart_sim_<D>_<H>_<A>.json``) and a final box
(``rotation_stints/player_checks_<D>.csv``, ``season_type=regular``), per side:

  * POOL: the sim's ``players[]`` (``min_mean``), joined to the box by (team, ``name_key``);
  * DNP SIM MASS: sim minutes held by pool players with no box row (did not play);
  * STARTER / BENCH BIAS: mean (sim - actual) minutes over pool players who played, split by the box ``starter`` flag
    (and, as the #714 reading did, by actual >= 28 min);
  * OUTSIDE-POOL MINUTES: box minutes of players who played and are not in the pool;
  * WHY each DNP pool player was in the pool -- ``injury_listed_unmatched`` (the sim's own ``context.excluded_players``
    names him only with extra tokens, e.g. "ISAIAH WAY STEWART", so the exclusion never matched), ``injury_listed``
    (the date's injury feed lists him OUT/DOUBTFUL now, under his own name), ``priced`` (a pre-tip prop line was
    posted, so the market expected him to play), else ``unlisted``;
  * MARKET: for pool players with a pre-tip points line (median over books of each book's latest pre-tip Over line),
    sim ``pts_mean`` - line and the line's MINUTES under the sim's own scoring rate
    (``min_mean * line / pts_mean``), each against the box.

Prints per-date coverage FIRST (sims, sides joined, box rows), then the per-side table and pooled numbers with 95%
cluster-bootstrap CIs over sides. ``--json`` writes every per-player row.

    python scripts/nba_sim_minutes_audit.py --processed /home/amyn/syndicate-prod/data/nba_source/data/processed \\
        --since 2026-10-20 [--raw <raw dir>] [--json out.json]

Read-only. A sim's build time is its file mtime; ``tip`` is ``smart_sim_tip_freeze.tip_time`` on the same files.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared.nba_current_rosters import name_key  # noqa: E402

EXCLUDING_STATUSES = {"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE", "REST"}
STARTER_MIN = 28.0


def sim_dates(processed: Path, since: Optional[str]) -> List[str]:
    out = set()
    for p in Path(processed).glob("smart_sim_*_*_*.json"):
        parts = p.stem.split("_")
        if len(parts) == 5 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2]):
            out.add(parts[2])
    return sorted(d for d in out if not since or d >= since)


def load_sims(processed: Path, date_str: str) -> Dict[str, Tuple[Dict[str, Any], float]]:
    """{"HOME_AWAY": (sim, mtime)}."""
    out = {}
    for p in sorted(Path(processed).glob(f"smart_sim_{date_str}_*.json")):
        if p.stem.count("_") == 4:
            out[p.stem[len("smart_sim_") + 11:]] = (json.loads(p.read_text(encoding="utf-8", errors="replace")),
                                                   p.stat().st_mtime)
    return out


def load_box(processed: Path, date_str: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{team: {name_key: {"min", "starter", "name"}}} for the date's regular-season box (players who played only)."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    path = Path(processed) / "rotation_stints" / f"player_checks_{date_str}.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("season_type") or "").lower() != "regular":
                continue
            try:
                m = float(r.get("box_minutes") or 0.0)
            except ValueError:
                continue
            team = str(r.get("team") or "").upper()
            out.setdefault(team, {})[name_key(r.get("player_name"))] = {
                "min": m, "starter": str(r.get("starter") or "").strip() in {"1", "True", "true"},
                "name": str(r.get("player_name") or ""),
            }
    return out


def pretip_prop_rows(processed: Path, raw: Optional[Path], date_str: str) -> Iterable[Dict[str, str]]:
    """Player-prop rows snapped BEFORE their game's commence_time. The raw history file keeps every snapshot of the
    day; the processed ``oddsapi_player_props_<D>.csv`` is overwritten by each pull (after tip it holds in-play rows
    only -- measured on 10-21), so it is the fallback, not the source."""
    hist = Path(raw) / f"odds_nba_player_props_history_{date_str}.csv" if raw else None
    path = hist if hist is not None and hist.is_file() else Path(processed) / f"oddsapi_player_props_{date_str}.csv"
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if not str(r.get("player_name") or "").strip():
                continue
            snap, commence = str(r.get("snapshot_ts") or ""), str(r.get("commence_time") or "")
            if commence and snap[:19] >= commence[:19]:
                continue
            yield r


def main_points_lines(rows: Iterable[Mapping[str, str]]) -> Dict[str, float]:
    """{name_key: median over books of each book's latest pre-tip Over points line}."""
    latest: Dict[Tuple[str, str], Tuple[str, float]] = {}
    for r in rows:
        if str(r.get("market") or "") != "player_points" or str(r.get("outcome_name") or "").lower() != "over":
            continue
        try:
            point = float(r.get("point"))
        except (TypeError, ValueError):
            continue
        snap = str(r.get("snapshot_ts") or "")
        slot = (name_key(r.get("player_name")), str(r.get("bookmaker") or ""))
        if slot not in latest or snap >= latest[slot][0]:
            latest[slot] = (snap, point)
    pooled: Dict[str, List[float]] = {}
    for (k, _b), (_s, point) in latest.items():
        pooled.setdefault(k, []).append(point)
    return {k: float(median(v)) for k, v in pooled.items()}


def injury_listed(raw: Optional[Path], date_str: str) -> Dict[str, set]:
    """{team: name_keys listed OUT/DOUBTFUL/... on the date in the injury feed AS IT IS NOW (the day's rows are
    replaced on every fetch, so this is the last report of the day, not the one the sim saw)."""
    out: Dict[str, set] = {}
    path = Path(raw) / "injuries.csv" if raw else None
    if path is None or not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("date") or "")[:10] != date_str:
                continue
            status = str(r.get("status") or "").upper().strip()
            if status in EXCLUDING_STATUSES or ("SEASON" in status and "OUT" in status):
                out.setdefault(str(r.get("team") or "").upper(), set()).add(name_key(r.get("player")))
    return out


def spliced_match(player_key: str, excluded: Iterable[str]) -> Optional[str]:
    """An excluded name that is the player's name with EXTRA tokens spliced in (same first and last token, every
    player token present in order) -- what the official-PDF parse produces ("isaiah way stewart")."""
    toks = player_key.split()
    if len(toks) < 2:
        return None
    for ex in excluded:
        et = name_key(ex).split()
        if len(et) <= len(toks) or et[0] != toks[0] or et[-1] != toks[-1]:
            continue
        it = iter(et)
        if all(t in it for t in toks):
            return ex
    return None


def tips_for(processed: Path, date_str: str):
    try:
        import pandas as pd

        from syndicate.features.shared import smart_sim_tip_freeze as tf
        from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local as to_tri
    except Exception:
        return lambda home, away: None
    rows: Dict[Tuple[str, str], Any] = {}
    odds = None
    try:
        pdf = pd.read_csv(Path(processed) / f"predictions_{date_str}.csv")
        for _, row in pdf.iterrows():
            rows[(to_tri(row.get("home_team")), to_tri(row.get("visitor_team")))] = row
    except Exception:
        pass
    try:
        odds = pd.read_csv(Path(processed) / f"game_odds_{date_str}.csv")
        odds["home_tri"] = odds.get("home_team", "").astype(str).map(to_tri)
        odds["away_tri"] = odds.get("visitor_team", "").astype(str).map(to_tri)
    except Exception:
        odds = None
    schedule = tf.schedule_tips(Path(processed), date_str)

    def _tip(home: str, away: str):
        try:
            return tf.tip_time(rows.get((home, away), {}), odds_df=odds, schedule=schedule, home=home, away=away)
        except Exception:
            return None

    return _tip


def audit_side(sim: Mapping[str, Any], side: str, team: str, box_team: Mapping[str, Mapping[str, Any]], *,
               lines: Mapping[str, float], priced: set, listed: set) -> Dict[str, Any]:
    pool = [r for r in ((sim.get("players") or {}).get(side) or []) if isinstance(r, dict)]
    excluded = ((sim.get("context") or {}).get("excluded_players") or {}).get(team) or []
    rows: List[Dict[str, Any]] = []
    seen = set()
    for r in pool:
        k = name_key(r.get("player_name"))
        seen.add(k)
        b = box_team.get(k)
        row = {"player": r.get("player_name"), "key": k, "sim_min": float(r.get("min_mean") or 0.0),
               "sim_pts": float(r.get("pts_mean") or 0.0), "played": b is not None,
               "actual_min": (b or {}).get("min"), "box_starter": bool((b or {}).get("starter")),
               "line_pts": lines.get(k), "priced": k in priced}
        if b is None:
            hit = spliced_match(k, excluded)
            row["dnp_cause"] = ("injury_listed_unmatched" if hit else "injury_listed" if k in listed
                                else "priced" if k in priced else "unlisted")
            if hit:
                row["excluded_as"] = hit
        if row["line_pts"] is not None and row["sim_pts"] > 0:
            row["line_min"] = row["sim_min"] * row["line_pts"] / row["sim_pts"]
        rows.append(row)
    outside = [{"player": v["name"], "key": k, "actual_min": v["min"], "box_starter": v["starter"],
                "priced": k in priced, "listed": k in listed}
               for k, v in box_team.items() if k not in seen]
    played = [r for r in rows if r["played"]]
    st = [r["sim_min"] - r["actual_min"] for r in played if r["box_starter"]]
    bn = [r["sim_min"] - r["actual_min"] for r in played if not r["box_starter"]]
    st28 = [r["sim_min"] - r["actual_min"] for r in played if r["actual_min"] >= STARTER_MIN]
    ot28 = [r["sim_min"] - r["actual_min"] for r in played if r["actual_min"] < STARTER_MIN]
    dnp = [r for r in rows if not r["played"]]
    by_cause: Dict[str, float] = {}
    for r in dnp:
        by_cause[r["dnp_cause"]] = by_cause.get(r["dnp_cause"], 0.0) + r["sim_min"]
    return {
        "team": team, "pool_n": len(rows), "played_n": len(played), "box_n": len(box_team),
        "dnp_n": len(dnp), "dnp_sim_min": sum(r["sim_min"] for r in dnp), "dnp_by_cause": by_cause,
        "starter_bias": mean(st) if st else None, "starter_n": len(st),
        "bench_bias": mean(bn) if bn else None, "bench_n": len(bn),
        "ge28_bias": mean(st28) if st28 else None, "lt28_bias": mean(ot28) if ot28 else None,
        "outside_min": sum(o["actual_min"] for o in outside), "outside_n": len(outside),
        "mae_played": mean(abs(r["sim_min"] - r["actual_min"]) for r in played) if played else None,
        "rows": rows, "outside": outside,
    }


def cluster_ci(values_by_side: Mapping[str, List[float]], *, n_boot: int = 10000, seed: int = 7) -> Tuple[float, float, float, int]:
    """(mean, lo, hi, n) of the pooled mean, 95% bootstrap over sides."""
    sides = [v for v in values_by_side.values() if v]
    flat = [x for v in sides for x in v]
    if not flat:
        return float("nan"), float("nan"), float("nan"), 0
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        pick = [x for _ in sides for x in rng.choice(sides)]
        boots.append(sum(pick) / len(pick))
    boots.sort()
    return sum(flat) / len(flat), boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], len(flat)


def run(processed: Path, raw: Optional[Path], dates: List[str]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"dates": {}, "sides": []}
    for d in dates:
        sims = load_sims(processed, d)
        box = load_box(processed, d)
        props = list(pretip_prop_rows(processed, raw, d))
        lines, listed = main_points_lines(props), injury_listed(raw, d)
        priced = {name_key(r.get("player_name")) for r in props}
        tip = tips_for(processed, d)
        cov = {"sims": len(sims), "box_teams": len(box), "box_rows": sum(len(v) for v in box.values()),
               "sides_joined": 0, "sides_no_box": [], "built_after_tip": [], "pretip_prop_rows": len(props),
               "players_with_points_line": len(lines)}
        for game, (sim, mtime) in sims.items():
            home, away = game.split("_", 1)
            t = tip(home, away)
            built = datetime.fromtimestamp(mtime, tz=timezone.utc)
            if t is not None and built >= t:
                cov["built_after_tip"].append(game)
            for side, team in (("home", home), ("away", away)):
                if team not in box:
                    cov["sides_no_box"].append(team)
                    continue
                cov["sides_joined"] += 1
                s = audit_side(sim, side, team, box[team], lines=lines, priced=priced, listed=listed.get(team, set()))
                s.update({"date": d, "game": game, "built_utc": built.isoformat(timespec="seconds"),
                          "tip_utc": t.isoformat(timespec="seconds") if t else None,
                          "built_after_tip": bool(t is not None and built >= t),
                          "rotation_history_applied": bool((((sim.get("rotation_minutes") or {}).get(side)) or {}).get("applied"))})
                report["sides"].append(s)
        report["dates"][d] = cov
    return report


# --- replay: the minutes layer OFF vs priced-first ON on production's frozen engine inputs ----------------------------
#
# The minutes layer is deterministic, and `engine_inputs/<D>/<H>_<A>.pkl` holds each side's pool frame exactly as the
# engine received it (written pre-tip; the tip freeze keeps it). So both arms are recomputed by the PRODUCTION function
# `_derive_sim_minutes_local` on that frame: OFF must reproduce the frame's own `_sim_min` (a side that does not is
# reported and dropped -- the replay is not the code that ran), ON is the same call with the switch on and the priced
# set rebuilt from the props snapshots taken no later than the pkl was written.


def _event_teams(rows: Iterable[Mapping[str, str]], to_tri) -> Dict[str, Tuple[str, str]]:
    """{event_id: (home_tri, away_tri)} from rows carrying home_team/away_team."""
    out: Dict[str, Tuple[str, str]] = {}
    for r in rows:
        eid, h, a = str(r.get("event_id") or ""), str(r.get("home_team") or ""), str(r.get("away_team") or "")
        if eid and h and a and eid not in out:
            out[eid] = (to_tri(h), to_tri(a))
    return out


def priced_by_game_asof(processed: Path, raw: Path, date_str: str, to_tri) -> List[Tuple[str, str, str, str]]:
    """[(snapshot_ts, home_tri, away_tri, player_name)] for every pre-tip player-prop row of the date (history file;
    event teams from the processed/raw snapshots that carry home_team/away_team)."""
    teams: Dict[str, Tuple[str, str]] = {}
    for p in (Path(raw) / f"odds_nba_player_props_{date_str}.csv", Path(processed) / f"oddsapi_player_props_{date_str}.csv",
              Path(raw) / f"odds_nba_player_props_opening_{date_str}.csv"):
        if p.is_file():
            with p.open(encoding="utf-8", errors="replace", newline="") as fh:
                for eid, ha in _event_teams(csv.DictReader(fh), to_tri).items():
                    teams.setdefault(eid, ha)
    out = []
    for r in pretip_prop_rows(processed, raw, date_str):
        ha = teams.get(str(r.get("event_id") or ""))
        if ha:
            out.append((str(r.get("snapshot_ts") or ""), ha[0], ha[1], str(r.get("player_name") or "")))
    return out


def replay(processed: Path, raw: Path, dates: List[str]) -> Dict[str, Any]:
    import os
    import pickle

    import numpy as np

    from syndicate.features.shared import basketball_props_smart_sim as b

    flag = b.NBA_SIM_MINUTES_PRICED_FIRST_FLAG
    prev_flag, prev_state = os.environ.get(flag), b._SMARTSIM_WORKER_STATE
    view = b._build_local_smart_sim_module(processed_root=Path(processed), league_code="nba")
    out: Dict[str, Any] = {"sides": [], "dropped": []}
    try:
        for d in dates:
            box = load_box(processed, d)
            priced_rows = priced_by_game_asof(processed, raw, d, b._to_tricode_local)
            sims = load_sims(processed, d)
            for pkl in sorted((Path(processed) / "engine_inputs" / d).glob("*.pkl")):
                rec = pickle.loads(pkl.read_bytes())
                home, away = str(rec.get("home") or "").upper(), str(rec.get("away") or "").upper()
                written = str(rec.get("written_at") or "")
                asof = {}
                for snap, h, a, name in priced_rows:
                    if (h, a) == (home, away) and snap[:19] <= written[:19]:
                        asof.setdefault((h, a), set()).add(name)
                b._MARKET_PLAYER_NAMES_CACHE_LOCAL[(str(Path(processed)), d)] = asof
                b._SMARTSIM_WORKER_STATE = {"date_str": d}
                sim = (sims.get(f"{home}_{away}") or ({}, 0.0))[0]
                for side, team, key in (("home", home, "home_players"), ("away", away, "away_players")):
                    frame = rec["kwargs"][key]
                    applied = bool((((sim.get("rotation_minutes") or {}).get(side)) or {}).get("applied"))
                    asof_date = str(frame["asof_date"].iloc[0])[:10] if "asof_date" in frame.columns else d
                    arms = {}
                    for mode in ("off", "on"):
                        os.environ[flag] = mode
                        arms[mode] = b._derive_sim_minutes_local(smart_sim_module=view, team_df=frame, date_str=asof_date,
                                                                 team_tri=team, league_code="nba").to_numpy(dtype=float)
                    prod = frame["_sim_min"].to_numpy(dtype=float)
                    max_dev = float(np.max(np.abs(arms["off"] - prod))) if len(prod) else 0.0
                    keys = frame["player_name"].map(name_key).tolist()
                    priced = {name_key(n) for n in asof.get((home, away), set())}
                    s = {"date": d, "game": f"{home}_{away}", "team": team, "written_at": written,
                         "rotation_history_applied": applied, "off_reproduces_production_max_dev": max_dev,
                         "priced_n": sum(k in priced for k in keys),
                         "engaged": bool(np.max(np.abs(arms["on"] - arms["off"])) > 1e-9) if len(prod) else False,
                         "rows": []}
                    for i, k in enumerate(keys):
                        bx = (box.get(team) or {}).get(k)
                        s["rows"].append({"player": str(frame["player_name"].iloc[i]), "key": k, "priced": k in priced,
                                          "prod": float(prod[i]), "off": float(arms["off"][i]), "on": float(arms["on"][i]),
                                          "played": bx is not None, "actual_min": (bx or {}).get("min"),
                                          "box_starter": bool((bx or {}).get("starter"))})
                    if applied or max_dev > 0.05:
                        out["dropped"].append({k2: s[k2] for k2 in ("date", "team", "rotation_history_applied",
                                                                    "off_reproduces_production_max_dev")})
                    else:
                        out["sides"].append(s)
    finally:
        if prev_flag is None:
            os.environ.pop(flag, None)
        else:
            os.environ[flag] = prev_flag
        b._SMARTSIM_WORKER_STATE = prev_state
    return out


def replay_rule(sides: List[Mapping[str, Any]], *, min_rows: int = 0) -> Dict[str, Any]:
    """The pre-registered PRIMARY: |ON - actual| - |OFF - actual| over pool players who played, on ENGAGED sides,
    cluster bootstrap over sides. PASS: CI upper < 0; FAIL: CI lower > 0; else INCONCLUSIVE (and INCONCLUSIVE
    below `min_rows`). Splits are reported, not gating."""
    eng = [s for s in sides if s["engaged"]]
    key = lambda s: f"{s['date']}:{s['team']}"  # noqa: E731

    def paired(pred):
        return {key(s): [abs(r["on"] - r["actual_min"]) - abs(r["off"] - r["actual_min"]) for r in s["rows"]
                         if r["played"] and pred(r)] for s in eng}

    def bias(arm, pred):
        return {key(s): [r[arm] - r["actual_min"] for r in s["rows"] if r["played"] and pred(r)] for s in eng}

    prim = cluster_ci(paired(lambda r: True))
    m, lo, hi, n = prim
    verdict = "INCONCLUSIVE" if n < min_rows else ("PASS" if hi < 0 else "FAIL" if lo > 0 else "INCONCLUSIVE")
    dnp_off = sum(r["off"] for s in eng for r in s["rows"] if not r["played"])
    dnp_on = sum(r["on"] for s in eng for r in s["rows"] if not r["played"])
    return {
        "sides": len(sides), "engaged_sides": len(eng), "primary": prim, "verdict": verdict, "min_rows": min_rows,
        "priced_played": cluster_ci(paired(lambda r: r["priced"])),
        "unpriced_played": cluster_ci(paired(lambda r: not r["priced"])),
        "starters": cluster_ci(paired(lambda r: r["box_starter"])),
        "bias_off_starters": cluster_ci(bias("off", lambda r: r["box_starter"])),
        "bias_on_starters": cluster_ci(bias("on", lambda r: r["box_starter"])),
        "bias_off_bench": cluster_ci(bias("off", lambda r: not r["box_starter"])),
        "bias_on_bench": cluster_ci(bias("on", lambda r: not r["box_starter"])),
        "mae_off": cluster_ci({key(s): [abs(r["off"] - r["actual_min"]) for r in s["rows"] if r["played"]] for s in eng}),
        "mae_on": cluster_ci({key(s): [abs(r["on"] - r["actual_min"]) for r in s["rows"] if r["played"]] for s in eng}),
        "dnp_sim_min_per_side_off": dnp_off / max(1, len(eng)), "dnp_sim_min_per_side_on": dnp_on / max(1, len(eng)),
    }


def print_replay(rep: Mapping[str, Any], rule: Mapping[str, Any]) -> None:
    print("REPLAY (production engine_inputs; OFF must reproduce production _sim_min within 0.05 min)")
    for x in rep["dropped"]:
        print(f"  dropped {x['date']} {x['team']}: rotation_history_applied={x['rotation_history_applied']} "
              f"off_vs_production_max_dev={x['off_reproduces_production_max_dev']:.3f}")
    for s in rep["sides"]:
        pl = [r for r in s["rows"] if r["played"]]
        d = [abs(r["on"] - r["actual_min"]) - abs(r["off"] - r["actual_min"]) for r in pl]
        print(f"  {s['date']} {s['team']:4} priced={s['priced_n']:2} engaged={int(s['engaged'])} "
              f"off_dev={s['off_reproduces_production_max_dev']:.3f} played={len(pl):2} "
              f"paired={mean(d) if d else float('nan'):+.2f} "
              f"DNP sim off/on={sum(r['off'] for r in s['rows'] if not r['played']):5.1f}/"
              f"{sum(r['on'] for r in s['rows'] if not r['played']):5.1f}")
    m, lo, hi, n = rule["primary"]
    print(f"PRIMARY paired |on-actual|-|off-actual| (played, engaged sides): {m:+.3f} [{lo:+.3f}, {hi:+.3f}] n={n} "
          f"over {rule['engaged_sides']} of {rule['sides']} sides -> {rule['verdict']} (min rows {rule['min_rows']})")
    for name in ("priced_played", "unpriced_played", "starters", "bias_off_starters", "bias_on_starters",
                 "bias_off_bench", "bias_on_bench", "mae_off", "mae_on"):
        m, lo, hi, n = rule[name]
        print(f"  {name:18} {m:+.3f} [{lo:+.3f}, {hi:+.3f}] n={n}")
    print(f"  DNP sim min per engaged side: off {rule['dnp_sim_min_per_side_off']:.1f} -> on {rule['dnp_sim_min_per_side_on']:.1f}")


# --- arms: two scratch worker runs (switch off / on) on the same frozen inputs -------------------------------------


def truth_points(processed: Path, date_str: str) -> Dict[str, float]:
    """{name_key: points} from player_logs.csv rows of the date (keyed by name, as the #714 reading joined them)."""
    out: Dict[str, float] = {}
    path = Path(processed) / "player_logs.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("GAME_DATE") or "")[:10] == date_str:
                try:
                    out[name_key(r.get("PLAYER_NAME"))] = float(r.get("PTS") or 0.0)
                except ValueError:
                    pass
    return out


def _iqr_sd(z: List[float]) -> float:
    if len(z) < 4:
        return float("nan")
    s = sorted(z)
    q = lambda p: s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]  # noqa: E731
    return (q(0.75) - q(0.25)) / 1.349


def arms(off_processed: Path, on_processed: Path, truth_processed: Path, raw: Path, date_str: str) -> Dict[str, Any]:
    """The pre-registered SECONDARY: served pts_mean, OFF vs ON, against player_logs points, over pool players who
    played on ENGAGED sides (a side where any player's ON min_mean differs from OFF). Also the minutes, the points
    line and the served width (IQR(z)/1.349, z = (actual - pts_mean) / pts_sd, played priced players)."""
    box, pts = load_box(truth_processed, date_str), truth_points(truth_processed, date_str)
    props = list(pretip_prop_rows(truth_processed, raw, date_str))
    lines, priced = main_points_lines(props), {name_key(r.get("player_name")) for r in props}
    off_sims, on_sims = load_sims(off_processed, date_str), load_sims(on_processed, date_str)
    rows: List[Dict[str, Any]] = []
    for game, (on_sim, _m) in on_sims.items():
        off_sim = (off_sims.get(game) or (None, 0))[0]
        if off_sim is None:
            continue
        home, away = game.split("_", 1)
        for side, team in (("home", home), ("away", away)):
            on_p = {name_key(r.get("player_name")): r for r in (on_sim.get("players") or {}).get(side) or []}
            off_p = {name_key(r.get("player_name")): r for r in (off_sim.get("players") or {}).get(side) or []}
            engaged = any(abs(float(on_p[k].get("min_mean") or 0) - float(off_p[k].get("min_mean") or 0)) > 1e-6
                          for k in on_p if k in off_p)
            for k in sorted(set(on_p) & set(off_p)):
                bx = (box.get(team) or {}).get(k)
                rows.append({"side": f"{date_str}:{team}", "key": k, "engaged": engaged, "played": bx is not None,
                             "box_starter": bool((bx or {}).get("starter")), "priced": k in priced,
                             "actual_min": (bx or {}).get("min"), "actual_pts": pts.get(k) if bx is not None else None,
                             "line_pts": lines.get(k),
                             **{f"{arm}_{f}": float(p[k].get(f) or 0.0) for arm, p in (("off", off_p), ("on", on_p))
                                for f in ("min_mean", "pts_mean", "pts_sd")}})
    use = [r for r in rows if r["engaged"] and r["played"] and r["actual_pts"] is not None]

    def by_side(f, pred=lambda r: True):
        out: Dict[str, List[float]] = {}
        for r in use:
            if pred(r):
                out.setdefault(r["side"], []).append(f(r))
        return out

    res = {
        "rows": len(rows), "engaged_sides": len({r["side"] for r in rows if r["engaged"]}), "sides": len({r["side"] for r in rows}),
        "points_paired": cluster_ci(by_side(lambda r: abs(r["on_pts_mean"] - r["actual_pts"]) - abs(r["off_pts_mean"] - r["actual_pts"]))),
        "points_paired_priced": cluster_ci(by_side(lambda r: abs(r["on_pts_mean"] - r["actual_pts"]) - abs(r["off_pts_mean"] - r["actual_pts"]), lambda r: r["priced"])),
        "minutes_paired": cluster_ci(by_side(lambda r: abs(r["on_min_mean"] - r["actual_min"]) - abs(r["off_min_mean"] - r["actual_min"]))),
        "pts_bias_off_starters": cluster_ci(by_side(lambda r: r["off_pts_mean"] - r["actual_pts"], lambda r: r["box_starter"])),
        "pts_bias_on_starters": cluster_ci(by_side(lambda r: r["on_pts_mean"] - r["actual_pts"], lambda r: r["box_starter"])),
        "line_gap_off_starters": cluster_ci(by_side(lambda r: r["off_pts_mean"] - r["line_pts"], lambda r: r["box_starter"] and r["line_pts"] is not None)),
        "line_gap_on_starters": cluster_ci(by_side(lambda r: r["on_pts_mean"] - r["line_pts"], lambda r: r["box_starter"] and r["line_pts"] is not None)),
        "line_gap_off_bench": cluster_ci(by_side(lambda r: r["off_pts_mean"] - r["line_pts"], lambda r: not r["box_starter"] and r["line_pts"] is not None)),
        "line_gap_on_bench": cluster_ci(by_side(lambda r: r["on_pts_mean"] - r["line_pts"], lambda r: not r["box_starter"] and r["line_pts"] is not None)),
        "width_off": _iqr_sd([(r["actual_pts"] - r["off_pts_mean"]) / r["off_pts_sd"] for r in use if r["priced"] and r["off_pts_sd"] > 0]),
        "width_on": _iqr_sd([(r["actual_pts"] - r["on_pts_mean"]) / r["on_pts_sd"] for r in use if r["priced"] and r["on_pts_sd"] > 0]),
        "width_n": sum(1 for r in use if r["priced"]),
    }
    m, lo, hi, n = res["points_paired"]
    res["secondary_verdict"] = "FAIL" if lo > 0 else "NOT FAIL"
    res["detail"] = rows
    return res


def print_arms(res: Mapping[str, Any]) -> None:
    print(f"ARMS: {res['engaged_sides']} of {res['sides']} sides engaged; {res['rows']} player rows")
    for name in ("points_paired", "points_paired_priced", "minutes_paired", "pts_bias_off_starters", "pts_bias_on_starters",
                 "line_gap_off_starters", "line_gap_on_starters", "line_gap_off_bench", "line_gap_on_bench"):
        m, lo, hi, n = res[name]
        print(f"  {name:22} {m:+.3f} [{lo:+.3f}, {hi:+.3f}] n={n}")
    print(f"  SECONDARY (points, must not FAIL): {res['secondary_verdict']}")
    print(f"  served pts width IQR(z)/1.349, played priced (n={res['width_n']}): off {res['width_off']:.3f} on {res['width_on']:.3f}")


def _fmt(x: Optional[float], nd: int = 1) -> str:
    return "  -  " if x is None else f"{x:+.{nd}f}" if nd == 1 else f"{x:.{nd}f}"


def summarize(report: Mapping[str, Any], *, pretip_only: bool = False) -> Dict[str, Any]:
    sides = [s for s in report["sides"] if not (pretip_only and s["built_after_tip"])]
    key = lambda s: f"{s['date']}:{s['team']}"  # noqa: E731
    starter = {key(s): [r["sim_min"] - r["actual_min"] for r in s["rows"] if r["played"] and r["box_starter"]] for s in sides}
    bench = {key(s): [r["sim_min"] - r["actual_min"] for r in s["rows"] if r["played"] and not r["box_starter"]] for s in sides}
    ge28 = {key(s): [r["sim_min"] - r["actual_min"] for r in s["rows"] if r["played"] and r["actual_min"] >= STARTER_MIN] for s in sides}
    absd = {key(s): [abs(r["sim_min"] - r["actual_min"]) for r in s["rows"] if r["played"]] for s in sides}
    dnp = {key(s): [s["dnp_sim_min"]] for s in sides}
    outside = {key(s): [s["outside_min"]] for s in sides}
    causes: Dict[str, float] = {}
    for s in sides:
        for c, v in s["dnp_by_cause"].items():
            causes[c] = causes.get(c, 0.0) + v
    outside_split = {"priced": 0.0, "unpriced": 0.0}
    for s in sides:
        for o in s["outside"]:
            outside_split["priced" if o["priced"] else "unpriced"] += o["actual_min"]
    # Market: the points line's minutes under the sim's own rate, vs the box, for pool players who played.
    mk_rows = [(key(s), r) for s in sides for r in s["rows"] if r["played"] and r.get("line_min") is not None]
    mk_sim = {}
    mk_line = {}
    mk_pts = {}
    for k, r in mk_rows:
        grp = "starter" if r["box_starter"] else "bench"
        mk_sim.setdefault(grp, {}).setdefault(k, []).append(r["sim_min"] - r["actual_min"])
        mk_line.setdefault(grp, {}).setdefault(k, []).append(r["line_min"] - r["actual_min"])
        mk_pts.setdefault(grp, {}).setdefault(k, []).append(r["sim_pts"] - r["line_pts"])
    dnp_priced = [(r["sim_pts"] - r["line_pts"]) for s in sides for r in s["rows"] if not r["played"] and r.get("line_pts") is not None]
    return {
        "sides": len(sides), "dates": sorted({s["date"] for s in sides}),
        "dnp_sim_min_per_side": cluster_ci(dnp), "dnp_by_cause_total": causes,
        "outside_min_per_side": cluster_ci(outside), "outside_min_by_priced": outside_split,
        "starter_bias": cluster_ci(starter), "bench_bias": cluster_ci(bench), "ge28_bias": cluster_ci(ge28),
        "mae_played": cluster_ci(absd),
        "market": {grp: {"sim_minus_actual": cluster_ci(mk_sim.get(grp, {})),
                         "line_minus_actual": cluster_ci(mk_line.get(grp, {})),
                         "sim_pts_minus_line": cluster_ci(mk_pts.get(grp, {}))} for grp in ("starter", "bench")},
        "dnp_with_points_line": len(dnp_priced),
    }


def print_report(report: Mapping[str, Any]) -> None:
    print("COVERAGE (per date):")
    for d, c in report["dates"].items():
        print(f"  {d}: sims={c['sims']} box_teams={c['box_teams']} box_rows={c['box_rows']} sides_joined={c['sides_joined']}"
              f" sides_without_box={c['sides_no_box'] or 0} built_after_tip={c['built_after_tip'] or 0}"
              f" pretip_prop_rows={c['pretip_prop_rows']} players_with_points_line={c['players_with_points_line']}")
    print()
    print("PER SIDE  (minutes; bias = sim - actual over pool players who PLAYED)")
    print("  date       team pool play dnp  DNP_sim  starter_bias(n)  bench_bias(n)  outside(n)  MAE   dnp by cause")
    for s in report["sides"]:
        causes = " ".join(f"{c}={v:.1f}" for c, v in sorted(s["dnp_by_cause"].items()))
        flag = (" [built after tip]" if s["built_after_tip"] else "") + (" [history path]" if s.get("rotation_history_applied") else "")
        print(f"  {s['date']} {s['team']:4} {s['pool_n']:4} {s['played_n']:4} {s['dnp_n']:3}  {s['dnp_sim_min']:6.1f}"
              f"   {_fmt(s['starter_bias']):>6} ({s['starter_n']})     {_fmt(s['bench_bias']):>6} ({s['bench_n']})"
              f"   {s['outside_min']:5.1f} ({s['outside_n']})  {_fmt(s['mae_played'], 2)}  {causes}{flag}")
    for label, pretip in (("ALL SIDES", False), ("SIDES BUILT BEFORE TIP", True)):
        sm = summarize(report, pretip_only=pretip)
        print()
        print(f"POOLED -- {label}: {sm['sides']} sides over {len(sm['dates'])} dates {sm['dates']} (95% CI, bootstrap over sides)")
        for name in ("dnp_sim_min_per_side", "outside_min_per_side", "starter_bias", "ge28_bias", "bench_bias", "mae_played"):
            m, lo, hi, n = sm[name]
            print(f"  {name:22} {m:+7.2f}  [{lo:+.2f}, {hi:+.2f}]  n={n}")
        print("  DNP sim minutes by cause (total): " + ", ".join(f"{c} {v:.1f}" for c, v in sorted(sm["dnp_by_cause_total"].items())))
        print("  outside-pool box minutes (total): " + ", ".join(f"{c} {v:.0f}" for c, v in sm["outside_min_by_priced"].items()))
        for grp, mk in sm["market"].items():
            a, b, c = mk["sim_minus_actual"], mk["line_minus_actual"], mk["sim_pts_minus_line"]
            print(f"  MARKET {grp:7} (played, has a points line, n={a[3]}): sim-actual min {a[0]:+.2f} [{a[1]:+.2f}, {a[2]:+.2f}];"
                  f" line's minutes-actual {b[0]:+.2f} [{b[1]:+.2f}, {b[2]:+.2f}]; sim pts - line {c[0]:+.2f} [{c[1]:+.2f}, {c[2]:+.2f}]")
        print(f"  DNP pool players who had a pre-tip points line: {sm['dnp_with_points_line']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--processed", required=True, type=Path)
    ap.add_argument("--raw", type=Path, default=None, help="raw dir holding injuries.csv (default: <processed>/../raw)")
    ap.add_argument("--since", default=None)
    ap.add_argument("--dates", default=None, help="comma-separated dates (overrides --since)")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--replay", action="store_true", help="OFF vs priced-first ON on production engine_inputs")
    ap.add_argument("--min-rows", type=int, default=0, help="replay: rows below which the verdict stays INCONCLUSIVE")
    ap.add_argument("--arms", nargs=2, type=Path, default=None, metavar=("OFF_PROCESSED", "ON_PROCESSED"),
                    help="score two scratch arms' sims; --processed is the TRUTH root (box, player_logs, props history)")
    args = ap.parse_args(argv)
    raw = args.raw or (args.processed.parent / "raw")
    if args.arms:
        for d in ([x.strip() for x in args.dates.split(",")] if args.dates else []):
            res = arms(args.arms[0], args.arms[1], args.processed, raw, d)
            print(f"DATE {d}")
            print_arms(res)
            if args.json:
                args.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
                print(f"\nwrote {args.json}")
        return 0
    dates = [d.strip() for d in args.dates.split(",") if d.strip()] if args.dates else sim_dates(args.processed, args.since)
    dates = [d for d in dates if (args.processed / "rotation_stints" / f"player_checks_{d}.csv").is_file()]
    if args.replay:
        rep = replay(args.processed, raw, dates)
        rule = replay_rule(rep["sides"], min_rows=args.min_rows)
        print_replay(rep, rule)
        if args.json:
            args.json.write_text(json.dumps({"replay": rep, "rule": rule}, indent=1, default=str), encoding="utf-8")
            print(f"\nwrote {args.json}")
        return 0
    report = run(args.processed, raw, dates)
    print_report(report)
    if args.json:
        args.json.write_text(json.dumps({"report": report, "summary_all": summarize(report),
                                         "summary_pretip": summarize(report, pretip_only=True)}, indent=1, default=str),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
