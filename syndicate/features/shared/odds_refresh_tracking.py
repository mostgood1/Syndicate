from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from syndicate.features.shared.basketball_props_tracking import sync_basketball_props_tracking_for_source_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _choose_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _coalesce_series(df: pd.DataFrame, candidates: list[str], default: Any = "") -> pd.Series:
    for column in candidates:
        if column in df.columns:
            return df[column]
    return pd.Series(default, index=df.index)


def _to_snapshot_ts(df: pd.DataFrame, *, fallback_ts: str) -> pd.Series:
    for column in ("snapshot_ts", "last_seen_at", "first_seen_at", "retrieved_at", "pulled_at"):
        if column in df.columns:
            values = pd.to_datetime(df[column], errors="coerce", utc=True)
            if values.notna().any():
                return values.fillna(pd.Timestamp(fallback_ts, tz="UTC")).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return pd.Series(fallback_ts, index=df.index)


def _persist_tracking_snapshot(
    *,
    tracking_root: Path,
    prefix: str,
    scope: str,
    snapshot_df: pd.DataFrame,
    key_cols: list[str],
    line_col: str | None,
    price_cols: list[str],
    label_cols: list[str] | None = None,
) -> dict[str, Any]:
    tracking_root.mkdir(parents=True, exist_ok=True)
    opening_path = tracking_root / f"{prefix}_opening_{scope}.csv"
    history_path = tracking_root / f"{prefix}_history_{scope}.csv"
    movement_path = tracking_root / f"{prefix}_movement_signals_{scope}.csv"

    normalized = snapshot_df.copy() if isinstance(snapshot_df, pd.DataFrame) else pd.DataFrame()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "empty_snapshot",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    required_cols = list(dict.fromkeys(key_cols + ([line_col] if line_col else []) + price_cols + ["snapshot_ts"]))
    if label_cols:
        required_cols.extend([col for col in label_cols if col not in required_cols])
    for column in required_cols:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    normalized = normalized[required_cols].copy()
    normalized["snapshot_ts"] = pd.to_datetime(normalized["snapshot_ts"], errors="coerce", utc=True)
    normalized = normalized[normalized["snapshot_ts"].notna()].copy()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "missing_snapshot_ts",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    normalized = normalized.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").reset_index(drop=True)
    existing_history = _read_csv(history_path)
    if existing_history.empty:
        combined_history = normalized.copy()
    else:
        for column in normalized.columns:
            if column not in existing_history.columns:
                existing_history[column] = pd.NA
        existing_history = existing_history[normalized.columns].copy()
        existing_history["snapshot_ts"] = pd.to_datetime(existing_history["snapshot_ts"], errors="coerce", utc=True)
        combined_history = pd.concat([existing_history, normalized], ignore_index=True, sort=False)
        dedupe_cols = [col for col in normalized.columns if col != "snapshot_ts"] + ["snapshot_ts"]
        combined_history = combined_history.drop_duplicates(subset=dedupe_cols, keep="first")
        combined_history = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").reset_index(drop=True)
    combined_history_to_write = combined_history.copy()
    combined_history_to_write["snapshot_ts"] = combined_history_to_write["snapshot_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    combined_history_to_write.to_csv(history_path, index=False)

    opening = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).first()
    opening_to_write = opening.copy()
    opening_to_write["snapshot_ts"] = pd.to_datetime(opening_to_write["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    opening_to_write.to_csv(opening_path, index=False)

    latest = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).last()
    movement = latest.merge(
        opening[key_cols + ([line_col] if line_col else []) + price_cols].rename(
            columns={
                **({line_col: "open_line"} if line_col else {}),
                **{column: f"open_{column}" for column in price_cols},
            }
        ),
        on=key_cols,
        how="left",
    )
    movement = movement.rename(columns={line_col: "current_line"} if line_col else {})
    for column in price_cols:
        movement = movement.rename(columns={column: f"current_{column}"})
    if line_col:
        movement["line_move"] = pd.to_numeric(movement.get("current_line"), errors="coerce") - pd.to_numeric(movement.get("open_line"), errors="coerce")
    for column in price_cols:
        movement[f"{column}_move"] = pd.to_numeric(movement.get(f"current_{column}"), errors="coerce") - pd.to_numeric(movement.get(f"open_{column}"), errors="coerce")
    movement["latest_snapshot_ts"] = pd.to_datetime(movement["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    movement = movement.drop(columns=["snapshot_ts"], errors="ignore")
    movement.to_csv(movement_path, index=False)

    return {
        "ok": True,
        "skipped": False,
        "opening_path": str(opening_path),
        "history_path": str(history_path),
        "movement_path": str(movement_path),
        "opening_rows": int(len(opening)),
        "history_rows": int(len(combined_history)),
        "signals_rows": int(len(movement)),
    }


def _build_nhl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event_id", "game_id", "date"], default="")
    out["player_key"] = _coalesce_series(df, ["player_id", "_merge_key", "player_name", "player"], default="")
    out["player_name"] = _coalesce_series(df, ["player_name", "player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book", "bookmaker"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line", "point"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_ncaab_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    home = _coalesce_series(df, ["home_team", "home", "team_home"], default="")
    away = _coalesce_series(df, ["away_team", "away", "team_away"], default="")
    event_id = _coalesce_series(df, ["event_id", "id"], default="")
    out["event_key"] = event_id.where(event_id.astype(str).str.strip().ne(""), away.astype(str) + " @ " + home.astype(str))
    out["book"] = _coalesce_series(df, ["bookmaker_key", "bookmaker", "provider", "book"], default="")
    out["market"] = _coalesce_series(df, ["market", "market_key"], default="")
    out["selection"] = _coalesce_series(df, ["outcome_name", "name", "team"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["point", "line", "spread", "overUnder"], default=pd.NA), errors="coerce")
    out["price"] = pd.to_numeric(_coalesce_series(df, ["price", "odds", "homeMoneyline", "awayMoneyline"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_nfl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event", "event_id"], default="")
    out["player_name"] = _coalesce_series(df, ["player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _flatten_team_lines_payload(payload: dict[str, Any], *, fallback_ts: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    lines = ((payload or {}).get("lines") or {}) if isinstance(payload, dict) else {}
    snapshot_ts = str((payload or {}).get("fetched_at") or fallback_ts)
    for event_key, event_payload in lines.items():
        event_data = event_payload or {}
        moneyline = event_data.get("moneyline") or {}
        for side in ("home", "away"):
            price = moneyline.get(side)
            if price is not None:
                rows.append({
                    "event_key": event_key,
                    "market": "moneyline",
                    "selection": side,
                    "line": pd.NA,
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
        total_runs = event_data.get("total_runs") or {}
        if total_runs:
            for side in ("over", "under"):
                price = total_runs.get(side)
                if price is not None:
                    rows.append({
                        "event_key": event_key,
                        "market": "total",
                        "selection": side,
                        "line": total_runs.get("line"),
                        "price": price,
                        "snapshot_ts": snapshot_ts,
                    })
        run_line = event_data.get("run_line") or {}
        if run_line:
            rows.append({
                "event_key": event_key,
                "market": "spread",
                "selection": "home",
                "line": run_line.get("home"),
                "price": pd.NA,
                "snapshot_ts": snapshot_ts,
            })
    return pd.DataFrame(rows)


def _flatten_mlb_game_lines(path: Path) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for game in payload.get("games") or []:
        event_key = f"{game.get('away_team', '')} @ {game.get('home_team', '')}".strip()
        segments = ((game.get("markets") or {}).get("segments") or {"full": game.get("markets") or {}})
        for segment_name, segment_payload in segments.items():
            if not isinstance(segment_payload, dict):
                continue
            h2h = segment_payload.get("h2h") or {}
            for side in ("home", "away"):
                odds_key = f"{side}_odds"
                if odds_key in h2h:
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "moneyline",
                        "selection": side,
                        "line": pd.NA,
                        "price": h2h.get(odds_key),
                        "snapshot_ts": snapshot_ts,
                    })
            spreads = segment_payload.get("spreads") or {}
            if spreads:
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_home",
                    "selection": "home",
                    "line": spreads.get("home_line"),
                    "price": spreads.get("home_odds"),
                    "snapshot_ts": snapshot_ts,
                })
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_away",
                    "selection": "away",
                    "line": spreads.get("away_line"),
                    "price": spreads.get("away_odds"),
                    "snapshot_ts": snapshot_ts,
                })
            totals = segment_payload.get("totals") or {}
            if totals:
                for side in ("over", "under"):
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "total",
                        "selection": side,
                        "line": totals.get("line"),
                        "price": totals.get(f"{side}_odds"),
                        "snapshot_ts": snapshot_ts,
                    })
    return pd.DataFrame(rows)


def _flatten_mlb_props(path: Path, root_key: str) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for player_name, markets in (payload.get(root_key) or {}).items():
        for market_name, market_payload in (markets or {}).items():
            if not isinstance(market_payload, dict):
                continue
            for side in ("over", "under"):
                price = market_payload.get(f"{side}_odds")
                if price is None:
                    continue
                rows.append({
                    "player_name": player_name,
                    "market": market_name,
                    "selection": side,
                    "line": market_payload.get("line"),
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
    return pd.DataFrame(rows)


def _sync_csv_tracking(*, tracking_root: Path, prefix: str, scope: str, snapshot_df: pd.DataFrame, key_cols: list[str], line_col: str, price_cols: list[str], label_cols: list[str] | None = None) -> dict[str, Any]:
    return _persist_tracking_snapshot(
        tracking_root=tracking_root,
        prefix=prefix,
        scope=scope,
        snapshot_df=snapshot_df,
        key_cols=key_cols,
        line_col=line_col,
        price_cols=price_cols,
        label_cols=label_cols,
    )


def _infer_nfl_week_scope(source_root: Path) -> tuple[str, Path | None]:
    current_week_path = _choose_existing([source_root / "current_week.json", source_root / "source_artifacts" / "current_week.json"])
    if current_week_path is not None and current_week_path.exists():
        payload = _read_json(current_week_path)
        if isinstance(payload, dict):
            season = payload.get("season")
            week = payload.get("week")
            if season and week:
                path = _choose_existing([
                    source_root / f"oddsapi_player_props_{season}_wk{week}.csv",
                    source_root / "source_artifacts" / f"oddsapi_player_props_{season}_wk{week}.csv",
                ])
                return f"{season}_wk{week}", path
    candidates = sorted(
        list(source_root.glob("oddsapi_player_props_*.csv")) + list((source_root / "source_artifacts").glob("oddsapi_player_props_*.csv")),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        stem = candidates[0].stem.replace("oddsapi_player_props_", "")
        return stem, candidates[0]
    return "unknown", None


def sync_sport_post_refresh_tracking(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    if slug in {"nba", "wnba"}:
        return sync_basketball_props_tracking_for_source_root(sport=slug, source_root=source_root, date_str=date_str)

    tracking_root = source_root / "tracking"
    results: dict[str, Any] = {"ok": True, "sport": slug, "date": date_str, "tracking_root": str(tracking_root), "artifacts": {}}

    if slug == "nhl":
        props_path = source_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv"
        team_path = source_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv"
        props_df = _build_nhl_props_snapshot(props_path)
        team_df = _build_ncaab_snapshot(team_path)
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_player_props",
            scope=date_str,
            snapshot_df=props_df,
            key_cols=["event_key", "player_key", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
            label_cols=["player_name"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        return results

    if slug == "nfl":
        scope, props_path = _infer_nfl_week_scope(source_root)
        props_df = _build_nfl_props_snapshot(props_path) if props_path is not None else pd.DataFrame()
        team_candidates = sorted(
            list(source_root.glob("real_betting_lines_*.json")) + list((source_root / "source_artifacts").glob("real_betting_lines_*.json")),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        team_df = _flatten_team_lines_payload(_read_json(team_candidates[0]), fallback_ts=_utc_now()) if team_candidates else pd.DataFrame()
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_player_props",
            scope=scope,
            snapshot_df=props_df,
            key_cols=["event_key", "player_name", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        return results

    if slug == "mlb":
        snapshot_root = source_root / "source_artifacts" / "data" / "daily" / "snapshots" / date_str
        if not snapshot_root.exists():
            snapshot_root = source_root / "data" / "daily" / "snapshots" / date_str
        date_slug = date_str.replace("-", "_")
        game_df = _flatten_mlb_game_lines(snapshot_root / f"oddsapi_game_lines_{date_slug}.json")
        hitter_df = _flatten_mlb_props(snapshot_root / f"oddsapi_hitter_props_{date_slug}.json", "hitter_props")
        pitcher_df = _flatten_mlb_props(snapshot_root / f"oddsapi_pitcher_props_{date_slug}.json", "pitcher_props")
        results["artifacts"]["game_lines"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_game_lines",
            scope=date_str,
            snapshot_df=game_df,
            key_cols=["event_key", "segment", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["hitter_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_hitter_props",
            scope=date_str,
            snapshot_df=hitter_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["pitcher_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_pitcher_props",
            scope=date_str,
            snapshot_df=pitcher_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        return results

    if slug == "ncaab":
        odds_path = source_root / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        if not odds_path.exists():
            odds_path = source_root / "data" / "ncaab_source" / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        team_df = _build_ncaab_snapshot(odds_path)
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_ncaab_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        return results

    if slug == "ncaaf":
        artifact_root = source_root / "source_artifacts"
        latest_predicted = sorted(artifact_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        manifest = {
            "sport": slug,
            "date": date_str,
            "generated_at": _utc_now(),
            "latest_predicted_totals": str(latest_predicted[0]) if latest_predicted else None,
            "predicted_totals_files": [str(path) for path in latest_predicted[:10]],
            "notes": "NCAAF currently mirrors schedule-enhanced totals snapshots rather than per-market odds rows; this manifest keeps the central post-refresh contract owned by Syndicate until a normalized lines snapshot is added.",
        }
        manifest_path = tracking_root / f"odds_ncaaf_source_manifest_{date_str}.json"
        _write_json(manifest_path, manifest)
        results["artifacts"]["source_manifest"] = {
            "ok": True,
            "skipped": False,
            "manifest_path": str(manifest_path),
            "predicted_totals_files": len(latest_predicted),
        }
        return results

    return {"ok": False, "sport": slug, "date": date_str, "error": f"unsupported_sport:{slug}"}


def sync_post_refresh_tracking_for_source_root(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    return sync_sport_post_refresh_tracking(sport=sport, source_root=source_root, date_str=date_str)