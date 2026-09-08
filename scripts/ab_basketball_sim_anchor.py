"""A/B the basketball smart-sim's PRE-SIMULATION market anchoring: anchor ON vs OFF.

Pricing plane v1, step 2 / P3. The NBA/WNBA quarter model blends its team means
toward the market BEFORE sampling (total 0.7*market + 0.3*model, margin
0.95*(-spread) + 0.05*model). With that on, a spread/total "edge" measured
against the same market is noise by construction. This harness runs the SAME
slate twice with IDENTICAL seeds -- `SYNDICATE_BASKETBALL_SIM_MARKET_ANCHOR=on`
then `=off` -- through the wrapper's real sim entry
(`_smart_sim_run_date_local`, sequential, in-process) so the difference is the
mechanism and nothing else.

It is LOCAL ONLY. No network, no production reads, no Render. It refuses to run
without a data root on disk and names the files it needs. Outputs are written
under their own prefix (`ab_anchor_<arm>_<date>_<HOME>_<AWAY>.json`) so the
production-shaped `smart_sim_*` artifacts in the same directory are never
touched, and are deleted afterwards unless `--keep`.

Usage:
  py -3 scripts/ab_basketball_sim_anchor.py --date 2026-05-18 --league wnba --data-root C:/path/to/wnba_source
  py -3 scripts/ab_basketball_sim_anchor.py --date 2026-05-18 --league nba --n-sims 100 --seed 7 --json out.json

Data root resolution (first hit wins): `--data-root`, `SYNDICATE_ARTIFACT_ROOT_<LEAGUE>`,
`<SYNDICATE_DATA_ROOT>/<league>_source`, `<repo>/data/<league>_source`. The root
must contain `data/processed/`. Remember the repo's own rule: `data/**` in git is
a lossy mirror -- say which root you ran against when you quote a number.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FLAG = "SYNDICATE_BASKETBALL_SIM_MARKET_ANCHOR"
ARMS = ("on", "off")
REQUIRED_FILES = ("predictions_{date}.csv", "props_predictions_{date}.csv")
MARKET_FILES = ("game_odds_{date}.csv",)


def _resolve_data_root(explicit: str | None, league: str) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_root = os.environ.get(f"SYNDICATE_ARTIFACT_ROOT_{league.upper()}")
    if env_root:
        return Path(env_root).expanduser().resolve()
    data_root = os.environ.get("SYNDICATE_DATA_ROOT")
    if data_root:
        return (Path(data_root).expanduser() / f"{league}_source").resolve()
    return (REPO_ROOT / "data" / f"{league}_source").resolve()


def _preflight(*, data_root: Path | None, date: str) -> list[str]:
    """Return the list of problems; empty means we can run."""
    problems: list[str] = []
    if data_root is None:
        problems.append("no data root: pass --data-root or set SYNDICATE_ARTIFACT_ROOT_<LEAGUE> / SYNDICATE_DATA_ROOT")
        return problems
    processed = data_root / "data" / "processed"
    if not processed.is_dir():
        problems.append(f"missing directory: {processed}")
    for template in REQUIRED_FILES:
        path = processed / template.format(date=date)
        if not path.exists():
            problems.append(f"missing required file: {path}")
    return problems


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        return out if out == out else None
    except Exception:
        return None


def _fmt(value: float | None, width: int = 7, digits: int = 2) -> str:
    if value is None:
        return " " * (width - 1) + "-"
    return f"{value:{width}.{digits}f}"


def _run_arm(*, arm: str, processed_root: Path, raw_root: Path, date: str, league: str, n_sims: int, seed: int, max_games: int | None) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    import numpy as np

    from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local

    prefix = f"ab_anchor_{arm}"
    os.environ[FLAG] = arm
    # The quarter sim draws from the GLOBAL numpy RNG (it takes no rng); the
    # player sim seeds from cfg.seed. Seed both so the two arms differ only in
    # the anchor.
    np.random.seed(int(seed))
    random.seed(int(seed))
    started = time.time()
    summary = _smart_sim_run_date_local(
        processed_root=processed_root,
        raw_root=raw_root,
        date_str=date,
        n_sims=int(n_sims),
        seed=int(seed),
        max_games=max_games,
        overwrite=True,
        pbp=True,
        workers=1,
        roster_mode="historical",
        out_prefix=prefix,
        league_code=league,
    )
    summary = dict(summary or {})
    summary["elapsed_s"] = round(time.time() - started, 1)
    games: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(processed_root.glob(f"{prefix}_{date}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        home = str(payload.get("home") or "").upper()
        away = str(payload.get("away") or "").upper()
        anchor = payload.get("market_anchor") if isinstance(payload.get("market_anchor"), dict) else {}
        score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
        games[(home, away)] = {
            "path": path,
            "state": anchor.get("state"),
            "total_w": _num(anchor.get("total_w")),
            "margin_w": _num(anchor.get("margin_w")),
            "market_total": _num(anchor.get("market_total")),
            "market_spread": _num(anchor.get("market_spread")),
            "model_total_raw": _num(anchor.get("model_total_raw")),
            "model_margin_raw": _num(anchor.get("model_margin_raw")),
            "anchored_total": _num(anchor.get("anchored_total")),
            "anchored_margin": _num(anchor.get("anchored_margin")),
            "sim_total_mean": _num(score.get("total_mean")),
            "sim_margin_mean": _num(score.get("margin_mean")),
            "p_home_win": _num(score.get("p_home_win")),
        }
    return summary, games


def _cleanup(processed_root: Path, date: str) -> int:
    removed = 0
    for arm in ARMS:
        for path in list(processed_root.glob(f"ab_anchor_{arm}_{date}_*.json")) + [processed_root / f"ab_anchor_{arm}_failures_{date}.csv"]:
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
            except Exception:
                pass
    return removed


def _mean_abs(values: list[float]) -> float | None:
    vals = [abs(v) for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def run_ab(*, data_root: Path, date: str, league: str, n_sims: int, seed: int, max_games: int | None, keep: bool) -> dict[str, Any]:
    processed_root = data_root / "data" / "processed"
    raw_root = data_root / "data" / "raw"
    market_present = any((processed_root / t.format(date=date)).exists() for t in MARKET_FILES)
    previous_flag = os.environ.get(FLAG)
    results: dict[str, tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]] = {}
    try:
        for arm in ARMS:
            results[arm] = _run_arm(arm=arm, processed_root=processed_root, raw_root=raw_root, date=date, league=league, n_sims=n_sims, seed=seed, max_games=max_games)
    finally:
        if previous_flag is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previous_flag
    on_summary, on_games = results["on"]
    off_summary, off_games = results["off"]
    keys = sorted(set(on_games) | set(off_games))
    rows: list[dict[str, Any]] = []
    for key in keys:
        on = on_games.get(key) or {}
        off = off_games.get(key) or {}
        rows.append(
            {
                "home": key[0],
                "away": key[1],
                "market_total": on.get("market_total", off.get("market_total")),
                "market_spread": on.get("market_spread", off.get("market_spread")),
                "model_total_raw": off.get("model_total_raw", on.get("model_total_raw")),
                "model_margin_raw": off.get("model_margin_raw", on.get("model_margin_raw")),
                "anchored_total": on.get("anchored_total"),
                "anchored_margin": on.get("anchored_margin"),
                "sim_total_on": on.get("sim_total_mean"),
                "sim_total_off": off.get("sim_total_mean"),
                "sim_margin_on": on.get("sim_margin_mean"),
                "sim_margin_off": off.get("sim_margin_mean"),
                "p_home_win_on": on.get("p_home_win"),
                "p_home_win_off": off.get("p_home_win"),
                "state_on": on.get("state"),
                "state_off": off.get("state"),
            }
        )
    if not keep:
        _cleanup(processed_root, date)
    deltas = {
        "games": len(rows),
        "games_with_market": sum(1 for r in rows if r["market_total"] is not None or r["market_spread"] is not None),
        "mean_abs_delta_sim_total": _mean_abs([(r["sim_total_on"] - r["sim_total_off"]) for r in rows if r["sim_total_on"] is not None and r["sim_total_off"] is not None]),
        "mean_abs_delta_sim_margin": _mean_abs([(r["sim_margin_on"] - r["sim_margin_off"]) for r in rows if r["sim_margin_on"] is not None and r["sim_margin_off"] is not None]),
        "mean_abs_delta_p_home_win": _mean_abs([(r["p_home_win_on"] - r["p_home_win_off"]) for r in rows if r["p_home_win_on"] is not None and r["p_home_win_off"] is not None]),
        "mean_abs_anchor_shift_total": _mean_abs([(r["anchored_total"] - r["model_total_raw"]) for r in rows if r["anchored_total"] is not None and r["model_total_raw"] is not None]),
        "mean_abs_anchor_shift_margin": _mean_abs([(r["anchored_margin"] - r["model_margin_raw"]) for r in rows if r["anchored_margin"] is not None and r["model_margin_raw"] is not None]),
    }
    return {
        "date": date,
        "league": league,
        "data_root": str(data_root),
        "n_sims": int(n_sims),
        "seed": int(seed),
        "market_file_present": bool(market_present),
        "runs": {"on": on_summary, "off": off_summary},
        "rows": rows,
        "summary": deltas,
    }


def _print_report(report: dict[str, Any]) -> None:
    rows = report["rows"]
    print(f"A/B pre-sim market anchor  league={report['league']} date={report['date']} n_sims={report['n_sims']} seed={report['seed']}")
    print(f"data_root={report['data_root']}")
    for arm in ARMS:
        run = report["runs"][arm]
        print(f"  arm={arm:<3} wrote={run.get('wrote')} failures={run.get('failures')} elapsed={run.get('elapsed_s')}s reason={run.get('reason') or '-'}")
    if not report["market_file_present"]:
        print("  NOTE: no game_odds file for this date -- without market lines the anchor has nothing to blend toward and both arms are identical BY CONSTRUCTION.")
    print()
    header = f"{'game':<10} {'mkt_tot':>7} {'mkt_spr':>7} | {'raw_tot':>7} {'raw_mrg':>7} | {'anc_tot':>7} {'anc_mrg':>7} | {'sim_tot_on':>10} {'sim_tot_off':>11} {'sim_mrg_on':>10} {'sim_mrg_off':>11} | {'pHW_on':>6} {'pHW_off':>7}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['away']}@{r['home']:<6} {_fmt(r['market_total'])} {_fmt(r['market_spread'])} | "
            f"{_fmt(r['model_total_raw'])} {_fmt(r['model_margin_raw'])} | "
            f"{_fmt(r['anchored_total'])} {_fmt(r['anchored_margin'])} | "
            f"{_fmt(r['sim_total_on'], 10)} {_fmt(r['sim_total_off'], 11)} {_fmt(r['sim_margin_on'], 10)} {_fmt(r['sim_margin_off'], 11)} | "
            f"{_fmt(r['p_home_win_on'], 6, 3)} {_fmt(r['p_home_win_off'], 7, 3)}"
        )
    print()
    s = report["summary"]
    print(f"games={s['games']} with_market={s['games_with_market']}")
    print(f"mean |anchor shift| pre-sim: total={_fmt(s['mean_abs_anchor_shift_total'])} margin={_fmt(s['mean_abs_anchor_shift_margin'])}")
    print(f"mean |on - off| post-sim:   total={_fmt(s['mean_abs_delta_sim_total'])} margin={_fmt(s['mean_abs_delta_sim_margin'])} p_home_win={_fmt(s['mean_abs_delta_p_home_win'], 7, 3)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, help="slate date YYYY-MM-DD")
    parser.add_argument("--league", required=True, choices=("nba", "wnba"))
    parser.add_argument("--data-root", default=None, help="<league>_source root containing data/processed (local disk only)")
    parser.add_argument("--n-sims", type=int, default=100, help="player-sim draws per game (live-odds-worker runs 100, refresh-worker 500)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--json", default=None, help="write the full report here")
    parser.add_argument("--keep", action="store_true", help="keep the ab_anchor_* outputs instead of deleting them")
    args = parser.parse_args(argv)

    data_root = _resolve_data_root(args.data_root, args.league)
    problems = _preflight(data_root=data_root, date=args.date)
    if problems:
        print("REFUSING TO RUN -- this harness is local-only and needs these on disk:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "  required: " + ", ".join(t.format(date=args.date) for t in REQUIRED_FILES)
            + "; for a non-trivial A/B also: " + ", ".join(t.format(date=args.date) for t in MARKET_FILES),
            file=sys.stderr,
        )
        print("  refresh a mirror first, e.g. scripts/refresh_<league>_source_mirror.ps1 -Date <date>", file=sys.stderr)
        return 2

    report = run_ab(data_root=data_root, date=args.date, league=args.league, n_sims=int(args.n_sims), seed=int(args.seed), max_games=args.max_games, keep=bool(args.keep))
    _print_report(report)
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = dict(report)
        serialisable["rows"] = [dict(r) for r in report["rows"]]
        out_path.write_text(json.dumps(serialisable, indent=2, default=str), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
