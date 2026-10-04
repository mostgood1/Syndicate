"""In-season blend weights for the NHL season inputs that feed PROPS and the faceoff engine.
Lane `nhl-season-inputs-in-season`.

Production's team_rates / team_special_teams / player_rates are frozen 2025-26 builds. Each is a ratio of COUNTS
(faceoff wins / faceoffs, PP goals / opponent minors, blocks / shots faced, a player's shots / games ...), so the
in-season version blends at the count level: the prior season enters as pseudo-counts worth W games,

    rate = (W * prior_num_per_game + cur_num) / (W * prior_den_per_game + cur_den)

W = 0 is current-only; W = inf is prior-only (production today). This picks W per field family by how well the
as-of blend FORECASTS each team's / player's value in its next game (squared error weighted by that game's
denominator), tuned on 2024-25 (prior = 2023-24) and checked on 2025-26 (prior = 2024-25). It measures the
INPUTS only; the props lane measures the end-to-end props effect.

Data (read-only): boxscores, landings, play-by-play for 2023-24 / 2024-25 cached from api-web.nhle.com;
2025-26 from the primary checkout's ingestion_cache (boxscore_, playbyplay_) and truth/raw (landing_).
Usage: py -3 scripts/nhl_season_inputs_fields_experiment.py
"""
from __future__ import annotations

import bisect
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

GRID = (0.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0, math.inf)


def _rj(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() and p.stat().st_size else None
    except (OSError, ValueError):
        return None


def load_season(box_dir: Path, land_dir: Path, pbp_dir: Path, *, box_pat: str, land_pat: str, pbp_pat: str) -> List[dict]:
    """Per regular-season game: date + per-team and per-player count rows (num, den) for every field family."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import parse_boxscore_block_rate
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import parse_landing
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import parse_boxscore_player_rates
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import parse_boxscore_sog, parse_play_by_play_faceoffs

    games = []
    for bf in sorted(box_dir.glob(box_pat)):
        box = _rj(bf)
        if not box or int(box.get("gameType") or 0) != 2:
            continue
        gid = str(box["id"])
        land = _rj(land_dir / land_pat.format(gid=gid))
        pbp = _rj(pbp_dir / pbp_pat.format(gid=gid))
        if not land or not pbp:
            continue
        h, a = str(box["homeTeam"]["abbrev"]).upper(), str(box["awayTeam"]["abbrev"]).upper()
        sog = parse_boxscore_sog(box) or {}
        fo = parse_play_by_play_faceoffs(pbp) or {}
        blk = parse_boxscore_block_rate(box)
        rec = parse_landing(land)
        if rec is None or blk is None:
            continue
        team = {h: {}, a: {}}
        team[h]["shots"] = (float(sog.get("home_sog", rec.home_sog)), 1.0)
        team[a]["shots"] = (float(sog.get("away_sog", rec.away_sog)), 1.0)
        fh, fa, ft = fo.get("home_wins"), fo.get("away_wins"), fo.get("total")
        if fh is not None and fa is not None and ft:
            team[h]["faceoff_pct"] = (float(fh), float(ft))
            team[a]["faceoff_pct"] = (float(fa), float(ft))
        team[h]["pp_pct"] = (float(rec.pp_goals_home), float(rec.penalties_committed_away))
        team[a]["pp_pct"] = (float(rec.pp_goals_away), float(rec.penalties_committed_home))
        team[h]["pk_ga_rate"] = (float(rec.pp_goals_away), float(rec.penalties_committed_home))
        team[a]["pk_ga_rate"] = (float(rec.pp_goals_home), float(rec.penalties_committed_away))
        team[h]["committed"] = (float(rec.penalties_committed_home), 1.0)
        team[a]["committed"] = (float(rec.penalties_committed_away), 1.0)
        team[h]["block_rate"] = (float(blk.home_blocks), float(blk.home_shots_faced))
        team[a]["block_rate"] = (float(blk.away_blocks), float(blk.away_shots_faced))
        players = {}
        for p in parse_boxscore_player_rates(box):
            players[int(p.player_id)] = {"pos": p.position, "shots": (float(p.shots), 1.0),
                                         "goals": (float(p.goals), 1.0), "blocks": (float(p.blocks), 1.0)}
        games.append({"gid": gid, "date": str(box.get("gameDate") or "")[:10], "team": team, "player": players, "rec": rec})
    games.sort(key=lambda g: (g["date"], g["gid"]))
    return games


def totals(games: List[dict], kind: str) -> Dict[object, Dict[str, List[float]]]:
    """{entity: {field: [num, den, games]}} over a season."""
    out: Dict[object, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))
    for g in games:
        for ent, fields in g[kind].items():
            for f, v in fields.items():
                if f == "pos":
                    continue
                e = out[ent][f]
                e[0] += v[0]; e[1] += v[1]; e[2] += 1
    return out


def position_means(games: List[dict]) -> Dict[str, Dict[str, Tuple[float, float]]]:
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for g in games:
        for _pid, fields in g["player"].items():
            for f in ("shots", "goals", "blocks"):
                acc[fields["pos"]][f][0] += fields[f][0]; acc[fields["pos"]][f][1] += fields[f][1]
    return {pos: {f: (v[0] / v[1], 1.0) for f, v in d.items()} for pos, d in acc.items()}


def evaluate(target: List[dict], prior: List[dict], kind: str, fields: List[str]) -> Dict[str, Dict[float, Tuple[float, int]]]:
    """For each field and W: weighted squared error forecasting each entity's value in each game from the
    as-of blend (prior pseudo-counts + current counts strictly before the game)."""
    ptot = totals(prior, kind)
    pos_mean = position_means(prior) if kind == "player" else {}
    running: Dict[object, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    res = {f: {w: [0.0, 0.0, 0] for w in GRID} for f in fields}
    for g in target:
        for ent, fv in g[kind].items():
            for f in fields:
                if f not in fv:
                    continue
                num, den = fv[f]
                if den <= 0:
                    continue
                y = num / den
                pt = ptot.get(ent, {}).get(f)
                if pt and pt[2] > 0 and pt[1] > 0:
                    p_num_pg, p_den_pg = pt[0] / pt[2], pt[1] / pt[2]
                elif kind == "player" and fv.get("pos") in pos_mean:
                    pm = pos_mean[fv["pos"]][f]
                    p_num_pg, p_den_pg = pm[0], pm[1]
                else:
                    continue
                c_num, c_den = running[ent][f]
                for w in GRID:
                    if w == math.inf or (w == 0.0 and c_den == 0):
                        pred = p_num_pg / p_den_pg if p_den_pg > 0 else 0.0
                    else:
                        pred = (w * p_num_pg + c_num) / (w * p_den_pg + c_den)
                    r = res[f][w]
                    r[0] += den * (pred - y) ** 2; r[1] += den; r[2] += 1
        for ent, fv in g[kind].items():  # update AFTER scoring the game (strictly as-of)
            for f in fields:
                if f in fv:
                    running[ent][f][0] += fv[f][0]; running[ent][f][1] += fv[f][1]
    return {f: {w: (v[0] / v[1] if v[1] else float("nan"), v[2]) for w, v in d.items()} for f, d in res.items()}


ELO_REGRESSION_GRID = (0.0, 0.25, 1.0 / 3.0, 0.5, 0.75, 1.0)


def evaluate_elo(target: List[dict], prior: List[dict]) -> Dict[float, Tuple[float, int]]:
    """Home-win Brier of the as-of Elo over `target` when each team starts at its `prior` FINAL rating
    regressed toward 1500 by r (r=1 is a fresh 1500 start; production's frozen file is no updates at all,
    scored as 'frozen')."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.elo_builder import (
        DEFAULT_ELO_SCALE, DEFAULT_HOME_ADVANTAGE, DEFAULT_K, _expected_home_win_prob, compute_elo_ratings)

    final = compute_elo_ratings([g["rec"] for g in prior])
    out: Dict[object, Tuple[float, int]] = {}
    for r in list(ELO_REGRESSION_GRID) + ["frozen"]:
        ratings = {t: 1500.0 + (1.0 - (0.0 if r == "frozen" else r)) * (e - 1500.0) for t, e in final.items()}
        se, n = 0.0, 0
        for g in target:
            rec = g["rec"]
            ra, rb = ratings.get(rec.home_abbr, 1500.0), ratings.get(rec.away_abbr, 1500.0)
            p = _expected_home_win_prob(ra, rb, scale=DEFAULT_ELO_SCALE, home_advantage=DEFAULT_HOME_ADVANTAGE)
            y = 1.0 if rec.home_win else 0.0
            se += (p - y) ** 2; n += 1
            if r != "frozen":
                d = DEFAULT_K * (y - p)
                ratings[rec.home_abbr] = ra + d; ratings[rec.away_abbr] = rb - d
        out[r] = (se / n if n else float("nan"), n)
    return out


TEAM_FIELDS = ["shots", "faceoff_pct", "pp_pct", "pk_ga_rate", "committed", "block_rate"]
PLAYER_FIELDS = ["shots", "goals", "blocks"]


def main() -> int:
    tmp = Path("C:/tmp/nhllines")
    prim = Path(__import__("subprocess").run(["git", "-C", str(REPO), "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout.splitlines()[0].split(" ", 1)[1].strip())
    src = prim / "data" / "nhl_source" / "data"
    s23 = load_season(tmp / "boxscore_2023", tmp / "landing_2023", tmp / "pbp_2023", box_pat="*.json", land_pat="{gid}.json", pbp_pat="{gid}.json")
    s24 = load_season(tmp / "boxscore_2024", tmp / "landing_2024", tmp / "pbp_2024", box_pat="*.json", land_pat="{gid}.json", pbp_pat="{gid}.json")
    s25 = load_season(src / "ingestion_cache", src / "truth" / "raw", src / "ingestion_cache",
                      box_pat="boxscore_2025*.json", land_pat="landing_{gid}.json", pbp_pat="playbyplay_{gid}.json")
    print(f"seasons with box+landing+pbp: 2023-24 {len(s23)}, 2024-25 {len(s24)}, 2025-26 {len(s25)}", flush=True)
    chosen = {}
    for kind, fields in (("team", TEAM_FIELDS), ("player", PLAYER_FIELDS)):
        tune = evaluate(s24, s23, kind, fields)
        check = evaluate(s25, s24, kind, fields)
        for f in fields:
            finite = {w: v for w, v in tune[f].items() if w not in (math.inf,)}
            w_star = min(finite, key=lambda w: finite[w][0])
            chosen[f"{kind}.{f}"] = w_star
            pri, cur, bl = check[f][math.inf][0], check[f][0.0][0], check[f][w_star][0]
            print(f"{kind}.{f:<12} W*={w_star:>5} (tuned 2024-25) | 2025-26 MSE prior-only {pri:.5f} current-only {cur:.5f} "
                  f"blend {bl:.5f} -> vs prior {100 * (bl / pri - 1):+.2f}% vs current {100 * (bl / cur - 1):+.2f}% (n={check[f][w_star][1]})", flush=True)
    et, ec = evaluate_elo(s24, s23), evaluate_elo(s25, s24)
    r_star = min(ELO_REGRESSION_GRID, key=lambda r: et[r][0])
    chosen["elo.regression"] = r_star
    print("elo Brier tune 2024-25: " + ", ".join(f"{k if isinstance(k, str) else round(k, 3)}={v[0]:.5f}" for k, v in et.items()), flush=True)
    print(f"elo r*={r_star:.3f} | 2025-26 Brier frozen {ec['frozen'][0]:.5f} fresh-1500 {ec[1.0][0]:.5f} carried {ec[r_star][0]:.5f} (n={ec[r_star][1]}) "
          "-- INERT in production (elo_blend_weight=0)", flush=True)
    (tmp / "season_inputs_fields_w.json").write_text(json.dumps({k: (None if v == math.inf else v) for k, v in chosen.items()}, indent=1), encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
