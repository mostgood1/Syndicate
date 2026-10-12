"""NCAAB player priors for the native possession engine: per-minute rates, minutes, starter share.

Phase P4 of `docs/ai_context/basketball_live_native_plan.md` (lane `ncaab-native-live-tier`).
User decision 2026-10-12: the NCAAB live lens resumes P1's PLAYER-level engine
(`syndicate/features/basketball_engine`), so NCAAB needs what the engine reads per player
(`engine.py`: `_sim_min`, `starter_prob`, `pred_pts`, `_prior_<stat>_pm`). Until this file
NCAAB had no player data at all.

TWO OUTPUTS, under `<ncaab root>/data/processed/` (`<ncaab root>` resolves as the ratings
producer does: `SYNDICATE_NCAAB_SOURCE_ROOT` or `SYNDICATE_DATA_ROOT/ncaab_source`):

  player_game_box_<season>.csv    one row per (game, player) from the ESPN summary box --
                                  incremental, with `player_game_box_<season>.dates.json`
                                  holding the dates whose every event is final and recorded.
  player_priors_<season>_asof_<YYYYMMDD>.csv
                                  DATED, never in place (the H2 backtest lost a pre-registered
                                  table to an in-place refresh). One row per player of a D-I team
                                  with a game in the season so far.

THE PRIOR, per player, from games STRICTLY BEFORE `as_of` (no leakage; `compute_priors` is
the same function the backtest calls walk-forward):

  rate_pm   = (sum stat + K x league_rate) / (sum minutes + K), K = SHRINK_MINUTES. A
              freshman with 12 minutes is mostly the league; a 900-minute starter is himself.
              Last season's rows for the same ESPN athlete id count at PRIOR_SEASON_WEIGHT
              (transfers keep their id; ~40% roster turnover is why it is not 1.0).
  min_proj  = mean minutes over the team's last RECENT_GAMES games, a DNP counted as 0.
  starter_prob = share of those games he started.
  pred_pts  = min_proj x pts_pm.

A player who missed the team's last MISSED_GAMES_OUT games is dropped from the projected
rotation (injury, transfer, suspension). `min_proj` is NOT renormalised to 200 here: the
engine scales by the team total (`engine.py::_team_rates_from_priors`), and the live builder
knows who is actually dressed.

Run research crawls at Idle priority -- the fleet shares this machine:
    py -3 scripts/build_ncaab_player_priors.py --season 2026 --rate 4
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

_SCRIPTS = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("build_ncaab_team_ratings", _SCRIPTS / "build_ncaab_team_ratings.py")
ratings = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ratings)  # type: ignore[union-attr]

# The engine's per-minute prior columns this producer feeds (engine.py reads `_prior_<k>_pm`).
RATE_STATS = ("pts", "fga", "fgm", "threes_att", "threes", "fta", "ftm", "oreb", "dreb", "reb", "ast", "tov", "stl", "blk", "pf")
BOX_FIELDS = (
    "season", "game_id", "date", "team_id", "opp_id", "athlete_id", "player_name", "starter", "dnp", "min",
) + RATE_STATS
PRIOR_FIELDS = (
    "season", "as_of", "team_id", "athlete_id", "player_name", "games", "minutes", "min_proj", "starter_prob",
    "last_game", "prior_season_minutes",
) + tuple(f"{k}_pm" for k in RATE_STATS)

SHRINK_MINUTES = 60.0
PRIOR_SEASON_WEIGHT = 0.5
RECENT_GAMES = 5
MISSED_GAMES_OUT = 3


def processed_dir() -> Path:
    return ratings.processed_dir()


def box_path(season: int) -> Path:
    return processed_dir() / f"player_game_box_{season}.csv"


def box_dates_path(season: int) -> Path:
    return processed_dir() / f"player_game_box_{season}.dates.json"


def priors_path(season: int, as_of: dt.date) -> Path:
    return processed_dir() / f"player_priors_{season}_asof_{as_of:%Y%m%d}.csv"


# ----------------------------------------------------------------------- parse

def _made_att(text: Any) -> tuple[float | None, float | None]:
    raw = str(text or "").strip()
    if "-" not in raw:
        return None, None
    a, b = raw.split("-", 1)
    try:
        return float(a), float(b)
    except ValueError:
        return None, None


def _num(text: Any) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def parse_player_box(payload: Mapping[str, Any], *, season: int, day: str) -> list[dict[str, Any]]:
    """One row per listed player of a FINISHED game. [] when the box is absent or malformed.

    A DNP row is kept (`dnp=1`, min 0): "listed and did not play" is the minutes signal.
    A row whose stats cannot be read is DROPPED, never zero-filled: a missing number and a
    genuine zero are different facts.
    """
    header = payload.get("header") or {}
    game_id = str(header.get("id") or "")
    teams = [b for b in (payload.get("boxscore") or {}).get("players") or [] if isinstance(b, Mapping)]
    if not game_id or len(teams) != 2:
        return []
    ids = [str((b.get("team") or {}).get("id") or "") for b in teams]
    rows: list[dict[str, Any]] = []
    for block, team_id, opp_id in ((teams[0], ids[0], ids[1]), (teams[1], ids[1], ids[0])):
        for stat in block.get("statistics") or []:
            names = [str(n) for n in stat.get("names") or stat.get("labels") or []]
            for athlete in stat.get("athletes") or []:
                info = athlete.get("athlete") or {}
                aid = str(info.get("id") or "")
                if not aid:
                    continue
                base = {
                    "season": season, "game_id": game_id, "date": day, "team_id": team_id, "opp_id": opp_id,
                    "athlete_id": aid, "player_name": str(info.get("displayName") or ""),
                    "starter": int(bool(athlete.get("starter"))),
                }
                vals = athlete.get("stats") or []
                if athlete.get("didNotPlay") or not vals:
                    rows.append({**base, "dnp": 1, "min": 0.0, **{k: 0.0 for k in RATE_STATS}})
                    continue
                cell = dict(zip(names, vals))
                fgm, fga = _made_att(cell.get("FG"))
                tpm, tpa = _made_att(cell.get("3PT"))
                ftm, fta = _made_att(cell.get("FT"))
                parsed = {
                    "min": _num(cell.get("MIN")), "pts": _num(cell.get("PTS")), "fga": fga, "fgm": fgm,
                    "threes_att": tpa, "threes": tpm, "fta": fta, "ftm": ftm, "oreb": _num(cell.get("OREB")),
                    "dreb": _num(cell.get("DREB")), "reb": _num(cell.get("REB")), "ast": _num(cell.get("AST")),
                    "tov": _num(cell.get("TO")), "stl": _num(cell.get("STL")), "blk": _num(cell.get("BLK")),
                    "pf": _num(cell.get("PF")),
                }
                if any(v is None for v in parsed.values()):
                    continue
                rows.append({**base, "dnp": int(parsed["min"] <= 0), **parsed})
    return rows


# --------------------------------------------------------------------- priors

def _f(row: Mapping[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute_priors(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: dt.date,
    d1: Mapping[str, str] | None = None,
    prior_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[tuple[str, str], dict[str, Any]]:
    """{(team_id, athlete_id): prior} from box rows strictly before `as_of`.

    `prior_rows` is last season's box (any team): it feeds the RATES only, at
    PRIOR_SEASON_WEIGHT, keyed by athlete id. Minutes and starter share come from this
    season alone -- last season's role says little about this one's.
    """
    cutoff = as_of.isoformat()
    cur = [r for r in rows if str(r.get("date") or "") < cutoff]
    if d1 is not None:
        cur = [r for r in cur if str(r.get("team_id")) in d1]
    if not cur:
        return {}
    # League per-minute rates (this season, before as_of): the shrinkage target.
    tot_min = sum(_f(r, "min") for r in cur)
    league = {k: (sum(_f(r, k) for r in cur) / tot_min if tot_min > 0 else 0.0) for k in RATE_STATS}
    prev: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in prior_rows:
        acc = prev[str(r.get("athlete_id"))]
        acc["min"] += _f(r, "min")
        for k in RATE_STATS:
            acc[k] += _f(r, k)
    # Team game order (for recency) and each player's rows on that team.
    team_games: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_games: set[tuple[str, str]] = set()
    by_player: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for r in cur:
        tid, gid = str(r.get("team_id")), str(r.get("game_id"))
        if (tid, gid) not in seen_games:
            seen_games.add((tid, gid))
            team_games[tid].append((str(r.get("date")), gid))
        by_player[(tid, str(r.get("athlete_id")))].append(r)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for (tid, aid), prow in by_player.items():
        order = sorted(team_games[tid])
        recent = [gid for _d, gid in order[-RECENT_GAMES:]]
        last_missed = [gid for _d, gid in order[-MISSED_GAMES_OUT:]]
        by_game = {str(r.get("game_id")): r for r in prow}
        played = [r for r in prow if _f(r, "min") > 0]
        if not played:
            continue
        if len(order) >= MISSED_GAMES_OUT and all(_f(by_game.get(g, {}), "min") <= 0 for g in last_missed):
            continue  # out of the rotation: not projected to play
        minutes = sum(_f(r, "min") for r in played)
        p = prev.get(aid)
        p_min = float(p["min"]) * PRIOR_SEASON_WEIGHT if p else 0.0
        rates = {}
        for k in RATE_STATS:
            num = sum(_f(r, k) for r in played) + (float(p[k]) * PRIOR_SEASON_WEIGHT if p else 0.0)
            rates[f"{k}_pm"] = round((num + SHRINK_MINUTES * league[k]) / (minutes + p_min + SHRINK_MINUTES), 5)
        min_proj = sum(_f(by_game.get(g, {}), "min") for g in recent) / max(1, len(recent))
        starts = sum(int(_f(by_game.get(g, {}), "starter") > 0) for g in recent) / max(1, len(recent))
        out[(tid, aid)] = {
            "team_id": tid,
            "athlete_id": aid,
            "player_name": str(played[-1].get("player_name") or ""),
            "games": len(played),
            "minutes": round(minutes, 1),
            "min_proj": round(min_proj, 2),
            "starter_prob": round(starts, 3),
            "last_game": max(str(r.get("date")) for r in played),
            "prior_season_minutes": round(float(p["min"]) if p else 0.0, 1),
            **rates,
        }
    return out


# ------------------------------------------------------------------------- io

def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def append_box(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOX_FIELDS)
        if new:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in BOX_FIELDS})


def write_priors(season: int, as_of: dt.date, priors: Mapping[Any, Mapping[str, Any]]) -> Path:
    path = priors_path(season, as_of)
    tmp = path.with_suffix(".csv.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRIOR_FIELDS)
        writer.writeheader()
        for p in sorted(priors.values(), key=lambda v: (v["team_id"], -float(v["min_proj"]))):
            writer.writerow({**{k: p.get(k) for k in PRIOR_FIELDS}, "season": season, "as_of": as_of.isoformat()})
    os.replace(tmp, path)
    return path


# ----------------------------------------------------------------------- run

def crawl(season: int, today: dt.date, *, rate: float, max_new_games: int | None) -> dict[str, Any]:
    path, dates_file = box_path(season), box_dates_path(season)
    done: set[str] = set()
    if dates_file.is_file():
        done = set(json.loads(dates_file.read_text(encoding="utf-8")).get("dates") or [])
    have = {row["game_id"] for row in read_csv(path)}
    counts = {"dates_checked": 0, "games_fetched": 0, "games_unusable": 0, "errors": 0}
    budget = max_new_games
    for day in ratings.season_dates(season, today):
        key = day.isoformat()
        if key in done:
            continue
        counts["dates_checked"] += 1
        try:
            ids, all_final = ratings.final_event_ids(day)
            time.sleep(1.0 / rate)
        except Exception as exc:  # noqa: BLE001
            print(f"[ncaab_player_priors] SCOREBOARD_FAILED date={key} {exc}", flush=True)
            counts["errors"] += 1
            continue
        complete = all_final
        for event_id in ids:
            if event_id in have:
                continue
            if budget is not None and budget <= 0:
                complete = False
                break
            try:
                rows = parse_player_box(ratings._get_json(f"summary?event={event_id}"), season=season, day=key)
                time.sleep(1.0 / rate)
            except Exception as exc:  # noqa: BLE001
                print(f"[ncaab_player_priors] SUMMARY_FAILED event={event_id} {exc}", flush=True)
                counts["errors"] += 1
                complete = False
                continue
            if not rows:
                counts["games_unusable"] += 1
                continue
            append_box(path, rows)
            have.add(event_id)
            counts["games_fetched"] += 1
            if budget is not None:
                budget -= 1
        if complete:
            done.add(key)
            dates_file.parent.mkdir(parents=True, exist_ok=True)
            dates_file.write_text(json.dumps({"season": season, "dates": sorted(done)}), encoding="utf-8")
        if counts["dates_checked"] % 10 == 0:
            print(f"[ncaab_player_priors] PROGRESS date={key} games={len(have)} " + " ".join(f"{k}={v}" for k, v in counts.items()), flush=True)
        if budget is not None and budget <= 0:
            break
    return {**counts, "games_total": len(have)}


def run(season: int, today: dt.date, *, rate: float, max_new_games: int | None, crawl_only: bool) -> dict[str, Any]:
    counts = crawl(season, today, rate=rate, max_new_games=max_new_games)
    written = None
    rows = read_csv(box_path(season))
    if rows and not crawl_only:
        as_of = min(today, dt.date.fromisoformat(max(r["date"] for r in rows)) + dt.timedelta(days=1))
        priors = compute_priors(rows, as_of=as_of, d1=ratings.load_registry(), prior_rows=read_csv(box_path(season - 1)))
        if priors:
            written = str(write_priors(season, as_of, priors))
        counts["players_rated"] = len(priors)
    summary = {**counts, "season": season, "box_rows": len(rows), "written": written}
    print("[ncaab_player_priors] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None, help="ESPN season year (the year it ends)")
    parser.add_argument("--rate", type=float, default=4.0)
    parser.add_argument("--max-new-games", type=int, default=None)
    parser.add_argument("--crawl-only", action="store_true", help="fetch box rows, write no priors table")
    args = parser.parse_args(argv)
    today = dt.date.today()
    season = args.season or ratings.default_season(today)
    summary = run(season, today, rate=max(args.rate, 0.2), max_new_games=args.max_new_games, crawl_only=args.crawl_only)
    return 0 if summary["errors"] == 0 or summary["games_fetched"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
