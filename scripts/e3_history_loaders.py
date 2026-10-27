#!/usr/bin/env python3
"""E3 derived-surface test -- HISTORY loaders (prior seasons, used to fit sigma and segment shares).

Read-only. Stdlib only (the fleet's python3 has no numpy). Run on the fleet host:

    MSYS_NO_PATHCONV=1 wsl -- nice -n 19 python3 scripts/e3_history_loaders.py [--sports nfl,nba,...]

Writes ``<out>/history_<sport>.json``:

    {"sport", "source", "line_source", "sign_check", "games": [{
        "season", "date", "home", "away", "home_spread", "total_line",
        "periods_home", "periods_away", "ot_home", "ot_away", "final_home", "final_away", "phase", ...}],
     "dropped": {reason: n}}

CONVENTIONS (every sport):
  * ``home_spread`` is the CLOSING spread from the HOME team's side: negative = home favoured. ``total_line`` is the
    closing total. Both null where the sport has no line source here (NHL, soccer).
  * ``periods_*`` are the REGULATION periods in order (quarters; NHL periods; soccer [first half, second half]).
  * ``ot_*`` is everything beyond regulation (0 when none). NHL: a shootout adds 1 goal to the winner's final,
    and that 1 sits in ``ot_*`` with ``"so": true``.
  * ``final_* == sum(periods_*) + ot_*`` is ASSERTED per game; a game that fails it is dropped and counted.
  * ``season`` is the START year of the season (NBA/NHL 2025 = 2025-26; soccer 2025 = 2025-26).
  * ``date`` is the local (US-Eastern for US sports) game date the source files it under.

Sources (fleet data root ``~/syndicate-prod/data`` unless noted):
  nfl    nfl_source/tracking/nflverse/schedules_games.csv (finals + closing spread_line/total_line; nflverse
         spread_line is HOME-MARGIN-POSITIVE, so home_spread = -spread_line) and pbp_<season>.csv (quarter-end
         cumulative total_home_score / total_away_score).
  nba    backfill/nba_props_2025_26/cache/espn/<date>.json (ESPN scoreboards; season.type 2 = regular season) and
         backfill/nba_props_2025_26/asof/game_odds/<date>.csv columns ``home_spread`` / ``total`` (bookmaker =
         oddsapi_consensus; the last capture committed before that slate's first tip -- NOT a verified close).
  ncaaf  ncaaf_source/historical_truth/games_2025.json.gz (CFBD /games, classification=fbs, regular season) and
         CFBD /lines from the PRIMARY Windows checkout data/ncaaf_source/data/cfbd_lines_wk*.json (season 2025).
         CFBD carries no consensus provider; DraftKings is taken when quoted, else the median of the other
         providers (ESPN Bet / Bovada) -- recorded per game in ``spread_provider`` / ``total_provider``.
  nhl    backfill/nhl_lines_2025_26/actuals.json, arm == "regular" (2025-26). No lines.
  soccer soccer_source/<league>/history/matches_<season>.csv (football-data.co.uk), seasons 2023-2025, every
         league that has the file. periods = [HT goals, FT - HT goals]. No lines.
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

csv.field_size_limit(10 ** 9)

DATA_ROOT = os.path.expanduser("~/syndicate-prod/data")
CFBD_LINES_DIR = "/mnt/c/Users/tempadmin/OneDrive/Coding/Syndicate/data/ncaaf_source/data"
OUT_DIR = "/mnt/c/tmp/e3/extract"


# --------------------------------------------------------------------------------------------- helpers

def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() in ("", "NA", "nan", "None"):
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() in ("", "NA", "nan", "None"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def norm_name(name: Any) -> str:
    """Accent-fold, lower-case, drop punctuation, collapse spaces. Names must then match EXACTLY."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    folded = folded.replace("'", "").replace(".", "")
    kept = "".join(ch if ch.isalnum() or ch == " " else " " for ch in folded)
    return " ".join(kept.split())


def utc_to_et_date(iso_utc: str) -> str:
    """UTC ISO timestamp -> US-Eastern calendar date (EDT before the first Sunday of November, else EST)."""
    ts = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    year = ts.year
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)   # 2nd Sun Mar, 02:00 EST
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=6)         # 1st Sun Nov, 02:00 EDT
    offset = -4 if dst_start <= ts < dst_end else -5
    return (ts + timedelta(hours=offset)).date().isoformat()


def game_record(*, season: int, date: str, home: str, away: str, home_spread: float | None,
                total_line: float | None, periods_home: list[int], periods_away: list[int], ot_home: int,
                ot_away: int, final_home: int, final_away: int, phase: str, **extra: Any) -> dict[str, Any]:
    rec = {"season": season, "date": date, "home": home, "away": away, "home_spread": home_spread,
           "total_line": total_line, "periods_home": periods_home, "periods_away": periods_away,
           "ot_home": ot_home, "ot_away": ot_away, "final_home": final_home, "final_away": final_away,
           "phase": phase}
    rec.update(extra)
    return rec


def consistent(rec: dict[str, Any]) -> bool:
    """final == sum(regulation periods) + ot, both sides, no missing period."""
    for side in ("home", "away"):
        periods = rec[f"periods_{side}"]
        if any(p is None for p in periods):
            return False
        if sum(periods) + rec[f"ot_{side}"] != rec[f"final_{side}"]:
            return False
    return True


def write_json(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def summarize(games: list[dict[str, Any]]) -> dict[str, Any]:
    if not games:
        return {"n": 0}
    dates = sorted(g["date"] for g in games)
    out: dict[str, Any] = {"n": len(games), "first_date": dates[0], "last_date": dates[-1],
                           "by_season": dict(sorted(Counter(g["season"] for g in games).items())),
                           "by_phase": dict(Counter(g["phase"] for g in games))}
    lined = [g for g in games if g["home_spread"] is not None and g["total_line"] is not None]
    out["n_with_spread_and_total"] = len(lined)
    return out


# --------------------------------------------------------------------------------------------- NFL

NFL_POST_TYPES = {"WC", "DIV", "CON", "SB"}


def nfl_quarter_ends(pbp_path: str) -> dict[str, dict[int, tuple[int, int]]]:
    """game_id -> {qtr: (home cumulative, away cumulative) at the END of that quarter}.

    nflverse `total_home_score` / `total_away_score` are the score AFTER each play and never decrease, so the max
    over a quarter's rows is the score at the end of it (verified on 2025_01_DAL_PHI: END QUARTER 1 7-7,
    END QUARTER 2 21-20, END QUARTER 3 24-20, END GAME 24-20)."""
    ends: dict[str, dict[int, tuple[int, int]]] = defaultdict(dict)
    with open(pbp_path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        ig, iq = header.index("game_id"), header.index("qtr")
        ih, ia = header.index("total_home_score"), header.index("total_away_score")
        for row in reader:
            q, h, a = _int(row[iq]), _int(row[ih]), _int(row[ia])
            if q is None or h is None or a is None:
                continue
            prev = ends[row[ig]].get(q, (0, 0))
            ends[row[ig]][q] = (max(prev[0], h), max(prev[1], a))
    return ends


def load_nfl_history(data_root: str = DATA_ROOT, seasons: Iterable[int] = (2022, 2023, 2024, 2025)) -> dict[str, Any]:
    seasons = list(seasons)
    nfl = os.path.join(data_root, "nfl_source", "tracking", "nflverse")
    dropped: Counter = Counter()
    games: list[dict[str, Any]] = []
    sign = {"games": 0, "ml_agrees": 0, "ml_disagrees": 0, "mean_result_minus_spread_line": None}
    resid: list[float] = []
    with open(os.path.join(nfl, "schedules_games.csv"), encoding="utf-8", newline="") as handle:
        schedule = [r for r in csv.DictReader(handle) if _int(r["season"]) in seasons]
    ends_by_season = {s: nfl_quarter_ends(os.path.join(nfl, "pbp", f"pbp_{s}.csv")) for s in seasons}
    for r in schedule:
        season = int(r["season"])
        fh, fa = _int(r["home_score"]), _int(r["away_score"])
        if fh is None or fa is None:
            dropped["not_final"] += 1
            continue
        spread_line, total_line = _float(r["spread_line"]), _float(r["total_line"])
        if spread_line is None or total_line is None:
            dropped["no_closing_line"] += 1
            continue
        ends = ends_by_season[season].get(r["game_id"])
        if not ends or any(q not in ends for q in (1, 2, 3, 4)):
            dropped["pbp_missing_quarter"] += 1
            continue
        cum = [ends[q] for q in (1, 2, 3, 4)]
        last = ends[max(ends)]
        if last != (fh, fa):
            dropped["pbp_final_mismatch"] += 1
            continue
        ph = [cum[0][0]] + [cum[i][0] - cum[i - 1][0] for i in (1, 2, 3)]
        pa = [cum[0][1]] + [cum[i][1] - cum[i - 1][1] for i in (1, 2, 3)]
        rec = game_record(
            season=season, date=r["gameday"], home=r["home_team"], away=r["away_team"],
            home_spread=-spread_line, total_line=total_line, periods_home=ph, periods_away=pa,
            ot_home=fh - cum[3][0], ot_away=fa - cum[3][1], final_home=fh, final_away=fa,
            phase="POST" if r["game_type"] in NFL_POST_TYPES else "REG",
            game_id=r["game_id"], espn_id=r.get("espn") or None, neutral=(r.get("location") == "Neutral"))
        if not consistent(rec):
            dropped["periods_do_not_sum_to_final"] += 1
            continue
        games.append(rec)
        # sign check: nflverse spread_line > 0 must mean the HOME side is the moneyline favourite
        hml, aml = _float(r.get("home_moneyline")), _float(r.get("away_moneyline"))
        if spread_line != 0 and hml is not None and aml is not None and hml != aml:
            sign["games"] += 1
            if (spread_line > 0) == (hml < aml):
                sign["ml_agrees"] += 1
            else:
                sign["ml_disagrees"] += 1
        resid.append((fh - fa) - spread_line)
    sign["mean_result_minus_spread_line"] = round(statistics.fmean(resid), 3) if resid else None
    sign["rule"] = "home_spread = -spread_line; spread_line>0 <=> home is the moneyline favourite"
    return {"sport": "nfl", "source": "nflverse schedules_games.csv + pbp_<season>.csv (fleet)",
            "line_source": "nflverse spread_line / total_line (closing), sign flipped to home-negative",
            "sign_check": sign, "games": games, "dropped": dict(dropped)}


# --------------------------------------------------------------------------------------------- NBA

ESPN_TO_ODDSAPI_NBA = {"LA Clippers": "Los Angeles Clippers"}


def espn_completed_events(paths: Iterable[str]) -> dict[str, tuple[str, dict[str, Any]]]:
    """event id -> (scoreboard file date YYYY-MM-DD, event), completed events only, de-duplicated by id."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted(paths):
        stem = os.path.basename(path).split(".")[0].replace("scoreboard_", "")
        day = stem if "-" in stem else f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        for event in payload.get("events") or []:
            if ((event.get("status") or {}).get("type") or {}).get("completed"):
                out.setdefault(str(event.get("id")), (day, event))
    return out


def espn_sides(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    comp = (event.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
    return sides.get("home") or {}, sides.get("away") or {}


def espn_periods(competitor: dict[str, Any]) -> list[int | None]:
    return [_int(x.get("value")) for x in competitor.get("linescores") or []]


def load_nba_history(data_root: str = DATA_ROOT) -> dict[str, Any]:
    base = os.path.join(data_root, "backfill", "nba_props_2025_26")
    dropped: Counter = Counter()
    odds: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in glob.glob(os.path.join(base, "asof", "game_odds", "*.csv")):
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                odds[(norm_name(row["home_team"]), norm_name(row["visitor_team"]))].append(row)
    sign = {"games": 0, "ml_agrees": 0, "ml_disagrees": 0,
            "rule": "game_odds.home_spread < 0 <=> home_ml < away_ml (home is the moneyline favourite); used as-is"}
    games: list[dict[str, Any]] = []
    used_rows: set[int] = set()
    for event_id, (day, event) in espn_completed_events(glob.glob(os.path.join(base, "cache", "espn", "*.json"))).items():
        stype = _int((event.get("season") or {}).get("type"))
        if stype != 2:
            dropped[f"not_regular_season(type={stype})"] += 1
            continue
        home, away = espn_sides(event)
        hname = ESPN_TO_ODDSAPI_NBA.get((home.get("team") or {}).get("displayName"), (home.get("team") or {}).get("displayName"))
        aname = ESPN_TO_ODDSAPI_NBA.get((away.get("team") or {}).get("displayName"), (away.get("team") or {}).get("displayName"))
        ph, pa = espn_periods(home), espn_periods(away)
        fh, fa = _int(home.get("score")), _int(away.get("score"))
        if len(ph) < 4 or len(pa) < 4 or fh is None or fa is None:
            dropped["missing_linescore"] += 1
            continue
        start = datetime.fromisoformat(str(event.get("date")).replace("Z", "+00:00"))
        cands = [row for row in odds.get((norm_name(hname), norm_name(aname)), [])
                 if abs((datetime.fromisoformat(row["commence_time"].replace("Z", "+00:00")) - start).total_seconds()) <= 12 * 3600]
        if not cands:
            dropped["no_game_odds_row"] += 1
            continue
        if len(cands) > 1:
            dropped["ambiguous_game_odds_row"] += 1
            continue
        row = cands[0]
        if id(row) in used_rows:
            dropped["game_odds_row_reused"] += 1
            continue
        used_rows.add(id(row))
        if row.get("bookmaker") != "oddsapi_consensus":
            # 22 rows on 2026-02-24/25 and 03-09 are single-book `bovada`; 4 of them contradict their own moneyline.
            dropped[f"game_odds_not_consensus({row.get('bookmaker')})"] += 1
            continue
        spread, total = _float(row.get("home_spread")), _float(row.get("total"))
        if spread is None or total is None:
            dropped["odds_row_missing_spread_or_total"] += 1
            continue
        rec = game_record(
            season=2025, date=day, home=hname, away=aname, home_spread=spread, total_line=total,
            periods_home=ph[:4], periods_away=pa[:4], ot_home=sum(p or 0 for p in ph[4:]),
            ot_away=sum(p or 0 for p in pa[4:]), final_home=fh, final_away=fa, phase="REG",
            espn_id=event_id, odds_commence=row["commence_time"], books_spreads=_int(row.get("books_spreads")),
            books_totals=_int(row.get("books_totals")))
        if not consistent(rec):
            dropped["periods_do_not_sum_to_final"] += 1
            continue
        games.append(rec)
        hml, aml = _float(row.get("home_ml")), _float(row.get("away_ml"))
        if spread != 0 and hml is not None and aml is not None and hml != aml:
            sign["games"] += 1                     # lower American price = the moneyline favourite
            sign["ml_agrees" if (spread < 0) == (hml < aml) else "ml_disagrees"] += 1
    games.sort(key=lambda g: (g["date"], g["home"]))
    return {"sport": "nba", "source": "backfill/nba_props_2025_26/cache/espn (ESPN scoreboards, season.type 2)",
            "line_source": "backfill/nba_props_2025_26/asof/game_odds/<date>.csv columns home_spread, total "
                           "(bookmaker=oddsapi_consensus; latest pre-tip committed capture, not a verified close)",
            "sign_check": sign, "games": games, "dropped": dict(dropped)}


# --------------------------------------------------------------------------------------------- NCAAF

def _is_dk(provider: Any) -> bool:
    return norm_name(provider).replace(" ", "") == "draftkings"


def cfbd_pick(lines: list[dict[str, Any]], field: str) -> tuple[float | None, str | None]:
    """DraftKings' value when quoted; else the median of every other provider's value; (None, None) if none."""
    dk = [_float(l.get(field)) for l in lines if _is_dk(l.get("provider")) and _float(l.get(field)) is not None]
    if dk:
        return dk[0], "DraftKings"
    rest = [(_float(l.get(field)), str(l.get("provider"))) for l in lines if _float(l.get(field)) is not None]
    if not rest:
        return None, None
    return statistics.median(v for v, _ in rest), "median(" + "+".join(sorted(p for _, p in rest)) + ")"


def _formatted_spread_sign_ok(row: dict[str, Any], line: dict[str, Any]) -> bool | None:
    """CFBD `formattedSpread` is '<favourite> -X'. If the favourite is the home team, `spread` must be negative."""
    text, spread = str(line.get("formattedSpread") or ""), _float(line.get("spread"))
    if not spread or " -" not in text:
        return None
    fav = text.rsplit(" -", 1)[0].strip()
    if fav == row.get("homeTeam"):
        return spread < 0
    if fav == row.get("awayTeam"):
        return spread > 0
    return None


def load_ncaaf_history(data_root: str = DATA_ROOT, lines_dir: str = CFBD_LINES_DIR, season: int = 2025) -> dict[str, Any]:
    with gzip.open(os.path.join(data_root, "ncaaf_source", "historical_truth", f"games_{season}.json.gz"), "rt",
                   encoding="utf-8") as handle:
        cfbd_games = json.load(handle)
    lines_by_id: dict[int, dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(lines_dir, "cfbd_lines_wk*.json"))):
        with open(path, encoding="utf-8") as handle:
            for row in json.load(handle):
                if _int(row.get("season")) == season and row.get("lines"):
                    lines_by_id[int(row["id"])] = row
    sign = {"lines_checked": 0, "formatted_spread_agrees": 0, "formatted_spread_disagrees": 0,
            "rule": "CFBD spread is home-side (negative = home favoured); used as-is"}
    for row in lines_by_id.values():
        for line in row["lines"]:
            ok = _formatted_spread_sign_ok(row, line)
            if ok is not None:
                sign["lines_checked"] += 1
                sign["formatted_spread_agrees" if ok else "formatted_spread_disagrees"] += 1
    dropped: Counter = Counter()
    providers: Counter = Counter()
    games: list[dict[str, Any]] = []
    for g in cfbd_games:
        if not g.get("completed"):
            dropped["not_completed"] += 1
            continue
        lh, la = g.get("homeLineScores") or [], g.get("awayLineScores") or []
        fh, fa = _int(g.get("homePoints")), _int(g.get("awayPoints"))
        if len(lh) < 4 or len(la) < 4 or fh is None or fa is None:
            dropped["missing_line_scores"] += 1
            continue
        lrow = lines_by_id.get(int(g["id"]))
        if lrow is None:
            dropped["no_cfbd_lines_row"] += 1
            continue
        spread, sprov = cfbd_pick(lrow["lines"], "spread")
        total, tprov = cfbd_pick(lrow["lines"], "overUnder")
        if spread is None or total is None:
            dropped["no_spread_or_total_quoted"] += 1
            continue
        providers[f"spread:{'DraftKings' if sprov == 'DraftKings' else 'median_other'}"] += 1
        providers[f"total:{'DraftKings' if tprov == 'DraftKings' else 'median_other'}"] += 1
        lh_i, la_i = [_int(x) for x in lh], [_int(x) for x in la]
        rec = game_record(
            season=season, date=utc_to_et_date(g["startDate"]), home=g["homeTeam"], away=g["awayTeam"],
            home_spread=spread, total_line=total, periods_home=lh_i[:4], periods_away=la_i[:4],
            ot_home=sum(x or 0 for x in lh_i[4:]), ot_away=sum(x or 0 for x in la_i[4:]), final_home=fh,
            final_away=fa, phase="REG", cfbd_id=int(g["id"]), week=g.get("week"),
            neutral=bool(g.get("neutralSite")),
            fbs_vs_fbs=(g.get("homeClassification") == "fbs" and g.get("awayClassification") == "fbs"),
            spread_provider=sprov, total_provider=tprov)
        if not consistent(rec):
            dropped["line_scores_do_not_sum_to_final"] += 1
            continue
        games.append(rec)
    games.sort(key=lambda r: (r["date"], r["home"]))
    return {"sport": "ncaaf", "source": f"ncaaf_source/historical_truth/games_{season}.json.gz (CFBD /games, fbs, regular)",
            "line_source": "CFBD /lines (primary Windows checkout cfbd_lines_wk*.json): `spread` / `overUnder` "
                           "(closing; *Open fields ignored). No consensus provider exists in CFBD 2025 "
                           "(providers: ESPN Bet, Bovada, DraftKings); DraftKings when quoted, else median of the others",
            "provider_counts": dict(providers), "sign_check": sign, "games": games, "dropped": dict(dropped)}


# --------------------------------------------------------------------------------------------- NHL

def load_nhl_history(data_root: str = DATA_ROOT) -> dict[str, Any]:
    with open(os.path.join(data_root, "backfill", "nhl_lines_2025_26", "actuals.json"), encoding="utf-8") as handle:
        actuals = json.load(handle)
    dropped: Counter = Counter()
    games: list[dict[str, Any]] = []
    for gid, a in sorted(actuals.items()):
        if a.get("arm") != "regular":
            dropped[f"arm={a.get('arm')}"] += 1
            continue
        ph = [_int(a.get(f"p{i}_h")) for i in (1, 2, 3)]
        pa = [_int(a.get(f"p{i}_a")) for i in (1, 2, 3)]
        fh, fa = _int(a.get("final_h")), _int(a.get("final_a"))
        if None in ph or None in pa or fh is None or fa is None:
            dropped["missing_period_or_final"] += 1
            continue
        rec = game_record(
            season=2025, date=a["date"], home=a["home"], away=a["away"], home_spread=None, total_line=None,
            periods_home=ph, periods_away=pa, ot_home=fh - sum(ph), ot_away=fa - sum(pa), final_home=fh,
            final_away=fa, phase="REG", so=bool(a.get("so")), last_period=a.get("last"), nhl_game_id=gid)
        ot_goals = (_int(a.get("ot_h")) or 0, _int(a.get("ot_a")) or 0)
        so_goal = (1 if rec["so"] and fh > fa else 0, 1 if rec["so"] and fa > fh else 0)
        if (rec["ot_home"], rec["ot_away"]) != (ot_goals[0] + so_goal[0], ot_goals[1] + so_goal[1]):
            dropped["ot_or_shootout_inconsistent"] += 1
            continue
        if not consistent(rec):
            dropped["periods_do_not_sum_to_final"] += 1
            continue
        games.append(rec)
    return {"sport": "nhl", "source": "backfill/nhl_lines_2025_26/actuals.json (arm=regular, 2025-26)",
            "line_source": None, "sign_check": None, "games": games, "dropped": dict(dropped)}


# --------------------------------------------------------------------------------------------- soccer

def _soccer_date(text: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def load_soccer_history(data_root: str = DATA_ROOT, seasons: Iterable[int] = (2023, 2024, 2025)) -> dict[str, Any]:
    dropped: Counter = Counter()
    games: list[dict[str, Any]] = []
    leagues: Counter = Counter()
    for season in seasons:
        for path in sorted(glob.glob(os.path.join(data_root, "soccer_source", "*", "history", f"matches_{season}.csv"))):
            league = path.split(os.sep)[-3]
            with open(path, encoding="utf-8", newline="") as handle:
                for r in csv.DictReader(handle):
                    fh, fa = _int(r.get("home_goals")), _int(r.get("away_goals"))
                    hh, ha = _int(r.get("ht_home_goals")), _int(r.get("ht_away_goals"))
                    day = _soccer_date(r.get("date") or "")
                    if fh is None or fa is None:
                        dropped["no_final"] += 1
                        continue
                    if hh is None or ha is None:
                        dropped["no_half_time_score"] += 1
                        continue
                    if hh > fh or ha > fa or day is None:
                        dropped["bad_half_time_or_date"] += 1
                        continue
                    games.append(game_record(
                        season=season, date=day, home=r["home_team"], away=r["away_team"], home_spread=None,
                        total_line=None, periods_home=[hh, fh - hh], periods_away=[ha, fa - ha], ot_home=0,
                        ot_away=0, final_home=fh, final_away=fa, phase="REG", league=league,
                        match_id=r.get("match_id")))
                    leagues[league] += 1
    return {"sport": "soccer", "source": "soccer_source/<league>/history/matches_<season>.csv (football-data.co.uk)",
            "line_source": None, "sign_check": None, "league_counts": dict(leagues), "games": games,
            "dropped": dict(dropped)}


# --------------------------------------------------------------------------------------------- main

LOADERS = {"nfl": load_nfl_history, "nba": load_nba_history, "ncaaf": load_ncaaf_history,
           "nhl": load_nhl_history, "soccer": load_soccer_history}


def main(sports: Iterable[str] = tuple(LOADERS), out_dir: str = OUT_DIR) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for sport in sports:
        payload = LOADERS[sport]()
        write_json(os.path.join(out_dir, f"history_{sport}.json"), payload)
        report[sport] = {"summary": summarize(payload["games"]), "dropped": payload["dropped"],
                         "sign_check": payload.get("sign_check"), "provider_counts": payload.get("provider_counts")}
        print(sport, json.dumps(report[sport]), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sports", default=",".join(LOADERS))
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()
    main([s.strip() for s in args.sports.split(",") if s.strip()], args.out_dir)
