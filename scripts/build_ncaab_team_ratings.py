"""NCAAB team efficiency ratings (adjusted offense / defense / tempo) from ESPN box scores.

WHY (lane `intelligence-evidence-coverage`, user 2026-10-07: "build the NCAAB
ratings producer"). The fleet's `ncaab_source` held 12 manifest files and no
data at all, so every NCAAB explanation would have had no season context and
the readiness gate reads NCAAB as not-ready (no `team_ratings_*` table). The
2026-27 season opens ~2026-11-03.

WHAT IT WRITES, under `<ncaab_source>/data/processed/`:
  * `team_game_box_<season>.csv` -- one row per team per finished D-I game:
    points, FGA, OREB, total turnovers, FTA and the possession estimate. The
    raw evidence, appended incrementally so a daily run only fetches new finals.
  * `team_ratings_<season>_asof_<YYYYMMDD>.csv` -- DATED, never overwritten in
    place. The 2026-10-07 H2 backtest lost its pre-registered SP+ table to an
    in-place refresh mid-run; ratings that are not kept by date cannot be
    tested point-in-time.
  * `team_game_box_<season>.dates.json` -- the dates already fully fetched.

THE MODEL (KenPom-shaped, stated rather than claimed equal to anything):
  * possessions per game = mean of the two teams' FGA - OREB + TOV + 0.475*FTA;
  * raw offense / defense = 100 * points scored / allowed per possession;
  * home court: each efficiency scaled by `HOME_EDGE` (1.4%) toward neutral;
  * iterate: AdjO_t = mean_g(OE_g * L / AdjD_opp), AdjD_t = mean_g(DE_g * L / AdjO_opp),
    AdjT_t = mean_g(poss_g * T / AdjT_opp), with L / T the league means, until stable;
  * D-I vs D-I games only (the ESPN D-I registry, `ncaab_team_registry.csv`);
  * early season: blended toward last season's final rating with weight
    games / (games + PRIOR_GAMES), regressed toward the mean, when a prior table exists.

ESPN's site API is undocumented; `site.api.espn.com` first, `site.web.api.espn.com`
second, the order `population_outcomes_espn` already uses. Polite by default
(`--rate`), and run it at low priority -- the fleet shares this machine.

    python scripts/build_ncaab_team_ratings.py                 # current / last season, incremental
    python scripts/build_ncaab_team_ratings.py --season 2026 --max-new-games 200
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "syndicate" / "features" / "shared" / "ncaab_team_registry.csv"
ESPN_HOSTS = ("site.api.espn.com", "site.web.api.espn.com")
SPORT_PATH = "apis/site/v2/sports/basketball/mens-college-basketball"

HOME_EDGE = 0.014  # ~3.5 points on a 100-possession game, the usual college estimate
PRIOR_GAMES = 8.0  # games at which this season's rating and last season's weigh equally
PRIOR_REGRESSION = 0.30  # last season's rating is regressed this far toward the mean first
ITERATIONS = 40
# MARGIN CALIBRATION, fitted 2026-10-07 by walk-forward on the 2025-26 season
# (ratings from games strictly before each date; both teams >= 5 prior games):
# actual_margin = k * model_margin + home, OLS on Nov-Jan (2,605 games), judged
# on Feb-Apr (1,955 held out). k = 0.780, home = 2.93 pts; held-out RMSE 11.25
# uncalibrated -> 11.16 calibrated (naive home+3.5: 13.29). The opponent
# adjustment's fixed point amplifies spread (sd 15.8 per 100 vs 9.4 raw); the
# additive form tied it (k 0.789, RMSE 11.16), so the model is unchanged and
# its deviations from the league mean are shrunk by k. A predicted margin in
# points is then (adj_em_a - adj_em_b) * game_tempo / 100 + HOME_POINTS at a home site.
MARGIN_CALIBRATION_K = 0.78
HOME_POINTS = 2.9

BOX_FIELDS = (
    "season", "game_id", "date", "season_type", "team_id", "team", "opp_id", "opp",
    "site", "pts", "opp_pts", "fga", "oreb", "tov", "fta", "poss",
)
RATING_FIELDS = (
    "team", "espn_id", "adj_off", "adj_def", "adj_em", "tempo", "raw_off", "raw_def",
    "games", "prior_weight", "calibration_k", "season", "as_of", "source",
)


# ----------------------------------------------------------------------- paths

def ncaab_root() -> Path:
    override = str(os.environ.get("SYNDICATE_NCAAB_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "ncaab_source"


def processed_dir() -> Path:
    return ncaab_root() / "data" / "processed"


# --------------------------------------------------------------------- season

def default_season(today: dt.date) -> int:
    """ESPN's season year: the calendar year the season ENDS in.

    November-December belong to next year's season; May-October are the
    offseason, whose last completed season is this calendar year's.
    """
    return today.year + 1 if today.month >= 11 else today.year


def season_dates(season: int, today: dt.date) -> list[dt.date]:
    start = dt.date(season - 1, 11, 1)
    end = min(dt.date(season, 4, 15), today - dt.timedelta(days=1))
    days = (end - start).days
    return [start + dt.timedelta(days=i) for i in range(days + 1)] if days >= 0 else []


# ----------------------------------------------------------------------- fetch

def _get_json(path: str, *, timeout: float = 30.0) -> Any:
    last: Exception | None = None
    for host in ESPN_HOSTS:
        url = f"https://{host}/{SPORT_PATH}/{path}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 -- try the other host, then report
            last = exc
    raise RuntimeError(f"ESPN unreachable for {path}: {type(last).__name__}: {last}")


def final_event_ids(day: dt.date) -> tuple[list[str], bool]:
    """(final event ids, every event on the date final?) for D-I (groups=50)."""
    payload = _get_json(f"scoreboard?dates={day:%Y%m%d}&groups=50&limit=500")
    ids: list[str] = []
    all_final = True
    for event in payload.get("events") or []:
        status = (((event.get("competitions") or [{}])[0].get("status") or {}).get("type") or {})
        if status.get("completed") or status.get("name") == "STATUS_FINAL":
            ids.append(str(event.get("id")))
        elif status.get("name") not in {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_FORFEIT"}:
            all_final = False
    return ids, all_final


# ----------------------------------------------------------------------- parse

def _stat(stats: Iterable[Mapping[str, Any]], *names: str) -> float | None:
    by_name = {str(s.get("name")): s.get("displayValue") for s in stats if isinstance(s, Mapping)}
    for name in names:
        raw = by_name.get(name)
        if raw is None:
            continue
        text = str(raw).strip()
        if "-" in text and name.endswith("Attempted"):
            text = text.split("-")[-1]
        try:
            return float(text)
        except ValueError:
            continue
    return None


def _attempts(stats: Iterable[Mapping[str, Any]], made_attempted: str, attempted: str) -> float | None:
    by_name = {str(s.get("name")): s.get("displayValue") for s in stats if isinstance(s, Mapping)}
    raw = by_name.get(made_attempted)
    if raw is not None and "-" in str(raw):
        try:
            return float(str(raw).split("-")[1])
        except (ValueError, IndexError):
            pass
    return _stat(stats, attempted)


def parse_summary(payload: Mapping[str, Any], *, season: int, day: str) -> list[dict[str, Any]]:
    """Two box rows (one per team) for a finished game, or [] if anything needed is missing."""
    header = payload.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    competitors = {str(c.get("id")): c for c in competition.get("competitors") or [] if isinstance(c, Mapping)}
    neutral = bool(competition.get("neutralSite"))
    season_type = ((header.get("season") or {}).get("type"))
    teams = (payload.get("boxscore") or {}).get("teams") or []
    if len(teams) != 2 or len(competitors) != 2:
        return []
    parsed = []
    for team in teams:
        info = team.get("team") or {}
        tid = str(info.get("id") or "")
        comp = competitors.get(tid) or {}
        stats = team.get("statistics") or []
        fga = _attempts(stats, "fieldGoalsMade-fieldGoalsAttempted", "fieldGoalsAttempted")
        fta = _attempts(stats, "freeThrowsMade-freeThrowsAttempted", "freeThrowsAttempted")
        oreb = _stat(stats, "offensiveRebounds")
        tov = _stat(stats, "totalTurnovers", "turnovers")
        try:
            pts = float(comp.get("score"))
        except (TypeError, ValueError):
            pts = None
        if None in (fga, fta, oreb, tov, pts) or not tid:
            return []
        parsed.append(
            {
                "team_id": tid,
                "team": str(info.get("location") or info.get("displayName") or tid),
                "home_away": str(comp.get("homeAway") or team.get("homeAway") or ""),
                "pts": pts,
                "fga": fga,
                "oreb": oreb,
                "tov": tov,
                "fta": fta,
            }
        )
    a, b = parsed
    poss = ((a["fga"] - a["oreb"] + a["tov"] + 0.475 * a["fta"]) + (b["fga"] - b["oreb"] + b["tov"] + 0.475 * b["fta"])) / 2.0
    if poss <= 0:
        return []
    game_id = str(header.get("id") or payload.get("gameId") or "")
    rows = []
    for me, opp in ((a, b), (b, a)):
        site = "neutral" if neutral else (me["home_away"] or "neutral")
        rows.append(
            {
                "season": season, "game_id": game_id, "date": day, "season_type": season_type,
                "team_id": me["team_id"], "team": me["team"], "opp_id": opp["team_id"], "opp": opp["team"],
                "site": site, "pts": me["pts"], "opp_pts": opp["pts"], "fga": me["fga"], "oreb": me["oreb"],
                "tov": me["tov"], "fta": me["fta"], "poss": round(poss, 2),
            }
        )
    return rows


# --------------------------------------------------------------------- ratings

def load_registry(path: Path = REGISTRY) -> dict[str, str]:
    """espn_id -> school, the D-I set."""
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["espn_id"]: row["school"] for row in csv.DictReader(handle) if row.get("espn_id")}


def compute_ratings(
    rows: Iterable[Mapping[str, Any]],
    d1: Mapping[str, str],
    *,
    prior: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, dict[str, float]]:
    """Adjusted offense/defense/tempo per D-I team (keyed by ESPN id).

    `prior` (ESPN id -> {adj_off, adj_def, tempo}) is last season's table, used
    only to steady teams with few games this season.
    """
    games: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        tid, oid = str(row["team_id"]), str(row["opp_id"])
        if tid not in d1 or oid not in d1 or (str(row["game_id"]), tid) in seen:
            continue
        seen.add((str(row["game_id"]), tid))
        poss = float(row["poss"])
        oe = 100.0 * float(row["pts"]) / poss
        de = 100.0 * float(row["opp_pts"]) / poss
        if row["site"] == "home":
            oe, de = oe / (1 + HOME_EDGE), de * (1 + HOME_EDGE)
        elif row["site"] == "away":
            oe, de = oe * (1 + HOME_EDGE), de / (1 + HOME_EDGE)
        games[tid].append((oid, oe, de, poss))
    if not games:
        return {}
    all_oe = [g[1] for gs in games.values() for g in gs]
    all_poss = [g[3] for gs in games.values() for g in gs]
    league = sum(all_oe) / len(all_oe)
    tempo_mean = sum(all_poss) / len(all_poss)
    raw = {t: (sum(g[1] for g in gs) / len(gs), sum(g[2] for g in gs) / len(gs), sum(g[3] for g in gs) / len(gs)) for t, gs in games.items()}
    adj_o = {t: r[0] for t, r in raw.items()}
    adj_d = {t: r[1] for t, r in raw.items()}
    adj_t = {t: r[2] for t, r in raw.items()}
    for _ in range(ITERATIONS):
        new_o, new_d, new_t = {}, {}, {}
        for t, gs in games.items():
            new_o[t] = sum(oe * league / adj_d.get(o, league) for o, oe, _de, _p in gs) / len(gs)
            new_d[t] = sum(de * league / adj_o.get(o, league) for o, _oe, de, _p in gs) / len(gs)
            new_t[t] = sum(p * tempo_mean / adj_t.get(o, tempo_mean) for o, _oe, _de, p in gs) / len(gs)
        adj_o, adj_d, adj_t = new_o, new_d, new_t
    out: dict[str, dict[str, float]] = {}
    for t in games:
        n = len(games[t])
        o, d, tp = adj_o[t], adj_d[t], adj_t[t]
        # Calibrated scale (see MARGIN_CALIBRATION_K): THIS season's estimate is
        # shrunk toward the league mean BEFORE the prior blend -- last season's
        # table is already calibrated, and shrinking after would scale it twice.
        o = league + MARGIN_CALIBRATION_K * (o - league)
        d = league + MARGIN_CALIBRATION_K * (d - league)
        weight = 1.0
        if prior and t in prior:
            p = prior[t]
            po = league + (1 - PRIOR_REGRESSION) * (float(p["adj_off"]) - league)
            pd = league + (1 - PRIOR_REGRESSION) * (float(p["adj_def"]) - league)
            pt = tempo_mean + (1 - PRIOR_REGRESSION) * (float(p["tempo"]) - tempo_mean)
            weight = n / (n + PRIOR_GAMES)
            o, d, tp = weight * o + (1 - weight) * po, weight * d + (1 - weight) * pd, weight * tp + (1 - weight) * pt
        out[t] = {
            "adj_off": round(o, 2), "adj_def": round(d, 2), "adj_em": round(o - d, 2), "tempo": round(tp, 2),
            "raw_off": round(raw[t][0], 2), "raw_def": round(raw[t][1], 2), "games": n, "prior_weight": round(1 - weight, 3),
            "calibration_k": MARGIN_CALIBRATION_K,
        }
    return out


# ------------------------------------------------------------------------- io

def read_box(path: Path) -> list[dict[str, Any]]:
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


def read_prior(season: int) -> dict[str, dict[str, float]] | None:
    """Last season's NEWEST dated table, keyed by ESPN id."""
    candidates = sorted(processed_dir().glob(f"team_ratings_{season - 1}_asof_*.csv"))
    if not candidates:
        return None
    with candidates[-1].open(encoding="utf-8", newline="") as handle:
        return {row["espn_id"]: row for row in csv.DictReader(handle) if row.get("espn_id")}


def write_ratings(season: int, ratings: Mapping[str, Mapping[str, float]], d1: Mapping[str, str], as_of: dt.date) -> Path:
    path = processed_dir() / f"team_ratings_{season}_asof_{as_of:%Y%m%d}.csv"
    tmp = path.with_suffix(".csv.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATING_FIELDS)
        writer.writeheader()
        for tid, r in sorted(ratings.items(), key=lambda item: -item[1]["adj_em"]):
            writer.writerow({**r, "team": d1[tid], "espn_id": tid, "season": season, "as_of": as_of.isoformat(), "source": "espn_box"})
    os.replace(tmp, path)
    return path


# ----------------------------------------------------------------------- main

def run(season: int, today: dt.date, *, rate: float, max_new_games: int | None, dry_run: bool) -> dict[str, Any]:
    d1 = load_registry()
    box_path = processed_dir() / f"team_game_box_{season}.csv"
    dates_path = processed_dir() / f"team_game_box_{season}.dates.json"
    done_dates: set[str] = set()
    if dates_path.is_file():
        done_dates = set(json.loads(dates_path.read_text(encoding="utf-8")).get("dates") or [])
    have_games = {row["game_id"] for row in read_box(box_path)}
    counts = {"dates_checked": 0, "games_fetched": 0, "games_skipped_incomplete": 0, "errors": 0}
    budget = max_new_games
    stop = False
    for day in season_dates(season, today):
        key = day.isoformat()
        if key in done_dates:
            continue
        counts["dates_checked"] += 1
        try:
            ids, all_final = final_event_ids(day)
            time.sleep(1.0 / rate)
        except Exception as exc:  # noqa: BLE001
            print(f"[ncaab_ratings] SCOREBOARD_FAILED date={key} {exc}", flush=True)
            counts["errors"] += 1
            continue
        date_complete = all_final
        for event_id in ids:
            if event_id in have_games:
                continue
            if budget is not None and budget <= 0:
                stop, date_complete = True, False
                break
            try:
                rows = parse_summary(_get_json(f"summary?event={event_id}"), season=season, day=key)
                time.sleep(1.0 / rate)
            except Exception as exc:  # noqa: BLE001
                print(f"[ncaab_ratings] SUMMARY_FAILED event={event_id} {exc}", flush=True)
                counts["errors"] += 1
                date_complete = False
                continue
            if not rows:
                counts["games_skipped_incomplete"] += 1
                continue
            if not dry_run:
                append_box(box_path, rows)
            have_games.add(event_id)
            counts["games_fetched"] += 1
            if budget is not None:
                budget -= 1
        if date_complete and not dry_run:
            done_dates.add(key)
            dates_path.parent.mkdir(parents=True, exist_ok=True)
            dates_path.write_text(json.dumps({"season": season, "dates": sorted(done_dates)}), encoding="utf-8")
        if stop:
            break
    rows = read_box(box_path)
    ratings = compute_ratings(rows, d1, prior=read_prior(season))
    last_game = max((row["date"] for row in rows), default=None)
    out_path = None
    if ratings and not dry_run and last_game:
        out_path = write_ratings(season, ratings, d1, dt.date.fromisoformat(last_game))
    summary = {**counts, "season": season, "box_rows": len(rows), "teams_rated": len(ratings), "last_game": last_game, "written": str(out_path) if out_path else None}
    print("[ncaab_ratings] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None, help="ESPN season year (the year it ends); default: current or last")
    parser.add_argument("--rate", type=float, default=4.0, help="requests per second (default 4)")
    parser.add_argument("--max-new-games", type=int, default=None, help="stop after fetching this many new games")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    today = dt.date.today()
    season = args.season or default_season(today)
    summary = run(season, today, rate=max(args.rate, 0.2), max_new_games=args.max_new_games, dry_run=args.dry_run)
    return 0 if summary["errors"] == 0 or summary["games_fetched"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
