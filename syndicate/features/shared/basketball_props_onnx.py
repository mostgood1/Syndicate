from __future__ import annotations

import contextlib
import os
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from syndicate.features.shared.memory_observability import log_dataframe_memory
from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path


PRIMARY_ONNX_TARGETS = ["t_pts", "t_reb", "t_ast", "t_pra", "t_threes"]
EXTRA_TARGETS = ["t_stl", "t_blk", "t_tov"]
_SUFFIX_TOKENS = frozenset({"JR", "SR", "II", "III", "IV", "V"})
_CANONICAL_PLAYER_NAME_ALIASES = {
    "CARLTON CARRINGTON": "BUB CARRINGTON",
    "CAM PAYNE": "CAMERON PAYNE",
    "HERB JONES": "HERBERT JONES",
    "MOE WAGNER": "MORITZ WAGNER",
    "NIC CLAXTON": "NICOLAS CLAXTON",
    "RON HOLLAND": "RONALD HOLLAND",
}


def normalize_player_name_key(value: Any, *, case: str = "upper") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "(" in text:
        text = text.split("(", 1)[0]
    text = text.replace("-", " ")
    text = text.replace(".", "").replace("'", "").replace(",", " ")
    text = " ".join(text.split())
    if not text:
        return ""
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    tokens = [token for token in text.upper().split() if token not in _SUFFIX_TOKENS]
    if not tokens:
        return ""
    normalized = " ".join(tokens)
    normalized = _CANONICAL_PLAYER_NAME_ALIASES.get(normalized, normalized)
    if case == "lower":
        return normalized.lower()
    return normalized


def _is_windows_arm() -> bool:
    try:
        import platform

        machine = platform.machine().lower()
        return os.name == "nt" and ("arm" in machine or "aarch64" in machine)
    except Exception:
        return False


class _SuppressStderrFD:
    def __enter__(self):
        if not _is_windows_arm():
            self._active = False
            return self
        import sys

        self._active = True
        self._fd = sys.stderr.fileno()
        self._saved = os.dup(self._fd)
        self._devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._devnull, self._fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if not getattr(self, "_active", False):
            return False
        try:
            os.dup2(self._saved, self._fd)
        finally:
            with contextlib.suppress(Exception):
                os.close(self._devnull)
            with contextlib.suppress(Exception):
                os.close(self._saved)
        return False


def _safe_num_series(df, col: str):
    import pandas as pd

    if col not in df.columns:
        return pd.Series(0.0, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)


def _blended_signal(df, stat: str):
    import pandas as pd

    parts = []
    weights = []
    for col, weight in [
        (f"lag1_{stat}", 0.15),
        (f"roll3_{stat}", 0.30),
        (f"roll5_{stat}", 0.35),
        (f"roll10_{stat}", 0.20),
    ]:
        if col in df.columns:
            parts.append(_safe_num_series(df, col) * weight)
            weights.append(weight)
    if not parts:
        return pd.Series(0.0, index=df.index, dtype=float)
    return sum(parts) / max(1e-6, float(sum(weights)))


@dataclass(frozen=True)
class PlayerPriorsConfig:
    days_back: int = 21
    min_games: int = 3
    min_minutes_avg: float = 4.0


@dataclass
class PlayerPriors:
    config: PlayerPriorsConfig
    rates: dict[tuple[str, str], dict[str, float]]
    games: dict[tuple[str, str], int]

    def rate(self, team: str, player_name: str, key: str) -> dict[str, float]:
        normalized_key = key or normalize_player_name_key(player_name, case="upper")
        return self.rates.get((str(team or "").strip().upper(), normalized_key), {})


_PLAYER_LOGS_CACHE: dict[str, object] = {}


def _load_boxscores_history_as_player_logs(processed_root: Path):
    import pandas as pd

    parquet_path = processed_root / "boxscores_history.parquet"
    csv_path = processed_root / "boxscores_history.csv"
    try:
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()
    if "date" in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["date"], errors="coerce")
    elif "GAME_DATE" in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    else:
        df["GAME_DATE"] = pd.NaT
    if "TEAM_ABBREVIATION" in df.columns:
        df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    if "PLAYER_NAME" in df.columns:
        df["PLAYER_KEY"] = df["PLAYER_NAME"].map(lambda value: normalize_player_name_key(value, case="upper"))
    for column in ("MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M", "FG3A", "FGA", "FGM", "FTA", "FTM", "PF"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = 0
    keep = [
        "GAME_DATE", "TEAM_ABBREVIATION", "PLAYER_NAME", "PLAYER_KEY", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M", "FG3A", "FGA", "FGM", "FTA", "FTM", "PF",
    ]
    return df[[column for column in keep if column in df.columns]].copy()


def _load_player_logs(processed_root: Path):
    import pandas as pd

    cache_key = str(processed_root.resolve()) if processed_root.exists() else str(processed_root)
    cached = _PLAYER_LOGS_CACHE.get(cache_key)
    if isinstance(cached, pd.DataFrame) and not cached.empty:
        return cached
    csv_path = processed_root / "player_logs.csv"
    if not csv_path.exists():
        fallback = _load_boxscores_history_as_player_logs(processed_root)
        _PLAYER_LOGS_CACHE[cache_key] = fallback
        return fallback
    df = pd.read_csv(csv_path)
    if not isinstance(df, pd.DataFrame) or df.empty:
        fallback = _load_boxscores_history_as_player_logs(processed_root)
        _PLAYER_LOGS_CACHE[cache_key] = fallback
        return fallback
    if "GAME_DATE" in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    if "TEAM_ABBREVIATION" in df.columns:
        df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    if "PLAYER_NAME" in df.columns:
        df["PLAYER_KEY"] = df["PLAYER_NAME"].map(lambda value: normalize_player_name_key(value, case="upper"))
    for column in ("MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M", "FG3A", "FGA", "FGM", "FTA", "FTM", "PF"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    _PLAYER_LOGS_CACHE[cache_key] = df
    return df


def _to_float(value: Any) -> float:
    try:
        import numpy as np

        numeric = float(value)
        return float(numeric) if np.isfinite(numeric) else 0.0
    except Exception:
        return 0.0


def compute_player_priors_local(*, processed_root: Path, date_str: str, cfg: PlayerPriorsConfig | None = None) -> PlayerPriors:
    warn_if_compute_in_request_path("compute_player_priors_local")
    import pandas as pd

    cfg = cfg or PlayerPriorsConfig()
    cutoff = pd.to_datetime(date_str, errors="coerce")
    if pd.isna(cutoff):
        cutoff = pd.Timestamp.utcnow().normalize()
    start = cutoff - pd.Timedelta(days=int(cfg.days_back))
    df = _load_player_logs(processed_root)
    if df.empty:
        return PlayerPriors(config=cfg, rates={}, games={})
    if "GAME_DATE" not in df.columns or "TEAM_ABBREVIATION" not in df.columns or "PLAYER_KEY" not in df.columns:
        return PlayerPriors(config=cfg, rates={}, games={})
    def _season_year(value) -> int | None:
        try:
            ts = pd.to_datetime(value, errors="coerce")
            if pd.isna(ts):
                return None
            return int(ts.year) if int(ts.month) >= 5 else int(ts.year) - 1
        except Exception:
            return None

    current_season_year = _season_year(cutoff)
    current_use = df[(df["GAME_DATE"].notna()) & (df["GAME_DATE"] >= start) & (df["GAME_DATE"] <= cutoff)].copy()
    prior_use = df[(df["GAME_DATE"].notna()) & (df["GAME_DATE"] < start)].copy()
    if "MIN" in current_use.columns:
        current_use = current_use[pd.to_numeric(current_use["MIN"], errors="coerce").fillna(0.0) > 0.0].copy()
    if "MIN" in prior_use.columns:
        prior_use = prior_use[pd.to_numeric(prior_use["MIN"], errors="coerce").fillna(0.0) > 0.0].copy()
    if current_use.empty and prior_use.empty:
        return PlayerPriors(config=cfg, rates={}, games={})
    if current_season_year is not None:
        if not current_use.empty:
            current_use["__season_year"] = current_use["GAME_DATE"].map(_season_year)
        if not prior_use.empty:
            prior_use["__season_year"] = prior_use["GAME_DATE"].map(_season_year)
    stat_cols = {
        "min": "MIN", "pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK", "tov": "TOV", "threes": "FG3M", "threes_att": "FG3A", "fga": "FGA", "fgm": "FGM", "fta": "FTA", "ftm": "FTM", "pf": "PF",
    }
    frames: list[pd.DataFrame] = []
    current_keys = set()
    if not current_use.empty:
        current_keys = {
            (str(row.get("TEAM_ABBREVIATION") or "").strip().upper(), str(row.get("PLAYER_KEY") or "").strip().upper())
            for _, row in current_use[["TEAM_ABBREVIATION", "PLAYER_KEY"]].drop_duplicates().iterrows()
        }
    prior_keys = set()
    if not prior_use.empty:
        prior_keys = {
            (str(row.get("TEAM_ABBREVIATION") or "").strip().upper(), str(row.get("PLAYER_KEY") or "").strip().upper())
            for _, row in prior_use[["TEAM_ABBREVIATION", "PLAYER_KEY"]].drop_duplicates().iterrows()
        }
    all_keys = current_keys | prior_keys
    for team, player_key in all_keys:
        player_current = current_use[(current_use["TEAM_ABBREVIATION"].astype(str).str.upper().str.strip() == team) & (current_use["PLAYER_KEY"].astype(str).str.upper().str.strip() == player_key)].copy()
        if not player_current.empty:
            frames.append(player_current)
            continue
        player_prior = prior_use[(prior_use["TEAM_ABBREVIATION"].astype(str).str.upper().str.strip() == team) & (prior_use["PLAYER_KEY"].astype(str).str.upper().str.strip() == player_key)].copy()
        if player_prior.empty:
            continue
        if "__season_year" in player_prior.columns and current_season_year is not None:
            fallback_season_year = int(player_prior["__season_year"].max())
            player_prior = player_prior[player_prior["__season_year"] == fallback_season_year].copy()
        frames.append(player_prior)
    use = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    log_dataframe_memory("basketball_props_onnx.player_history_concat", use)
    if use.empty:
        return PlayerPriors(config=cfg, rates={}, games={})
    keep = ["TEAM_ABBREVIATION", "PLAYER_KEY"] + [column for column in stat_cols.values() if column in use.columns]
    use = use[keep].copy()
    grouped = use.groupby(["TEAM_ABBREVIATION", "PLAYER_KEY"], as_index=False)
    agg = {column: "mean" for column in stat_cols.values() if column in use.columns}
    out = grouped.agg(agg)
    games = use.groupby(["TEAM_ABBREVIATION", "PLAYER_KEY"]).size().reset_index()
    games = games.rename(columns={0: "games", "size": "games"})
    out = out.merge(games, on=["TEAM_ABBREVIATION", "PLAYER_KEY"], how="left")
    log_dataframe_memory("basketball_props_onnx.player_priors_output", out)
    rates: dict[tuple[str, str], dict[str, float]] = {}
    games_map: dict[tuple[str, str], int] = {}
    for _, row in out.iterrows():
        team = str(row.get("TEAM_ABBREVIATION") or "").strip().upper()
        player_key = str(row.get("PLAYER_KEY") or "").strip().upper()
        if not team or not player_key:
            continue
        games_played = int(row.get("games") or 0)
        games_map[(team, player_key)] = games_played
        min_mu = _to_float(row.get("MIN"))
        stat_rates = {"min_mu": min_mu}
        if games_played >= int(cfg.min_games) and min_mu >= float(cfg.min_minutes_avg):
            for name, column in stat_cols.items():
                if name == "min":
                    continue
                stat_rates[f"{name}_pm"] = _to_float(row.get(column)) / max(min_mu, 1e-6)
        rates[(team, player_key)] = stat_rates
    return PlayerPriors(config=cfg, rates=rates, games=games_map)


def _predict_props_without_models_local(*, features_df, processed_root: Path):
    import pandas as pd

    if features_df.empty:
        return features_df.copy()
    out = features_df.copy()
    date_str = None
    if "asof_date" in out.columns and not out["asof_date"].empty:
        date_str = str(out["asof_date"].iloc[0])
    priors = compute_player_priors_local(
        processed_root=processed_root,
        date_str=date_str or pd.Timestamp.utcnow().date().isoformat(),
    )
    b2b = _safe_num_series(out, "b2b").clip(lower=0.0, upper=1.0)
    b2b_factor = 1.0 - (0.03 * b2b)
    blended_min = _blended_signal(out, "min").clip(lower=8.0)
    out["pred_min"] = blended_min.copy()
    core_defaults = {
        "pts": _blended_signal(out, "pts"),
        "reb": _blended_signal(out, "reb"),
        "ast": _blended_signal(out, "ast"),
        "threes": _blended_signal(out, "threes"),
    }
    for index, row in out.iterrows():
        team = str(row.get("team") or "").strip().upper()
        player_name = str(row.get("player_name") or "").strip()
        player_key = normalize_player_name_key(player_name, case="upper") if player_name else ""
        prior = priors.rate(team, player_name, player_key) if team and player_name else {}
        pred_min = float(blended_min.loc[index])
        prior_min = prior.get("min_mu")
        if prior_min is not None:
            pred_min = float(max(4.0, (0.65 * pred_min) + (0.35 * float(prior_min))))
        pred_min = float(max(4.0, pred_min * float(b2b_factor.loc[index])))
        out.at[index, "pred_min"] = pred_min
        for stat in ("pts", "reb", "ast", "threes"):
            signal = float(core_defaults[stat].loc[index]) * float(b2b_factor.loc[index])
            rate = prior.get(f"{stat}_pm")
            pred = signal if rate is None else (0.60 * float(rate) * pred_min) + (0.40 * signal)
            out.at[index, f"pred_{stat}"] = float(max(0.0, pred))
        fallback_rates = {"stl": 0.022, "blk": 0.018, "tov": 0.060}
        stat_caps = {"stl": 4.5, "blk": 4.5, "tov": 7.5}
        for stat in ("stl", "blk", "tov"):
            rate = prior.get(f"{stat}_pm")
            pred = float(pred_min) * float(rate if rate is not None else fallback_rates[stat])
            out.at[index, f"pred_{stat}"] = float(min(stat_caps[stat], max(0.0, pred)))
    for column in ("pred_pts", "pred_reb", "pred_ast", "pred_threes", "pred_stl", "pred_blk", "pred_tov", "pred_min"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0).clip(lower=0.0)
    if all(column in out.columns for column in ("pred_pts", "pred_reb", "pred_ast")):
        out["pred_pra"] = out["pred_pts"] + out["pred_reb"] + out["pred_ast"]
        out["pred_pr"] = out["pred_pts"] + out["pred_reb"]
        out["pred_pa"] = out["pred_pts"] + out["pred_ast"]
        out["pred_ra"] = out["pred_reb"] + out["pred_ast"]
    if all(column in out.columns for column in ("pred_stl", "pred_blk")):
        out["pred_stocks"] = out["pred_stl"] + out["pred_blk"]
    print("[WARN] Props model artifacts missing; using priors + rolling-stat fallback predictions")
    return out


def _load_feature_columns(models_dir: Path) -> list[str]:
    import pickle

    feature_cols_path = models_dir / "props_feature_columns.joblib"
    if not feature_cols_path.exists():
        raise FileNotFoundError(str(feature_cols_path))
    with feature_cols_path.open("rb") as handle:
        feature_columns = pickle.load(handle)
    return list(feature_columns)


def _load_linear_props_models_local(models_dir: Path):
    import numpy as np

    npz_path = models_dir / "pure_linear_props_models.npz"
    if not npz_path.exists():
        raise FileNotFoundError(str(npz_path))
    data = np.load(npz_path, allow_pickle=True)
    feature_cols = list(data["feature_cols"].tolist())
    result: dict[str, dict[str, object]] = {"feature_cols": feature_cols}
    for key in data.files:
        if key.startswith("coef_"):
            target = key[len("coef_"):]
            result.setdefault(target, {})["coef"] = data[key]
        elif key.startswith("intercept_"):
            target = key[len("intercept_"):]
            result.setdefault(target, {})["intercept"] = float(data[key])
    return result


def _predict_with_linear_models_local(features_df, models):
    feat_cols = models.get("feature_cols")
    if not feat_cols:
        return features_df
    out = features_df.copy()
    x_values = out[list(feat_cols)].fillna(0.0).to_numpy(dtype=float)
    for target, spec in models.items():
        if target == "feature_cols":
            continue
        weights = spec.get("coef")
        intercept = spec.get("intercept")
        if weights is None or intercept is None:
            continue
        out[target.replace("t_", "pred_")] = x_values @ weights + float(intercept)
    return out


class PureONNXPredictorLocal:
    def __init__(self, *, models_dir: Path):
        self.models_dir = Path(models_dir)
        self.feature_columns = _load_feature_columns(self.models_dir)
        self.sessions: dict[str, object] = {}
        self.extra_models: dict[str, object] = {}
        self.ort = self._import_ort()
        self.has_qnn = "QNNExecutionProvider" in self.ort.get_available_providers()
        self._load_onnx_models()

    def _import_ort(self):
        with _SuppressStderrFD():
            import onnxruntime as ort

        return ort

    def _setup_qnn_paths(self) -> None:
        qnn_roots = [
            os.environ.get("QNN_SDK"),
            os.environ.get("QNN_SDK_ROOT"),
            "C:/Qualcomm/QNN_SDK",
        ]
        for root in [path for path in qnn_roots if path]:
            for subdir in ("lib/aarch64-windows-msvc", "lib/arm64x-windows-msvc", "lib/x86_64-windows-msvc"):
                dll_dir = os.path.join(root, subdir)
                if os.path.isdir(dll_dir):
                    with contextlib.suppress(Exception):
                        os.add_dll_directory(dll_dir)

    def _resolve_qnn_backend(self) -> str | None:
        candidates = [
            os.environ.get("QNN_BACKEND_PATH"),
            "C:/Qualcomm/QNN_SDK/lib/aarch64-windows-msvc/QnnHtp.dll",
            "C:/Qualcomm/QNN_SDK/lib/arm64x-windows-msvc/QnnHtp.dll",
            "C:/Qualcomm/QNN_SDK/lib/x86_64-windows-msvc/QnnHtp.dll",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _create_session(self, model_path: Path):
        providers = []
        provider_options = []
        if self.has_qnn:
            self._setup_qnn_paths()
            qnn_options = {"target_device": "xelite", "runtime": "htp"}
            backend_path = self._resolve_qnn_backend()
            if backend_path:
                qnn_options["backend_path"] = backend_path
            providers.append("QNNExecutionProvider")
            provider_options.append(qnn_options)
        providers.append("CPUExecutionProvider")
        provider_options.append({})
        session_options = self.ort.SessionOptions()
        session_options.log_severity_level = 3
        return self.ort.InferenceSession(
            str(model_path),
            sess_options=session_options,
            providers=providers,
            provider_options=provider_options,
        )

    def _load_onnx_models(self) -> None:
        import joblib

        loaded = 0
        for target in PRIMARY_ONNX_TARGETS:
            onnx_path = self.models_dir / f"{target}_ridge.onnx"
            if not onnx_path.exists():
                raise FileNotFoundError(str(onnx_path))
            self.sessions[target] = self._create_session(onnx_path)
            loaded += 1
        if loaded != len(PRIMARY_ONNX_TARGETS):
            raise FileNotFoundError("Missing primary ONNX models")
        models_store = None
        models_path = self.models_dir / "props_models.joblib"
        if models_path.exists():
            with contextlib.suppress(Exception):
                models_store = joblib.load(models_path)
        for target in EXTRA_TARGETS:
            onnx_path = self.models_dir / f"{target}_ridge.onnx"
            if onnx_path.exists():
                with contextlib.suppress(Exception):
                    self.sessions[target] = self._create_session(onnx_path)
                    continue
            if models_store is not None and target in models_store:
                self.extra_models[target] = models_store[target]
        missing_extras = [target for target in EXTRA_TARGETS if target not in self.sessions and target not in self.extra_models]
        if missing_extras:
            with contextlib.suppress(FileNotFoundError):
                self.extra_models.update(_load_linear_props_models_local(self.models_dir))

    def predict(self, features_df):
        import numpy as np

        if features_df.empty:
            return features_df.copy()
        missing_cols = [column for column in self.feature_columns if column not in features_df.columns]
        if missing_cols:
            features_df = features_df.copy()
            for column in missing_cols:
                features_df[column] = 0.0
        x_values = features_df[self.feature_columns].fillna(0.0).values.astype(np.float32)
        result_df = features_df.copy()
        total_ms = 0.0
        predictions_made = 0
        for target in PRIMARY_ONNX_TARGETS:
            pred_col = target.replace("t_", "pred_")
            session = self.sessions[target]
            input_name = session.get_inputs()[0].name
            started = time.perf_counter()
            predictions = session.run(None, {input_name: x_values})[0]
            total_ms += (time.perf_counter() - started) * 1000.0
            result_df[pred_col] = predictions.flatten()
            predictions_made += 1
        for target in EXTRA_TARGETS:
            pred_col = target.replace("t_", "pred_")
            if target in self.sessions:
                session = self.sessions[target]
                input_name = session.get_inputs()[0].name
                started = time.perf_counter()
                predictions = session.run(None, {input_name: x_values})[0]
                total_ms += (time.perf_counter() - started) * 1000.0
                result_df[pred_col] = predictions.flatten()
                predictions_made += 1
            elif target in self.extra_models and hasattr(self.extra_models[target], "predict"):
                result_df[pred_col] = self.extra_models[target].predict(x_values)
                predictions_made += 1
        if "feature_cols" in self.extra_models:
            result_df = _predict_with_linear_models_local(result_df, self.extra_models)
        if predictions_made > 0:
            provider = "NPU" if self.has_qnn else "CPU"
            print(f"[PERF] {provider} inference: {total_ms:.2f}ms total")
        return result_df


def predict_props_pure_onnx_local(*, features_df, models_dir: Path, processed_root: Path):
    try:
        predictor = PureONNXPredictorLocal(models_dir=models_dir)
        return predictor.predict(features_df)
    except Exception as exc:
        if isinstance(exc, FileNotFoundError) or exc.__class__.__name__ in {"ImportError", "ModuleNotFoundError"}:
            return _predict_props_without_models_local(features_df=features_df, processed_root=processed_root)
        raise