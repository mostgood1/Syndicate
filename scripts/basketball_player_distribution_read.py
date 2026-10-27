"""Phase 1 read of lane basketball-player-distribution (pre-registered 6507de9d,
.syndicate/findings_2026-10-26_basketball_player_distribution.md).

Raw engine PLAYER outcome distributions against real player boxes. Input: a scenario-harness sim directory run with
`--record-player-draws` (per draw, per player [pts, reb, ast, threes, on-floor possessions]) plus the ESPN summary
cache for the truth.

Per stat: randomised PIT u = P(X < y) + U.P(X = y) over the draws; tail shares P(u < .1), P(u > .9) (nominal .10 each);
central-80% miss = their sum (nominal .20); width ratio = sd(y - sim mean) / rms(sim sd); bias = mean(y - sim mean).
CIs: game-clustered bootstrap. Splits: starters (top-5 by input minutes) / bench; close (final |margin| <= 10) /
blowout (>= 20). Decomposition: a MINUTES-ORACLE arm rescales each draw's stat by actual min / that draw's sim min.

Usage:
    py -3 scripts/basketball_player_distribution_read.py --sim DIR --cache DIR [--json-out FILE]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

STATS = ("pts", "reb", "ast", "threes")
TRI = {"GS": "GSW", "UTAH": "UTA", "SA": "SAS", "WSH": "WAS", "NO": "NOP", "NY": "NYK"}


def tri(t: str) -> str:
    return TRI.get(str(t), str(t))


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def pit(draws: Sequence[float], y: float, u: float) -> float:
    """Randomised PIT of y under the empirical distribution of `draws` (u ~ U(0,1) supplied by the caller)."""
    x = np.asarray(draws, dtype=float)
    n = len(x)
    if n == 0:
        return float("nan")
    return float(((x < y).sum() + u * (x == y).sum()) / n)


def cell_summary(rows: List[Dict[str, Any]], rng: np.random.Generator, n_boot: int = 2000) -> Dict[str, Any]:
    """rows: dicts with game, u (PIT), err (y - sim mean), sd (sim sd). Game-clustered bootstrap for the miss."""
    if not rows:
        return {"n": 0}
    u = np.array([r["u"] for r in rows], float)
    err = np.array([r["err"] for r in rows], float)
    sd = np.array([r["sd"] for r in rows], float)
    lo, hi = float((u < 0.1).mean()), float((u > 0.9).mean())
    games = sorted({r["game"] for r in rows})
    gi = {g: i for i, g in enumerate(games)}
    miss_g = np.zeros(len(games)); n_g = np.zeros(len(games))
    for r in rows:
        k = gi[r["game"]]
        miss_g[k] += float(r["u"] < 0.1 or r["u"] > 0.9); n_g[k] += 1
    bs = []
    for _ in range(n_boot):
        ix = rng.integers(0, len(games), len(games))
        bs.append(miss_g[ix].sum() / max(1.0, n_g[ix].sum()))
    rms_sd = float(np.sqrt(np.mean(sd ** 2)))
    return {"n": len(rows), "games": len(games), "bias": float(err.mean()), "p_lo": lo, "p_hi": hi, "miss": lo + hi,
            "miss_ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "width_ratio": float(err.std(ddof=1) / rms_sd) if rms_sd > 0 and len(err) > 1 else float("nan")}


def flagged(cell: Dict[str, Any]) -> bool:
    """Pre-registered: miss outside [.15, .25] with its CI excluding .20."""
    if not cell.get("n"):
        return False
    lo, hi = cell["miss_ci"]
    return (cell["miss"] < 0.15 or cell["miss"] > 0.25) and not (lo <= 0.20 <= hi)


def actual_players(cache: Path, eid: str) -> Dict[str, Tuple[float, ...]]:
    f = cache / f"summary_{eid}.json.gz"
    if not f.exists():
        return {}
    d = json.load(gzip.open(f))
    out: Dict[str, Tuple[float, ...]] = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        st = (t.get("statistics") or [{}])[0]
        names = st.get("names") or st.get("labels") or []
        ix = {n: i for i, n in enumerate(names)}
        if not {"MIN", "PTS", "REB", "AST", "3PT"} <= set(ix):
            continue
        for a in st.get("athletes") or []:
            v = a.get("stats") or []
            if not v:
                continue
            try:
                mn = float(v[ix["MIN"]])
            except (TypeError, ValueError):
                continue
            if mn <= 0:
                continue
            tpm = str(v[ix["3PT"]]).split("-")[0]
            out[norm((a.get("athlete") or {}).get("displayName"))] = (mn, float(v[ix["PTS"]]), float(v[ix["REB"]]),
                                                                       float(v[ix["AST"]]), float(tpm))
    return out


def player_games(sim_dir: Path, cache: Path) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """One record per (game, player) that the sim simulated AND who played; counts of the excluded populations."""
    real = {}
    for ln in open(sim_dir / "real_nba.jsonl", encoding="utf-8"):
        x = json.loads(ln)
        if x.get("season_type") == 2:
            real[(x["date"], tri(x["home"]), tri(x["away"]))] = x
    out: List[Dict[str, Any]] = []
    counts = defaultdict(int)
    for f in sorted((sim_dir / "sim_nba").glob("*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            g = json.loads(ln)
            draws = g.get("draws") or []
            if not draws or "pl" not in draws[0] or not g.get("pnames"):
                continue
            key = (g["date"], tri(g["home"]), tri(g["away"]))
            r = real.get(key)
            if r is None:
                counts["game_no_real"] += 1
                continue
            act = actual_players(cache, str(r["event_id"]))
            if not act:
                counts["game_no_box"] += 1
                continue
            counts["games"] += 1
            margin = abs(float(r["home_pts"]) - float(r["away_pts"]))
            inp = {s: {str(n): float(m) for n, m in (g.get("minutes") or {}).get(full, [])}
                   for s, full in (("h", "home"), ("a", "away"))}
            seen = set()
            for s in ("h", "a"):
                names = g["pnames"][s]
                top5 = set(sorted(names, key=lambda n: -inp[s].get(n, 0.0))[:5])
                for j, n in enumerate(names):
                    nn = norm(n)
                    seen.add(nn)
                    if nn not in act:
                        counts["sim_only_dnp"] += 1
                        continue
                    lines = np.array([d["pl"][s][j] for d in draws], float)            # draws x 5
                    game_min = np.array([48.0 + 5.0 * float(d.get("otn", 0)) for d in draws])
                    on_n = np.array([float(d.get("on_n", -1)) for d in draws])
                    sim_min = np.where((lines[:, 4] >= 0) & (on_n > 0), game_min * lines[:, 4] / np.maximum(on_n, 1), np.nan)
                    out.append({"game": key, "player": n, "starter": n in top5, "margin": margin,
                                "input_min": inp[s].get(n, float("nan")), "actual": act[nn],
                                "draws": lines[:, :4], "sim_min": sim_min})
            counts["real_only"] += sum(1 for nn in act if nn not in seen)
    return out, dict(counts)


def read(pg: List[Dict[str, Any]], seed: int = 0) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    cells: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in pg:
        y_min = r["actual"][0]
        splits = ["all", "starter" if r["starter"] else "bench"]
        if r["margin"] <= 10:
            splits.append("close")
        elif r["margin"] >= 20:
            splits.append("blowout")
        sm = r["sim_min"]
        if np.isfinite(sm).any():
            x = sm[np.isfinite(sm)]
            row = {"game": r["game"], "u": pit(x, y_min, rng.random()), "err": y_min - float(x.mean()), "sd": float(x.std())}
            for sp in splits:
                cells[f"min|{sp}"].append(row)
        cells["min_input_bias|all"].append({"game": r["game"], "u": 0.5, "err": y_min - r["input_min"], "sd": 0.0})
        for k, st in enumerate(STATS):
            x = r["draws"][:, k]
            y = r["actual"][k + 1]
            row = {"game": r["game"], "u": pit(x, y, rng.random()), "err": y - float(x.mean()), "sd": float(x.std())}
            for sp in splits:
                cells[f"{st}|{sp}"].append(row)
            ok = np.isfinite(sm) & (sm > 0)
            if ok.sum() >= 20:
                xo = x[ok] * (y_min / sm[ok])
                cells[f"{st}_oracle|all"].append({"game": r["game"], "u": pit(xo, y, rng.random()),
                                                  "err": y - float(xo.mean()), "sd": float(xo.std())})
    out = {k: cell_summary(v, rng) for k, v in sorted(cells.items())}
    for k, c in out.items():
        c["flagged"] = flagged(c) if not k.startswith("min_input_bias") else False
    return out


def box_roster(cache: Path, eid: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Every athlete on the ESPN box, by team tri: {norm name: {min, dnp, reason, name}} (min None when no stats)."""
    f = cache / f"summary_{eid}.json.gz"
    if not f.exists():
        return {}
    d = json.load(gzip.open(f))
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = tri((t.get("team") or {}).get("abbreviation") or "")
        st = (t.get("statistics") or [{}])[0]
        ix = {n: i for i, n in enumerate(st.get("names") or st.get("labels") or [])}
        roster = out.setdefault(team, {})
        for a in st.get("athletes") or []:
            v = a.get("stats") or []
            mn: Optional[float] = None
            if v and "MIN" in ix:
                try:
                    mn = float(v[ix["MIN"]])
                except (TypeError, ValueError):
                    mn = None
            name = str((a.get("athlete") or {}).get("displayName") or "")
            roster[norm(name)] = {"min": mn, "dnp": bool(a.get("didNotPlay")), "reason": str(a.get("reason") or ""), "name": name}
    return out


def names_match(a: str, b: str) -> bool:
    """The pre-registered JOIN rule on normalised names: difflib ratio >= 0.80, or same last name + first initial."""
    import difflib

    if not a or not b:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.80:
        return True
    pa, pb = a.split(), b.split()
    return len(pa) >= 2 and len(pb) >= 2 and pa[-1] == pb[-1] and pa[0][0] == pb[0][0]


def gap_rows(sim_dir: Path, cache: Path) -> Iterable[Dict[str, Any]]:
    """Step 1's population: one row per sim-only / real-only player-game, plus a `cls: None` row per team-game
    (carrying the sim's roster). Keys: date, team, cls, name (display), nn (norm), min (sim min for the sim-side
    classes, real min for REAL_ONLY), label (the step-1 example text)."""
    real = {}
    for ln in open(sim_dir / "real_nba.jsonl", encoding="utf-8"):
        x = json.loads(ln)
        if x.get("season_type") == 2:
            real[(x["date"], tri(x["home"]), tri(x["away"]))] = x
    for f in sorted((sim_dir / "sim_nba").glob("*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            g = json.loads(ln)
            draws = g.get("draws") or []
            if not draws or "pl" not in draws[0] or not g.get("pnames"):
                continue
            key = (g["date"], tri(g["home"]), tri(g["away"]))
            r = real.get(key)
            if r is None:
                continue
            box = box_roster(cache, str(r["event_id"]))
            if not box:
                continue
            for s, team in (("h", key[1]), ("a", key[2])):
                roster = box.get(team)
                if roster is None:
                    yield {"date": g["date"], "team": team, "cls": "team_missing_in_box"}
                    continue
                names = g["pnames"][s]
                sim_norm = [norm(n) for n in names]
                yield {"date": g["date"], "team": team, "cls": None, "sim_names": sim_norm}
                on_n = np.array([float(d.get("on_n", -1)) for d in draws])
                gm = np.array([48.0 + 5.0 * float(d.get("otn", 0)) for d in draws])
                played = {nn: v for nn, v in roster.items() if (v["min"] or 0) > 0}
                real_only = [nn for nn in played if nn not in set(sim_norm)]
                matched_ro: set = set()
                for j, nn in enumerate(sim_norm):
                    if nn in played:
                        continue
                    on = np.array([float(d["pl"][s][j][4]) for d in draws])
                    m = float(np.mean(np.where(on_n > 0, gm * on / np.maximum(on_n, 1), 0.0)))
                    hit = next((ro for ro in real_only if ro not in matched_ro and names_match(nn, ro)), None)
                    row = {"date": g["date"], "team": team, "name": names[j], "nn": nn, "min": m}
                    if hit is not None:
                        matched_ro.add(hit)
                        row.update(cls="JOIN", label=f"{names[j]} ~ {played[hit]['name']}")
                    elif nn in roster:
                        rs = roster[nn]["reason"].upper()
                        row.update(cls="DNP_LISTED_COACH" if "COACH" in rs else "DNP_LISTED_OTHER",
                                   label=f"{names[j]}: {roster[nn]['reason']}")
                    else:
                        row.update(cls="ABSENT", label=f"{g['date']} {team} {names[j]} ({m:.1f} sim min)")
                    yield row
                for ro in real_only:
                    if ro in matched_ro:
                        continue
                    yield {"date": g["date"], "team": team, "cls": "REAL_ONLY", "name": played[ro]["name"], "nn": ro,
                           "min": float(played[ro]["min"]),
                           "label": f"{g['date']} {team} {played[ro]['name']} ({played[ro]['min']:.0f} min)"}


def gaps(sim_dir: Path, cache: Path) -> Dict[str, Any]:
    """Phase 2 step 1 (pre-registered bf73ce71): classify sim-only and real-only player-games."""
    cls: Dict[str, int] = defaultdict(int)
    sim_min: Dict[str, List[float]] = defaultdict(list)
    real_only_min: List[float] = []
    by_month: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    examples: Dict[str, List[str]] = defaultdict(list)
    team_games = 0
    for row in gap_rows(sim_dir, cache):
        c = row["cls"]
        if c is None:
            team_games += 1
            continue
        cls[c] += 1
        if c == "team_missing_in_box":
            continue
        by_month[row["date"][:7]][c] += 1
        if c == "REAL_ONLY":
            real_only_min.append(row["min"])
        else:
            sim_min[c].append(row["min"])
        if c != "DNP_LISTED_COACH" and len(examples[c]) < 12:
            examples[c].append(row["label"])
    ro = np.array(real_only_min) if real_only_min else np.zeros(0)
    return {
        "team_games": team_games, "counts": dict(cls),
        "sim_min_per_team_game": {c: float(np.sum(v) / max(1, team_games)) for c, v in sim_min.items()},
        "sim_min_mean_per_player": {c: float(np.mean(v)) for c, v in sim_min.items()},
        "real_only_min_per_team_game": float(ro.sum() / max(1, team_games)),
        "real_only_min_mean": float(ro.mean()) if len(ro) else float("nan"),
        "real_only_share_ge10": float((ro >= 10).mean()) if len(ro) else float("nan"),
        "by_month": {k: dict(v) for k, v in sorted(by_month.items())}, "examples": dict(examples),
    }


def box_timeline(cache: Path, teams: Optional[set] = None) -> Dict[str, List[Tuple[str, str]]]:
    """Step 1b (pre-registered 7eaaa4ef): every regular-season box's active list, as {norm name: sorted [(date, team)]}.
    Date = header UTC minus 6 h (the US game day)."""
    from datetime import datetime, timedelta

    out: Dict[str, set] = defaultdict(set)
    for f in sorted(cache.glob("summary_*.json.gz")):
        hdr = json.load(gzip.open(f)).get("header") or {}
        if int((hdr.get("season") or {}).get("type") or 0) != 2:
            continue
        try:
            ts = str((hdr.get("competitions") or [{}])[0].get("date") or "")
            day = (datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M") - timedelta(hours=6)).strftime("%Y-%m-%d")
        except ValueError:
            continue
        for team, roster in box_roster(cache, f.name[len("summary_"):-len(".json.gz")]).items():
            if teams is not None and team not in teams:
                continue  # ESPN files the All-Star game (WORLD / STRIPES) as season type 2
            for nn in roster:
                out[nn].add((day, team))
    return {k: sorted(v) for k, v in out.items()}


def classify_absent(apps: Sequence[Tuple[str, str]], team: str, d: str) -> str:
    """The sim put the player on `team` on `d` and that box does not list him. `apps`: his real (date, team) listings."""
    if not apps:
        return "NO_BOX"
    t_before = any(x < d and t == team for x, t in apps)
    t_after = any(x > d and t == team for x, t in apps)
    if t_before and t_after:
        return "T_AROUND"
    if t_after:
        return "LEAK_FUTURE" if any(x <= d and t != team for x, t in apps) else "T_ONLY_AFTER_NO_OTHER"
    if t_before:
        return "STALE_PAST" if any(x >= d and t != team for x, t in apps) else "T_ONLY_BEFORE_NO_OTHER"
    return "NEVER_T_OTHER_TEAM"


def classify_real_only(sim_dates: Sequence[str], d: str) -> str:
    """The player played for the team on `d` and the sim's roster that day lacks him. `sim_dates`: the dates the sim
    listed him for that team."""
    before = any(x < d for x in sim_dates)
    after = any(x > d for x in sim_dates)
    if before and after:
        return "SIM_AROUND"
    if after:
        return "SIM_LATER_ONLY"
    if before:
        return "SIM_EARLIER_ONLY"
    return "SIM_NEVER_T"


def rosters(sim_dir: Path, cache: Path) -> Dict[str, Any]:
    """Phase 2 step 1b: leak / stale / availability census of step 1's ABSENT and REAL_ONLY player-games."""
    rows = list(gap_rows(sim_dir, cache))
    sim_on: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    team_games = 0
    for r in rows:
        if r["cls"] is None:
            team_games += 1
            for nn in r["sim_names"]:
                sim_on[(r["team"], nn)].append(r["date"])
    tl = box_timeline(cache, teams={r["team"] for r in rows if r["cls"] is None})
    out: Dict[str, Any] = {"team_games": team_games}
    # Descriptive, post-hoc (disclosed, not pre-registered): is each team's sim roster ONE snapshot across the window?
    by_team: Dict[str, Dict[str, set]] = defaultdict(dict)
    for r in rows:
        if r["cls"] is None:
            by_team[r["team"]][r["date"]] = set(r["sim_names"])
    jac = []
    for t, dd in by_team.items():
        ks = sorted(dd)
        a, b = dd[ks[0]], dd[ks[-1]]
        jac.append(len(a & b) / max(1, len(a | b)))
    out["sim_roster_first_vs_last_jaccard"] = {"median": float(np.median(jac)), "min": float(np.min(jac)), "teams": len(jac)}
    sens = {"T_ONLY_AFTER_NO_OTHER_first_listed_elsewhere": 0, "SIM_NEVER_T_last_listed_elsewhere": 0,
            "SIM_NEVER_T_last_listed_on_T": 0}
    for src in ("ABSENT", "REAL_ONLY"):
        n: Dict[str, int] = defaultdict(int)
        mins: Dict[str, float] = defaultdict(float)
        by_month: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        ex: Dict[str, List[str]] = defaultdict(list)
        for r in rows:
            if r["cls"] != src:
                continue
            if src == "ABSENT":
                apps = tl.get(r["nn"], [])
                c = classify_absent(apps, r["team"], r["date"])
                near = [f"{x} {t}" for x, t in apps
                        if abs(int((np.datetime64(x) - np.datetime64(r["date"])) / np.timedelta64(1, "D"))) <= 21]
                note = f"{r['label']} | real boxes +/-21d: {', '.join(near[:6]) or 'none'}"
                if c == "T_ONLY_AFTER_NO_OTHER" and apps and apps[0][1] != r["team"]:
                    sens["T_ONLY_AFTER_NO_OTHER_first_listed_elsewhere"] += 1  # window-start leak (traded TO the team later)
            else:
                c = classify_real_only(sim_on.get((r["team"], r["nn"]), []), r["date"])
                note = r["label"]
                apps = tl.get(r["nn"], [])
                if c == "SIM_NEVER_T" and apps:
                    sens["SIM_NEVER_T_last_listed_elsewhere" if apps[-1][1] != r["team"] else "SIM_NEVER_T_last_listed_on_T"] += 1
            n[c] += 1
            mins[c] += r["min"]
            by_month[r["date"][:7]][c] += 1
            if len(ex[c]) < 12:
                ex[c].append(note)
        out[src] = {"counts": dict(n), "min_per_team_game": {c: v / max(1, team_games) for c, v in mins.items()},
                    "by_month": {k: dict(v) for k, v in sorted(by_month.items())}, "examples": dict(ex)}
    out["post_hoc_sensitivity"] = sens
    return out


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--gaps", action="store_true", help="Phase 2 step 1: classify the sim-only / real-only player-games")
    ap.add_argument("--rosters", action="store_true", help="Phase 2 step 1b: leak / stale / availability census")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.gaps or a.rosters:
        res_g = rosters(a.sim, a.cache) if a.rosters else gaps(a.sim, a.cache)
        print(json.dumps(res_g, indent=1))
        if a.json_out:
            a.json_out.write_text(json.dumps(res_g, indent=1), encoding="utf-8")
        return 0
    pg, counts = player_games(a.sim, a.cache)
    res = read(pg)
    print("population", json.dumps(counts), "player-games", len(pg))
    for k, c in res.items():
        if not c.get("n"):
            continue
        print(f"{k:22s} n={c['n']:6d} bias {c['bias']:+.3f} width {c['width_ratio']:.3f} lo {c['p_lo']:.3f} hi {c['p_hi']:.3f} "
              f"miss {c['miss']:.3f} [{c['miss_ci'][0]:.3f},{c['miss_ci'][1]:.3f}]{'  FLAG' if c['flagged'] else ''}")
    if a.json_out:
        a.json_out.write_text(json.dumps({"population": counts, "player_games": len(pg), "cells": res}, indent=1, default=str),
                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
