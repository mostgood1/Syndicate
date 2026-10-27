#!/usr/bin/env python3
"""E3 derived-surface test -- WINDOW score loaders (outcomes for the test window).

Read-only. Stdlib only. Run on the fleet host:

    MSYS_NO_PATHCONV=1 wsl -- nice -n 19 python3 scripts/e3_window_loaders.py [--sports nba,wnba,...]

Window: anchor ``commence`` in [2026-09-30T00:00Z, 2026-10-26T08:00Z]. Every game is keyed by OUR book event_id
from ``anchors_<sport>.json`` (``{"events": [{"event_id", "commence", "home", "away", ...}]}``; ``quotes`` is never
read). No market price of any kind is read here.

Writes ``<out>/window_<sport>.json``:

    {"sport", "window", "sources", "games": {<event_id>: {"season", "date", "commence", "home", "away",
        "source_home", "source_away", "periods_home", "periods_away", "ot_home", "ot_away", "final_home",
        "final_away", "phase", "source", ...}},
     "unmatched": [{"event_id", "commence", "home", "away", "reason"}], "summary": {...}}

Score conventions are the HISTORY loaders' (periods = regulation periods in order, ot = everything beyond
regulation, final == sum(periods) + ot asserted). Sport specifics:
  * NHL: a shootout adds 1 goal to the winner in ``ot_*`` and sets ``"so": true``.
  * MLB: periods = innings 1..9, ot = runs in innings 10+. A bottom half that was never played (home team ahead
    after 8.5 or a walk-off) is ``None`` -- a hole, not a zero; ``final`` sums the innings actually played.

MATCHING (exact-or-refuse): anchor commence -> US-Eastern date; a source game matches when BOTH team names are equal
after ``norm_name`` (accent fold, lower-case, punctuation dropped) plus an explicit per-sport name map, home to
home and away to away. Pass 1 takes a unique game on the same ET date; pass 2 takes a unique, not-yet-claimed game
on ET date +-1. Anything else is refused and listed in ``unmatched`` with the reason.

Sources (fleet data root ``~/syndicate-prod/data``):
  nba    interval_history/nba/<date>.json (ESPN, preseason excluded by its writer); fallback
         nba_source/data/processed/linescores_<date>.json (ESPN scoreboard incl. preseason, tri-codes).
  wnba   interval_history/wnba/<date>.json; fallback ESPN scoreboard caches wnba_source/data/processed/_espn_cache.
  nhl    nhl_source/data/ingestion_cache/score_<date>.json (api-web, league feed); fallback interval_history/nhl;
         every game in both is cross-checked.
  mlb    interval_history/mlb/<date>.json (StatsAPI linescore) + daily schedule snapshots (gameType, start time);
         cross-check settlement_inputs/finals_<date>.json (scores only).
  ncaaf  ncaaf_source/historical_truth/games_2026.json.gz (CFBD) + team registry (school + mascot = OddsAPI name).
  nfl    nfl_source/tracking/nflverse/schedules_games.csv (finals) + pbp/pbp_2026.csv (quarter-end scores).
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import unicodedata
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

csv.field_size_limit(10 ** 9)

DATA_ROOT = os.path.expanduser("~/syndicate-prod/data")
EXTRACT_DIR = "/mnt/c/tmp/e3/extract"
WINDOW_START = "2026-09-30T00:00:00+00:00"
WINDOW_END = "2026-10-26T08:00:00+00:00"


# --------------------------------------------------------------------------------------------- helpers

def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() in ("", "NA", "nan", "None"):
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def norm_name(name: Any) -> str:
    """Accent-fold, lower-case, drop apostrophes/periods, other punctuation -> space, collapse spaces."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    folded = folded.replace("'", "").replace(".", "")
    kept = "".join(ch if ch.isalnum() or ch == " " else " " for ch in folded)
    return " ".join(kept.split())


def parse_utc(text: str) -> datetime:
    ts = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def utc_to_et(iso_utc: str) -> datetime:
    """UTC ISO timestamp -> US-Eastern wall clock (EDT 2nd Sun Mar 02:00 .. 1st Sun Nov 02:00, else EST)."""
    ts = parse_utc(iso_utc)
    mar1 = datetime(ts.year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    nov1 = datetime(ts.year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    return ts + timedelta(hours=-4 if dst_start <= ts < dst_end else -5)


def utc_to_et_date(iso_utc: str) -> str:
    return utc_to_et(iso_utc).date().isoformat()


def et_to_utc(day: str, hhmm: str) -> str | None:
    """US-Eastern local date + 'HH:MM' -> UTC ISO: the offset (4 or 5 h) whose UTC instant reads back as that
    same Eastern wall clock."""
    try:
        local = datetime.fromisoformat(f"{day}T{hhmm.strip()}:00").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    for offset in (4, 5):
        ts = local + timedelta(hours=offset)
        if utc_to_et(ts.isoformat()) == local:
            return ts.isoformat()
    return None


def shift_day(day: str, days: int) -> str:
    return (_date.fromisoformat(day) + timedelta(days=days)).isoformat()


def write_json(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def load_anchors(sport: str, extract_dir: str = EXTRACT_DIR) -> list[dict[str, Any]]:
    """Anchor events inside the window. Only event_id / commence / home / away are read."""
    with open(os.path.join(extract_dir, f"anchors_{sport}.json"), encoding="utf-8") as handle:
        events = json.load(handle).get("events") or []
    lo, hi = parse_utc(WINDOW_START), parse_utc(WINDOW_END)
    out = []
    for e in events:
        start = parse_utc(e["commence"])
        if lo <= start <= hi:
            out.append({"event_id": e["event_id"], "commence": e["commence"], "home": e["home"], "away": e["away"]})
    return out


def score_fields(periods_home: list[int | None], periods_away: list[int | None], regulation: int,
                 *, final_home: int | None = None, final_away: int | None = None) -> dict[str, Any] | None:
    """Split per-period scores into regulation + ot; None if a regulation period (other than MLB's unplayed
    bottom half, handled by the caller) is missing or the final does not reconcile."""
    if len(periods_home) < regulation or len(periods_away) < regulation:
        return None
    rh, ra = periods_home[:regulation], periods_away[:regulation]
    oh = sum(p or 0 for p in periods_home[regulation:])
    oa = sum(p or 0 for p in periods_away[regulation:])
    fh = sum(p or 0 for p in rh) + oh if final_home is None else final_home
    fa = sum(p or 0 for p in ra) + oa if final_away is None else final_away
    if sum(p or 0 for p in rh) + oh != fh or sum(p or 0 for p in ra) + oa != fa:
        return None
    return {"periods_home": rh, "periods_away": ra, "ot_home": oh, "ot_away": oa, "final_home": fh, "final_away": fa}


# A candidate is {"date": ET date, "home": source name, "away": source name, "key_home", "key_away", **score fields}.

def match_anchors(anchors: list[dict[str, Any]], candidates: list[dict[str, Any]],
                  anchor_key: Callable[[str], str | None]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Exact-or-refuse join of anchors to source games. Returns ({event_id: candidate}, unmatched)."""
    by_teams: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    known: set[str] = set()
    for c in candidates:
        by_teams[(c["key_home"], c["key_away"])].append(c)
        known.update((c["key_home"], c["key_away"]))
    matched: dict[str, dict[str, Any]] = {}
    claimed: set[int] = set()
    pending: list[tuple[dict[str, Any], str, str, str]] = []
    unmatched: list[dict[str, Any]] = []

    def refuse(a: dict[str, Any], reason: str) -> None:
        unmatched.append({**a, "reason": reason})

    for a in anchors:
        kh, ka = anchor_key(a["home"]), anchor_key(a["away"])
        if kh is None or ka is None:
            refuse(a, "team_name_unmapped:" + ",".join(n for n, k in ((a["home"], kh), (a["away"], ka)) if k is None))
            continue
        et = utc_to_et_date(a["commence"])
        same = [c for c in by_teams.get((kh, ka), []) if c["date"] == et]
        if len(same) == 1:
            matched[a["event_id"]] = same[0]
            claimed.add(id(same[0]))
        elif len(same) > 1:
            refuse(a, f"ambiguous:{len(same)}_source_games_same_date")
        else:
            pending.append((a, kh, ka, et))
    # Two anchors on the same ET date claiming ONE source game (a duplicate / stale OddsAPI event). When the source
    # carries its own start time, keep the claimant closest to it if that one is within 3h AND at least 30 min closer
    # than every other claimant; otherwise refuse every claimant. One game never feeds two anchors.
    claimants: dict[int, list[str]] = defaultdict(list)
    for event_id, c in matched.items():
        claimants[id(c)].append(event_id)
    anchor_by_id = {a["event_id"]: a for a in anchors}
    for cid, event_ids in claimants.items():
        if len(event_ids) < 2:
            continue
        c = matched[event_ids[0]]
        keep = None
        if c.get("start_utc"):
            gaps = sorted((abs((parse_utc(anchor_by_id[e]["commence"]) - parse_utc(c["start_utc"])).total_seconds()), e)
                          for e in event_ids)
            if gaps[0][0] <= 3 * 3600 and gaps[1][0] - gaps[0][0] >= 30 * 60:
                keep = gaps[0][1]
                c["duplicate_anchors_refused"] = [e for _, e in gaps[1:]]
        for e in event_ids:
            if e == keep:
                continue
            matched.pop(e)
            refuse(anchor_by_id[e], "duplicate_anchor_commence_not_at_source_start" if keep
                   else f"multiple_anchors_claim_one_source_game:{len(event_ids)}")
    for a, kh, ka, et in pending:
        near = [c for c in by_teams.get((kh, ka), [])
                if c["date"] in (shift_day(et, -1), shift_day(et, 1)) and id(c) not in claimed]
        if len(near) == 1:
            matched[a["event_id"]] = near[0]
            claimed.add(id(near[0]))
            continue
        if len(near) > 1:
            refuse(a, f"ambiguous:{len(near)}_source_games_within_1_day")
            continue
        swapped = [c for c in by_teams.get((ka, kh), []) if abs((_date.fromisoformat(c["date"]) - _date.fromisoformat(et)).days) <= 1]
        if swapped:
            refuse(a, "home_away_swapped_in_source")
        elif kh not in known or ka not in known:
            refuse(a, "team_absent_from_source:" + ",".join(n for n, k in ((a["home"], kh), (a["away"], ka)) if k not in known))
        else:
            refuse(a, "no_source_game_within_1_day")
    return matched, unmatched


def build_payload(sport: str, anchors: list[dict[str, Any]], layers: list[tuple[str, list[dict[str, Any]]]],
                  anchor_key: Callable[[str], str | None], season: int) -> dict[str, Any]:
    """Match anchors against source layers in priority order; a later layer only sees what earlier ones left."""
    games: dict[str, dict[str, Any]] = {}
    remaining = list(anchors)
    unmatched: list[dict[str, Any]] = []
    reasons_by_event: dict[str, list[str]] = defaultdict(list)
    per_source: Counter = Counter()
    for label, cands in layers:
        matched, unmatched = match_anchors(remaining, cands, anchor_key)
        for u in unmatched:
            reasons_by_event[u["event_id"]].append(f"{label}: {u['reason']}")
        for u in unmatched:
            u["reasons_by_layer"] = list(reasons_by_event[u["event_id"]])
        for a in remaining:
            c = matched.get(a["event_id"])
            if c is None:
                continue
            rec = {"season": season, "date": c["date"], "commence": a["commence"], "home": a["home"], "away": a["away"],
                   "source_home": c["home"], "source_away": c["away"], "source": label}
            rec.update({k: v for k, v in c.items() if k not in ("date", "home", "away", "key_home", "key_away")})
            games[a["event_id"]] = rec
            per_source[label] += 1
        remaining = [a for a in remaining if a["event_id"] not in matched]
    reasons = Counter(u["reason"].split(":")[0] for u in unmatched)
    return {"sport": sport, "window": [WINDOW_START, WINDOW_END], "sources": [label for label, _ in layers],
            "games": games, "unmatched": unmatched,
            "summary": {"anchors_in_window": len(anchors), "matched": len(games), "by_source": dict(per_source),
                        "by_phase": dict(Counter(g.get("phase") for g in games.values())),
                        "unmatched_by_reason": dict(reasons)}}


# --------------------------------------------------------------------------------------------- name maps

NBA_ALIASES = {"la clippers": "los angeles clippers"}
NBA_ESPN_ABBR = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers", "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GS": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves", "NO": "New Orleans Pelicans", "NY": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SA": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTAH": "Utah Jazz", "WSH": "Washington Wizards"}
NHL_ABBR = {
    "ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres", "CGY": "Calgary Flames",
    "CAR": "Carolina Hurricanes", "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche",
    "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars", "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers", "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montreal Canadiens",
    "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders", "NYR": "New York Rangers",
    "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers", "PIT": "Pittsburgh Penguins", "SJS": "San Jose Sharks",
    "SEA": "Seattle Kraken", "STL": "St Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights", "WSH": "Washington Capitals",
    "WPG": "Winnipeg Jets"}
NFL_ABBR = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}


def plain_key(aliases: dict[str, str] | None = None) -> Callable[[str], str | None]:
    aliases = aliases or {}

    def key(name: str) -> str | None:
        k = norm_name(name)
        return aliases.get(k, k) or None
    return key


# --------------------------------------------------------------------------------------------- sources

def interval_history_candidates(sport: str, regulation: int, data_root: str = DATA_ROOT,
                                aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """interval_history/<sport>/<ET date>.json -> candidates (final games only). Files are dated by the feed's
    own local date (ESPN `dates=` / StatsAPI officialDate)."""
    key = plain_key(aliases)
    out = []
    for path in sorted(glob.glob(os.path.join(data_root, "interval_history", sport, "*.json"))):
        day = os.path.basename(path)[:10]
        with open(path, encoding="utf-8") as handle:
            for g in json.load(handle):
                if not g.get("final"):
                    continue
                ph, pa = list(g.get("home_periods") or []), list(g.get("away_periods") or [])
                rec = interval_score(sport, ph, pa, regulation)
                if rec is None:
                    continue
                out.append({"date": day, "home": g["home"], "away": g["away"], "key_home": key(g["home"]),
                            "key_away": key(g["away"]), **rec})
    return out


def interval_score(sport: str, ph: list[int | None], pa: list[int | None], regulation: int) -> dict[str, Any] | None:
    if sport == "nhl":
        # ESPN NHL linescores: [p1, p2, p3, (OT), (SO)]; the SO entry is 1 for the shootout winner, 0 for the loser
        # (verified against api-web score_2026-10-08.json: VGK [1,2,0,0,1] / TOR [3,0,0,0,0] -> final 4-3, SO).
        if len(ph) != len(pa) or len(ph) < 3 or any(p is None for p in ph + pa):
            return None
        so = len(ph) == 5
        ot_h = (ph[3] if len(ph) > 3 else 0) + (1 if so and ph[4] > pa[4] else 0)
        ot_a = (pa[3] if len(pa) > 3 else 0) + (1 if so and pa[4] > ph[4] else 0)
        if so and ph[4] == pa[4]:
            return None
        return {"periods_home": ph[:3], "periods_away": pa[:3], "ot_home": ot_h, "ot_away": ot_a,
                "final_home": sum(ph[:3]) + ot_h, "final_away": sum(pa[:3]) + ot_a, "so": so,
                "phase": "REG_OR_POST"}
    if sport == "mlb":
        # A None in inning 9 is an unplayed bottom half; anything else missing is a hole -> refuse.
        if len(ph) < regulation or len(pa) < regulation:
            return None
        if any(p is None for p in pa) or any(p is None for i, p in enumerate(ph) if i != len(ph) - 1):
            return None
        rec = score_fields(ph, pa, regulation)
        if rec is None:
            return None
        rec["phase"] = "REG_OR_POST"
        rec["home_last_half_unplayed"] = ph[-1] is None
        return rec
    if any(p is None for p in ph + pa):
        return None
    rec = score_fields(ph, pa, regulation)
    if rec is not None:
        rec["phase"] = "REG_OR_POST"
    return rec


def espn_linescores_file_candidates(league: str, data_root: str = DATA_ROOT) -> list[dict[str, Any]]:
    """<league>_source/data/processed/linescores_<date>.json (ESPN scoreboard, completed games, tri-codes,
    preseason INCLUDED). Tri-codes are mapped to full names through NBA_ESPN_ABBR; an unknown code is skipped."""
    out = []
    for path in sorted(glob.glob(os.path.join(data_root, f"{league}_source", "data", "processed", "linescores_*.json"))):
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        day = str(payload.get("date") or os.path.basename(path)[11:21])
        for event_id, g in (payload.get("games") or {}).items():
            home, away = NBA_ESPN_ABBR.get(g.get("home")), NBA_ESPN_ABBR.get(g.get("away"))
            if home is None or away is None:
                continue
            rec = score_fields(list(g.get("home_periods") or []), list(g.get("away_periods") or []), 4)
            if rec is None:
                continue
            out.append({"date": day, "home": home, "away": away, "key_home": norm_name(home),
                        "key_away": norm_name(away), **rec, "phase": "UNKNOWN", "espn_id": event_id})
    return out


def espn_scoreboard_cache_candidates(league: str, data_root: str = DATA_ROOT,
                                     aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Cached raw ESPN scoreboards (<league>_source/data/processed/_espn_cache[/<league>]/scoreboard_YYYYMMDD.json),
    completed events only, de-duplicated by ESPN id. Phase from season.type (1 PRE, 2 REG, 3 POST)."""
    key = plain_key(aliases)
    base = os.path.join(data_root, f"{league}_source", "data", "processed", "_espn_cache")
    seen: set[str] = set()
    out = []
    for path in sorted(glob.glob(os.path.join(base, "scoreboard_*.json")) + glob.glob(os.path.join(base, league, "scoreboard_*.json"))):
        stem = os.path.basename(path)[11:19]
        day = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        for event in payload.get("events") or []:
            eid = str(event.get("id"))
            if eid in seen or not ((event.get("status") or {}).get("type") or {}).get("completed"):
                continue
            comp = (event.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
            home, away = sides.get("home") or {}, sides.get("away") or {}
            ph = [_int(x.get("value")) for x in home.get("linescores") or []]
            pa = [_int(x.get("value")) for x in away.get("linescores") or []]
            if any(p is None for p in ph + pa):
                continue
            rec = score_fields(ph, pa, 4, final_home=_int(home.get("score")), final_away=_int(away.get("score")))
            if rec is None:
                continue
            seen.add(eid)
            hname, aname = (home.get("team") or {}).get("displayName"), (away.get("team") or {}).get("displayName")
            stype = _int((event.get("season") or {}).get("type"))
            out.append({"date": day, "start_utc": event.get("date"), "home": hname, "away": aname,
                        "key_home": key(hname), "key_away": key(aname),
                        **rec, "phase": {1: "PRE", 2: "REG", 3: "POST"}.get(stype, f"type{stype}"), "espn_id": eid})
    return out


def nhl_score_candidates(data_root: str = DATA_ROOT) -> list[dict[str, Any]]:
    """api-web /v1/score/<date> caches: per-period goals from `goals[]`, final from team.score (includes the
    shootout winner's +1). gameType 1 = PRE, 2 = REG, 3 = POST."""
    out = []
    seen: set[int] = set()
    for path in sorted(glob.glob(os.path.join(data_root, "nhl_source", "data", "ingestion_cache", "score_*.json"))):
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        for g in payload.get("games") or []:
            if g.get("gameState") not in ("OFF", "FINAL") or g.get("id") in seen:
                continue
            home, away = NHL_ABBR.get((g.get("homeTeam") or {}).get("abbrev")), NHL_ABBR.get((g.get("awayTeam") or {}).get("abbrev"))
            fh, fa = _int((g.get("homeTeam") or {}).get("score")), _int((g.get("awayTeam") or {}).get("score"))
            if home is None or away is None or fh is None or fa is None:
                continue
            ph, pa = [0, 0, 0], [0, 0, 0]
            for goal in g.get("goals") or []:
                pdsc = goal.get("periodDescriptor") or {}
                if pdsc.get("periodType") == "REG" and 1 <= int(pdsc.get("number") or 0) <= 3:
                    team = goal.get("teamAbbrev")
                    team = team.get("default") if isinstance(team, dict) else team
                    side = ph if team == g["homeTeam"]["abbrev"] else pa
                    side[int(pdsc["number"]) - 1] += 1
            so = (g.get("gameOutcome") or {}).get("lastPeriodType") == "SO"
            seen.add(g.get("id"))
            out.append({"date": g.get("gameDate") or os.path.basename(path)[6:16], "start_utc": g.get("startTimeUTC"),
                        "home": home, "away": away,
                        "key_home": norm_name(home), "key_away": norm_name(away), "periods_home": ph,
                        "periods_away": pa, "ot_home": fh - sum(ph), "ot_away": fa - sum(pa), "final_home": fh,
                        "final_away": fa, "so": so, "phase": {1: "PRE", 2: "REG", 3: "POST"}.get(g.get("gameType"), "UNKNOWN"),
                        "nhl_game_id": g.get("id")})
    return out


def ncaaf_candidates(data_root: str = DATA_ROOT, season: int = 2026) -> list[dict[str, Any]]:
    with gzip.open(os.path.join(data_root, "ncaaf_source", "historical_truth", f"games_{season}.json.gz"), "rt",
                   encoding="utf-8") as handle:
        games = json.load(handle)
    out = []
    for g in games:
        if not g.get("completed"):
            continue
        lh = [_int(x) for x in g.get("homeLineScores") or []]
        la = [_int(x) for x in g.get("awayLineScores") or []]
        if any(x is None for x in lh + la):
            continue
        rec = score_fields(lh, la, 4, final_home=_int(g.get("homePoints")), final_away=_int(g.get("awayPoints")))
        if rec is None:
            continue
        out.append({"date": utc_to_et_date(g["startDate"]), "start_utc": g["startDate"], "home": g["homeTeam"],
                    "away": g["awayTeam"], "key_home": norm_name(g["homeTeam"]), "key_away": norm_name(g["awayTeam"]), **rec,
                    "phase": "REG", "cfbd_id": g.get("id"), "neutral": bool(g.get("neutralSite"))})
    return out


def ncaaf_name_key(data_root: str = DATA_ROOT) -> Callable[[str], str | None]:
    """OddsAPI 'School Mascot' -> CFBD school, via the CFBD team registry. A registry spelling that maps to two
    different schools is discarded, so a name either resolves to exactly one school or is refused."""
    path = os.path.join(data_root, "ncaaf_source", "source_artifacts", "data", "processed", "team_registry",
                        "ncaaf_team_registry.csv")
    table: dict[str, set[str]] = defaultdict(set)
    with open(path, encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle):
            school = norm_name(r["canonical_team_name"])
            mascot = r.get("mascot_name") or ""
            for base in {r["canonical_team_name"], r.get("school_name") or "", r.get("display_name") or ""}:
                if base and mascot:
                    table[norm_name(f"{base} {mascot}")].add(school)
    resolved = {k: next(iter(v)) for k, v in table.items() if len(v) == 1}
    for odds_name, cfbd_school in NCAAF_ODDSAPI_TO_CFBD.items():
        resolved.setdefault(norm_name(odds_name), norm_name(cfbd_school))

    def key(name: str) -> str | None:
        return resolved.get(norm_name(name))
    return key


# OddsAPI spellings whose school part differs from every CFBD registry spelling (measured 2026-10-26 on the
# window's anchors; each CFBD side checked against the registry's canonical_team_name).
NCAAF_ODDSAPI_TO_CFBD = {
    "UMass Minutemen": "Massachusetts", "McNeese State Cowboys": "McNeese",
    "Southern Mississippi Golden Eagles": "Southern Miss", "Sam Houston State Bearkats": "Sam Houston",
    "Appalachian State Mountaineers": "App State", "Citadel Bulldogs": "The Citadel"}


def nfl_candidates(data_root: str = DATA_ROOT, season: int = 2026) -> list[dict[str, Any]]:
    nfl = os.path.join(data_root, "nfl_source", "tracking", "nflverse")
    ends: dict[str, dict[int, tuple[int, int]]] = defaultdict(dict)
    with open(os.path.join(nfl, "pbp", f"pbp_{season}.csv"), encoding="utf-8", newline="") as handle:
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
    out = []
    with open(os.path.join(nfl, "schedules_games.csv"), encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle):
            if _int(r["season"]) != season:
                continue
            fh, fa = _int(r["home_score"]), _int(r["away_score"])
            e = ends.get(r["game_id"])
            home, away = NFL_ABBR.get(r["home_team"]), NFL_ABBR.get(r["away_team"])
            if fh is None or fa is None or not e or any(q not in e for q in (1, 2, 3, 4)) or not home or not away:
                continue
            if e[max(e)] != (fh, fa):
                continue                                    # pbp disagrees with the schedule final: refuse
            cum = [e[q] for q in (1, 2, 3, 4)]
            ph = [cum[0][0]] + [cum[i][0] - cum[i - 1][0] for i in (1, 2, 3)]
            pa = [cum[0][1]] + [cum[i][1] - cum[i - 1][1] for i in (1, 2, 3)]
            out.append({"date": r["gameday"], "start_utc": et_to_utc(r["gameday"], r.get("gametime") or ""),
                        "home": home, "away": away, "key_home": norm_name(home),
                        "key_away": norm_name(away), "periods_home": ph, "periods_away": pa,
                        "ot_home": fh - cum[3][0], "ot_away": fa - cum[3][1], "final_home": fh, "final_away": fa,
                        "phase": "REG" if r["game_type"] == "REG" else "POST", "game_id": r["game_id"]})
    return out


# --------------------------------------------------------------------------------------------- per sport

def load_nba_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    layers = [("interval_history/nba", interval_history_candidates("nba", 4, data_root, NBA_ALIASES)),
              ("nba_source/data/processed/linescores_<date>.json", espn_linescores_file_candidates("nba", data_root))]
    payload = build_payload("nba", load_anchors("nba"), layers, plain_key(NBA_ALIASES), 2026)
    # linescores files carry no season type. interval_history drops ESPN preseason, so a fallback game dated
    # before the first non-preseason game interval_history holds in the window is preseason.
    ih_dates = sorted(c["date"] for c in layers[0][1] if c["date"] >= WINDOW_START[:10])
    first_ih = ih_dates[0] if ih_dates else "9999-12-31"
    payload["summary"]["first_non_preseason_date_in_interval_history"] = ih_dates[0] if ih_dates else None
    for g in payload["games"].values():
        if g["source"] != "interval_history/nba":
            g["phase"] = "PRE" if g["date"] < first_ih else "UNKNOWN"
    payload["summary"]["by_phase"] = dict(Counter(g["phase"] for g in payload["games"].values()))
    return payload


def load_wnba_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    layers = [("interval_history/wnba", interval_history_candidates("wnba", 4, data_root)),
              ("wnba_source/data/processed/_espn_cache", espn_scoreboard_cache_candidates("wnba", data_root))]
    return build_payload("wnba", load_anchors("wnba"), layers, plain_key(), 2026)


def load_nhl_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    """PRIMARY = the league's own api-web score cache (carries gameType and start time); interval_history (ESPN)
    only for dates the score cache has not reached. Every game in both is cross-checked. Measured 2026-10-26:
    173 agree, 1 disagree -- 2026-10-06 OTT@DET, ESPN 4-3 vs api-web 5-3, and api-web's boxscore and landing
    files both say 5-3, so the league feed is the one trusted."""
    score = nhl_score_candidates(data_root)
    ih = interval_history_candidates("nhl", 3, data_root)
    layers = [("nhl_source/data/ingestion_cache/score_<date>.json", score), ("interval_history/nhl", ih)]
    payload = build_payload("nhl", load_anchors("nhl"), layers, plain_key(), 2026)
    ih_by_key = {(c["date"], c["key_home"], c["key_away"]): c for c in ih}
    fields = ("periods_home", "periods_away", "ot_home", "ot_away", "final_home", "final_away", "so")
    check = Counter()
    for g in payload["games"].values():
        if g["source"] != layers[0][0]:
            continue
        other = ih_by_key.get((g["date"], norm_name(g["source_home"]), norm_name(g["source_away"])))
        if other is None:
            check["not_in_interval_history"] += 1
            continue
        same = all(g[k] == other[k] for k in fields)
        check["agree" if same else "disagree"] += 1
        if not same:
            g["interval_history_disagrees"] = {k: other[k] for k in fields}
    payload["summary"]["cross_check_api_web_vs_interval_history"] = dict(check)
    return payload


def mlb_schedule_snapshots(data_root: str = DATA_ROOT) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """(officialDate, home, away) -> StatsAPI schedule rows from the daily snapshots (gameType, gameDate UTC)."""
    out: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    for path in glob.glob(os.path.join(data_root, "mlb_source", "source_artifacts", "data", "daily", "snapshots", "*", "schedule_raw.json")):
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        rows = raw if isinstance(raw, list) else [g for d in raw.get("dates") or [] for g in d.get("games") or []]
        for r in rows:
            teams = r.get("teams") or {}
            k = (str(r.get("officialDate")), norm_name(((teams.get("home") or {}).get("team") or {}).get("name")),
                 norm_name(((teams.get("away") or {}).get("team") or {}).get("name")))
            out[k][r.get("gamePk")] = r
    return {k: list(v.values()) for k, v in out.items()}


def load_mlb_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    sched = mlb_schedule_snapshots(data_root)
    ih = interval_history_candidates("mlb", 9, data_root)
    for c in ih:                                            # start time + gamePk, only when unambiguous (1 game)
        rows = [r for r in sched.get((c["date"], c["key_home"], c["key_away"]), [])
                if str((r.get("status") or {}).get("abstractGameState")) == "Final"]
        if len(rows) == 1:
            c["start_utc"], c["game_pk"] = rows[0].get("gameDate"), rows[0].get("gamePk")
    layers = [("interval_history/mlb", ih)]
    payload = build_payload("mlb", load_anchors("mlb"), layers, plain_key(), 2026)
    # Name the postponement when the anchor's own ET date holds only a decided-but-unplayed game (empty linescore).
    postponed: set[tuple[str, str, str]] = set()
    for path in glob.glob(os.path.join(data_root, "interval_history", "mlb", "*.json")):
        with open(path, encoding="utf-8") as handle:
            for g in json.load(handle):
                if g.get("decided") and not g.get("home_periods"):
                    postponed.add((os.path.basename(path)[:10], norm_name(g["home"]), norm_name(g["away"])))
    for u in payload["unmatched"]:
        if (utc_to_et_date(u["commence"]), norm_name(u["home"]), norm_name(u["away"])) in postponed:
            u["reason"] = "source_game_postponed_on_anchor_date(empty_linescore):" + u["reason"]
    payload["summary"]["unmatched_by_reason"] = dict(Counter(u["reason"].split(":")[0] for u in payload["unmatched"]))
    finals: dict[tuple[str, str, str], tuple[int, int]] = {}
    for path in glob.glob(os.path.join(data_root, "settlement_inputs", "finals_*.json")):
        with open(path, encoding="utf-8") as handle:
            for r in json.load(handle).get("rows") or []:
                if r.get("sport") == "mlb":
                    finals[(r["date"], norm_name(r["home_team"]), norm_name(r["away_team"]))] = (r["home_score"], r["away_score"])
    # Phase from StatsAPI gameType in the daily schedule snapshots: R = regular season, F/D/L/W = postseason.
    check = Counter()
    for g in payload["games"].values():
        k = (g["date"], norm_name(g["home"]), norm_name(g["away"]))
        f = finals.get(k)
        if f is None:
            check["no_finals_row"] += 1
        else:
            check["agree" if f == (g["final_home"], g["final_away"]) else "disagree"] += 1
        types = {str(r.get("gameType")) for r in sched.get(k, [])}
        gt = types.pop() if len(types) == 1 else None
        g["phase"] = "REG" if gt == "R" else "POST" if gt in ("F", "D", "L", "W") else "UNKNOWN"
        g["mlb_game_type"] = gt
    payload["summary"]["cross_check_vs_settlement_finals"] = dict(check)
    payload["summary"]["by_phase"] = dict(Counter(g["phase"] for g in payload["games"].values()))
    return payload


def load_ncaaf_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    layers = [("ncaaf_source/historical_truth/games_2026.json.gz", ncaaf_candidates(data_root))]
    return build_payload("ncaaf", load_anchors("ncaaf"), layers, ncaaf_name_key(data_root), 2026)


def load_nfl_window(data_root: str = DATA_ROOT) -> dict[str, Any]:
    layers = [("nflverse schedules_games.csv + pbp_2026.csv", nfl_candidates(data_root))]
    return build_payload("nfl", load_anchors("nfl"), layers, plain_key(), 2026)


LOADERS = {"nba": load_nba_window, "wnba": load_wnba_window, "nhl": load_nhl_window, "mlb": load_mlb_window,
           "ncaaf": load_ncaaf_window, "nfl": load_nfl_window}


def main(sports: Iterable[str] = tuple(LOADERS), out_dir: str = EXTRACT_DIR) -> dict[str, Any]:
    report = {}
    for sport in sports:
        payload = LOADERS[sport]()
        write_json(os.path.join(out_dir, f"window_{sport}.json"), payload)
        report[sport] = payload["summary"]
        print(sport, json.dumps(payload["summary"]), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sports", default=",".join(LOADERS))
    parser.add_argument("--out-dir", default=EXTRACT_DIR)
    args = parser.parse_args()
    main([s.strip() for s in args.sports.split(",") if s.strip()], args.out_dir)
