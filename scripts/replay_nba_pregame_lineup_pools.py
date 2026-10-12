"""As-of replay: do NBA PREGAME smart-sim calls get lineup pools from rotation history? (lane `nba-pregame-lineup-pools`)

The production pregame path (`export_props_predictions_local` -> smart sim, roster mode "pregame") is rerun as of each
REGULAR-season date on a SCRATCH copy of the NBA data root. The scratch recipe is P3's
(`resim_nba_availability.prepare_scratch` + `record_nba_engine_inputs_asof._add_473_inputs`) with one difference:
P3's recipe deletes `rotation_stints_history` on every date (REMOVE_ALWAYS), so it can never show a pool. This puts
it back, truncated to rows strictly before the slate date, from the READ-ONLY live copy.

Pregame, enforced rather than assumed: every ESPN summary the sim reads has its `boxscore` stripped, at both call
sites (the bpss name map and the orchestrator's connected-game reader). That is what ESPN returns before tip.

Per side it records the pool path's own diag (`_rotation_sim_minutes_from_history_local`, the `rotation_minutes`
block), the name-map size, and the engine's `home_lineups`/`away_lineups`. It also records, without using it, a
COUNTERFACTUAL call of the same function with the slate date D instead of production's D-1 (pregame as-of,
orchestrator/smart_sim.py:1207-1213, :1507): the window keeps `date < cutoff`, so production drops D-1's games.

Run in WSL with the fleet venv at nice 19, never against the production data root:

  nice -n 19 ~/.venvs/syndicate/bin/python scripts/replay_nba_pregame_lineup_pools.py \
      --code /mnt/c/tmp/syndicate-sessions/nba-pregame-lineup-pools --pristine ~/nba_resim/pristine \
      --scratch ~/lp_replay/scratch --asof /mnt/c/tmp/nba_bt/out/asof --out /mnt/c/tmp/lp_replay/out.jsonl \
      --dates 2025-11-12,2026-01-14
"""
from __future__ import annotations

import argparse
import copy
import json
import pickle
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict


def _strip_box(summary: Any) -> Any:
    if isinstance(summary, dict) and "boxscore" in summary:
        summary = dict(summary)
        summary.pop("boxscore", None)
    return summary


def _add_rotation_history(live_processed: Path, dst: Path, d: str) -> int:
    import pandas as pd

    src = live_processed / "rotation_stints_history.parquet"
    df = pd.read_parquet(src)
    days = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = df[days < d]
    out.to_parquet(dst / "rotation_stints_history.parquet", index=False)
    return int(len(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--out", required=True, help="JSONL, one row per (date, team side)")
    ap.add_argument("--dates", required=True, help="comma-separated YYYY-MM-DD")
    ap.add_argument("--n-sims", type=int, default=2)
    ap.add_argument("--corpus-dir", default=None,
                    help="also write each game's first engine call in record_basketball_engine_corpus.py's format, "
                         "so scripts/basketball_engine_input_checklist.py --corpus can read it")
    ap.add_argument("--live-processed", default="~/syndicate-prod/data/nba_source/data/processed",
                    help="READ-ONLY source of rotation_stints_history and #473's inputs")
    args = ap.parse_args(argv)

    code, pristine, asof = Path(args.code), Path(args.pristine).expanduser(), Path(args.asof)
    scratch = Path(args.scratch).expanduser()
    live_processed = Path(args.live_processed).expanduser()
    prod = Path("~/syndicate-prod/data").expanduser().resolve()
    if str(scratch.resolve()).startswith(str(prod)):
        raise SystemExit("REFUSED: scratch is inside the production data root")
    sys.path[:0] = [str(code / "scripts"), str(code)]
    os.environ.update({
        "SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_NBA_SOURCE_ROOT": str(scratch / "nba_source"),
        "NBA_BETTING_DATA_ROOT": str(scratch / "nba_source" / "data"), "SYNDICATE_REFRESH_STATE_BACKEND": "file",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1",
    })
    for k in [k for k in os.environ if any(m in k.upper() for m in ("KEYVALUE", "REDIS", "VALKEY", "ODDS_API", "ODDSAPI"))]:
        os.environ.pop(k, None)

    import pandas as pd

    import resim_nba_availability as rs
    from record_nba_engine_inputs_asof import _add_473_inputs
    from syndicate.features.basketball_engine.orchestrator import boxscores as ob
    from syndicate.features.basketball_engine.orchestrator import connected_game as ocg
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    bpss._resolve_smart_sim_roster_mode_local = lambda **_k: "pregame"

    orig_bpss_summary = bpss._espn_summary_local
    bpss._espn_summary_local = lambda **kw: _strip_box(orig_bpss_summary(**kw))
    orig_ob_summary = ob._espn_summary
    ob._espn_summary = lambda *a, **kw: _strip_box(orig_ob_summary(*a, **kw))
    ocg._espn_summary = ob._espn_summary

    cur: Dict[str, Any] = {"date": "", "rows": []}
    orig_map = bpss._espn_name_to_id_map_for_game_local

    def map_spy(**kw):
        out = orig_map(**kw)
        cur["last_map_n"] = len(out)
        return out

    bpss._espn_name_to_id_map_for_game_local = map_spy

    orig_hist = bpss._rotation_sim_minutes_from_history_local

    def hist_spy(**kw):
        cur["last_map_n"] = None
        res = orig_hist(**kw)
        diag = dict(res[3] or {})
        prod_map_n = cur.get("last_map_n")
        cf: Dict[str, Any] = {}
        try:
            d_slate = cur["date"]
            if str(kw.get("date_str")) != d_slate:
                r2 = orig_hist(**{**kw, "date_str": d_slate})
                d2 = r2[3] or {}
                cf = {"cf_applied": bool(d2.get("applied")), "cf_reason": d2.get("reason"),
                      "cf_pool_n": d2.get("lineup_pool_n"), "cf_history_rows": d2.get("history_rows")}
        except Exception as exc:  # noqa: BLE001
            cf = {"cf_error": f"{type(exc).__name__}: {exc}"[:200]}
        cur["rows"].append({
            "date": cur["date"], "rot_date": str(kw.get("date_str")), "team": str(kw.get("team_tri")).upper(),
            "home": str(kw.get("home_tri")).upper(), "away": str(kw.get("away_tri")).upper(),
            "applied": bool(diag.get("applied")), "reason": diag.get("reason"), "slate_phase": diag.get("slate_phase"),
            "phase_filtered_rows": diag.get("phase_filtered_rows"), "history_rows": diag.get("history_rows"),
            "name_map_n": prod_map_n, "mapped_id_n": diag.get("mapped_id_n"),
            "mapped_minutes_frac": diag.get("mapped_minutes_frac"), "lineup_pool_n": diag.get("lineup_pool_n"),
            **cf,
        })
        return res

    bpss._rotation_sim_minutes_from_history_local = hist_spy

    engine_games: Dict[tuple, Dict[str, int]] = {}
    orig_engine = bpss._simulate_pbp_game_boxscore_local

    def engine_spy(**kw):
        try:
            h = str(kw["home_players"]["team"].iloc[0]).upper()
            a = str(kw["away_players"]["team"].iloc[0]).upper()
            key = (cur["date"], h, a)
            if key not in engine_games:
                engine_games[key] = {"home_lineups": len(kw.get("home_lineups") or []),
                                     "away_lineups": len(kw.get("away_lineups") or [])}
                if args.corpus_dir:
                    body = {k: v for k, v in kw.items() if k not in ("rng", "league_code")}
                    corpus = Path(args.corpus_dir)
                    corpus.mkdir(parents=True, exist_ok=True)
                    with (corpus / f"nba_{cur['date']}_{h}_{a}.pkl").open("wb") as fh:
                        pickle.dump({"league": "nba", "date": cur["date"], "kwargs": copy.deepcopy(body),
                                     "rng_states": []}, fh, protocol=4)
        except Exception:  # noqa: BLE001
            pass
        return orig_engine(**kw)

    bpss._simulate_pbp_game_boxscore_local = engine_spy

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for d in [x.strip() for x in args.dates.split(",") if x.strip()]:
        props_csv = asof / "props_odds_hist" / f"{d}.csv"
        if not props_csv.exists() or props_csv.stat().st_size <= 1000:
            print(f"SKIP {d} no as-of props snapshot (no OddsAPI fetch from here)", flush=True)
            continue
        rs.prepare_scratch(pristine, scratch, d, asof, props_csv)
        processed = scratch / "nba_source" / "data" / "processed"
        _add_473_inputs(live_processed, processed, d)
        n_hist = _add_rotation_history(live_processed, processed, d)
        # Production's NBA data root holds pbp_espn_history only as .parquet, which nothing reads; mirror that.
        assert not (processed / "pbp_espn_history.csv").exists()
        cur["date"], cur["rows"] = d, []
        src_root = scratch / "nba_source"
        try:
            export_props_predictions_local(
                source_root=src_root, date_str=d, out_path=processed / f"props_predictions_{d}.csv",
                calib_window=7, calibrate_player=True, player_calib_window=30, player_min_pairs=6, player_shrink_k=8,
                use_smart_sim=True, smart_sim_n_sims=args.n_sims, smart_sim_pbp=True, smart_sim_workers=1,
                smart_sim_overwrite=True, log_file=out_path.parent / f"replay_{d}.log")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {d} {exc!r}"[:300], flush=True)
        with out_path.open("a", encoding="utf-8") as fh:
            for row in cur["rows"]:
                eg = engine_games.get((d, row["home"], row["away"]), {})
                side = "home_lineups" if row["team"] == row["home"] else "away_lineups"
                row["engine_lineups"] = eg.get(side)
                row["history_rows_asof"] = n_hist
                fh.write(json.dumps(row) + "\n")
        n_app = sum(1 for r in cur["rows"] if r["applied"])
        print(f"DATE {d} sides={len(cur['rows'])} applied={n_app} engine_games={sum(1 for k in engine_games if k[0] == d)}",
              flush=True)
    shutil.rmtree(scratch / "nba_source", ignore_errors=True)
    print("REPLAY_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
