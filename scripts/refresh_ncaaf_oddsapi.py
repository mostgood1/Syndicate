from __future__ import annotations

import argparse
import contextlib
import csv
import errno
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PRED_FILES_GLOB = "college_football_schedule_*_predicted_totals_enhanced*.csv"
_SPACE_RE = re.compile(r"\s+")

DIRECTORIES = (
    "recommendations_summary",
)

ALIASES = {
    "miami oh": "miami ohio",
    "miami ohio": "miami ohio",
    "ole miss": "mississippi",
    "miss st": "mississippi state",
    "utsa": "texas san antonio",
    "ut san antonio": "texas san antonio",
    "utsa roadrunners": "texas san antonio",
    "app state": "appalachian state",
    "appalachian st": "appalachian state",
    "app st": "appalachian state",
    "southern miss": "southern mississippi",
    "hawaii": "hawaii",
    "la lafayette": "louisiana",
    "louisiana lafayette": "louisiana",
    "la monroe": "louisiana monroe",
    "umass": "massachusetts",
    "uconn": "connecticut",
    "byu cougars": "byu",
    "central florida": "ucf",
    "central florida knights": "ucf",
    "south florida": "usf",
    "south florida bulls": "usf",
    "louisiana state": "lsu",
    "louisiana state tigers": "lsu",
    "texas christian": "tcu",
    "texas christian horned frogs": "tcu",
    "southern california": "usc",
    "southern california trojans": "usc",
    "southern methodist": "smu",
    "southern methodist mustangs": "smu",
    "alabama birmingham": "uab",
    "alabama birmingham blazers": "uab",
    "texas el paso": "utep",
    "texas el paso miners": "utep",
    "texas a&m": "texas am",
    "texas a and m": "texas am",
    "penn st": "penn state",
    "penn state nittany lions": "penn state",
    "mich st": "michigan state",
    "michigan st": "michigan state",
    "florida st": "florida state",
    "florida state seminoles": "florida state",
    "boise st": "boise state",
    "boise state broncos": "boise state",
    "san josé state": "san jose state",
    "sjsu": "san jose state",
    "miami fl": "miami",
    "miami florida": "miami",
    "ole miss rebels": "mississippi",
    "arkansas razorbacks": "arkansas",
    "umass minutemen": "massachusetts",
    "notre dame fighting irish": "notre dame",
    "texas a m aggies": "texas am",
    "texas am aggies": "texas am",
    "texas a and m aggies": "texas am",
    "miami hurricanes": "miami",
    "florida gators": "florida",
    "georgia bulldogs": "georgia",
    "alabama crimson tide": "alabama",
    "oregon ducks": "oregon",
    "nebraska cornhuskers": "nebraska",
    "michigan wolverines": "michigan",
    "lsu tigers": "lsu",
    "uconn huskies": "connecticut",
    "delaware blue hens": "delaware",
    "sam houston state": "sam houston",
    "sam houston bearkats": "sam houston",
    "sam houston state bearkats": "sam houston",
    "new mexico st": "new mexico state",
    "new mexico state aggies": "new mexico state",
}


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination)
    return True


def _copy_tree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_dir():
        return False
    try:
        if source.resolve() == destination.resolve():
            return True
    except Exception:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    _copy_tree_with_fallback(source, destination)
    return True


def _copy_file_with_fallback(source: Path, destination: Path) -> None:
    try:
        shutil.copy2(source, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise
    source_fd = os.open(str(source), os.O_RDONLY)
    try:
        destination_fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                os.write(destination_fd, chunk)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    with contextlib.suppress(OSError):
        shutil.copystat(source, destination)


def _copy_tree_with_fallback(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for root, _dirs, files in os.walk(source):
        root_path = Path(root)
        relative_root = root_path.relative_to(source)
        target_root = destination / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            _copy_file_with_fallback(root_path / file_name, target_root / file_name)


def _base_norm(name: str) -> str:
    try:
        if source.resolve() == destination.resolve():
            return True
    except Exception:
        pass
    try:
        text = str(name or "")
    except Exception:
        return ""


def _resolve_data_root(*, source_root: Path | None, artifact_root: Path) -> Path:
    if source_root is not None:
        return source_root.resolve()
    if (artifact_root / PRED_FILES_GLOB.replace("*", "")).exists():
        return artifact_root.resolve()
    pattern_matches = list(artifact_root.glob(PRED_FILES_GLOB))
    if pattern_matches:
        return artifact_root.resolve()
    raise FileNotFoundError("NCAAF runner needs --source-root or an --artifact-root containing the predicted schedule CSV.")
    text = text.strip().lower().replace("&", " and ")
    text = text.replace("ʻ", "'").replace("’", "'")
    text = re.sub(r"[^a-z0-9 '\-]", " ", text)
    text = text.replace("hawai'i", "hawaii")
    return _SPACE_RE.sub(" ", text).strip()


def _norm_team(name: str) -> str:
    base = _base_norm(name)
    return ALIASES.get(base, base)


def _best_schedule_norm(raw: str, schedule_norm_set: set[str]) -> str:
    normalized = _norm_team(raw)
    if normalized in schedule_norm_set:
        return normalized
    tokens = normalized.split()
    while len(tokens) > 1:
        tokens = tokens[:-1]
        candidate = " ".join(tokens)
        if candidate in schedule_norm_set:
            return candidate
    return normalized


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_int(value: object) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def _has_value(value: object) -> bool:
    return str(value or "").strip() not in {"", "nan", "None"}


def _parse_utc_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _prediction_files(source_root: Path) -> list[Path]:
    data_root = source_root / "data"
    return sorted(data_root.glob(PRED_FILES_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)


def _prediction_context(source_root: Path) -> dict[str, Any]:
    for path in _prediction_files(source_root):
        try:
            rows = _read_csv_rows(path)
        except Exception:
            continue
        if not rows or "season" not in rows[0]:
            continue
        seasons = sorted({_parse_int(row.get("season")) for row in rows if _parse_int(row.get("season")) is not None}, reverse=True)
        if not seasons:
            continue
        latest_game_dt = None
        parsed_dates = [
            parsed
            for parsed in (
                _parse_utc_datetime(row.get("start_date_api") or row.get("start_date"))
                for row in rows
            )
            if parsed is not None
        ]
        if parsed_dates:
            latest_game_dt = max(parsed_dates)
        return {
            "path": path,
            "rows": rows,
            "season": int(seasons[0]),
            "latest_game_dt": latest_game_dt,
        }
    raise FileNotFoundError(f"No predictions files found under {source_root / 'data'}")


def _lines_file_name(season: int) -> str:
    return f"college_football_betting_lines_{int(season)}.csv"


def _root_files_for_season(season: int) -> tuple[str, ...]:
    return (
        "recommendations_latest.json",
        f"recommendations_{int(season)}.csv",
        _lines_file_name(int(season)),
    )


def _should_skip_auto_refresh(*, prediction_season: int, latest_game_dt: datetime | None) -> bool:
    now_utc = datetime.now(timezone.utc)
    if latest_game_dt is not None and latest_game_dt < (now_utc - timedelta(days=30)):
        return True
    return int(prediction_season) < int(now_utc.year)


def _select_predictions_rows(source_root: Path, week: int) -> list[dict[str, str]]:
    context = _prediction_context(source_root)
    season = int(context["season"])
    subset = [row for row in context["rows"] if _parse_int(row.get("season")) == season and _parse_int(row.get("week")) == week]
    if subset:
        return subset
    raise FileNotFoundError(f"No predictions file with season {season} week {week} found under {source_root / 'data'}")


def _detect_upcoming_week(source_root: Path) -> int | None:
    context = _prediction_context(source_root)
    season = int(context["season"])
    subset = [row for row in context["rows"] if _parse_int(row.get("season")) == season]
    done = [row for row in subset if _has_value(row.get("actual_home_points")) and _has_value(row.get("actual_away_points")) and _parse_int(row.get("week")) is not None]
    if done:
        return max(_parse_int(row.get("week")) or 0 for row in done) + 1
    available_weeks = [_parse_int(row.get("week")) for row in subset]
    available_weeks = [week_value for week_value in available_weeks if week_value is not None]
    if available_weeks:
        return min(available_weeks)
    return None


def _fetch_odds(*, api_key: str, sport: str, regions: str, markets: str, odds_format: str) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "apiKey": api_key,
        }
    )
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?{query}"
    try:
        with urlopen(url, timeout=15) as response:
            payload = response.read().decode("utf-8")
            status_code = getattr(response, "status", 200)
    except Exception as exc:
        raise RuntimeError(f"Odds API request failed: {exc}") from exc
    if status_code != 200:
        raise RuntimeError(f"Odds API error {status_code}: {payload[:400]}")
    return json.loads(payload)


def _extract_markets(bookmaker: dict[str, Any], home_team: str, away_team: str) -> dict[str, Any]:
    spread_val = None
    total_val = None
    home_ml = None
    away_ml = None
    home_norm = _norm_team(home_team)
    away_norm = _norm_team(away_team)

    def _belongs(outcome_name: str, base_name: str) -> bool:
        if outcome_name == base_name:
            return True
        return outcome_name.startswith(base_name + " ")

    for market in bookmaker.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])
        if key == "spreads":
            for outcome in outcomes:
                team_name = _norm_team(outcome.get("name", ""))
                if _belongs(team_name, home_norm):
                    try:
                        spread_val = float(outcome.get("point"))
                    except Exception:
                        pass
                elif _belongs(team_name, away_norm) and spread_val is None:
                    try:
                        spread_val = -float(outcome.get("point"))
                    except Exception:
                        pass
        elif key == "totals":
            for outcome in outcomes:
                try:
                    total_val = float(outcome.get("point"))
                except Exception:
                    continue
                break
        elif key == "h2h":
            for outcome in outcomes:
                team_name = _norm_team(outcome.get("name", ""))
                if _belongs(team_name, home_norm):
                    home_ml = outcome.get("price")
                elif _belongs(team_name, away_norm):
                    away_ml = outcome.get("price")

    return {
        "provider": bookmaker.get("title") or bookmaker.get("key"),
        "spread": spread_val,
        "formattedSpread": (f"{home_team} {spread_val:+.1f}" if spread_val is not None else ""),
        "overUnder": total_val,
        "homeMoneyline": home_ml,
        "awayMoneyline": away_ml,
    }


def _build_lines_rows(source_root: Path, week: int, odds_events: list[dict[str, Any]], *, debug: bool = False) -> list[dict[str, Any]]:
    pred_rows = _select_predictions_rows(source_root, week)
    season = _parse_int((pred_rows[0] or {}).get("season")) if pred_rows else None
    schedule_index: dict[tuple[str, str], tuple[str, str]] = {}
    schedule_team_norms: set[str] = set()
    schedule_dates: dict[tuple[str, str], datetime] = {}

    for row in pred_rows:
        home_team = str(row["home_team"])
        away_team = str(row["away_team"])
        norm_home = _norm_team(home_team)
        norm_away = _norm_team(away_team)
        schedule_index[(norm_home, norm_away)] = (home_team, away_team)
        schedule_team_norms.update((norm_home, norm_away))
        start_date = _parse_utc_datetime(row.get("start_date"))
        if start_date is not None:
            schedule_dates[(norm_home, norm_away)] = start_date
            schedule_dates[(norm_away, norm_home)] = start_date

    week_start = None
    week_end = None
    start_dates = [parsed for parsed in (_parse_utc_datetime(row.get("start_date")) for row in pred_rows) if parsed is not None]
    if start_dates:
        week_start = min(start_dates) - timedelta(days=3)
        week_end = max(start_dates) + timedelta(days=3)

    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []
    skipped_time = 0

    for event in odds_events:
        raw_home = event.get("home_team")
        raw_away = event.get("away_team")
        if not raw_home or not raw_away:
            continue
        norm_home = _best_schedule_norm(raw_home, schedule_team_norms)
        norm_away = _best_schedule_norm(raw_away, schedule_team_norms)
        key = (norm_home, norm_away)
        if key not in schedule_index:
            reverse_key = (norm_away, norm_home)
            if reverse_key in schedule_index:
                key = reverse_key
            else:
                unmatched.append({"home": str(raw_home), "away": str(raw_away)})
                continue

        commence_time = event.get("commence_time") or event.get("commenceTime")
        if commence_time:
            commence_dt = _parse_utc_datetime(commence_time)
            if commence_dt is not None:
                game_dt = schedule_dates.get(key)
                if game_dt is not None:
                    if commence_dt < (game_dt - timedelta(days=3)) or commence_dt > (game_dt + timedelta(days=3)):
                        skipped_time += 1
                        continue
                elif week_start is not None and week_end is not None:
                    if commence_dt < week_start or commence_dt > week_end:
                        skipped_time += 1
                        continue

        sched_home, sched_away = schedule_index[key]
        providers = []
        for bookmaker in event.get("bookmakers", []):
            try:
                providers.append(_extract_markets(bookmaker, sched_home, sched_away))
            except Exception:
                continue
        if not providers:
            continue
        rows.append(
            {
                "year": int(season or 0),
                "week": week,
                "homeTeam": sched_home,
                "awayTeam": sched_away,
                "lines": json.dumps(providers, separators=(",", ":")),
            }
        )

    if unmatched:
        print(f"[warn] Unmatched odds events: {len(unmatched)}", file=sys.stderr)
    if skipped_time and debug:
        print(f"[info] Skipped events outside inferred week window: {skipped_time}", file=sys.stderr)
    return rows


def _merge_and_write(source_root: Path, rows: list[dict[str, Any]], season: int, week: int) -> dict[str, Any]:
    lines_path = source_root / "data" / _lines_file_name(season)
    if lines_path.exists():
        try:
            old_rows = _read_csv_rows(lines_path)
        except Exception:
            old_rows = []
    else:
        old_rows = []

    def _row_key(row: dict[str, Any]) -> tuple[int, int, str, str] | None:
        year_value = _parse_int(row.get("year"))
        week_value = _parse_int(row.get("week"))
        if year_value is None or week_value is None:
            return None
        return (year_value, week_value, str(row.get("homeTeam", "")), str(row.get("awayTeam", "")))

    new_keys = {_row_key(row) for row in rows if _row_key(row) is not None}
    keep_rows = [row for row in old_rows if not (_parse_int(row.get("year")) == int(season) and _parse_int(row.get("week")) == week)]
    preserved_same_week = [row for row in old_rows if _parse_int(row.get("year")) == int(season) and _parse_int(row.get("week")) == week and _row_key(row) not in new_keys]
    merged = keep_rows + preserved_same_week + rows
    merged.sort(key=lambda row: (_parse_int(row.get("year")) or 0, _parse_int(row.get("week")) or 0, str(row.get("homeTeam", "")), str(row.get("awayTeam", ""))))

    lines_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = lines_path.with_suffix(lines_path.suffix + ".tmp")
    fieldnames = ["year", "week", "homeTeam", "awayTeam", "lines"]
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    os.replace(tmp_path, lines_path)
    return {
        "written_rows": len(rows),
        "preserved_rows": len(preserved_same_week),
        "total_rows": len(merged),
        "path": str(lines_path),
    }


def _run_refresh(*, source_root: Path, week: int, api_key: str, debug: bool = False) -> dict[str, Any]:
    context = _prediction_context(source_root)
    season = int(context["season"])
    sport = os.environ.get("ODDS_API_SPORT", "americanfootball_ncaaf")
    regions = os.environ.get("ODDS_API_REGIONS", "us,us2,eu,uk")
    markets = os.environ.get("ODDS_API_MARKETS", "h2h,spreads,totals")
    odds_format = os.environ.get("ODDS_API_ODDS_FORMAT", "american")
    print(f"[info] Fetching OddsAPI sport={sport} season={season} week={week} regions={regions} markets={markets}")
    events = _fetch_odds(api_key=api_key, sport=sport, regions=regions, markets=markets, odds_format=odds_format)
    rows = _build_lines_rows(source_root, week, events, debug=debug)
    if not rows:
        return {"status": "empty", "season": season, "week": week, "matched_games": 0, "pred_games_in_week": len(_select_predictions_rows(source_root, week))}
    result = _merge_and_write(source_root, rows, season, week)
    return {
        "status": "ok",
        "season": season,
        "week": week,
        **result,
        "matched_games": len(rows),
        "pred_games_in_week": len(_select_predictions_rows(source_root, week)),
    }


def _materialize_artifact_bundle(*, source_root: Path, artifact_root: Path) -> dict[str, object]:
    source_data_root = source_root / "data"
    copied: dict[str, object] = {}
    context = _prediction_context(source_root)
    season = int(context["season"])

    for name in _root_files_for_season(season):
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    source = Path(context["path"])
    destination = artifact_root / source.name
    if _copy_if_exists(source, destination):
        copied.setdefault("files", []).append(str(destination))

    for name in DIRECTORIES:
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_tree_if_exists(source, destination):
            copied.setdefault("directories", []).append(str(destination))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NCAAF OddsAPI lines through a Syndicate-owned runner.")
    parser.add_argument("--source-root", required=False)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "ncaaf_source" / "source_artifacts"))
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else None
    data_root = _resolve_data_root(source_root=source_root, artifact_root=artifact_root)
    prediction_context = _prediction_context(data_root)
    prediction_season = int(prediction_context["season"])
    api_key = args.api_key or os.environ.get("ODDS_API_KEY")
    week = args.week if args.week is not None else _detect_upcoming_week(data_root)

    if args.week is None and _should_skip_auto_refresh(prediction_season=prediction_season, latest_game_dt=prediction_context.get("latest_game_dt")):
        copied = _materialize_artifact_bundle(source_root=data_root, artifact_root=artifact_root)
        print(
            json.dumps(
                {
                    "ok": True,
                    "status": "skipped",
                    "reason": "stale_source_season",
                    "season": prediction_season,
                    "latest_game_dt": prediction_context.get("latest_game_dt").isoformat() if prediction_context.get("latest_game_dt") else None,
                    "artifact_bundle_root": str(artifact_root),
                    "artifact_bundle_files": copied,
                },
                indent=2,
            )
        )
        return 0

    if not api_key:
        print(json.dumps({"ok": False, "error": "Missing Odds API key (provide --api-key or set ODDS_API_KEY)."}))
        return 2
    if week is None:
        print(json.dumps({"ok": False, "error": "Could not determine upcoming week."}))
        return 3

    try:
        result = _run_refresh(source_root=data_root, week=week, api_key=api_key, debug=args.debug)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if result.get("status") == "empty":
        print("[warn] No rows matched schedule / produced provider lines; nothing written.")
    else:
        print(json.dumps(result, indent=2))

    copied = _materialize_artifact_bundle(source_root=data_root, artifact_root=artifact_root)
    print(
        json.dumps(
            {
                "ok": True,
                "season": prediction_season,
                "week": week,
                "artifact_bundle_root": str(artifact_root),
                "refresh_result": result,
                "artifact_bundle_files": copied,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())