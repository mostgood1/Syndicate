from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from syndicate.features.shared.memory_observability import log_dataframe_memory


_PLAYER_PROP_BOOKMAKER_ALIASES = {
    "fanduel": "fanduel",
    "fd": "fanduel",
    "draftkings": "draftkings",
    "dk": "draftkings",
    "betmgm": "betmgm",
    "mgm": "betmgm",
    "bet365": "bet365",
    "bet365us": "bet365",
}

_MARKET_TO_STAT = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes",
    "player_points_rebounds_assists": "pra",
    "player_points_rebounds": "pr",
    "player_points_assists": "pa",
    "player_rebounds_assists": "ra",
    "player_steals": "stl",
    "player_blocks": "blk",
    "player_turnovers": "tov",
    "player_double_double": "dd",
    "player_triple_double": "td",
}


@dataclass
class _SigmaConfig:
    pts: float = 7.5
    reb: float = 3.0
    ast: float = 2.5
    threes: float = 1.3
    pra: float = 9.0
    stl: float = 1.2
    blk: float = 1.3
    tov: float = 1.5


def _norm_name(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if "(" in text:
        text = text.split("(", 1)[0]
    text = text.replace("-", " ")
    text = text.replace(".", "").replace("'", "").replace(",", " ").strip()
    for suffix in [" JR", " SR", " II", " III", " IV"]:
        if text.upper().endswith(suffix):
            text = text[: -len(suffix)]
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return text.upper().strip()


def _short_key(value: object) -> str:
    norm = _norm_name(value)
    parts = [part for part in norm.replace("-", " ").split() if part]
    if not parts:
        return norm
    last = parts[-1]
    first_initial = parts[0][0] if parts[0] else ""
    return f"{last}{first_initial}"


def _map_side(value: object) -> str | None:
    upper = str(value or "").upper()
    if "OVER" in upper:
        return "OVER"
    if "UNDER" in upper:
        return "UNDER"
    if upper in {"YES", "Y"}:
        return "YES"
    if upper in {"NO", "N"}:
        return "NO"
    return None


def _load_props_odds_from_path(raw_path: Path):
    import pandas as pd

    usecols = [
        "snapshot_ts",
        "event_id",
        "commence_time",
        "bookmaker",
        "bookmaker_title",
        "market",
        "outcome_name",
        "player_name",
        "point",
        "price",
        "home_team",
        "away_team",
    ]
    usecols_set = set(usecols)
    if str(raw_path).lower().endswith(".parquet"):
        try:
            return pd.read_parquet(raw_path, columns=usecols)
        except Exception:
            return pd.read_parquet(raw_path)
    return pd.read_csv(raw_path, usecols=lambda column: column in usecols_set)


def _load_props_prob_calibration(processed_root: Path) -> dict[str, object] | None:
    candidates = [
        processed_root / "props_prob_calibration_by_stat.json",
        processed_root / "props_prob_calibration.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _apply_prob_curve(value: float, curve: dict[str, object]) -> float:
    try:
        xs = curve.get("x") or []
        ys = curve.get("y") or []
        if not (isinstance(xs, list) and isinstance(ys, list) and len(xs) >= 2 and len(xs) == len(ys)):
            return float(max(0.0, min(1.0, value)))
        x = [float(v) for v in xs]
        y = [float(v) for v in ys]
        if x[0] >= x[-1]:
            return float(max(0.0, min(1.0, value)))
        if any(x[index + 1] < x[index] for index in range(len(x) - 1)):
            return float(max(0.0, min(1.0, value)))
        if any(v < -1e-9 or v > 1.0 + 1e-9 for v in y):
            return float(max(0.0, min(1.0, value)))
        import numpy as np

        clipped = float(max(0.0, min(1.0, value)))
        return float(max(0.0, min(1.0, np.interp(clipped, x, y))))
    except Exception:
        return float(max(0.0, min(1.0, value)))


def _compute_props_edges_file_only_local(
    *,
    source_root: Path,
    date_str: str,
    raw_path: Path,
    predictions_path: Path,
    calibrate_prob: bool,
):
    import numpy as np
    import pandas as pd

    preds = pd.read_csv(predictions_path)
    odds = _load_props_odds_from_path(raw_path)
    if preds is None or preds.empty or odds is None or odds.empty:
        raise ValueError(f"No edges computed for {date_str} (missing odds or predictions).")

    base_map = {
        "pts": ("mean_pts", "pred_pts"),
        "reb": ("mean_reb", "pred_reb"),
        "ast": ("mean_ast", "pred_ast"),
        "threes": ("mean_threes", "pred_threes"),
        "pra": ("mean_pra", "pred_pra"),
        "stl": ("mean_stl", "pred_stl"),
        "blk": ("mean_blk", "pred_blk"),
        "tov": ("mean_tov", "pred_tov"),
    }
    pred_map: dict[str, str] = {}
    for stat, (mean_col, pred_col) in base_map.items():
        pred_map[stat] = mean_col if mean_col in preds.columns else pred_col

    for need in ["player_id", "player_name", *pred_map.values()]:
        if need not in preds.columns:
            raise ValueError(f"Predictions missing column: {need}")

    preds = preds.copy()
    preds["name_key"] = preds["player_name"].astype(str).map(_norm_name)
    preds["short_key"] = preds["player_name"].astype(str).map(_short_key)

    keep_cols = [
        "snapshot_ts",
        "event_id",
        "bookmaker",
        "bookmaker_title",
        "market",
        "outcome_name",
        "player_name",
        "point",
        "price",
        "commence_time",
        "home_team",
        "away_team",
    ]
    odds = odds[[column for column in keep_cols if column in odds.columns]].copy()
    if "player_name" not in odds.columns and "outcome_name" in odds.columns:
        odds["player_name"] = odds["outcome_name"].astype(str)
    odds["name_key"] = odds["player_name"].astype(str).map(_norm_name)
    odds["short_key"] = odds["player_name"].astype(str).map(_short_key)
    odds["side"] = odds["outcome_name"].astype(str).map(_map_side)
    odds["stat"] = odds["market"].map(_MARKET_TO_STAT)
    base_ok = odds["name_key"].notna() & odds["stat"].notna() & odds["side"].notna()
    is_yesno = odds["stat"].isin(["dd", "td"])
    price_ok = odds["price"].notna()
    point_ok = odds["point"].notna()
    odds = odds.loc[base_ok & price_ok & (is_yesno | point_ok)].copy()
    if odds.empty:
        raise ValueError(f"No edges computed for {date_str} (missing odds or predictions).")

    extra_cols = [column for column in ("sd_pts", "sd_reb", "sd_ast", "sd_threes", "sd_pra", "sd_stl", "sd_blk", "sd_tov") if column in preds.columns]
    pred_cols = [pred_map[key] for key in ("pts", "reb", "ast", "threes", "pra", "stl", "blk", "tov") if pred_map.get(key) in preds.columns]
    merged = odds.merge(
        preds[["name_key", "short_key", "player_id", "player_name", "team", *pred_cols, *extra_cols]],
        on="name_key",
        how="left",
        suffixes=("", "_pred"),
    )

    unmatched = merged[merged["player_id"].isna()].copy()
    if not unmatched.empty:
        alt = odds.merge(
            preds[["short_key", "player_id", "player_name", "team", *pred_cols]].rename(columns={"short_key": "short_key_pred"}),
            left_on="short_key",
            right_on="short_key_pred",
            how="left",
            suffixes=("", "_pred"),
        )
        if "player_name_pred" in alt.columns:
            alt["player_name_join"] = alt["player_name_pred"].fillna(alt.get("player_name"))
        else:
            alt["player_name_join"] = alt.get("player_name")
        keep = [column for column in ["short_key", "player_id", "player_name_join", "team", *pred_cols] if column in alt.columns]
        alt = alt[keep].copy().rename(columns={"player_name_join": "player_name"})
        merged = merged.merge(alt.add_suffix("_alt"), left_on="short_key", right_on="short_key_alt", how="left")
        for column in ["player_id", "player_name", "team", *pred_cols]:
            alt_column = f"{column}_alt"
            if column in merged.columns and alt_column in merged.columns:
                merged[column] = merged[column].fillna(merged[alt_column])

    log_dataframe_memory("basketball_props_edges.merged_odds_predictions", merged)

    def _num_col(column_name: str | None) -> pd.Series:
        if not column_name or column_name not in merged.columns:
            return pd.Series(np.nan, index=merged.index, dtype="float64")
        return pd.to_numeric(merged[column_name], errors="coerce")

    stat_s = merged.get("stat").astype(str).str.lower() if "stat" in merged.columns else pd.Series("", index=merged.index)
    model_mean = pd.Series(np.nan, index=merged.index, dtype="float64")
    pts_v = _num_col(pred_map.get("pts"))
    reb_v = _num_col(pred_map.get("reb"))
    ast_v = _num_col(pred_map.get("ast"))
    for stat in ("pts", "reb", "ast", "threes", "pra", "stl", "blk", "tov"):
        mask = stat_s == stat
        if mask.any():
            model_mean.loc[mask] = _num_col(pred_map.get(stat)).loc[mask]
    for stat, values in {
        "pr": pts_v + reb_v,
        "pa": pts_v + ast_v,
        "ra": reb_v + ast_v,
    }.items():
        mask = stat_s == stat
        if mask.any():
            model_mean.loc[mask] = values.loc[mask]
    merged["model_mean"] = model_mean

    def _safe_sd_series(column_name: str) -> pd.Series:
        if column_name not in merged.columns:
            return pd.Series(np.nan, index=merged.index, dtype="float64")
        series = pd.to_numeric(merged[column_name], errors="coerce").astype(float)
        series = series.where(np.isfinite(series))
        return series.where((series > 0.05) & (series < 50.0))

    sd_pts = _safe_sd_series("sd_pts")
    sd_reb = _safe_sd_series("sd_reb")
    sd_ast = _safe_sd_series("sd_ast")
    sd_threes = _safe_sd_series("sd_threes")
    sd_pra = _safe_sd_series("sd_pra")
    sd_stl = _safe_sd_series("sd_stl")
    sd_blk = _safe_sd_series("sd_blk")
    sd_tov = _safe_sd_series("sd_tov")

    sigma = _SigmaConfig()
    fallback_sig = {
        "pts": float(sigma.pts),
        "reb": float(sigma.reb),
        "ast": float(sigma.ast),
        "threes": float(sigma.threes),
        "pra": float(sigma.pra),
        "stl": float(sigma.stl),
        "blk": float(sigma.blk),
        "tov": float(sigma.tov),
        "pr": float(np.sqrt(float(sigma.pts) ** 2 + float(sigma.reb) ** 2)),
        "pa": float(np.sqrt(float(sigma.pts) ** 2 + float(sigma.ast) ** 2)),
        "ra": float(np.sqrt(float(sigma.reb) ** 2 + float(sigma.ast) ** 2)),
    }
    sig = stat_s.map(fallback_sig).astype(float)
    for stat, sd in (("pts", sd_pts), ("reb", sd_reb), ("ast", sd_ast), ("threes", sd_threes), ("pra", sd_pra), ("stl", sd_stl), ("blk", sd_blk), ("tov", sd_tov)):
        mask = stat_s == stat
        if mask.any():
            sig.loc[mask] = sd.loc[mask].fillna(sig.loc[mask])
    for stat, left, right, default_left, default_right in (
        ("pr", sd_pts, sd_reb, float(sigma.pts), float(sigma.reb)),
        ("pa", sd_pts, sd_ast, float(sigma.pts), float(sigma.ast)),
        ("ra", sd_reb, sd_ast, float(sigma.reb), float(sigma.ast)),
    ):
        mask = stat_s == stat
        if mask.any():
            s1 = left.fillna(default_left)
            s2 = right.fillna(default_right)
            sig.loc[mask] = np.sqrt(np.square(s1.loc[mask]) + np.square(s2.loc[mask]))
    merged["sigma"] = sig

    merged["line"] = pd.to_numeric(merged.get("point"), errors="coerce")
    merged["price"] = pd.to_numeric(merged.get("price"), errors="coerce")
    side_s = merged.get("side").astype(str).str.strip().str.upper() if "side" in merged.columns else pd.Series("", index=merged.index)

    def _norm_cdf_vec(values: np.ndarray) -> np.ndarray:
        z = values / np.sqrt(2.0)
        t = 1.0 / (1.0 + 0.5 * np.abs(z))
        tau = t * np.exp(
            -z * z
            - 1.26551223
            + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277))))))))
        )
        erf_approx = np.sign(z) * (1.0 - tau)
        return np.clip(0.5 * (1.0 + erf_approx), 0.0, 1.0)

    n = int(len(merged))
    prob = np.full(n, np.nan, dtype=float)
    mean_arr = pd.to_numeric(merged.get("model_mean"), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    sig_arr = pd.to_numeric(merged.get("sigma"), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    line_arr = pd.to_numeric(merged.get("line"), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    over_arr = np.full(n, np.nan, dtype=float)
    valid = np.isfinite(mean_arr) & np.isfinite(sig_arr) & np.isfinite(line_arr) & (sig_arr > 0)
    if bool(valid.any()):
        z = (line_arr[valid] - mean_arr[valid]) / sig_arr[valid]
        over_arr[valid] = 1.0 - _norm_cdf_vec(z)
    over_arr = np.clip(over_arr, 0.0, 1.0)

    is_yesno_arr = stat_s.isin(["dd", "td"]).to_numpy(dtype=bool)
    side_over = (side_s == "OVER").to_numpy(dtype=bool)
    side_under = (side_s == "UNDER").to_numpy(dtype=bool)
    mask_ou = ~is_yesno_arr
    if bool((mask_ou & side_over).any()):
        prob[mask_ou & side_over] = over_arr[mask_ou & side_over]
    if bool((mask_ou & side_under).any()):
        prob[mask_ou & side_under] = 1.0 - over_arr[mask_ou & side_under]

    if bool(is_yesno_arr.any()):
        mean_pts = pd.to_numeric(merged.get(pred_map.get("pts") or ""), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        mean_reb = pd.to_numeric(merged.get(pred_map.get("reb") or ""), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        mean_ast = pd.to_numeric(merged.get(pred_map.get("ast") or ""), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        p10_pts = np.full(n, np.nan, dtype=float)
        p10_reb = np.full(n, np.nan, dtype=float)
        p10_ast = np.full(n, np.nan, dtype=float)
        for means, out_arr, default_sigma in ((mean_pts, p10_pts, float(sigma.pts)), (mean_reb, p10_reb, float(sigma.reb)), (mean_ast, p10_ast, float(sigma.ast))):
            ok = np.isfinite(means)
            if bool(ok.any()):
                z = (10.0 - means[ok]) / default_sigma
                out_arr[ok] = 1.0 - _norm_cdf_vec(z)
        p_td_yes = p10_pts * p10_reb * p10_ast
        p_dd_yes = (p10_pts * p10_reb) + (p10_pts * p10_ast) + (p10_reb * p10_ast) - (p10_pts * p10_reb * p10_ast)
        p_yes = np.full(n, np.nan, dtype=float)
        stat_arr = stat_s.to_numpy(dtype=str)
        p_yes[stat_arr == "td"] = p_td_yes[stat_arr == "td"]
        p_yes[stat_arr == "dd"] = p_dd_yes[stat_arr == "dd"]
        side_yes = (side_s == "YES").to_numpy(dtype=bool)
        side_no = (side_s == "NO").to_numpy(dtype=bool)
        if bool((is_yesno_arr & side_yes).any()):
            prob[is_yesno_arr & side_yes] = p_yes[is_yesno_arr & side_yes]
        if bool((is_yesno_arr & side_no).any()):
            prob[is_yesno_arr & side_no] = 1.0 - p_yes[is_yesno_arr & side_no]

    merged["model_prob"] = prob
    merged["model_prob_raw"] = merged["model_prob"]
    merged["_prob_calibrated"] = False
    if calibrate_prob:
        try:
            cal = _load_props_prob_calibration(source_root / "data" / "processed") or {}
            mp = pd.to_numeric(merged["model_prob"], errors="coerce")
            per_stat = cal.get("per_stat") if isinstance(cal.get("per_stat"), dict) else {}
            global_curve = cal.get("global") if isinstance(cal.get("global"), dict) else None
            out = mp.copy()
            applied = pd.Series(False, index=merged.index)
            for market_key in sorted(set(stat_s.dropna().astype(str).tolist())):
                mask = stat_s == market_key
                if not bool(mask.any()):
                    continue
                curve = per_stat.get(market_key) if isinstance(per_stat, dict) else None
                if not isinstance(curve, dict):
                    curve = global_curve
                if not isinstance(curve, dict):
                    continue
                values = pd.to_numeric(out.loc[mask], errors="coerce")
                out.loc[mask] = values.apply(lambda value: _apply_prob_curve(float(value), curve) if pd.notna(value) else np.nan)
                applied.loc[mask] = True
            merged["model_prob"] = out
            merged.loc[applied.index, "_prob_calibrated"] = applied
        except Exception:
            pass

    try:
        k_by_stat = {"pts": 0.45, "pra": 0.50}
        for stat, k in k_by_stat.items():
            mask = (stat_s == stat) & (~pd.to_numeric(merged.get("_prob_calibrated"), errors="coerce").fillna(False).astype(bool))
            if mask.any():
                p = pd.to_numeric(merged.loc[mask, "model_prob"], errors="coerce")
                merged.loc[mask, "model_prob"] = (0.5 + float(k) * (p - 0.5)).clip(lower=0.0, upper=1.0)
    except Exception:
        pass

    merged["model_prob"] = pd.to_numeric(merged["model_prob"], errors="coerce").clip(lower=0.01, upper=0.99)
    price_num = pd.to_numeric(merged.get("price"), errors="coerce")
    implied = pd.Series(np.nan, index=merged.index, dtype="float64")
    m_pos = price_num > 0
    if m_pos.any():
        implied.loc[m_pos] = 100.0 / (price_num.loc[m_pos] + 100.0)
    m_neg = price_num < 0
    if m_neg.any():
        implied.loc[m_neg] = (-price_num.loc[m_neg]) / ((-price_num.loc[m_neg]) + 100.0)
    merged["implied_prob"] = implied

    try:
        pm = pd.to_numeric(merged.get("model_prob"), errors="coerce")
        pi = pd.to_numeric(merged.get("implied_prob"), errors="coerce")
        for stat, weight in {"pa": 0.22, "pr": 0.22, "ra": 0.22, "ast": 0.15, "reb": 0.15}.items():
            mask = (stat_s == stat) & (~pd.to_numeric(merged.get("_prob_calibrated"), errors="coerce").fillna(False).astype(bool))
            if mask.any():
                merged.loc[mask, "model_prob"] = (pi.loc[mask].clip(0.0, 1.0) + float(weight) * (pm.loc[mask].clip(0.0, 1.0) - pi.loc[mask].clip(0.0, 1.0))).clip(0.0, 1.0)
        mask = (stat_s == "pra") & (~pd.to_numeric(merged.get("_prob_calibrated"), errors="coerce").fillna(False).astype(bool))
        if mask.any():
            merged.loc[mask, "model_prob"] = (pi.loc[mask].clip(0.0, 1.0) + 0.35 * (pm.loc[mask].clip(0.0, 1.0) - pi.loc[mask].clip(0.0, 1.0))).clip(0.0, 1.0)
    except Exception:
        pass

    merged["edge"] = merged["model_prob"] - merged["implied_prob"]
    ev = pd.Series(np.nan, index=merged.index, dtype="float64")
    if m_pos.any():
        ev.loc[m_pos] = merged.loc[m_pos, "model_prob"] * (price_num.loc[m_pos] / 100.0) - (1.0 - merged.loc[m_pos, "model_prob"])
    if m_neg.any():
        ev.loc[m_neg] = merged.loc[m_neg, "model_prob"] * (100.0 / (-price_num.loc[m_neg])) - (1.0 - merged.loc[m_neg, "model_prob"])
    merged["ev"] = ev

    if "bookmaker_title" not in merged.columns and "bookmaker" in merged.columns:
        merged["bookmaker_title"] = merged["bookmaker"]

    desired_cols = [
        "snapshot_ts",
        "player_id",
        "player_name",
        "team",
        "stat",
        "side",
        "line",
        "price",
        "implied_prob",
        "model_prob",
        "model_prob_raw",
        "edge",
        "ev",
        "bookmaker",
        "bookmaker_title",
        "commence_time",
        "home_team",
        "away_team",
    ]
    out = merged[[column for column in desired_cols if column in merged.columns]].copy()
    if out.empty:
        raise ValueError(f"No edges computed for {date_str} (missing odds or predictions).")
    out.insert(0, "date", pd.to_datetime(date_str).date())
    dedup_keys = [column for column in ["date", "player_id", "player_name", "team", "stat", "side", "line", "price", "bookmaker", "bookmaker_title", "commence_time"] if column in out.columns]
    if dedup_keys:
        out = out.drop_duplicates(subset=dedup_keys, keep="first").reset_index(drop=True)
    return out


def _standardize_edge_columns(edges):
    if edges is None:
        return edges
    columns_attr = getattr(edges, "columns", None)
    columns = list(columns_attr) if columns_attr is not None else []
    if getattr(edges, "empty", False):
        return edges

    out = edges.copy()
    if "expected_value" not in columns and "ev" in columns:
        out["expected_value"] = out["ev"]
    if "edge_pct" not in columns and "edge" in columns:
        out["edge_pct"] = out["edge"] * 100.0
    if "model_probability" not in columns and "model_prob" in columns:
        out["model_probability"] = out["model_prob"]
    if "market_probability" not in columns and "implied_prob" in columns:
        out["market_probability"] = out["implied_prob"]
    return out


def _normalize_bookmaker_key(book: object) -> str:
    try:
        raw = str(book or "").strip().lower()
    except Exception:
        return ""
    if not raw:
        return ""
    compact = raw.replace(" ", "").replace("-", "").replace("_", "")
    return _PLAYER_PROP_BOOKMAKER_ALIASES.get(compact, raw)


def _resolve_player_prop_bookmakers(raw: str | None = None) -> tuple[str, ...]:
    value = str(raw or "").strip()
    if not value:
        return tuple()
    if value.lower() in {"all", "none", "off", "0", "false", "no"}:
        return tuple()
    out: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        bookmaker = _normalize_bookmaker_key(part)
        if not bookmaker or bookmaker in seen:
            continue
        seen.add(bookmaker)
        out.append(bookmaker)
    return tuple(out)


def _filter_player_prop_bookmakers_df(edges, raw: str | None = None):
    if edges is None:
        return edges
    columns_attr = getattr(edges, "columns", None)
    columns = list(columns_attr) if columns_attr is not None else []
    if getattr(edges, "empty", False) or "bookmaker" not in columns:
        return edges

    out = edges.copy()
    bookmaker_series = out["bookmaker"]
    out["bookmaker"] = bookmaker_series.astype(str).map(_normalize_bookmaker_key)

    allowed = set(_resolve_player_prop_bookmakers(raw))
    if not allowed:
        return out
    return out[out["bookmaker"].isin(allowed)].copy()


def export_props_edges_local(
    *,
    source_root: Path,
    date_str: str,
    raw_path: Path,
    predictions_path: Path,
    out_path: Path,
    bookmakers: str | None = None,
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
            edges = _compute_props_edges_file_only_local(
                source_root=source_root,
                date_str=date_str,
                raw_path=raw_path,
                predictions_path=predictions_path,
                calibrate_prob=True,
            )

            edges = _filter_player_prop_bookmakers_df(edges, bookmakers)
            edges = _standardize_edge_columns(edges)
            edges = edges[(edges["edge"] >= 0.0) & (edges["ev"] >= 0.0)].copy()
            if edges.empty:
                raise ValueError(f"No edges computed for {date_str} (missing odds or predictions).")

            if "ev" in edges.columns:
                edges.sort_values(["stat", "ev"], ascending=[True, False], inplace=True)
            else:
                edges.sort_values(["stat", "edge"], ascending=[True, False], inplace=True)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            edges.to_csv(out_path, index=False)
            return int(len(edges.index)), out_path
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