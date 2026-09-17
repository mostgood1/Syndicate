"""The published soccer corners, from team corner rates and pregame pressure -- not the possession sim.

WHY. Season to date the engine's match-total corners correlated with the actual
count at r = 0.02, and a constant (last season's league mean) beat them on MAE
(audit `findings_2026-09-15_soccer_season_market_audit.md`). The sim's
per-possession corner chance is built from generic attack/defense indices
(`possession_priors.py`), and a team's own corner rate moves only a set-piece
index by 0.03 per corner, so which team wins corners, and how many a game holds,
never reached the number.

WHAT REPLACES IT (lane `soccer-corners-model-rebuild`, stage 1:
`scripts/soccer_season_audit/corners_estimators.py`, E3). Held out on 554
current-season matches: MAE 2.773 and r 0.182, against the engine's 2.873 and
0.046. On the 251 with a captured corners main line it reached market parity:
r 0.172 vs the market's own 0.155, and MAE 2.790 vs 2.818. It is shipped under H27
(`log/2026-09-16.md` ~22:45 CT), graded forward on frozen pre-kickoff matches.
**Every constant below is fixed by that registration.** k and the half-life were
chosen on the 2025 season only; the pressure coefficients were fitted on it.

THE ESTIMATOR, per match, from rows dated strictly before the slate date:
  league venue means mu_H, mu_A, each weighted 0.5 ** (age_days / 180);
  per team, corners-for and corners-against normalised by the venue mean and
  shrunk toward 1.0 with prior weight k = 20;
  home = mu_H * for[home] * against[away];  away = mu_A * for[away] * against[home];
  then, when the pregame 1X2 is priced:
    total  += -0.080 + 0.415 * |pH - pA| + 2.125 * (pOver2.5 - 0.5)   (pOver 0.5 when unpriced)
    margin += -0.350 + 2.866 * (pH - pA)
  each side floored at 0.5.

A MECHANISM WAS NOT ADDED, AN OUTPUT WAS REPLACED. The sim still runs its own
corners (they feed set-piece goals and the live lens), and its values are kept
beside the published ones as `sim_home_corners` / `sim_away_corners`. So goals
calibration cannot move (`model_engine_standard.md` 4.4 is about re-adding a
mechanism to calibrated rates; this changes no rate the sim uses).

INPUTS, all production artifacts under the soccer data root:
  `<league>/history/matches_*.csv`          football-data corners, prior seasons (no MLS)
  `<league>/api/live_state/live_state_*.json`  `match_box[*].teams.{home,away}.stats.Corners`,
                                              this season (448 of 449 boxes carry it, 2026-08-20..)
  `<league>/api/odds/game_odds_current.csv`  h2h (3-way) and totals at 2.5
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.soccer.features.market_odds import american_to_probability
from syndicate.features.soccer.features.team_names import canonical_team_name, match_team_name

CORNERS_BASIS = "team_rates_pressure_v1"
K_SHRINK = 20.0
HALF_LIFE_DAYS = 180.0
BETA_TOTAL = (-0.080, 0.415, 2.125)
BETA_MARGIN = (-0.350, 2.866)
MIN_LEAGUE_ROWS = 30
FLOOR = 0.5


def corners_estimator_enabled() -> bool:
    """On unless `SYNDICATE_SOCCER_CORNERS_ESTIMATOR` is 0/false/no/off. Read per call."""
    raw = str(os.environ.get("SYNDICATE_SOCCER_CORNERS_ESTIMATOR") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class CornerRow:
    day: date
    home: str
    away: str
    home_corners: float
    away_corners: float


def _parse_day(text: Any) -> date | None:
    value = str(text or "").strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value, fmt).date()
        except ValueError:
            continue
    return None


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def history_corner_rows(league_dir: Path) -> list[CornerRow]:
    rows: list[CornerRow] = []
    for path in sorted((league_dir / "history").glob("matches_*.csv")):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    day = _parse_day(raw.get("date"))
                    hc, ac = _as_float(raw.get("home_corners")), _as_float(raw.get("away_corners"))
                    if day is None or hc is None or ac is None:
                        continue
                    rows.append(CornerRow(day, canonical_team_name(raw.get("home_team") or ""),
                                          canonical_team_name(raw.get("away_team") or ""), hc, ac))
        except OSError:
            continue
    return rows


def live_state_corner_rows(league_dir: Path) -> list[CornerRow]:
    """Finished and in-play box scores; a record without both teams' Corners is skipped."""
    rows: list[CornerRow] = []
    seen: set[str] = set()
    for path in sorted((league_dir / "api" / "live_state").glob("live_state_*.json")):
        day = _parse_day(path.stem.replace("live_state_", ""))
        if day is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        boxes = payload.get("match_box") if isinstance(payload, Mapping) else None
        if not isinstance(boxes, Mapping):
            continue
        for event_id, record in boxes.items():
            teams = (record or {}).get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            hc = _as_float((home.get("stats") or {}).get("Corners"))
            ac = _as_float((away.get("stats") or {}).get("Corners"))
            if hc is None or ac is None or str(event_id) in seen:
                continue
            seen.add(str(event_id))
            rows.append(CornerRow(day, str(home.get("team") or ""), str(away.get("team") or ""), hc, ac))
    return rows


@lru_cache(maxsize=16)
def _league_rows_cached(league_dir: str, live_state_signature: tuple[tuple[str, float], ...]) -> tuple[CornerRow, ...]:
    root = Path(league_dir)
    history = history_corner_rows(root)
    names = sorted({r.home for r in history} | {r.away for r in history})
    mapped: dict[str, str] = {}

    def to_history_name(name: str) -> str:
        if name not in mapped:
            hit = match_team_name(name, names) if names and name else None
            mapped[name] = canonical_team_name(hit) if hit else canonical_team_name(name)
        return mapped[name]

    current = [CornerRow(r.day, to_history_name(r.home), to_history_name(r.away), r.home_corners, r.away_corners)
               for r in live_state_corner_rows(root)]
    return tuple(history + current)


def league_corner_rows(league_dir: Path) -> tuple[CornerRow, ...]:
    """History + this season, names on the history spelling. Cached until a live_state file changes."""
    folder = league_dir / "api" / "live_state"
    try:
        signature = tuple(sorted((p.name, p.stat().st_mtime) for p in folder.glob("live_state_*.json")))
    except OSError:
        signature = ()
    return _league_rows_cached(str(league_dir), signature)


def map_team(rows: Iterable[CornerRow], name: str) -> str:
    names = sorted({r.home for r in rows} | {r.away for r in rows})
    hit = match_team_name(name, names) if names and name else None
    return canonical_team_name(hit) if hit else canonical_team_name(name)


def estimate_corners(rows: Iterable[CornerRow], home: str, away: str, as_of: date,
                     pressure: Mapping[str, float | None] | None = None) -> dict[str, Any] | None:
    """(home, away) corners for one fixture, or None when the league has too little history."""
    train = [r for r in rows if r.day < as_of]
    if len(train) < MIN_LEAGUE_ROWS:
        return None
    weights = [0.5 ** ((as_of - r.day).days / HALF_LIFE_DAYS) for r in train]
    total_w = sum(weights)
    mu_h = sum(w * r.home_corners for w, r in zip(weights, train)) / total_w
    mu_a = sum(w * r.away_corners for w, r in zip(weights, train)) / total_w
    if mu_h <= 0 or mu_a <= 0:
        return None
    num_for: dict[str, float] = defaultdict(float)
    num_against: dict[str, float] = defaultdict(float)
    den: dict[str, float] = defaultdict(float)
    for w, r in zip(weights, train):
        num_for[r.home] += w * r.home_corners / mu_h
        num_against[r.home] += w * r.away_corners / mu_a
        den[r.home] += w
        num_for[r.away] += w * r.away_corners / mu_a
        num_against[r.away] += w * r.home_corners / mu_h
        den[r.away] += w

    def rate(num: Mapping[str, float], team: str) -> float:
        return (num.get(team, 0.0) + K_SHRINK) / (den.get(team, 0.0) + K_SHRINK)

    home_c = mu_h * rate(num_for, home) * rate(num_against, away)
    away_c = mu_a * rate(num_for, away) * rate(num_against, home)
    applied = False
    p_home = (pressure or {}).get("p_home")
    p_away = (pressure or {}).get("p_away")
    if p_home is not None and p_away is not None:
        p_over = (pressure or {}).get("p_over")
        p_over = 0.5 if p_over is None else p_over
        total = home_c + away_c + BETA_TOTAL[0] + BETA_TOTAL[1] * abs(p_home - p_away) + BETA_TOTAL[2] * (p_over - 0.5)
        margin = home_c - away_c + BETA_MARGIN[0] + BETA_MARGIN[1] * (p_home - p_away)
        home_c, away_c = (total + margin) / 2.0, (total - margin) / 2.0
        applied = True
    return {
        "home_corners": round(max(FLOOR, home_c), 4),
        "away_corners": round(max(FLOOR, away_c), 4),
        "league_rows": len(train),
        "home_team_weight": round(den.get(home, 0.0), 3),
        "away_team_weight": round(den.get(away, 0.0), 3),
        "pressure_applied": applied,
    }


def pressure_by_team_pair(odds_csv: Path) -> dict[tuple[str, str], dict[str, float | None]]:
    """De-vigged pH/pA (3-way) and pOver2.5 per event, keyed by canonical (home, away).

    The rules of `market_odds.py`: every price becomes an implied probability first,
    means are taken in probability space, the de-vig is proportional, and a value that
    is not an American price is refused (`american_to_probability` returns None).
    """
    if not odds_csv.is_file():
        return {}
    h2h: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    ou: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    try:
        with odds_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    for row in rows:
        home, away = str(row.get("home_team") or ""), str(row.get("away_team") or "")
        key = (canonical_team_name(home), canonical_team_name(away))
        market = str(row.get("market") or "").strip().casefold()
        side = str(row.get("side") or "").strip()
        probability = american_to_probability(row.get("price"))
        if probability is None:
            continue
        if market in {"h2h", "moneyline", "ml"}:
            if side.casefold() in {"draw", "tie", "x"}:
                h2h[key]["draw"].append(probability)
            elif match_team_name(side, (home,)) is not None:
                h2h[key]["home"].append(probability)
            elif match_team_name(side, (away,)) is not None:
                h2h[key]["away"].append(probability)
        elif market in {"totals", "total", "over_under", "ou"} and _as_float(row.get("line")) == 2.5:
            if side.casefold() in {"over", "o"}:
                ou[key]["over"].append(probability)
            elif side.casefold() in {"under", "u"}:
                ou[key]["under"].append(probability)
    out: dict[tuple[str, str], dict[str, float | None]] = {}
    for key in set(h2h) | set(ou):
        entry: dict[str, float | None] = {"p_home": None, "p_away": None, "p_over": None}
        sides = h2h.get(key) or {}
        if all(sides.get(s) for s in ("home", "draw", "away")):
            means = {s: sum(v) / len(v) for s, v in sides.items()}
            norm = sum(means.values())
            entry["p_home"], entry["p_away"] = means["home"] / norm, means["away"] / norm
        totals = ou.get(key) or {}
        if totals.get("over") and totals.get("under"):
            over = sum(totals["over"]) / len(totals["over"])
            under = sum(totals["under"]) / len(totals["under"])
            entry["p_over"] = over / (over + under)
        out[key] = entry
    return out


def _pressure_for(pressure: Mapping[tuple[str, str], Mapping[str, float | None]], home: str, away: str) -> Mapping[str, float | None] | None:
    key = (canonical_team_name(home), canonical_team_name(away))
    if key in pressure:
        return pressure[key]
    homes = sorted({k[0] for k in pressure})
    aways = sorted({k[1] for k in pressure})
    hit_h = match_team_name(home, homes) if homes else None
    hit_a = match_team_name(away, aways) if aways else None
    if hit_h and hit_a:
        return pressure.get((canonical_team_name(hit_h), canonical_team_name(hit_a)))
    return None


def apply_corners_estimator(league: str, data_root: Path, iso_date: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace each match's published corners in place; return the audit the artifact publishes."""
    audit: dict[str, Any] = {"basis": CORNERS_BASIS, "state": None, "estimated": 0, "declined": 0, "pressure_applied": 0, "league_rows": None}
    if not corners_estimator_enabled():
        audit["state"] = "disabled"
        return audit
    as_of = _parse_day(iso_date)
    if as_of is None:
        audit["state"] = "bad_date"
        return audit
    league_dir = Path(data_root) / league
    rows = league_corner_rows(league_dir)
    pressure = pressure_by_team_pair(league_dir / "api" / "odds" / "game_odds_current.csv")
    for match in matches:
        volume = match.get("volume_projection")
        if not isinstance(volume, dict):
            continue
        matchup = match.get("matchup") or {}
        home = map_team(rows, str(matchup.get("home_team") or ""))
        away = map_team(rows, str(matchup.get("away_team") or ""))
        estimate = estimate_corners(rows, home, away, as_of,
                                    _pressure_for(pressure, str(matchup.get("home_team") or ""), str(matchup.get("away_team") or "")))
        volume.setdefault("sim_home_corners", volume.get("home_corners"))
        volume.setdefault("sim_away_corners", volume.get("away_corners"))
        if estimate is None:
            volume["corners_basis"] = "sim"
            audit["declined"] += 1
            continue
        volume["home_corners"] = estimate["home_corners"]
        volume["away_corners"] = estimate["away_corners"]
        volume["corners_basis"] = CORNERS_BASIS
        volume["corners_estimator"] = {k: estimate[k] for k in ("league_rows", "home_team_weight", "away_team_weight", "pressure_applied")}
        audit["estimated"] += 1
        audit["pressure_applied"] += int(estimate["pressure_applied"])
        audit["league_rows"] = estimate["league_rows"]
    audit["state"] = "on"
    return audit
