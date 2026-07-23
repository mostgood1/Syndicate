from __future__ import annotations

import contextlib
import importlib
import os
import sys
import threading
import traceback
from pathlib import Path

from . import basketball_props_calibration
from . import basketball_props_features
from . import basketball_props_onnx
from . import basketball_props_smart_sim
from .source_roots import repo_root_from


_TEAM_ALIASES = {
    "la lakers": "Los Angeles Lakers",
    "l.a. lakers": "Los Angeles Lakers",
    "lakers": "Los Angeles Lakers",
    "warriors": "Golden State Warriors",
    "clippers": "Los Angeles Clippers",
    "la clippers": "Los Angeles Clippers",
    "l.a. clippers": "Los Angeles Clippers",
    "boston": "Boston Celtics",
    "celtics": "Boston Celtics",
    "atl": "Atlanta Hawks",
    "bos": "Boston Celtics",
    "bkn": "Brooklyn Nets",
    "cha": "Charlotte Hornets",
    "chi": "Chicago Bulls",
    "cle": "Cleveland Cavaliers",
    "dal": "Dallas Mavericks",
    "den": "Denver Nuggets",
    "det": "Detroit Pistons",
    "gsw": "Golden State Warriors",
    "hou": "Houston Rockets",
    "ind": "Indiana Pacers",
    "lac": "Los Angeles Clippers",
    "lal": "Los Angeles Lakers",
    "mem": "Memphis Grizzlies",
    "mia": "Miami Heat",
    "mil": "Milwaukee Bucks",
    "min": "Minnesota Timberwolves",
    "nop": "New Orleans Pelicans",
    "no": "New Orleans Pelicans",
    "nyk": "New York Knicks",
    "okc": "Oklahoma City Thunder",
    "orl": "Orlando Magic",
    "phi": "Philadelphia 76ers",
    "phx": "Phoenix Suns",
    "por": "Portland Trail Blazers",
    "sac": "Sacramento Kings",
    "sas": "San Antonio Spurs",
    "sa": "San Antonio Spurs",
    "tor": "Toronto Raptors",
    "uta": "Utah Jazz",
    "utah": "Utah Jazz",
    "was": "Washington Wizards",
}

_CANONICAL_BY_LOWER = {value.lower(): value for value in _TEAM_ALIASES.values()}

_NAME_TO_TRI = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

_PRED_STATS = ("pts", "reb", "ast", "threes", "pra", "stl", "blk", "tov")


def _normalize_team(name: object) -> str:
    raw = str(name or "").strip()
    key = raw.lower()
    if key in _TEAM_ALIASES:
        return _TEAM_ALIASES[key]
    if key in _CANONICAL_BY_LOWER:
        return _CANONICAL_BY_LOWER[key]
    return raw


def _to_tricode(name: object) -> str:
    if not name:
        return ""
    normalized = _normalize_team(name)
    tricode = _NAME_TO_TRI.get(normalized)
    if tricode:
        return tricode
    value = str(name).strip().upper()
    if len(value) == 3:
        return value
    return value


def _models_dir_for_source_root(source_root: Path) -> Path:
    """Resolve the props model artifacts directory for a source root.

    On Render, source_root is a persistent *data* disk
    (e.g. /opt/render/project/data/wnba_source) that has no models/
    directory -- the trained model artifacts only ship inside this repo's
    vendored code checkout (vendor/<pkg>_repo/models). Blindly using
    source_root/models made PureONNXPredictorLocal raise FileNotFoundError
    on props_feature_columns.joblib every run, silently downgrading all
    props predictions to the priors + rolling-stat fallback. Same
    ephemeral-vs-persistent path class as _vendor_code_root in
    refresh_wnba_oddsapi_props.py.
    """
    local = source_root / "models"
    try:
        gate = local / "props_feature_columns.joblib"
        if gate.is_file() and gate.stat().st_size > 0:
            return local
    except OSError:
        pass
    name = str(source_root).lower()
    package_name = "wnba_betting" if "wnba" in name else "nba_betting"
    override = str(os.environ.get(f"SYNDICATE_VENDOR_ROOT_{package_name.upper()}") or "").strip()
    if override:
        return Path(override).expanduser().resolve() / "models"
    return repo_root_from(__file__) / "vendor" / f"{package_name}_repo" / "models"


def _export_props_predictions_without_smart_sim_local(*, source_root: Path, date_str: str, out_path: Path) -> tuple[int, Path]:
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    import pandas as pd

    feats = basketball_props_features.build_features_for_date_local(
        processed_root=source_root / "data" / "processed",
        date=date_str,
    )
    if feats is None or getattr(feats, "empty", False):
        raise RuntimeError(f"No feature rows built for {date_str}")

    preds = basketball_props_onnx.predict_props_pure_onnx_local(
        features_df=feats,
        models_dir=_models_dir_for_source_root(source_root),
        processed_root=source_root / "data" / "processed",
    )
    if preds is None or getattr(preds, "empty", False):
        raise RuntimeError(f"Pure ONNX prediction produced no rows for {date_str}")

    for stat in _PRED_STATS:
        pred_col = f"pred_{stat}"
        mean_col = f"mean_{stat}"
        if pred_col in preds.columns and mean_col not in preds.columns:
            preds[mean_col] = pd.to_numeric(preds[pred_col], errors="coerce")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    preds.to_csv(out_path, index=False)
    return int(len(preds.index)), out_path


def finalize_props_predictions_local(
    *,
    source_root: Path,
    date_str: str,
    out_path: Path,
    calib_window: int,
    calibrate: bool,
    calibrate_player: bool,
    player_calib_window: int,
    player_min_pairs: int,
    player_shrink_k: int,
) -> tuple[int, Path]:
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    previous_cwd = Path.cwd()
    try:
        os.chdir(source_root)

        import pandas as pd

        processed_root = source_root / "data" / "processed"
        preds = pd.read_csv(out_path)

        if calibrate:
            try:
                biases = basketball_props_calibration.compute_biases(
                    processed_root=processed_root,
                    anchor_date=date_str,
                    window_days=int(calib_window),
                )
                preds = basketball_props_calibration.apply_biases(preds=preds, biases=biases)
                basketball_props_calibration.save_calibration(
                    processed_root=processed_root,
                    biases=biases,
                    anchor_date=date_str,
                    window_days=int(calib_window),
                )
            except Exception:
                pass

        if calibrate_player:
            try:
                player_biases = basketball_props_calibration.compute_player_biases(
                    processed_root=processed_root,
                    anchor_date=date_str,
                    window_days=int(player_calib_window),
                    min_pairs_per_player=int(player_min_pairs),
                    shrink_k=float(player_shrink_k),
                    shrink_k_by_stat=None,
                    min_pairs_by_stat=None,
                )
                if player_biases is not None and not player_biases.empty:
                    preds = basketball_props_calibration.apply_player_biases(preds=preds, player_biases=player_biases)
                    basketball_props_calibration.save_player_calibration(
                        processed_root=processed_root,
                        player_biases=player_biases,
                        anchor_date=date_str,
                        window_days=int(player_calib_window),
                    )

                meta = {
                    "date": date_str,
                    "window_days": int(player_calib_window),
                    "global": {
                        "K": float(player_shrink_k),
                        "min_pairs": int(player_min_pairs),
                    },
                    "by_stat": {},
                }
                out_meta = processed_root / f"props_player_calibration_used_{date_str}.json"
                out_meta.write_text(__import__("json").dumps(meta, indent=2), encoding="utf-8")
            except Exception:
                pass

        try:
            ls_path_final = processed_root / f"league_status_{date_str}.csv"
            if ls_path_final.exists() and ("player_id" in preds.columns):
                lsdf = pd.read_csv(ls_path_final)
                if isinstance(lsdf, pd.DataFrame) and (not lsdf.empty) and {"player_id", "team"}.issubset(set(lsdf.columns)):
                    tmp_ls = lsdf[["player_id", "team"]].copy()
                    tmp_ls["player_id"] = pd.to_numeric(tmp_ls["player_id"], errors="coerce")
                    tmp_ls = tmp_ls.dropna(subset=["player_id"]).copy()
                    tmp_ls["_pid"] = tmp_ls["player_id"].astype(int)
                    tmp_ls["team"] = tmp_ls["team"].astype(str).str.upper().str.strip()
                    pid_to_team = dict(zip(tmp_ls["_pid"].tolist(), tmp_ls["team"].tolist()))

                    pids = pd.to_numeric(preds["player_id"], errors="coerce")
                    pid_int = pids.where(pids.notna(), pd.NA).astype("Int64")
                    if "team" not in preds.columns:
                        preds["team"] = [
                            pid_to_team.get(int(value)) if (value is not None and not pd.isna(value)) else ""
                            for value in pid_int.tolist()
                        ]
                    else:
                        cur_team_s = preds["team"].astype(str).str.upper().str.strip()
                        new_team: list[object] = []
                        for pid_val, existing in zip(pid_int.tolist(), cur_team_s.tolist()):
                            if pid_val is not None and (not pd.isna(pid_val)):
                                mapped = pid_to_team.get(int(pid_val))
                                if mapped:
                                    new_team.append(mapped)
                                    continue
                            new_team.append(existing)
                        preds["team"] = new_team

                    go_path = processed_root / f"game_odds_{date_str}.csv"
                    if go_path.exists() and ("team" in preds.columns):
                        go = pd.read_csv(go_path)
                        if isinstance(go, pd.DataFrame) and (not go.empty):
                            home_col = "home_team" if "home_team" in go.columns else None
                            away_col = "visitor_team" if "visitor_team" in go.columns else ("away_team" if "away_team" in go.columns else None)
                            if home_col and away_col:
                                opp_map: dict[str, str] = {}
                                home_map: dict[str, bool] = {}
                                for _, row in go.iterrows():
                                    home_team = _to_tricode(row.get(home_col) or "")
                                    away_team = _to_tricode(row.get(away_col) or "")
                                    if home_team and away_team:
                                        opp_map[home_team] = away_team
                                        home_map[home_team] = True
                                        opp_map[away_team] = home_team
                                        home_map[away_team] = False
                                if opp_map:
                                    team_values = preds["team"].astype(str).str.upper().str.strip()
                                    if "opponent" in preds.columns:
                                        preds["opponent"] = [
                                            opp_map.get(team_value, preds.loc[index, "opponent"])
                                            for index, team_value in enumerate(team_values.tolist())
                                        ]
                                    if "home" in preds.columns:
                                        preds["home"] = [
                                            home_map.get(team_value, preds.loc[index, "home"])
                                            for index, team_value in enumerate(team_values.tolist())
                                        ]
        except Exception:
            pass

        try:
            preds = preds.copy()
            for col in (
                "pred_pts",
                "pred_reb",
                "pred_ast",
                "pred_threes",
                "pred_stl",
                "pred_blk",
                "pred_tov",
            ):
                if col in preds.columns:
                    preds[col] = pd.to_numeric(preds[col], errors="coerce").clip(lower=0.0)

            if all(col in preds.columns for col in ("pred_pts", "pred_reb", "pred_ast")):
                preds["pred_pra"] = (
                    pd.to_numeric(preds["pred_pts"], errors="coerce").fillna(0.0)
                    + pd.to_numeric(preds["pred_reb"], errors="coerce").fillna(0.0)
                    + pd.to_numeric(preds["pred_ast"], errors="coerce").fillna(0.0)
                )
                preds["pred_pra"] = pd.to_numeric(preds["pred_pra"], errors="coerce").clip(lower=0.0)

            for col in (
                "sd_pts",
                "sd_reb",
                "sd_ast",
                "sd_threes",
                "sd_pra",
                "sd_stl",
                "sd_blk",
                "sd_tov",
            ):
                if col in preds.columns:
                    preds[col] = pd.to_numeric(preds[col], errors="coerce").clip(lower=0.0)

            if all(col in preds.columns for col in ("asof_date", "team", "player_id")):
                preds["asof_date"] = preds["asof_date"].where(preds["asof_date"].notna(), date_str)
                preds["team"] = preds["team"].astype(str).str.upper().str.strip()
                preds["player_id"] = pd.to_numeric(preds["player_id"], errors="coerce")
                preds = preds[preds["player_id"].notna()].copy()
                score_cols = [
                    col for col in (
                        "sd_pts",
                        "sd_reb",
                        "sd_ast",
                        "sd_pra",
                        "pred_pts",
                        "pred_reb",
                        "pred_ast",
                        "pred_pra",
                    ) if col in preds.columns
                ]
                preds["_row_score"] = preds[score_cols].notna().sum(axis=1) if score_cols else 0
                preds = preds.sort_values(["asof_date", "team", "player_id", "_row_score"]).drop_duplicates(
                    subset=["asof_date", "team", "player_id"],
                    keep="last",
                )
                preds = preds.drop(columns=["_row_score"], errors="ignore")
        except Exception:
            pass

        if preds is None or preds.empty:
            raise RuntimeError(f"predict-props produced no rows for {date_str}")

        preds.to_csv(out_path, index=False)
        return int(len(preds.index)), out_path
    finally:
        try:
            os.chdir(previous_cwd)
        except Exception:
            pass


def export_props_predictions_local(
    *,
    source_root: Path,
    date_str: str,
    out_path: Path,
    calib_window: int,
    calibrate_player: bool,
    player_calib_window: int,
    player_min_pairs: int,
    player_shrink_k: int,
    use_smart_sim: bool,
    smart_sim_n_sims: int,
    smart_sim_pbp: bool,
    smart_sim_workers: int,
    smart_sim_overwrite: bool = False,
    only_matchups: set[tuple[str, str]] | None = None,
    log_file: Path | None = None,
    heartbeat_cb: callable | None = None,
    heartbeat_every_s: float = 15.0,
) -> tuple[int, Path]:
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    stop_event = threading.Event()
    heartbeat_thread = None
    if heartbeat_cb is not None:
        def _heartbeat_loop() -> None:
            while not stop_event.wait(max(1.0, float(heartbeat_every_s))):
                try:
                    heartbeat_cb()
                except Exception:
                    pass

        heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        heartbeat_thread.start()

    previous_cwd = Path.cwd()
    try:
        with contextlib.ExitStack() as stack:
            if log_file is not None:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                out = stack.enter_context(log_file.open("a", encoding="utf-8", errors="ignore"))
                stack.enter_context(contextlib.redirect_stdout(out))
                stack.enter_context(contextlib.redirect_stderr(out))

            os.chdir(source_root)
            if use_smart_sim:
                basketball_props_smart_sim.export_props_predictions_with_smart_sim_local(
                    source_root=source_root,
                    date_str=date_str,
                    out_path=out_path,
                    smart_sim_n_sims=int(smart_sim_n_sims),
                    smart_sim_pbp=bool(smart_sim_pbp),
                    smart_sim_workers=int(smart_sim_workers),
                    smart_sim_overwrite=bool(smart_sim_overwrite),
                    only_matchups=only_matchups,
                )
            else:
                _export_props_predictions_without_smart_sim_local(
                    source_root=source_root,
                    date_str=date_str,
                    out_path=out_path,
                )

            finalize_props_predictions_local(
                source_root=source_root,
                date_str=date_str,
                out_path=out_path,
                calib_window=int(calib_window),
                calibrate=True,
                calibrate_player=bool(calibrate_player),
                player_calib_window=int(player_calib_window),
                player_min_pairs=int(player_min_pairs),
                player_shrink_k=int(player_shrink_k),
            )

        if not out_path.exists() or not out_path.is_file():
            raise RuntimeError(f"predict-props completed without writing {out_path.name}")
        try:
            import pandas as pd

            out_df = pd.read_csv(out_path)
            return int(len(out_df.index)), out_path
        except Exception:
            return 0, out_path
    except Exception:
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8", errors="ignore") as out:
                traceback.print_exc(file=out)
        raise
    finally:
        try:
            os.chdir(previous_cwd)
        except Exception:
            pass
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)