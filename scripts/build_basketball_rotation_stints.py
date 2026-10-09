"""NBA / WNBA / NCAAB rotation stints from completed games' ESPN play-by-play -- Syndicate-owned.

WHY (phase P2 of `docs/ai_context/basketball_live_native_plan.md`, lane `basketball-native-live-state`).
The smart sim reads `rotation_stints_history` for each team's minutes split and lineup pool
(`basketball_props_smart_sim._rotation_sim_minutes_from_history_local`, 28-day lookback, NBA same-phase
filter). Its only producer was the VENDORED CLI step `update-rotations-espn-history`, subprocessed once a
day for yesterday by `refresh_{nba,wnba}_oddsapi_props._ensure_rotation_inputs_for_props_refresh`.
Measured on the fleet 2026-10-09: NBA history 17 KB (preseason days only), WNBA 1,592 rows (2026-09 only).
That builder also never inferred period-start lineups (a substitution made between periods is not in
ESPN's log at all) and padded short lineups from the roster in arbitrary order. User decision 2026-10-09:
nothing on the basketball live path relies on the vendored app. This replaces it.

WHAT IT WRITES under `<league>_source/data/processed/` (plain files on SYNDICATE_DATA_ROOT -- not the
keyvalue store, which refuses writes over 8 MB):
  * `rotation_stints/stints_<YYYY-MM-DD>.csv`        DATED: every lineup stint of every final that day
  * `rotation_stints/player_stints_<YYYY-MM-DD>.csv` DATED: per player, contiguous on-floor intervals
  * `rotation_stints/games_<YYYY-MM-DD>.csv`         DATED: per game, reconstructed vs official score,
                                                      anomalies, phase -- the verification evidence
  * `rotation_stints/player_checks_<YYYY-MM-DD>.csv` DATED: per player-game, stint minutes vs box
                                                      minutes, play-by-play PF vs box PF
  * `rotation_stints/_dates.json`                    which dates are complete (incremental runs)
  * `pbp_events/<season>/<event_id>.jsonl.gz`        the normalised event log per game (P3's backtest
                                                      substrate; replays without refetching ESPN)
  * `rotation_stints_history.csv` + `.parquet`       every dated stints file, consolidated -- the table
                                                      the sim reads (parquet first). Columns are a
                                                      superset of the vendored builder's.
  * `rotation_stints_<season>_<phase>.csv`           one table per (season, phase): preseason, regular,
                                                      play-in and playoffs are separate populations and a
                                                      fit must pick one (learnings: season-phase models)

`season` is ESPN's season year -- the year the season ENDS (NBA 2026 = 2025-26, WNBA 2026 = 2026,
NCAAB 2026 = 2025-26), as `build_ncaab_team_ratings.py`. A date is complete when every event on it is
final or postponed/canceled; today and later are never read.

    python scripts/build_basketball_rotation_stints.py                          # all leagues, incremental
    python scripts/build_basketball_rotation_stints.py --league nba --season 2026 --full
    python scripts/build_basketball_rotation_stints.py --league ncaab --start 2026-02-14 --end 2026-02-14

Run backfills at low priority (`nice -n 19` / Idle): the fleet shares this machine.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import basketball_pbp as pbp  # noqa: E402

LEAGUES = ("nba", "wnba", "ncaab")
SOURCE = "syndicate_espn_pbp_v1"
STINT_FIELDS = (
    "league", "season", "season_type", "date", "game_id", "event_id", "team", "team_id", "opp", "side", "period",
    "start_sec", "end_sec", "duration_sec", "lineup_player_ids", "lineup_size", "pts_for", "pts_against", "source",
)
PLAYER_STINT_FIELDS = (
    "league", "season", "season_type", "date", "event_id", "team", "side", "player_id", "player_name", "period",
    "in_sec", "out_sec", "duration_sec", "pts_for", "pts_against",
)
GAME_FIELDS = (
    "league", "season", "season_type", "date", "event_id", "home", "away", "official_home", "official_away",
    "pbp_home", "pbp_away", "running_home", "running_away", "score_match", "plays", "stints", "anomalies",
    "notes", "source",
)
PAIR_FIELDS = (
    "league", "season", "season_type", "date", "game_id", "event_id", "team", "player1_id", "player2_id",
    "sec_together", "segments", "min_together",
)
# The columns `lineup_context_features.build_lineup_teammate_effects` reads from play_context_history
# (the vendored builder wrote these names; kept so that reader keeps working until P3 replaces it).
CONTEXT_FIELDS = (
    "league", "season", "season_type", "date", "game_id", "event_id", "play_id", "sequence", "period", "clock_sec_remaining",
    "abs_time_sec", "type", "kind", "text", "team", "home_team", "away_team", "scoring_play", "shooting_play", "score_value",
    "points_attempted", "participant1_id", "participant2_id", "enter_player_id", "exit_player_id",
    "home_lineup_player_ids", "away_lineup_player_ids", "source",
)
CHECK_FIELDS = (
    "league", "season", "season_type", "date", "event_id", "team", "player_id", "player_name", "starter",
    "box_minutes", "stint_minutes", "minutes_diff", "within_1", "box_pf", "pbp_pf",
)
# ESPN season year Y -> the calendar window that can hold that season (preseason through finals)
WINDOWS = {
    "nba": lambda y: (dt.date(y - 1, 10, 1), dt.date(y, 6, 30)),
    "wnba": lambda y: (dt.date(y, 4, 20), dt.date(y, 10, 31)),
    "ncaab": lambda y: (dt.date(y - 1, 11, 1), dt.date(y, 4, 15)),
}
STALE_PENDING_DAYS = 7
NOT_PLAYED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_FORFEIT", "STATUS_SUSPENDED"}


# ----------------------------------------------------------------------------------------- paths

def source_root(league: str) -> Path:
    override = str(os.environ.get(f"SYNDICATE_{league.upper()}_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / f"{league}_source"


def processed_dir(league: str) -> Path:
    return source_root(league) / "data" / "processed"


def stints_dir(league: str) -> Path:
    return processed_dir(league) / "rotation_stints"


def current_season(league: str, today: dt.date) -> int:
    """The season containing `today`, or the most recent one in the offseason."""
    for year in (today.year + 1, today.year, today.year - 1):
        start, end = WINDOWS[league](year)
        if start <= today <= end:
            return year
    starts = [(WINDOWS[league](y)[0], y) for y in (today.year + 1, today.year, today.year - 1)]
    return max(y for s, y in starts if s <= today)


def season_dates(league: str, season: int, today: dt.date) -> list[dt.date]:
    start, end = WINDOWS[league](season)
    end = min(end, today - dt.timedelta(days=1))
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)] if end >= start else []


# ------------------------------------------------------------------------------------------- io

def _atomic_write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    n = 0
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            n += 1
    os.replace(tmp, path)
    return n


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_context(path: Path, rows: list[dict[str, Any]]) -> None:
    """Play context is ~450 rows a game: parquet, not csv (an NBA season of csv would be ~0.5 GB)."""
    import pandas as pd

    frame = pd.DataFrame(rows, columns=list(CONTEXT_FIELDS))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def load_dates_index(league: str) -> dict[str, Any]:
    path = stints_dir(league) / "_dates.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def save_dates_index(league: str, index: dict[str, Any]) -> None:
    _atomic_write_text(stints_dir(league) / "_dates.json", json.dumps(dict(sorted(index.items())), indent=1))


def write_events_log(league: str, season: int | None, event_id: str, events: list[pbp.PbpEvent]) -> Path:
    path = processed_dir(league) / "pbp_events" / str(season or "unknown") / f"{event_id}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for ev in events:
            handle.write(json.dumps(pbp.to_jsonable(ev), separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------------------------- one game

def game_tables(summary: dict[str, Any], league: str, date: str) -> dict[str, Any]:
    """Rows for every output table from one final game's summary."""
    rec = pbp.reconstruct(summary, league, date=date)
    meta = rec.meta
    base = {"league": league, "season": meta.season, "season_type": meta.season_type, "date": date, "event_id": meta.event_id}
    stint_rows = []
    for st in rec.stints:
        opp = meta.team("away" if st.side == "home" else "home")
        stint_rows.append({
            **base, "game_id": meta.event_id, "team": st.team, "team_id": meta.team(st.side).team_id, "opp": opp.code,
            "side": st.side, "period": st.period, "start_sec": round(st.start_elapsed, 1), "end_sec": round(st.end_elapsed, 1),
            "duration_sec": round(st.duration_sec, 1), "lineup_player_ids": ";".join(st.lineup), "lineup_size": len(st.lineup),
            "pts_for": st.pts_for, "pts_against": st.pts_against, "source": SOURCE,
        })
    player_rows = []
    for iv in pbp.player_intervals(rec.stints):
        box = meta.box.get(iv["player_id"])
        player_rows.append({
            **base, "team": iv["team"], "side": iv["side"], "player_id": iv["player_id"], "player_name": box.name if box else "",
            "period": iv["period"], "in_sec": round(iv["in_elapsed"], 1), "out_sec": round(iv["out_elapsed"], 1),
            "duration_sec": round(iv["duration_sec"], 1), "pts_for": iv["pts_for"], "pts_against": iv["pts_against"],
        })
    seconds = pbp.player_seconds(rec.stints)
    pf = pbp.personal_fouls(rec.events, league)
    check_rows = []
    for pid, box in meta.box.items():
        if box.did_not_play and seconds.get(pid, 0.0) <= 0:
            continue
        stint_min = seconds.get(pid, 0.0) / 60.0
        diff = None if box.minutes is None else round(stint_min - box.minutes, 2)
        check_rows.append({
            **base, "team": meta.team(box.side).code, "player_id": pid, "player_name": box.name, "starter": int(box.starter),
            "box_minutes": box.minutes, "stint_minutes": round(stint_min, 2), "minutes_diff": diff,
            "within_1": "" if diff is None else int(abs(diff) <= 1.0), "box_pf": box.pf, "pbp_pf": pf.get(pid, 0),
        })
    pair_rows = []
    for (side, p1, p2), (sec, n) in sorted(pbp.pair_seconds(rec.stints).items()):
        pair_rows.append({**base, "game_id": meta.event_id, "team": meta.team(side).code, "player1_id": p1, "player2_id": p2,
                          "sec_together": round(sec, 1), "segments": int(n), "min_together": round(sec / 60.0, 3)})
    context_rows = []
    for ev, (home_five, away_five) in zip(rec.events, rec.lineups_at):
        context_rows.append({
            **base, "game_id": meta.event_id, "play_id": ev.play_id, "sequence": ev.seq, "period": ev.period,
            "clock_sec_remaining": ev.clock_left, "abs_time_sec": round(ev.elapsed, 1), "type": ev.type_text, "kind": ev.kind,
            "text": ev.text, "team": meta.team(ev.side).code if ev.side else "", "home_team": meta.home.code, "away_team": meta.away.code,
            "scoring_play": bool(ev.points), "shooting_play": ev.shooting_play, "score_value": ev.points,
            "points_attempted": ev.points_attempted,
            "participant1_id": ev.players[0] if len(ev.players) > 0 else "", "participant2_id": ev.players[1] if len(ev.players) > 1 else "",
            "enter_player_id": ev.sub_in[0] if ev.sub_in else "", "exit_player_id": ev.sub_out[0] if ev.sub_out else "",
            "home_lineup_player_ids": ";".join(home_five), "away_lineup_player_ids": ";".join(away_five), "source": SOURCE,
        })
    score = pbp.reconstructed_score(rec.events)
    last_running = next(((e.home_score, e.away_score) for e in reversed(rec.events) if e.home_score is not None), (None, None))
    game_row = {
        **base, "home": meta.home.code, "away": meta.away.code, "official_home": meta.home.score, "official_away": meta.away.score,
        "pbp_home": score["home"], "pbp_away": score["away"], "running_home": last_running[0], "running_away": last_running[1],
        "score_match": int(score["home"] == meta.home.score and score["away"] == meta.away.score),
        "plays": len(rec.events), "stints": len(rec.stints), "anomalies": rec.anomalies,
        "notes": "|".join(rec.notes[:20]), "source": SOURCE,
    }
    return {"meta": meta, "events": rec.events, "stints": stint_rows, "players": player_rows, "checks": check_rows, "game": game_row,
            "pairs": pair_rows, "context": context_rows}


# ------------------------------------------------------------------------------------- one date

def build_date(league: str, day: dt.date, *, fetch_scoreboard: Callable | None = None, fetch_summary: Callable | None = None,
               rate: float = 0.3, keep_events: bool = True, today: dt.date | None = None) -> dict[str, Any]:
    """Fetch and write one date. Returns the `_dates.json` entry; `status` is done / empty / incomplete."""
    fetch_scoreboard = fetch_scoreboard or pbp.fetch_scoreboard
    fetch_summary = fetch_summary or pbp.fetch_summary
    today = today or dt.date.today()
    date = day.isoformat()
    events = pbp.scoreboard_events(fetch_scoreboard(league, day.strftime("%Y%m%d")))
    finals = [e for e in events if e["completed"] or e["state"] == "post"]
    pending = [e for e in events if e not in finals and e["status_name"] not in NOT_PLAYED]
    stale_pending = 0
    if pending:
        # A game still "scheduled" a week later was never played (ESPN leaves some NCAAB cancellations
        # unmarked). Waiting on it forever would keep the whole date -- and the job's exit code -- red.
        if (today - day).days < STALE_PENDING_DAYS:
            return {"status": "incomplete", "games": len(finals), "pending": len(pending)}
        stale_pending = len(pending)
    if not finals:
        return {"status": "empty", "games": 0, "built_at": _now()}
    out = {"stints": [], "players": [], "checks": [], "games": [], "pairs": [], "context": []}
    errors: list[str] = []
    for ev in finals:
        try:
            summary = fetch_summary(league, ev["event_id"])
            tables = game_tables(summary, league, date)
        except Exception as exc:  # noqa: BLE001 -- recorded; the date stays incomplete so it is retried
            errors.append(f"{ev['event_id']}:{type(exc).__name__}:{exc}"[:200])
            time.sleep(rate)
            continue
        if not tables["events"]:
            errors.append(f"{ev['event_id']}:no_plays")  # ESPN carries no play-by-play for this game
        for key, src in (("stints", "stints"), ("players", "players"), ("checks", "checks"), ("pairs", "pairs"), ("context", "context")):
            out[key].extend(tables[src])
        out["games"].append(tables["game"])
        if keep_events and tables["events"]:
            write_events_log(league, tables["meta"].season, tables["meta"].event_id, tables["events"])
        time.sleep(rate)
    base = stints_dir(league)
    _atomic_write_csv(base / f"stints_{date}.csv", STINT_FIELDS, out["stints"])
    _atomic_write_csv(base / f"player_stints_{date}.csv", PLAYER_STINT_FIELDS, out["players"])
    _atomic_write_csv(base / f"games_{date}.csv", GAME_FIELDS, out["games"])
    _atomic_write_csv(base / f"player_checks_{date}.csv", CHECK_FIELDS, out["checks"])
    _atomic_write_csv(base / f"pair_minutes_{date}.csv", PAIR_FIELDS, out["pairs"])
    _write_context(base / f"play_context_{date}.parquet", out["context"])
    fetch_errors = [e for e in errors if not e.endswith(":no_plays")]
    return {
        "status": "incomplete" if fetch_errors else "done",
        "games": len(out["games"]), "stints": len(out["stints"]), "no_plays": len(errors) - len(fetch_errors),
        "score_match": sum(int(g["score_match"]) for g in out["games"]), "stale_pending": stale_pending,
        "errors": errors[:10], "built_at": _now(),
    }


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------ consolidated tables

def rebuild_history(league: str) -> dict[str, Any]:
    """Consolidate every dated stints file into the sim-facing history and the per-(season, phase) tables."""
    import pandas as pd

    files = sorted(stints_dir(league).glob("stints_*.csv"))
    frames = []
    for path in files:
        try:
            frame = pd.read_csv(path, dtype={"lineup_player_ids": str, "event_id": str, "game_id": str, "team_id": str})
        except Exception:  # noqa: BLE001 -- an empty date file has a header only
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return {"rows": 0, "files": len(files)}
    hist = pd.concat(frames, ignore_index=True)
    hist = hist.drop_duplicates(subset=["event_id", "side", "start_sec", "end_sec", "lineup_player_ids"], keep="last")
    hist = hist.sort_values(["date", "event_id", "side", "start_sec"], kind="stable").reset_index(drop=True)
    root = processed_dir(league)
    csv_path = root / "rotation_stints_history.csv"
    pq_path = root / "rotation_stints_history.parquet"
    tmp_csv = csv_path.with_name(f".{csv_path.name}.{os.getpid()}.tmp")
    hist.to_csv(tmp_csv, index=False)
    os.replace(tmp_csv, csv_path)
    # The sim reads the PARQUET first. A parquet that cannot be rewritten must not survive to shadow the
    # fresh csv (the vendored builder's parquet would otherwise keep winning), so a failure removes it.
    try:
        tmp_pq = pq_path.with_name(f".{pq_path.name}.{os.getpid()}.tmp")
        hist.to_parquet(tmp_pq, index=False)
        os.replace(tmp_pq, pq_path)
        parquet = str(pq_path)
    except Exception as exc:  # noqa: BLE001
        pq_path.unlink(missing_ok=True)
        parquet = f"removed ({type(exc).__name__})"
    pairs = _consolidate_pairs(league)
    context = _consolidate_context(league, int(hist["season"].max()) if hist["season"].notna().any() else None)
    phases = {}
    for (season, phase), part in hist.groupby(["season", "season_type"], dropna=False):
        name = f"rotation_stints_{int(season) if pd.notna(season) else 'unknown'}_{phase}.csv"
        tmp = root / f".{name}.{os.getpid()}.tmp"
        part.to_csv(tmp, index=False)
        os.replace(tmp, root / name)
        phases[name] = int(len(part))
    return {"rows": int(len(hist)), "files": len(files), "csv_bytes": csv_path.stat().st_size, "parquet": parquet, "phase_tables": phases,
            "pair_rows": pairs, "context_rows": context}


def _replace_parquet_and_csv(frame, root: Path, stem: str, *, csv_too: bool) -> None:
    """Write `<stem>.parquet` (and `.csv`), removing a parquet that cannot be rewritten: readers prefer the
    parquet, and a stale one left by the vendored builder would otherwise shadow the fresh table."""
    pq = root / f"{stem}.parquet"
    if csv_too:
        tmp_csv = root / f".{stem}.csv.{os.getpid()}.tmp"
        frame.to_csv(tmp_csv, index=False)
        os.replace(tmp_csv, root / f"{stem}.csv")
    else:
        (root / f"{stem}.csv").unlink(missing_ok=True)  # the vendored builder's csv copy, now stale
    try:
        tmp_pq = root / f".{stem}.parquet.{os.getpid()}.tmp"
        frame.to_parquet(tmp_pq, index=False)
        os.replace(tmp_pq, pq)
    except Exception:  # noqa: BLE001
        pq.unlink(missing_ok=True)


def _consolidate_pairs(league: str) -> int:
    import pandas as pd

    frames = []
    for path in sorted(stints_dir(league).glob("pair_minutes_*.csv")):
        try:
            frame = pd.read_csv(path, dtype={"player1_id": str, "player2_id": str, "event_id": str, "game_id": str})
        except Exception:  # noqa: BLE001 -- header-only file
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return 0
    pairs = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["event_id", "team", "player1_id", "player2_id"], keep="last")
    _replace_parquet_and_csv(pairs, processed_dir(league), "pair_minutes_history", csv_too=True)
    return int(len(pairs))


def _consolidate_context(league: str, season: int | None) -> int:
    """play_context_history.parquet for the newest season only: its reader filters to season-start..yesterday,
    and a whole-history file would only cost memory in that reader."""
    import pandas as pd

    frames = []
    for path in sorted(stints_dir(league).glob("play_context_*.parquet")):
        frame = pd.read_parquet(path)
        if season is not None:
            frame = frame[frame["season"] == season]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return 0
    context = pd.concat(frames, ignore_index=True)
    _replace_parquet_and_csv(context, processed_dir(league), "play_context_history", csv_too=False)
    return int(len(context))


# ------------------------------------------------------------------------------------------- main

def run_league(league: str, *, seasons: list[int] | None, start: dt.date | None, end: dt.date | None, full: bool,
               rate: float, max_games: int | None, today: dt.date, keep_events: bool = True) -> dict[str, Any]:
    index = load_dates_index(league)
    if start or end:
        s = start or end
        e = min(end or start, today - dt.timedelta(days=1))
        days = [s + dt.timedelta(days=i) for i in range((e - s).days + 1)] if e >= s else []
    else:
        days = [d for season in (seasons or [current_season(league, today)]) for d in season_dates(league, season, today)]
    todo = [d for d in days if full or (index.get(d.isoformat()) or {}).get("status") not in {"done", "empty"}]
    built = games = 0
    started = time.time()
    for day in todo:
        try:
            entry = build_date(league, day, rate=rate, keep_events=keep_events, today=today)
        except Exception as exc:  # noqa: BLE001 -- scoreboard failure: leave the date for the next run
            entry = {"status": "incomplete", "error": f"{type(exc).__name__}: {exc}"[:200]}
        index[day.isoformat()] = entry
        built += 1
        games += int(entry.get("games") or 0)
        if built % 10 == 0:
            save_dates_index(league, index)
            print(f"[{league}] {built}/{len(todo)} dates, {games} games, {time.time() - started:.0f}s", flush=True)
        if max_games is not None and games >= max_games:
            break
    save_dates_index(league, index)
    history = rebuild_history(league) if built or not (processed_dir(league) / "rotation_stints_history.csv").is_file() else {"rows": None, "unchanged": True}
    statuses: dict[str, int] = {}
    for d in days:
        st = (index.get(d.isoformat()) or {}).get("status", "missing")
        statuses[st] = statuses.get(st, 0) + 1
    return {"league": league, "dates_considered": len(days), "dates_built": built, "games_built": games,
            "statuses": statuses, "history": history, "seconds": round(time.time() - started, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", default=",".join(LEAGUES), help="comma list of nba, wnba, ncaab")
    ap.add_argument("--season", default="", help="comma list of ESPN season years (default: current / most recent)")
    ap.add_argument("--start", default="", help="YYYY-MM-DD (overrides --season)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD")
    ap.add_argument("--full", action="store_true", help="rebuild dates already marked done")
    ap.add_argument("--rate", type=float, default=0.3, help="seconds between ESPN summary requests")
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--no-events", action="store_true", help="do not keep the per-game normalised event log")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for tests")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    seasons = [int(s) for s in args.season.split(",") if s.strip()] or None
    start = dt.date.fromisoformat(args.start) if args.start else None
    end = dt.date.fromisoformat(args.end) if args.end else None
    rc = 0
    for league in [x.strip().lower() for x in args.league.split(",") if x.strip()]:
        if league not in LEAGUES:
            print(f"unknown league {league}", file=sys.stderr)
            return 2
        result = run_league(league, seasons=seasons, start=start, end=end, full=args.full, rate=args.rate,
                            max_games=args.max_games, today=today, keep_events=not args.no_events)
        print("BASKETBALL_ROTATION_STINTS " + json.dumps(result, default=str), flush=True)
        if result["statuses"].get("incomplete"):
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
