"""High-hit-rate NHL same-game parlays from EVERY priced alt rung (lane `nhl-sgp-builder`, user 2026-10-17: "The idea
is to use the consistency sheets to build them so we can deliver high hit rates, not long shots. Between alt lines hit
rates and consistency data in general + our sim engine data we should generate high hit rate SGPS not plays that wiull
never win"; then "Two tiers" and long shots "Off the sheet").

Why a pool of its own: the first hit-rate family drew its legs from the sheet's ladders, and the sheet carries 30 of
the board's ~186 NHL player-stats -- 1 to 4 per game on 10-17 -- while the alt capture prices EVERY player a book lists
(38 players and 1,301 rungs for one game, 5 credits). So legs come from the alt capture, and a rung is a LEG only when
three independent reads agree it is likely:

  market   the books' median price on the rung, de-vigged by the market's typical margin     >= LEG_MIN_MARKET
  record   cleared it in >= LEG_MIN_HITS of the player's last LEG_GAMES games (the NHL game log)
  sim      the engine's own P(over): Poisson on its projected mean (props_recommendations)    >= LEG_MIN_SIM

The leg's PROBABILITY stays the market's, nudged by the record (`consistency_posterior`, k=40): the 2026-10-14
consistency backtest found streaks already in the price, so the record and the sim SELECT legs and never inflate them.
The sim is a veto, not a driver, until its accuracy on alt rungs is measured. The joint uses the measured NHL
correlations (`core.ticket_joints`). The player's tonight lineup slot is required (a scratched player's rung can sit on
a book for hours).

Every leg carries the game log's `player_id`, so the reconcile grades it from the box score even when the sheet never
graded that player (`leg_actuals`).
"""
from __future__ import annotations

import collections
import csv
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.nfl import sgp as core

GAME_LOG_DIR = Path("nhl_source") / "source_artifacts" / "data" / "raw"
PROJECTIONS_DIR = Path("nhl_source") / "data" / "processed"
STAT_COLUMNS = {"SOG": ("shots",), "GOALS": ("goals",), "ASSISTS": ("assists",), "POINTS": ("goals", "assists"),
                "SAVES": ("saves",)}
ALT_MARKET = {"player_shots_on_goal": "SOG", "player_points": "POINTS", "player_goals": "GOALS",
              "player_assists": "ASSISTS", "player_total_saves": "SAVES"}

# The gate, the tiers and the ticket search are shared with NFL (`syndicate.features.shared.sgp_hit_rate`).
from syndicate.features.shared.sgp_hit_rate import (LEG_GAMES, LEG_MAX_MARKET, LEG_MIN_HITS, LEG_MIN_MARKET,  # noqa: E402,F401
                                                    LEG_MIN_SIM, POOL_CAP, TIERS)
from syndicate.features.shared import sgp_hit_rate as shared  # noqa: E402


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def _initial_key(name: Any) -> str:
    from syndicate.features.shared.prop_evidence.common import initial_key

    return initial_key(name)


def _log_name(raw: Any) -> str:
    from syndicate.features.shared.prop_evidence.nhl import _log_name as log_name

    return log_name(raw)


def _eastern_day(iso: Any) -> str | None:
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (ts.astimezone(timezone.utc) - timedelta(hours=4)).date().isoformat()   # NHL dates are Eastern


def poisson_over(mean: float | None, line: float) -> float | None:
    if mean is None or mean < 0:
        return None
    k_max = int(math.floor(line))
    term, cdf = math.exp(-mean), 0.0
    for k in range(k_max + 1):
        if k:
            term *= mean / k
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


# ----------------------------------------------------------------------------- the game log
class GameLog:
    """Every played regular-season / playoff game per player (preseason is another population), newest first."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        games: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
        for row in rows:
            pid, pk = str(row.get("player_id") or "").strip(), str(row.get("gamePk") or "").strip()
            if not pid or len(pk) < 6 or pk[4:6] == "01":
                continue
            toi = str(row.get("timeOnIce") or "").strip()
            if not toi or toi in ("0", "00:00", "0:00"):
                continue
            games[pid].setdefault(pk, dict(row))
        self.games = {pid: sorted(g.values(), key=lambda r: str(r.get("date") or ""), reverse=True)
                      for pid, g in games.items()}
        self.by_key: dict[str, list[str]] = collections.defaultdict(list)
        for pid, rows_ in self.games.items():
            self.by_key[_initial_key(_log_name(rows_[0].get("player")))].append(pid)

    @classmethod
    def load(cls, data_root: Path) -> "GameLog":
        folder = Path(data_root) / GAME_LOG_DIR
        rows: list[dict[str, Any]] = []
        for path in [folder / "player_game_stats.csv"] + sorted(folder.glob("player_game_log_????????.csv"), reverse=True):
            try:
                with open(path, encoding="utf-8") as fh:
                    rows.extend(csv.DictReader(fh))
            except OSError:
                continue
        return cls(rows)

    def team_of(self, pid: str) -> str:
        rows = self.games.get(pid) or []
        return str(rows[0].get("team") or "") if rows else ""

    def resolve(self, name: Any, teams: Iterable[str]) -> str | None:
        """The one player id with this initial + surname whose latest team is in tonight's game; None if 0 or 2+."""
        teams = {str(t) for t in teams}
        hits = [pid for pid in self.by_key.get(_initial_key(name), []) if self.team_of(pid) in teams]
        return hits[0] if len(hits) == 1 else None

    def values(self, pid: str, market: str, *, before: str | None = None, n: int = LEG_GAMES) -> list[tuple[str, float]]:
        """(gamePk, stat) for the player's last `n` played games before `before` (an Eastern date), newest first."""
        cols = STAT_COLUMNS.get(market)
        out: list[tuple[str, float]] = []
        for row in self.games.get(pid) or []:
            if before and (_eastern_day(row.get("date")) or "") >= before:
                continue
            try:
                value = sum(float(row.get(c) or "") for c in cols)
            except ValueError:
                continue
            out.append((str(row.get("gamePk")), value))
            if len(out) >= n:
                break
        return out

    def actual(self, pid: str, market: str, day: str) -> float | None:
        cols = STAT_COLUMNS.get(market)
        for row in self.games.get(pid) or []:
            if _eastern_day(row.get("date")) == day:
                try:
                    return sum(float(row.get(c) or "") for c in cols)
                except ValueError:
                    return None
        return None


# ----------------------------------------------------------------------------- the sim
def sim_means(data_root: Path, day: str) -> dict[tuple[str, str], float]:
    """(player, market) -> the engine's projected mean for `day`. A market whose every row carries one mean is a
    degenerate file (prop_evidence flags the same), so it vetoes nothing and feeds nothing: it is left out."""
    path = Path(data_root) / PROJECTIONS_DIR / f"props_recommendations_{day}.csv"
    means: dict[tuple[str, str], float] = {}
    by_market: dict[str, set[float]] = collections.defaultdict(set)
    try:
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                market = str(row.get("market") or "").strip().upper()
                try:
                    lam = float(row.get("proj_lambda") or row.get("proj") or "")
                except ValueError:
                    continue
                by_market[market].add(lam)
                means.setdefault((_norm(row.get("player")), market), lam)
    except OSError:
        return {}
    flat = {m for m, lams in by_market.items() if len(lams) == 1 and sum(1 for k in means if k[1] == m) > 1}
    return {k: v for k, v in means.items() if k[1] not in flat}


# ----------------------------------------------------------------------------- the legs
def legs_by_game(sheet: Mapping[str, Any], data_root: Path, day: str, roles: Mapping[str, str], *,
                 log: GameLog | None = None, alt_rows: Iterable[Mapping[str, Any]] | None = None,
                 means: Mapping[tuple[str, str], float] | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict]:
    """Every rung that passes all three reads, per game; and the counts behind it (what each gate removed)."""
    from syndicate.features.shared import alt_consistency as ac

    log = log if log is not None else GameLog.load(data_root)
    alt_rows = list(alt_rows) if alt_rows is not None else ac.load_alt_rows(data_root, "nhl", day)
    means = means if means is not None else sim_means(data_root, day)
    margins = shared.margins(sheet)
    rungs, games = shared.alt_rungs(alt_rows, ALT_MARKET)
    faces: dict[str, dict[str, Any]] = {}
    for src in list(sheet.get("ladders") or []) + list(sheet.get("rows") or []):
        faces.setdefault(_norm(src.get("player")), {k: src.get(k) for k in ("headshot_src", "headshot_url", "team_logo_src",
                                                                             "team_logo", "team_name", "pos") if src.get(k)})
    counts: collections.Counter = collections.Counter()
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for (event, player, market), ladder in rungs.items():
        game = games.get(event) or {}
        counts["player_stats"] += 1
        role = roles.get(_norm(player))
        if role is None:
            counts["not_in_lineup"] += 1
            continue
        pid = log.resolve(player, (game.get("home"), game.get("away")))
        if pid is None:
            counts["no_game_log"] += 1
            continue
        history = log.values(pid, market, before=day)
        if len(history) < LEG_GAMES:
            counts["short_history"] += 1
            continue
        lam = means.get((_norm(player), market))
        factor = margins.get(market) or margins["*"]
        for rung, books in ladder.items():
            counts["rungs"] += 1
            p_market = shared.market_prob(books, factor)
            hits = sum(1 for _pk, v in history if v > rung)
            p_sim = poisson_over(lam, rung) if lam is not None else None
            if not shared.gate(p_market, hits, p_sim, counts):
                continue
            p_leg = shared.leg_prob(p_market, hits, len(history))
            counts["legs"] += 1
            out[event].append({
                "player": player, "team": log.team_of(pid), "market": market, "side": "over", "line": rung,
                "p_over": p_leg, "p_side": p_leg, "type": f"{market}|{role}", "role": role, "prices": dict(books),
                "event_id": event, "p_market": round(p_market, 4), "p_sim": round(p_sim, 4), "hits": hits,
                "games": len(history), "alt": True, "player_id": pid, "_history": history,
                **faces.get(_norm(player), {})})
    return shared.cap(out), {"counts": dict(counts), "games": games}


# ----------------------------------------------------------------------------- the tickets
_together = shared.together


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]], *,
            exclude: Any = None) -> list[dict[str, Any]]:
    return shared.tickets(pool, cells, games, exclude=exclude)


# ----------------------------------------------------------------------------- grading
def leg_player_id(log: GameLog, leg: Mapping[str, Any]) -> str | None:
    """A correlation-family leg (built off the sheet's rows or ladder) carries no game-log id: the one player with this
    initial + surname whose latest team is the leg's own, team names compared canonically ('St Louis Blues' vs
    'St. Louis Blues', 'NJD' vs 'New Jersey Devils'). 0 or 2+ -> None: a wrong player's line is worse than none.
    Measured 2026-10-27 (todo #743): 488 of 493 pending NHL ledger legs had no id; this resolves 153 of the 163 unique
    (day, player, stat) with an actual."""
    from syndicate.features.shared.team_aliases import canonical_team

    want = canonical_team("nhl", leg.get("team")) if leg.get("team") else None
    if not want:
        return None
    hits = [pid for pid in log.by_key.get(_initial_key(leg.get("player")), [])
            if canonical_team("nhl", log.team_of(pid)) == want]
    return hits[0] if len(hits) == 1 else None


def leg_actuals(data_root: Path, day: str, tickets_: Iterable[Mapping[str, Any]], *, log: GameLog | None = None) -> dict[str, float]:
    """`prop_result_key` prefix (player|market) -> the player's stat in `day`'s game, from the box-score log, for
    every leg -- the legs the sheet itself never graded. A leg without a game-log `player_id` is resolved by name and
    team (`leg_player_id`)."""
    from syndicate.features.shared.cheat_sheets import prop_result_key

    log = log if log is not None else GameLog.load(data_root)
    out: dict[str, float] = {}
    for t in tickets_:
        for leg in t.get("legs") or []:
            market = str(leg.get("market") or "").upper()
            if market not in STAT_COLUMNS:
                continue
            pid = str(leg.get("player_id") or "") or leg_player_id(log, leg)
            if not pid:
                continue
            value = log.actual(pid, market, day)
            if value is not None:
                parts = prop_result_key(leg).split("|")
                out[f"{parts[0]}|{parts[1]}"] = value
    return out
