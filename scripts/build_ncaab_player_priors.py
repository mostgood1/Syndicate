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
from typing import Any, Iterable, Mapping, Sequence

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
) + tuple(f"{k}_pm" for k in RATE_STATS) + ("prior_source",)

SHRINK_MINUTES = 60.0
PRIOR_SEASON_WEIGHT = 0.5
RECENT_GAMES = 5
MISSED_GAMES_OUT = 3
# PRESEASON (user request 2026-10-12: opening night must not refuse for want of a table). Before a
# season's first finals the table is built from the team's CURRENT ESPN roster joined, by athlete id,
# to last season's box -- transfers keep their id. A newcomer with no D-I history gets league rates
# and NEWCOMER_MINUTES, labelled `newcomer` so a thin projection is visible, never dressed as a fit.
NEWCOMER_MINUTES = 8.0
# Early in the season the preseason projection is BLENDED into minutes and starter share, worth
# PRESEASON_WEIGHT_GAMES games, fading linearly to zero by PRESEASON_FADE_GAMES team games.
PRESEASON_WEIGHT_GAMES = 3.0
PRESEASON_FADE_GAMES = 10
# STALE ROSTERS ARE EXCLUDED, NOT PROJECTED. Measured 2026-10-12: ESPN still served LAST season's
# roster for most teams (sample of 8 per band: 0/8 stale at <= 65% returning, 8/8 at 65-95%, 5/8 at
# >= 95%) -- the tell is a player labelled "Freshman" who already has D-I box rows, which a real
# freshman cannot. A stale team is left OUT of the table, so its games refuse by name at game time
# rather than being priced off players who left. The daily job re-reads rosters; a team enters the
# table the day ESPN loads its real one.
STALE_RETURNING_SHARE = 0.95


def processed_dir() -> Path:
    return ratings.processed_dir()


def box_path(season: int) -> Path:
    return processed_dir() / f"player_game_box_{season}.csv"


def box_dates_path(season: int) -> Path:
    return processed_dir() / f"player_game_box_{season}.dates.json"


def priors_path(season: int, as_of: dt.date) -> Path:
    return processed_dir() / f"player_priors_{season}_asof_{as_of:%Y%m%d}.csv"


def default_season(today: dt.date) -> int:
    """The season this job should serve: the UPCOMING one from October.

    The ratings producer's `default_season` keeps the finished season until November 1, which is
    right for ratings but wrong here. Measured 2026-10-12 on the fleet: the scheduled job re-crawled
    the finished 2025-26 season and would never have built the 2026-27 preseason table before the
    ~11-03 opener. October has no games, so October belongs to the coming season.
    """
    return today.year + 1 if today.month >= 10 else ratings.default_season(today)


def preseason_path(season: int, as_of: dt.date) -> Path:
    return processed_dir() / f"player_preseason_{season}_asof_{as_of:%Y%m%d}.csv"


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
    preseason: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """{(team_id, athlete_id): prior} from box rows strictly before `as_of`.

    `preseason` ({(team_id, athlete_id): preseason prior}) is blended into min_proj and
    starter_prob early in the season (PRESEASON_WEIGHT_GAMES, fading by PRESEASON_FADE_GAMES
    team games): one or two games are not a rotation.

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
        pre = (preseason or {}).get((tid, aid))
        weight = PRESEASON_WEIGHT_GAMES * max(0.0, (PRESEASON_FADE_GAMES - len(order)) / PRESEASON_FADE_GAMES)
        if pre is not None and weight > 0:
            n = len(recent)
            min_proj = (n * min_proj + weight * _f(pre, "min_proj")) / (n + weight)
            starts = (n * starts + weight * _f(pre, "starter_prob")) / (n + weight)
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
            "prior_source": "in_season+preseason" if pre is not None and weight > 0 else "in_season",
        }
    return out


def stale_roster_reason(roster: Sequence[Mapping[str, Any]], prev_athletes: set[str], team_id: str,
                        prev_teams: Mapping[str, set[str]]) -> str | None:
    """Why this roster looks like LAST season's, or None. See STALE_RETURNING_SHARE."""
    if not roster:
        return "empty_roster"
    if any(str(p.get("experience") or "").lower() == "freshman" and str(p.get("athlete_id")) in prev_athletes for p in roster):
        return "freshman_with_prior_season_box"
    returning = sum(1 for p in roster if str(team_id) in prev_teams.get(str(p.get("athlete_id")), set()))
    if returning / len(roster) >= STALE_RETURNING_SHARE:
        return "returning_share_at_or_above_stale_floor"
    return None


def compute_preseason(
    rosters: Mapping[str, Sequence[Mapping[str, Any]]],
    prev_rows: Iterable[Mapping[str, Any]],
    *,
    stale_out: dict[str, str] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """{(team_id, athlete_id): prior} for every rostered player, before any game is played.

    `rosters` is {team_id: [{"athlete_id", "player_name"}...]} from ESPN's CURRENT team roster;
    `prev_rows` is last season's player box, any team. Rates use ALL of last season (it is the
    only data there is), shrunk to last season's league; minutes are last season's per-game
    minutes when he played, else NEWCOMER_MINUTES. `prior_source` says which:
    returning (same team) / transfer (another team) / newcomer (no D-I box rows).
    """
    prev = [r for r in prev_rows if _f(r, "min") > 0]
    tot_min = sum(_f(r, "min") for r in prev)
    league = {k: (sum(_f(r, k) for r in prev) / tot_min if tot_min > 0 else 0.0) for k in RATE_STATS}
    acc: dict[str, dict[str, Any]] = {}
    for r in prev:
        a = acc.setdefault(str(r.get("athlete_id")), {"min": 0.0, "games": 0, "starts": 0, "teams": set(), **{k: 0.0 for k in RATE_STATS}})
        a["min"] += _f(r, "min")
        a["games"] += 1
        a["starts"] += int(_f(r, "starter") > 0)
        a["teams"].add(str(r.get("team_id")))
        for k in RATE_STATS:
            a[k] += _f(r, k)
    prev_teams = {aid: a["teams"] for aid, a in acc.items()}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for tid, roster in rosters.items():
        stale = stale_roster_reason(roster, set(acc), str(tid), prev_teams)
        if stale:
            if stale_out is not None:
                stale_out[str(tid)] = stale
            continue
        for player in roster:
            aid = str(player.get("athlete_id") or "")
            if not aid:
                continue
            a = acc.get(aid)
            if a:
                source = "returning" if str(tid) in a["teams"] else "transfer"
                rates = {f"{k}_pm": round((a[k] + SHRINK_MINUTES * league[k]) / (a["min"] + SHRINK_MINUTES), 5) for k in RATE_STATS}
                min_proj, starter = a["min"] / a["games"], a["starts"] / a["games"]
            else:
                source = "newcomer"
                rates = {f"{k}_pm": round(league[k], 5) for k in RATE_STATS}
                min_proj, starter = NEWCOMER_MINUTES, 0.0
            out[(str(tid), aid)] = {
                "team_id": str(tid), "athlete_id": aid, "player_name": str(player.get("player_name") or ""),
                "games": 0, "minutes": 0.0, "min_proj": round(min_proj, 2), "starter_prob": round(starter, 3),
                "last_game": "", "prior_season_minutes": round(a["min"], 1) if a else 0.0, **rates,
                "prior_source": source,
            }
    return out


def fetch_roster(team_id: str) -> list[dict[str, str]]:
    """ESPN's CURRENT roster for one team (the coming season's, in the preseason)."""
    payload = ratings._get_json(f"teams/{team_id}/roster")
    out = []
    for a in payload.get("athletes") or []:
        if isinstance(a, Mapping) and a.get("id"):
            out.append({"athlete_id": str(a["id"]), "player_name": str(a.get("displayName") or a.get("fullName") or ""),
                        "experience": str((a.get("experience") or {}).get("displayValue") or "")})
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


def write_priors(season: int, as_of: dt.date, priors: Mapping[Any, Mapping[str, Any]], *, path: Path | None = None) -> Path:
    path = path or priors_path(season, as_of)
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


def newest_preseason(season: int) -> dict[tuple[str, str], dict[str, Any]]:
    paths = sorted(processed_dir().glob(f"player_preseason_{season}_asof_*.csv"))
    return {(r["team_id"], r["athlete_id"]): r for r in read_csv(paths[-1])} if paths else {}


def build_preseason(season: int, today: dt.date, *, rate: float) -> dict[str, Any]:
    """Rosters for every D-I team -> the preseason table, written TWICE: as `player_preseason_*`
    (the blend's source once the season starts) and as `player_priors_*` dated today (what the
    live re-sim reads until the first in-season table supersedes it)."""
    d1 = ratings.load_registry()
    rosters: dict[str, list] = {}
    errors = 0
    for tid in sorted(d1):
        try:
            rosters[tid] = fetch_roster(tid)
        except Exception as exc:  # noqa: BLE001
            print(f"[ncaab_player_priors] ROSTER_FAILED team={tid} {exc}", flush=True)
            errors += 1
        time.sleep(1.0 / rate)
    prev = read_csv(box_path(season - 1))
    stale: dict[str, str] = {}
    pre = compute_preseason(rosters, prev, stale_out=stale)
    sources: dict[str, int] = defaultdict(int)
    for p in pre.values():
        sources[p["prior_source"]] += 1
    out = {"teams_rostered": sum(1 for v in rosters.values() if v), "roster_errors": errors,
           "teams_stale_excluded": len(stale), "teams_in_table": len({k[0] for k in pre}),
           "prev_box_rows": len(prev), "preseason_players": len(pre), **{f"preseason_{k}": v for k, v in sources.items()}}
    if pre and prev:
        write_priors(season, today, pre, path=preseason_path(season, today))
        out["written"] = str(write_priors(season, today, pre))
    elif not prev:
        # WITHOUT LAST SEASON'S BOX EVERY PLAYER IS A NEWCOMER: refuse to write a table that would
        # look complete and carry no information.
        out["refused"] = f"no prior-season box at {box_path(season - 1)}"
    return out


def run(season: int, today: dt.date, *, rate: float, max_new_games: int | None, crawl_only: bool,
        preseason: bool = False) -> dict[str, Any]:
    counts = crawl(season, today, rate=rate, max_new_games=max_new_games)
    written = None
    rows = read_csv(box_path(season))
    if not crawl_only and (preseason or not rows):
        counts.update(build_preseason(season, today, rate=rate))
        written = counts.get("written")
    elif rows and not crawl_only:
        as_of = min(today, dt.date.fromisoformat(max(r["date"] for r in rows)) + dt.timedelta(days=1))
        priors = compute_priors(rows, as_of=as_of, d1=ratings.load_registry(), prior_rows=read_csv(box_path(season - 1)),
                                preseason=newest_preseason(season))
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
    parser.add_argument("--preseason", action="store_true", help="build the roster-based preseason table even if games exist")
    args = parser.parse_args(argv)
    today = dt.date.today()
    season = args.season or default_season(today)
    summary = run(season, today, rate=max(args.rate, 0.2), max_new_games=args.max_new_games, crawl_only=args.crawl_only,
                  preseason=args.preseason)
    return 0 if summary["errors"] == 0 or summary["games_fetched"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
