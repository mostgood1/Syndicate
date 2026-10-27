"""E3 sim-distribution loaders: each sport's own per-game sim distribution, joined to the book's games.

READ-ONLY on the fleet data root. Writes only `sims_<sport>.json` into the output directory. Reads no venue
price and no outcome. Stdlib only, so it runs on the fleet's system python3.

Sources (mapped 2026-10-26; see the e3-derived-surface lane):
  nba / wnba  <sport>_source/data/processed/smart_sim_<D>_<HOME>_<AWAY>.json  -> score.dist (count histograms)
  nfl         nfl_source/smartsim2_segment_distributions_<season>_wk<W>.json  (+ smartsim2_projections csv)
  ncaaf       ncaaf_source/data/smartsim2_segment_distributions_<season>_wk<W>.json
  mlb         mlb_source/source_artifacts/data/daily/sims_pregame/<D>/sim_pk<pk>_g<n>.json  (pregame freeze ONLY)
  soccer      soccer_source/<league>/api/recommendations/recommendations_prekickoff_<D>.<service>.json
  nhl         skipped: predictions_<D>.csv carries per-period means and one-line probabilities, no distribution.

Output, per sport, keyed by BOOK event id. Every margin is BOOK-home minus BOOK-away: a sim whose home is the
book's away is negated. Weights are the stored counts (or stored probabilities: MLB's widened full-game margin,
soccer's scoreline pmf), never smoothed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc
SIM_SPORTS = ("nba", "wnba", "nfl", "ncaaf", "mlb", "soccer")
SIM_JOIN_WINDOW = timedelta(days=1)          # a sim may join a book event whose commence is within +-1 day
SIM_NAME_STRONG = 0.9                        # exact or school/club-prefix name match
SIM_NAME_OK = 0.6                            # both names at least this good -> a match
SIM_NAME_PARTIAL = 0.3                       # ...or one strong and the other at least this (token overlap)
SIM_FRAME_TOL = 0.05                         # |dist mean margin - the sim's own stored home-minus-away mean|
BASKETBALL_SEGMENTS = ("full", "h1", "h2", "q1", "q2", "q3", "q4")
FOOTBALL_SEGMENTS = ("full", "h1", "h2", "q1", "q2", "q3", "q4")
MLB_SEGMENTS = ("full", "first1", "first3", "first5")

NFL_TEAM_NAMES: Mapping[str, str] = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SF": "San Francisco 49ers",
    "SEA": "Seattle Seahawks", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

# Sim-side spelling -> a spelling the book uses (folded keys). Only for names the generic matcher cannot reach.
SIM_NAME_ALIASES: Mapping[str, Mapping[str, str]] = {
    "ncaaf": {
        "app state": "appalachian state",
        "southern miss": "southern mississippi",
        "massachusetts": "umass",
        "sam houston": "sam houston state",
        "hawai i": "hawaii",
        "nicholls": "nicholls state",
        "se louisiana": "southeastern louisiana",
        "the citadel": "citadel",
        "houston christian": "houston baptist",
        "ualbany": "albany",
        "ut martin": "tennessee martin",
        "louisiana": "louisiana ragin cajuns",
    },
    "soccer": {
        "union st gilloise": "union saint gilloise",
        "oh leuven": "leuven",
        "fc cologne": "1 fc koln",
        "stade rennais": "rennes",
        "lafc": "los angeles fc",
        "internazionale": "inter milan",
    },
}
_NAME_STOP = frozenset({"fc", "cf", "sc", "afc", "ac", "club", "de", "the", "cd", "sd", "ud", "sk", "fk", "bk",
                        "ssc", "calcio", "1", "and"})


# ============================================================================= shared helpers


def sim_parse_ts(value: object) -> datetime | None:
    """ISO text -> aware UTC datetime, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def sim_iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat() if moment else None


def sim_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def sim_read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, EOFError):
        return None


def sim_fold(name: object) -> str:
    """Team-name fold for MATCHING only: strip accents, lowercase, '&' -> 'and', punctuation -> space."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def sim_name_score(sim_name: str, book_name: str, aliases: Mapping[str, str] | None = None) -> float:
    """1.0 equal, 0.9 one name is a whole-word prefix of the other ('Coastal Carolina' / '... Chanticleers'),
    else a token-overlap score in [0, 0.8]."""
    a, b = sim_fold(sim_name), sim_fold(book_name)
    if aliases and a in aliases:
        a = aliases[a]
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b.startswith(a + " ") or a.startswith(b + " "):
        return SIM_NAME_STRONG
    ta, tb = set(a.split()) - _NAME_STOP, set(b.split()) - _NAME_STOP
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return SIM_NAME_STRONG
    inter = len(ta & tb)
    if not inter:
        return 0.0
    return round(0.5 * inter / min(len(ta), len(tb)) + 0.3 * inter / len(ta | tb), 4)


def sim_hist(raw: Mapping[Any, Any] | None) -> dict[str, float]:
    """{outcome: weight} with integer-string keys, zero weights dropped, order by outcome."""
    out: dict[int, float] = {}
    for key, value in (raw or {}).items():
        try:
            k, v = int(round(float(key))), float(value)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = out.get(k, 0.0) + v
    return {str(k): (int(v) if float(v).is_integer() else round(v, 9)) for k, v in sorted(out.items())}


def sim_hist_mean(hist: Mapping[str, float]) -> float | None:
    total = sum(float(v) for v in hist.values())
    return sum(int(k) * float(v) for k, v in hist.items()) / total if total > 0 else None


def sim_negate(hist: Mapping[str, float]) -> dict[str, float]:
    """The margin histogram seen from the other side."""
    return {str(-int(k)): v for k, v in sorted(hist.items(), key=lambda kv: -int(kv[0]))}


def sim_record(*, sport: str, key: str, source_file: Path, home: str, away: str, start: datetime | None,
               date: str | None, written_at: datetime | None, written_basis: str, n_draws: int,
               dists: dict[str, dict[str, float]], frame_ok: bool, frame_note: str) -> dict[str, Any]:
    """One sim game, in the sim's OWN orientation (home/away as the sim has them)."""
    return {"sport": sport, "key": key, "source_file": str(source_file), "home": home, "away": away,
            "start": start, "date": date, "written_at": written_at, "written_basis": written_basis,
            "n_draws": int(n_draws), "dists": dists, "frame_ok": frame_ok, "frame_note": frame_note}


# ============================================================================= per-sport loaders


def load_basketball_sims(root: Path, league: str) -> list[dict[str, Any]]:
    """smart_sim_<D>_<H>_<A>.json -> score.dist. Team names and tip from game_cards_<D>.csv (tricode -> name)."""
    processed = root / f"{league}_source" / "data" / "processed"
    names: dict[str, str] = {}
    cards: dict[tuple[str, str, str], dict[str, str]] = {}
    for path in sorted(processed.glob("game_cards_*.csv")):
        slate = path.stem.replace("game_cards_", "")
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                h, a = str(row.get("home_tri") or "").upper(), str(row.get("away_tri") or "").upper()
                if h and row.get("home_team"):
                    names[h] = str(row["home_team"]).strip()
                if a and (row.get("visitor_team") or row.get("away_team")):
                    names[a] = str(row.get("visitor_team") or row.get("away_team")).strip()
                cards[(slate, h, a)] = row
    out: list[dict[str, Any]] = []
    for path in sorted(processed.glob("smart_sim_*_*_*.json")):
        parts = path.stem.split("_")
        if len(parts) != 5:
            continue                                   # smart_sim_failures_<D>.csv etc.
        slate, home_tri, away_tri = parts[2], parts[3].upper(), parts[4].upper()
        payload = sim_read_json(path)
        dist = ((payload or {}).get("score") or {}).get("dist") if isinstance(payload, dict) else None
        if not isinstance(dist, dict) or not isinstance(dist.get("segments"), dict):
            out.append(sim_record(sport=league, key=path.name, source_file=path, home=home_tri, away=away_tri,
                                  start=None, date=slate, written_at=None, written_basis="mtime", n_draws=0,
                                  dists={}, frame_ok=False, frame_note="no score.dist"))
            continue
        segments = dist["segments"]
        dists: dict[str, dict[str, float]] = {}
        for seg in BASKETBALL_SEGMENTS:
            block = segments.get(seg) or {}
            if block.get("margin") and block.get("total"):
                dists[f"{seg}_margin"] = sim_hist(block["margin"])
                dists[f"{seg}_total"] = sim_hist(block["total"])
        # FRAME: the vendor score block is regulation-only and drawn from the same draws, so the regulation
        # histogram's mean must equal score.margin_mean (home minus away, the sim's home).
        reg_mean = sim_hist_mean(sim_hist((segments.get("regulation") or {}).get("margin")))
        stored = payload["score"].get("margin_mean")
        frame_ok = (str(dist.get("margin_frame") or "home_minus_away") == "home_minus_away"
                    and str(payload.get("home") or home_tri).upper() == home_tri
                    and reg_mean is not None and stored is not None and abs(reg_mean - float(stored)) <= SIM_FRAME_TOL)
        row = cards.get((slate, home_tri, away_tri)) or {}
        out.append(sim_record(
            sport=league, key=path.name, source_file=path,
            home=str(row.get("home_team") or names.get(home_tri) or home_tri),
            away=str(row.get("visitor_team") or row.get("away_team") or names.get(away_tri) or away_tri),
            start=sim_parse_ts(row.get("commence_time")), date=slate, written_at=sim_mtime(path),
            written_basis="mtime", n_draws=int(dist.get("n") or 0), dists=dists, frame_ok=frame_ok,
            frame_note=f"regulation margin mean {reg_mean} vs score.margin_mean {stored}"))
    return out


def _nfl_kickoffs(root: Path) -> dict[str, datetime]:
    """nflverse game_id -> kickoff (gameday + gametime are US Eastern)."""
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    out: dict[str, datetime] = {}
    path = root / "nfl_source" / "tracking" / "nflverse" / "schedules_games.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                local = datetime.fromisoformat(f"{row['gameday']}T{row['gametime'] or '13:00'}")
            except (KeyError, ValueError):
                continue
            out[str(row.get("game_id"))] = local.replace(tzinfo=eastern).astimezone(UTC)
    return out


def _ncaaf_kickoffs(root: Path) -> dict[str, datetime]:
    """CFBD game id -> startDate (UTC), from the historical-truth game list (no scores are read)."""
    out: dict[str, datetime] = {}
    for path in sorted((root / "ncaaf_source" / "historical_truth").glob("games_*.json.gz")):
        for game in sim_read_json(path) or []:
            if isinstance(game, dict) and game.get("id") is not None:
                start = sim_parse_ts(game.get("startDate"))
                if start:
                    out[str(game["id"])] = start
    return out


def load_football_sims(root: Path, league: str) -> list[dict[str, Any]]:
    """smartsim2_segment_distributions_<season>_wk<W>.json; home/away from the sibling projections csv."""
    folder = root / "nfl_source" if league == "nfl" else root / "ncaaf_source" / "data"
    kickoffs = _nfl_kickoffs(root) if league == "nfl" else _ncaaf_kickoffs(root)
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("smartsim2_segment_distributions_*_wk*.json")):
        payload = sim_read_json(path)
        if not isinstance(payload, dict):
            continue
        teams: dict[str, tuple[str, str]] = {}
        csv_path = folder / f"smartsim2_projections_{payload.get('season')}_wk{payload.get('week')}.csv"
        if csv_path.exists():
            with open(csv_path, encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    teams[str(row.get("game_id"))] = (str(row.get("home_team") or ""), str(row.get("away_team") or ""))
        generated = sim_parse_ts(payload.get("generated_at"))
        for game_id, block in (payload.get("games") or {}).items():
            home, away = teams.get(str(game_id), ("", ""))
            if league == "nfl":
                if not home:                               # nflverse id is <season>_<week>_<AWAY>_<HOME>
                    bits = str(game_id).split("_")
                    away, home = (bits[2], bits[3]) if len(bits) == 4 else ("", "")
                home, away = NFL_TEAM_NAMES.get(home, home), NFL_TEAM_NAMES.get(away, away)
            segments = block.get("segments") or {}
            dists: dict[str, dict[str, float]] = {}
            for seg in FOOTBALL_SEGMENTS:
                entry = segments.get(seg) or {}
                if entry.get("margin_dist") and entry.get("total_points_dist"):
                    dists[f"{seg}_margin"] = sim_hist(entry["margin_dist"])
                    dists[f"{seg}_total"] = sim_hist(entry["total_points_dist"])
            # FRAME: every segment's margin histogram mean must equal its own home_points_mean - away_points_mean.
            notes, frame_ok = [], bool(dists)
            for seg in FOOTBALL_SEGMENTS:
                entry = segments.get(seg) or {}
                got = sim_hist_mean(dists.get(f"{seg}_margin") or {})
                want = float(entry.get("home_points_mean") or 0) - float(entry.get("away_points_mean") or 0)
                if got is None or abs(got - want) > 0.002:
                    frame_ok = False
                    notes.append(f"{seg}: {got} vs {want:.4f}")
            out.append(sim_record(
                sport=league, key=f"{path.name}:{game_id}", source_file=path, home=home, away=away,
                start=kickoffs.get(str(game_id)), date=None, written_at=generated, written_basis="generated_at",
                n_draws=int(block.get("sims") or 0), dists=dists, frame_ok=frame_ok,
                frame_note="; ".join(notes) or "segment margin means == home_points_mean - away_points_mean"))
    return out


def load_mlb_sims(root: Path) -> list[dict[str, Any]]:
    """daily/sims_pregame/<D>/sim_pk<pk>_g<n>.json ONLY (the freeze; daily/sims/ is rewritten after first pitch)."""
    folder = root / "mlb_source" / "source_artifacts" / "data" / "daily" / "sims_pregame"
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*/sim_pk*_g*.json")):
        payload = sim_read_json(path)
        if not isinstance(payload, dict):
            continue
        freeze = payload.get("_freeze") or {}
        segments = ((payload.get("sim") or {}).get("segments")) or {}
        dists: dict[str, dict[str, float]] = {}
        notes, frame_ok = [], True
        for seg in MLB_SEGMENTS:
            entry = segments.get(seg) or {}
            if not (entry.get("run_margin_dist") and entry.get("total_runs_dist")):
                continue
            dists[f"{seg}_margin"] = sim_hist(entry["run_margin_dist"])     # full: widened x1.048, fractional
            dists[f"{seg}_total"] = sim_hist(entry["total_runs_dist"])
            # FRAME: margin mean == home_runs_mean - away_runs_mean (the widening is about the dist's own mean).
            got = sim_hist_mean(dists[f"{seg}_margin"])
            want = float(entry.get("home_runs_mean") or 0) - float(entry.get("away_runs_mean") or 0)
            if got is None or abs(got - want) > SIM_FRAME_TOL:
                frame_ok = False
                notes.append(f"{seg}: {got} vs {want:.4f}")
        mtime = freeze.get("source_mtime")
        written = datetime.fromtimestamp(float(mtime), UTC) if mtime else None
        out.append(sim_record(
            sport="mlb", key=f"{path.parent.name}/{path.name}", source_file=path,
            home=str((payload.get("home") or {}).get("name") or ""), away=str((payload.get("away") or {}).get("name") or ""),
            start=sim_parse_ts((payload.get("schedule") or {}).get("game_date")), date=str(payload.get("date") or ""),
            written_at=written, written_basis="freeze_source_mtime",
            n_draws=int((payload.get("sim") or {}).get("sims") or 0), dists=dists, frame_ok=frame_ok and bool(dists),
            frame_note="; ".join(notes) or "segment margin means == home_runs_mean - away_runs_mean"))
    return out


def load_soccer_sims(root: Path) -> list[dict[str, Any]]:
    """Pre-kickoff freezes, every league and service; per match the LATEST frozen_at that is <= its kickoff."""
    best: dict[tuple[str, str], tuple[datetime, Path, dict[str, Any]]] = {}
    for path in sorted((root / "soccer_source").glob("*/api/recommendations/recommendations_prekickoff_*.json")):
        payload = sim_read_json(path)
        if not isinstance(payload, dict):
            continue
        league = path.parts[-4]
        for match_id, entry in (payload.get("matches") or {}).items():
            frozen, kickoff = sim_parse_ts(entry.get("frozen_at")), sim_parse_ts(entry.get("kickoff"))
            if not frozen or not kickoff or frozen > kickoff:
                continue
            key = (league, str(match_id))
            if key not in best or frozen > best[key][0]:
                best[key] = (frozen, path, entry)
    out: list[dict[str, Any]] = []
    for (league, match_id), (frozen, path, entry) in sorted(best.items()):
        match = entry.get("match") or {}
        pmf = match.get("scoreline_probabilities") or {}
        margin: dict[int, float] = defaultdict(float)
        total: dict[int, float] = defaultdict(float)
        home_mean = 0.0
        for scoreline, prob in pmf.items():
            try:
                h, a = (int(x) for x in str(scoreline).split("-"))
                p = float(prob)
            except (TypeError, ValueError):
                continue
            margin[h - a] += p
            total[h + a] += p
            home_mean += h * p
        dists = {"full_margin": sim_hist(margin), "full_total": sim_hist(total)}
        proj = match.get("team_projection") or {}
        # FRAME: scorelines are "<home>-<away>": E[home goals] from the pmf must equal team_projection.home_mean.
        frame_ok = bool(pmf) and proj.get("home_mean") is not None and abs(home_mean - float(proj["home_mean"])) <= SIM_FRAME_TOL
        matchup = match.get("matchup") or {}
        out.append(sim_record(
            sport="soccer", key=f"{league}:{match_id}", source_file=path, home=str(matchup.get("home_team") or ""),
            away=str(matchup.get("away_team") or ""), start=sim_parse_ts(entry.get("kickoff")), date=None,
            written_at=frozen, written_basis="frozen_at", n_draws=int(match.get("simulations") or 0), dists=dists,
            frame_ok=frame_ok, frame_note=f"pmf E[home] {home_mean:.4f} vs team_projection.home_mean {proj.get('home_mean')}"))
    return out


# ============================================================================= join to the book's games


def _candidate_score(sim: Mapping[str, Any], event: Mapping[str, Any], aliases: Mapping[str, str]) -> tuple[float, bool, float, float]:
    """(pair score, flipped, home-side score, away-side score) for the better of the two orientations."""
    hh, aa = sim_name_score(sim["home"], event["home"], aliases), sim_name_score(sim["away"], event["away"], aliases)
    ha, ah = sim_name_score(sim["home"], event["away"], aliases), sim_name_score(sim["away"], event["home"], aliases)

    def pair(x: float, y: float) -> float:
        lo, hi = min(x, y), max(x, y)
        if lo >= SIM_NAME_OK:
            return lo
        return lo * 0.5 if hi >= SIM_NAME_STRONG and lo >= SIM_NAME_PARTIAL else 0.0

    straight, swapped = pair(hh, aa), pair(ha, ah)
    if straight == swapped:
        return 0.0, False, hh, aa                  # names cannot tell the sides apart: no orientation, no match
    if swapped > straight:
        return swapped, True, ha, ah
    return straight, False, hh, aa


def _time_gap(sim: Mapping[str, Any], event_start: datetime) -> float | None:
    """Hours between sim start and book commence; date-only sims use the slate date (+-1 calendar day)."""
    if sim.get("start"):
        return abs((event_start - sim["start"]).total_seconds()) / 3600.0
    if sim.get("date"):
        try:
            day = datetime.fromisoformat(str(sim["date"])[:10]).date()
        except ValueError:
            return None
        delta = abs((event_start.date() - day).days)
        return float(delta * 24) if delta <= 1 else None
    return None


def join_sims_to_book(sport: str, sims: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Each sim -> at most one book event (both names, commence within +-1 day); each event -> at most one sim."""
    aliases = SIM_NAME_ALIASES.get(sport, {})
    starts = {e["event_id"]: sim_parse_ts(e.get("commence")) for e in events}
    lo = min(s for s in starts.values() if s) - SIM_JOIN_WINDOW
    hi = max(s for s in starts.values() if s) + SIM_JOIN_WINDOW
    unmatched: list[dict[str, Any]] = []
    proposals: dict[str, list[tuple[tuple[float, float], Mapping[str, Any], bool, float]]] = defaultdict(list)
    counts: Counter = Counter()
    for sim in sims:
        anchor = sim.get("start") or (sim_parse_ts(f"{sim['date']}T18:00:00+00:00") if sim.get("date") else None)
        if anchor is None or not (lo <= anchor <= hi):
            counts["sims_outside_book_window"] += 1
            continue
        counts["sims_in_window"] += 1
        if not sim["frame_ok"]:
            unmatched.append({"file_or_id": sim["key"], "reason": f"frame check failed: {sim['frame_note']}"})
            continue
        scored = []
        for event in events:
            start = starts[event["event_id"]]
            gap = _time_gap(sim, start) if start else None
            if gap is None or gap > SIM_JOIN_WINDOW.total_seconds() / 3600.0:
                continue
            score, flipped, s1, s2 = _candidate_score(sim, event, aliases)
            if score > 0:
                scored.append(((score, -gap), event, flipped, gap))
        if not scored:
            late = anchor > hi - SIM_JOIN_WINDOW
            unmatched.append({"file_or_id": sim["key"], "reason": (
                f"starts after the last book commence ({sim_iso(hi - SIM_JOIN_WINDOW)})" if late else
                f"no book event within +-1 day naming both {sim['home']!r} and {sim['away']!r}")})
            continue
        scored.sort(key=lambda item: item[0], reverse=True)
        # Two equally-named book events (a re-listed event, or a series on consecutive days): a sim with its own
        # start time takes the closer one when they differ by >= 30 min; a date-only sim cannot choose.
        tie_gap = 0.5 if sim.get("start") else 12.0
        if len(scored) > 1 and scored[1][0][0] == scored[0][0][0] and abs(scored[1][3] - scored[0][3]) < tie_gap:
            unmatched.append({"file_or_id": sim["key"], "reason": "ambiguous: two book events equally named and equally "
                              f"close: {scored[0][1]['event_id']}, {scored[1][1]['event_id']}"})
            continue
        top = scored[0]
        proposals[top[1]["event_id"]].append((top[0], sim, top[2], top[3]))

    games: dict[str, Any] = {}
    for event_id, offers in proposals.items():
        offers.sort(key=lambda item: item[0], reverse=True)
        (score, _), sim, flipped, gap = offers[0][0], offers[0][1], offers[0][2], offers[0][3]
        for _, loser, _, _ in offers[1:]:
            unmatched.append({"file_or_id": loser["key"], "reason": f"book event {event_id} already taken by {sim['key']}"})
        commence = starts[event_id]
        written = sim["written_at"]
        # Pregame only, against the BOOK's commence: basketball (mtime) and soccer (frozen_at; three freezes sit
        # before the sim's own kickoff but after the book's, where the two disagree by 1-24h). MLB keeps its freeze
        # (status Scheduled/Pre-Game/Warmup at sim time is the stronger test); football is kept as stored.
        if sport in ("nba", "wnba", "soccer") and written and commence and written > commence:
            unmatched.append({"file_or_id": sim["key"], "reason": f"written after book commence ({sim_iso(written)} > {sim_iso(commence)})"})
            counts["excluded_written_after_commence"] += 1
            continue
        if written and commence and written > commence:
            counts["kept_written_after_commence"] += 1
        dists = {k: (sim_negate(v) if flipped and k.endswith("_margin") else dict(v)) for k, v in sim["dists"].items()}
        counts["flipped"] += int(flipped)
        counts["match_quality_strong" if score >= SIM_NAME_STRONG else "match_quality_ok" if score >= SIM_NAME_OK
               else "match_quality_partial"] += 1
        games[event_id] = {
            "source_file": sim["source_file"], "written_at": sim_iso(written), "written_basis": sim["written_basis"],
            "n_draws": sim["n_draws"], "orientation_checked": True, "orientation_flipped": flipped,
            "sim_home": sim["home"], "sim_away": sim["away"], "book_home": next(e["home"] for e in events if e["event_id"] == event_id),
            "book_away": next(e["away"] for e in events if e["event_id"] == event_id), "commence": sim_iso(commence),
            "sim_start": sim_iso(sim.get("start")), "join_gap_hours": round(gap, 2), "name_score": round(score, 3),
            "dists": dists,
        }
    for event in events:
        if event["event_id"] not in games:
            unmatched.append({"file_or_id": f"book:{event['event_id']}", "reason":
                              f"book event with no pregame sim: {event['away']} @ {event['home']} {event.get('commence')}"})
    days = sorted({str(g["commence"])[:10] for g in games.values()})
    counts.update({
        "sims_loaded": len(sims), "book_events": len(events), "matched": len(games),
        "book_events_without_sim": len(events) - len(games),
        "sim_side_unmatched": sum(1 for u in unmatched if not str(u["file_or_id"]).startswith("book:")),
    })
    return {
        "sport": sport, "games": games, "unmatched": unmatched,
        "counts": {**dict(counts), "dates": len(days), "first_date": days[0] if days else None,
                   "last_date": days[-1] if days else None,
                   "n_draws": dict(sorted(Counter(str(g["n_draws"]) for g in games.values()).items())),
                   "dist_keys": sorted({k for g in games.values() for k in g["dists"]})},
    }


# ============================================================================= CLI


def load_sport_sims(root: Path, sport: str) -> list[dict[str, Any]]:
    if sport in ("nba", "wnba"):
        return load_basketball_sims(root, sport)
    if sport in ("nfl", "ncaaf"):
        return load_football_sims(root, sport)
    if sport == "mlb":
        return load_mlb_sims(root)
    if sport == "soccer":
        return load_soccer_sims(root)
    raise ValueError(f"no sim loader for {sport}")


def main(data_root: str | Path, extract_dir: str | Path, out_dir: str | Path, sports: Iterable[str] = SIM_SPORTS) -> dict[str, Any]:
    """Load, join and write sims_<sport>.json for each sport; returns {sport: counts}."""
    root, extract, out = Path(data_root).expanduser(), Path(extract_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {}
    for sport in sports:
        anchors = sim_read_json(extract / f"anchors_{sport}.json") or {}
        events = [e for e in anchors.get("events") or [] if e.get("event_id") and e.get("home") and e.get("away")]
        result = join_sims_to_book(sport, load_sport_sims(root, sport), events)
        target = out / f"sims_{sport}.json"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(result, indent=1), encoding="utf-8")
        os.replace(tmp, target)
        summary[sport] = result["counts"]
        print(f"[sim_loaders] {sport}: " + json.dumps(result["counts"]), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=os.path.expanduser("~/syndicate-prod/data"))
    parser.add_argument("--extract-dir", default="/mnt/c/tmp/e3/extract")
    parser.add_argument("--out-dir", default="/mnt/c/tmp/e3/extract")
    parser.add_argument("--sports", default=",".join(SIM_SPORTS))
    args = parser.parse_args()
    main(args.data_root, args.extract_dir, args.out_dir, [s for s in args.sports.split(",") if s])
