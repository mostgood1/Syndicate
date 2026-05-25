from __future__ import annotations

import json
from pathlib import Path


STAT_KEYS = ["pts", "reb", "ast", "threes", "pra"]
PRED_COLS = {
    "pts": "pred_pts",
    "reb": "pred_reb",
    "ast": "pred_ast",
    "threes": "pred_threes",
    "pra": "pred_pra",
}


def _list_recent_dates(anchor_date: str, days: int) -> list[str]:
    import pandas as pd

    d = pd.to_datetime(anchor_date).date()
    out: list[str] = []
    for i in range(1, days + 1):
        out.append(str(d - pd.Timedelta(days=i)))
    return out


def _read_predictions_for_date(*, processed_root: Path, date_str: str):
    import pandas as pd

    path = processed_root / f"props_predictions_{date_str}.csv"
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _read_recon_for_date(*, processed_root: Path, date_str: str):
    import pandas as pd

    path = processed_root / f"recon_props_{date_str}.csv"
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _merge_pred_recon_for_date(*, processed_root: Path, date_str: str):
    pred = _read_predictions_for_date(processed_root=processed_root, date_str=date_str)
    recon = _read_recon_for_date(processed_root=processed_root, date_str=date_str)
    if pred is None or recon is None or pred.empty or recon.empty:
        return None

    join_keys: list[tuple[str, str]] = []
    if "player_id" in pred.columns and "player_id" in recon.columns:
        join_keys = [("player_id", "player_id")]
    elif "player_name" in pred.columns and "player_name" in recon.columns:
        join_keys = [("player_name", "player_name")]
        if "team" in pred.columns and "team_abbr" in recon.columns:
            join_keys.append(("team", "team_abbr"))
    else:
        return None

    left_on = [left for left, _ in join_keys]
    right_on = [right for _, right in join_keys]
    try:
        merged = pred.merge(recon, left_on=left_on, right_on=right_on, how="inner", suffixes=("_pred", "_act"))
    except Exception:
        return None
    if merged.empty:
        return None
    return merged


def compute_biases(*, processed_root: Path, anchor_date: str, window_days: int = 7, min_pairs: int = 50) -> dict[str, float]:
    import numpy as np
    import pandas as pd

    dates = _list_recent_dates(anchor_date, window_days)
    errs: dict[str, list[float]] = {key: [] for key in STAT_KEYS}
    total_pairs = 0
    for date_str in dates:
        pred = _read_predictions_for_date(processed_root=processed_root, date_str=date_str)
        recon = _read_recon_for_date(processed_root=processed_root, date_str=date_str)
        if pred is None or recon is None or pred.empty or recon.empty:
            continue

        join_keys: list[tuple[str, str]] = []
        if "player_id" in pred.columns and "player_id" in recon.columns:
            join_keys = [("player_id", "player_id")]
        elif "player_name" in pred.columns and "player_name" in recon.columns:
            join_keys = [("player_name", "player_name")]
            if "team" in pred.columns and "team_abbr" in recon.columns:
                join_keys.append(("team", "team_abbr"))
        else:
            continue

        left_on = [left for left, _ in join_keys]
        right_on = [right for _, right in join_keys]
        try:
            merged = pred.merge(recon, left_on=left_on, right_on=right_on, how="inner", suffixes=("_pred", "_act"))
        except Exception:
            continue
        if merged.empty:
            continue

        for stat in STAT_KEYS:
            pred_col = PRED_COLS.get(stat)
            if pred_col in merged.columns and stat in merged.columns:
                try:
                    actual = pd.to_numeric(merged[stat], errors="coerce")
                    predicted = pd.to_numeric(merged[pred_col], errors="coerce")
                    diff = (actual - predicted).astype(float)
                    if diff.notna().sum() > 10:
                        q1, q99 = np.nanpercentile(diff.dropna(), [1, 99])
                    else:
                        q1, q99 = (np.nan, np.nan)
                    if not np.isnan(q1) and not np.isnan(q99):
                        mask = (diff >= q1) & (diff <= q99)
                        values = diff[mask].tolist()
                    else:
                        values = diff.tolist()
                    errs[stat].extend([value for value in values if np.isfinite(value)])
                except Exception:
                    continue
        total_pairs += int(len(merged))

    if total_pairs < min_pairs:
        return {key: 0.0 for key in STAT_KEYS}

    biases: dict[str, float] = {}
    caps = {"pts": 2.5, "reb": 1.5, "ast": 1.5, "threes": 0.8, "pra": 3.5}
    for stat in STAT_KEYS:
        arr = np.array(errs.get(stat, []), dtype=float)
        if arr.size == 0:
            biases[stat] = 0.0
            continue
        bias = float(np.nanmedian(arr))
        cap = caps.get(stat, 3.0)
        if bias > cap:
            bias = cap
        if bias < -cap:
            bias = -cap
        biases[stat] = bias
    return biases


def apply_biases(*, preds, biases: dict[str, float]):
    import pandas as pd

    out = preds.copy()
    for stat, pred_col in PRED_COLS.items():
        if pred_col in out.columns and stat in biases:
            try:
                out[pred_col] = pd.to_numeric(out[pred_col], errors="coerce") + float(biases[stat])
            except Exception:
                continue
    return out


def save_calibration(*, processed_root: Path, biases: dict[str, float], anchor_date: str, window_days: int) -> Path:
    obj = {
        "date": anchor_date,
        "window_days": int(window_days),
        "biases": {key: float(value) for key, value in biases.items()},
    }
    out = processed_root / f"props_calibration_{anchor_date}.json"
    try:
        out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out


def compute_player_biases(
    *,
    processed_root: Path,
    anchor_date: str,
    window_days: int = 30,
    min_pairs_per_player: int = 6,
    shrink_k: float = 8.0,
    shrink_k_by_stat: dict[str, float] | None = None,
    min_pairs_by_stat: dict[str, int] | None = None,
):
    import numpy as np
    import pandas as pd

    dates = _list_recent_dates(anchor_date, window_days)
    rows: list[tuple[int | None, str | None, str, float]] = []
    for date_str in dates:
        merged = _merge_pred_recon_for_date(processed_root=processed_root, date_str=date_str)
        if merged is None or merged.empty:
            continue

        pid_col = "player_id" if "player_id" in merged.columns else None
        pname_col = "player_name_pred" if "player_name_pred" in merged.columns else ("player_name" if "player_name" in merged.columns else None)
        for stat in STAT_KEYS:
            pred_col = PRED_COLS.get(stat)
            if pred_col in merged.columns and stat in merged.columns:
                try:
                    actual = pd.to_numeric(merged[stat], errors="coerce")
                    predicted = pd.to_numeric(merged[pred_col], errors="coerce")
                    diff = (actual - predicted).astype(float)
                    values = diff.to_numpy()
                    values = values[np.isfinite(values)]
                    if values.size == 0:
                        continue
                    if values.size > 10:
                        q1, q99 = np.nanpercentile(values, [1, 99])
                        mask = (diff >= q1) & (diff <= q99)
                    else:
                        mask = diff.notna()
                    cols = [column for column in [pid_col, pname_col] if column] + [stat, pred_col]
                    tmp = merged.loc[mask, cols].copy()
                    tmp["_err"] = pd.to_numeric(tmp[stat], errors="coerce") - pd.to_numeric(tmp[pred_col], errors="coerce")
                    for _, row in tmp.iterrows():
                        player_id = int(row[pid_col]) if pid_col and pd.notna(row[pid_col]) else None
                        player_name = str(row[pname_col]) if pname_col and pd.notna(row[pname_col]) else None
                        err = float(row["_err"]) if pd.notna(row["_err"]) else np.nan
                        if np.isfinite(err):
                            rows.append((player_id, player_name, stat, err))
                except Exception:
                    continue

    if not rows:
        return pd.DataFrame(columns=["player_id", "player_name", "stat", "bias", "n", "adj"])

    df = pd.DataFrame(rows, columns=["player_id", "player_name", "stat", "err"])
    agg = df.groupby(["player_id", "player_name", "stat"]).agg(
        n=("err", "count"),
        bias=("err", lambda series: float(np.nanmedian(np.asarray(list(series), dtype=float)))),
    ).reset_index()

    caps = {"pts": 3.0, "reb": 1.8, "ast": 1.8, "threes": 1.0, "pra": 4.5}
    agg["bias"] = agg.apply(
        lambda row: max(-caps.get(str(row["stat"]), 3.0), min(caps.get(str(row["stat"]), 3.0), float(row["bias"]))),
        axis=1,
    )

    if min_pairs_by_stat:
        try:
            def _ok_min(row):
                stat = str(row["stat"])
                required = int(min_pairs_by_stat.get(stat, min_pairs_per_player))
                return int(row["n"]) >= required

            agg = agg[agg.apply(_ok_min, axis=1)].copy()
        except Exception:
            agg = agg[agg["n"] >= int(min_pairs_per_player)].copy()
    else:
        agg = agg[agg["n"] >= int(min_pairs_per_player)].copy()

    if agg.empty:
        return pd.DataFrame(columns=["player_id", "player_name", "stat", "bias", "n", "adj"])

    if shrink_k_by_stat:
        def _adj_row(row):
            try:
                stat = str(row["stat"]) if pd.notna(row["stat"]) else None
                k_value = float(shrink_k_by_stat.get(stat, shrink_k))
            except Exception:
                k_value = float(shrink_k)
            n_value = float(row["n"]) if pd.notna(row["n"]) else 0.0
            bias_value = float(row["bias"]) if pd.notna(row["bias"]) else 0.0
            return bias_value * (n_value / (n_value + k_value)) if (n_value + k_value) > 0 else 0.0

        agg["adj"] = agg.apply(_adj_row, axis=1)
    else:
        agg["adj"] = agg.apply(
            lambda row: float(row["bias"]) * (float(row["n"]) / (float(row["n"]) + float(shrink_k))),
            axis=1,
        )

    return agg.sort_values(["stat", "n"], ascending=[True, False]).reset_index(drop=True)


def apply_player_biases(*, preds, player_biases):
    import pandas as pd

    if preds is None or preds.empty or player_biases is None or player_biases.empty:
        return preds.copy()

    out = preds.copy()
    if "player_id" not in out.columns:
        return out

    for stat, pred_col in PRED_COLS.items():
        if pred_col not in out.columns:
            continue
        sub = player_biases[player_biases["stat"] == stat][["player_id", "adj"]].copy()
        if sub.empty:
            continue
        sub = sub.rename(columns={"adj": f"adj_{stat}"})
        out = out.merge(sub, on="player_id", how="left")
        adj_col = f"adj_{stat}"
        if adj_col in out.columns:
            try:
                out[pred_col] = pd.to_numeric(out[pred_col], errors="coerce") + pd.to_numeric(out[adj_col], errors="coerce").fillna(0.0)
            except Exception:
                pass
            out.drop(columns=[adj_col], inplace=True, errors="ignore")
    return out


def save_player_calibration(*, processed_root: Path, player_biases, anchor_date: str, window_days: int) -> Path:
    out = processed_root / f"props_player_calibration_{anchor_date}.csv"
    try:
        player_biases = player_biases.copy()
        player_biases["date"] = str(anchor_date)
        player_biases["window_days"] = int(window_days)
        player_biases.to_csv(out, index=False)
    except Exception:
        pass
    return out