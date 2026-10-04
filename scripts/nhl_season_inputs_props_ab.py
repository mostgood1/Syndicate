"""End-to-end props A/B for the in-season season inputs (lane `nhl-season-inputs-in-season`).

Question: does replacing production's FROZEN prior-season `team_rates / team_special_teams / player_rates /
team_elo` files with the in-season blend (`syndicate/features/nhl/inseason_season_inputs.py`, the code that
would ship) make the NHL player-prop projections more accurate?

Method: the props lane's harness (`scripts/backtest_nhl_props.py`), UNMODIFIED, runs the production props
path over 2025-26 regular-season dates. Only its season-input writer is swapped, per arm:
  * prior -- every season file is the full 2024-25 build (the producers' own aggregation, via the harness's
             own `write_season_inputs`), written as `_latest` only: what production reads all season today.
  * blend -- the same `_latest` files, PLUS `<stem>_2025-2026.csv` for the four stems, built by the shipping
             module's builders from 2025-26 games STRICTLY BEFORE the date. Team xG is identical in both arms.
Everything else (collector, lineups, goalies, engine, n_sims, seeds) is the harness's. Scored paired per
(game, player, market) on players who played, MAE vs the actual box, game-clustered bootstrap.

Usage: py -3 scripts/nhl_season_inputs_props_ab.py --base C:/tmp/nhlprops/bt_lqp_0.5 --out C:/tmp/nhllines/props_ab
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import random
import shutil
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MARKET_STAT = {"SOG": "sog", "GOALS": "g", "ASSISTS": "a", "POINTS": "pts", "BLOCKS": "blk", "SAVES": "sv"}
_A: Dict = {}


def _bt():
    spec = importlib.util.spec_from_file_location("backtest_nhl_props", REPO / "scripts" / "backtest_nhl_props.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_nhl_props"] = mod
    spec.loader.exec_module(mod)
    return mod


def _rj(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() and p.stat().st_size else None
    except (OSError, ValueError):
        return None


def prior_records(tmp: Path) -> Dict[str, Dict]:
    """2024-25 regular-season records in the harness's `season_recs` shape (same parsers as parse_records)."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import parse_boxscore_block_rate
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import parse_boxscore_shot_strength
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (
        parse_playbyplay_faceoffs_by_role, parse_playbyplay_faceoffs_by_zone, parse_playbyplay_faceoffs_ev)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import parse_landing
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (
        parse_boxscore_player_rates, parse_playbyplay_player_faceoffs, parse_playbyplay_roster_names)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.shot_xg_model import parse_play_by_play_shots
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import build_game_team_rates

    out: Dict[str, Dict] = {}
    for bf in sorted((tmp / "boxscore_2024").glob("*.json")):
        box = _rj(bf)
        if not box or int(box.get("gameType") or 0) != 2:
            continue
        gid = str(box["id"])
        pbp, land = _rj(tmp / "pbp_2024" / f"{gid}.json"), _rj(tmp / "landing_2024" / f"{gid}.json")
        rec = {"date": "2024-01-01"}  # any date < every cutoff: the whole prior season is as-of
        rec["team_rates"] = build_game_team_rates([box], {gid: pbp} if pbp else {}).get(gid)
        rec["players"] = parse_boxscore_player_rates(box)
        rec["shot_str"] = parse_boxscore_shot_strength(box)
        rec["block"] = parse_boxscore_block_rate(box)
        rec["landing"] = parse_landing(land) if land else None
        if pbp:
            rec["pfo"] = parse_playbyplay_player_faceoffs(pbp)
            rec["pnames"] = parse_playbyplay_roster_names(pbp)
            rec["fo_ev"] = parse_playbyplay_faceoffs_ev(pbp)
            rec["fo_zone"] = parse_playbyplay_faceoffs_by_zone(pbp)
            rec["fo_role"] = parse_playbyplay_faceoffs_by_role(pbp)
            rec["shots"] = parse_play_by_play_shots(pbp)
            home, away = pbp.get("homeTeam") or {}, pbp.get("awayTeam") or {}
            rec["team_map"] = ({"home_id": int(home["id"]), "home_abbr": str(home.get("abbrev") or "").upper(),
                                "away_id": int(away["id"]), "away_abbr": str(away.get("abbrev") or "").upper()}
                               if home.get("id") is not None and away.get("id") is not None else None)
        out[gid] = rec
    return out


def current_game_counts(src: Path) -> List[Dict]:
    """Per 2025-26 regular-season game: (date, the shipping module's counts for that one game)."""
    from syndicate.features.nhl.inseason_season_inputs import current_counts

    cache, truth = src / "data" / "ingestion_cache", src / "data" / "truth" / "raw"
    out = []
    for bf in sorted(cache.glob("boxscore_2025020*.json")):
        box = _rj(bf)
        if not box or int(box.get("gameType") or 0) != 2:
            continue
        gid = str(box["id"])
        c = current_counts([{"box": box, "landing": _rj(truth / f"landing_{gid}.json"), "pbp": _rj(cache / f"playbyplay_{gid}.json")}])
        if c["records"]:
            out.append({"date": str(box.get("gameDate") or "")[:10], "counts": c})
    return out


def _merge(parts: List[Dict]) -> Dict:
    team: Dict = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    player: Dict = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    records = []
    for c in parts:
        for dst, srcd in ((team, c["team"]), (player, c["player"])):
            for k, fields in srcd.items():
                for f, (n, d) in fields.items():
                    dst[k][f][0] += n
                    dst[k][f][1] += d
        records.extend(c["records"])
    return {"team": {k: dict(v) for k, v in team.items()}, "player": {k: dict(v) for k, v in player.items()}, "records": records}


def _init(src: str, out: str, allow_net: bool, arm: str, side: str) -> None:
    bt = _bt()
    bt._worker_init(src, out, allow_net)
    with open(side, "rb") as fh:
        side_data = pickle.load(fh)
    orig = bt.write_season_inputs

    def patched(proc: Path, _season_recs, cutoff: str, *, latest_only: bool):
        info = orig(proc, side_data["prior_recs"], "9999-12-31", latest_only=True)
        info["ab_arm"] = arm
        if arm == "blend":
            import csv as _csv
            from syndicate.features.nhl import inseason_season_inputs as M
            cur = _merge([g["counts"] for g in side_data["current"] if g["date"] < cutoff])
            builders = {"team_rates": lambda r: M.build_team_rates(r, cur["team"]),
                        "team_special_teams": lambda r: M.build_special_teams(r, cur["team"]),
                        "player_rates": lambda r: M.build_player_rates(r, cur["player"]),
                        "team_elo": lambda r: M.build_team_elo(r, cur["records"])}
            for stem in M.STEMS:
                header, rows = M._read_rows(proc / f"{stem}_latest.csv")
                M._write_atomic(proc / f"{stem}_2025-2026.csv", header, builders[stem](rows))
            info["ab_current_games"] = len(cur["records"])
        return info

    bt.write_season_inputs = patched
    _A["bt"] = bt


def _run(date: str, n_sims: int) -> Dict:
    return _A["bt"].run_date(date, "regular", n_sims)


def score(outs: Dict[str, Path], actuals: Dict, n_boot: int = 2000) -> Dict:
    lam: Dict[str, Dict] = {arm: {} for arm in outs}
    for arm, out in outs.items():
        for f in (out / "sim").glob("regular_*.json"):
            res = json.loads(f.read_text(encoding="utf-8"))
            for g in res["games"]:
                for p in g.get("players") or []:
                    for mk, v in p["m"].items():
                        if v.get("lam") is not None:
                            lam[arm][(g["gid"], p["pid"], mk)] = (res["date"], v["lam"])
    played = {(gid, p["pid"]): p for gid, a in actuals.items() for p in a["players"] if p["toi"] > 0}
    keys = sorted(k for k in set(lam["prior"]) & set(lam["blend"]) if (k[0], k[1]) in played)
    report = {}
    for mk in MARKET_STAT:
        for period, lo, hi in (("all", "", "9999"), ("Oct", "2025-10", "2025-11"), ("Nov", "2025-11", "2025-12"), ("Dec+", "2025-12", "9999")):
            rows = [(k[0], abs(lam["blend"][k][1] - played[(k[0], k[1])][MARKET_STAT[mk]]) -
                     abs(lam["prior"][k][1] - played[(k[0], k[1])][MARKET_STAT[mk]]),
                     abs(lam["prior"][k][1] - played[(k[0], k[1])][MARKET_STAT[mk]]))
                    for k in keys if k[2] == mk and lo <= lam["prior"][k][0] < hi]
            if not rows:
                continue
            by_game: Dict[str, List[float]] = defaultdict(list)
            for gid, d, _ in rows:
                by_game[gid].append(d)
            gids = sorted(by_game)
            rng = random.Random(11)
            boots = []
            for _ in range(n_boot):
                s = n = 0
                for gid in (rng.choice(gids) for _ in gids):
                    s += sum(by_game[gid]); n += len(by_game[gid])
                boots.append(s / n)
            boots.sort()
            mean_d = sum(r[1] for r in rows) / len(rows)
            report[f"{mk}.{period}"] = {"n": len(rows), "games": len(gids), "mae_prior": sum(r[2] for r in rows) / len(rows),
                                        "dmae_blend_minus_prior": mean_d,
                                        "ci95": [boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]]}
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True, help="a props-harness out dir holding records.pkl + cache/")
    ap.add_argument("--out", type=Path, default=Path("C:/tmp/nhllines/props_ab"))
    ap.add_argument("--tmp", type=Path, default=Path("C:/tmp/nhllines"))
    ap.add_argument("--start", default="2025-10-08")
    ap.add_argument("--end", default="2026-01-31")
    ap.add_argument("--date-step", type=int, default=2)
    ap.add_argument("--n-sims", type=int, default=200)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--score-only", action="store_true")
    args = ap.parse_args()
    import subprocess
    prim = Path(subprocess.run(["git", "-C", str(REPO), "worktree", "list", "--porcelain"], capture_output=True,
                               text=True).stdout.splitlines()[0].split(" ", 1)[1].strip())
    src = prim / "data" / "nhl_source"
    args.out.mkdir(parents=True, exist_ok=True)
    side = args.out / "side.pkl"
    if not side.exists():
        t0 = time.time()
        data = {"prior_recs": prior_records(args.tmp), "current": current_game_counts(src)}
        with side.open("wb") as fh:
            pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"side data: {len(data['prior_recs'])} 2024-25 records, {len(data['current'])} 2025-26 games ({time.time() - t0:.0f}s)", flush=True)
    with (args.base / "records.pkl").open("rb") as fh:
        actuals = pickle.load(fh)["actuals"]
    dates = sorted({a["date"] for a in actuals.values() if a["season"] == 20252026 and a["gtype"] == 2
                    and args.start <= a["date"] <= args.end})[::max(1, args.date_step)]
    outs = {arm: args.out / arm for arm in ("prior", "blend")}
    if not args.score_only:
        for arm, out in outs.items():
            out.mkdir(parents=True, exist_ok=True)
            if not (out / "records.pkl").exists():
                shutil.copy(args.base / "records.pkl", out / "records.pkl")
            if not (out / "cache").exists():
                shutil.copytree(args.base / "cache", out / "cache")
            jobs = [d for d in dates if not (out / "sim" / f"regular_{d}.json").exists()]
            print(f"arm {arm}: {len(dates)} dates, {len(jobs)} to run", flush=True)
            t1 = time.time()
            with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                                     initargs=(str(src), str(out), False, arm, str(side))) as ex:
                futs = {ex.submit(_run, d, args.n_sims): d for d in jobs}
                for i, f in enumerate(as_completed(futs), 1):
                    try:
                        r = f.result()
                        print(f"  [{arm} {i}/{len(jobs)}] {r['date']} games={r['games']} {r['t']}s ({time.time() - t1:.0f}s)", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [{arm} {i}/{len(jobs)}] FAILED {futs[f]}: {exc!r}", flush=True)
    rep = score(outs, actuals)
    (args.out / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for k, v in rep.items():
        lo, hi = v["ci95"]
        print(f"{k:<14} n={v['n']:>6} games={v['games']:>4} MAE prior {v['mae_prior']:.4f}  blend-prior {v['dmae_blend_minus_prior']:+.4f} [{lo:+.4f}, {hi:+.4f}]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
