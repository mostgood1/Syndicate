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
import itertools
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

LEG_MIN_MARKET, LEG_MAX_MARKET = 0.75, 0.95   # above 95% a leg adds vig, not payout
LEG_MIN_HITS, LEG_GAMES = 8, 10
LEG_MIN_SIM = 0.75
DEFAULT_MARGIN = 1.05                          # the de-vig factor when the sheet has no main-line margin to read
POOL_CAP = 16                                  # legs per game kept for the search, best market probability first
# The two tiers (user 2026-10-17: "Two tiers"). On 10-17's prices three ~87% legs win ~66% at about -200, and five
# win ~50% at about +110. `min_decimal` is the legs-multiplied price floor: a ticket that pays less is not a bet.
TIERS = (
    {"tier": "safer", "label": "Higher hit rate", "sizes": (2, 3), "min_joint": 0.62, "min_decimal": 1.40,
     "per_game": 2, "per_sheet": 10},
    {"tier": "payout", "label": "Bigger payout", "sizes": (4, 5), "min_joint": 0.45, "min_decimal": 1.70,
     "per_game": 1, "per_sheet": 6},
)


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
def _margins(sheet: Mapping[str, Any]) -> dict[str, float]:
    from syndicate.features.shared import alt_consistency as ac

    found: dict[str, list[float]] = collections.defaultdict(list)
    for row in sheet.get("rows") or []:
        f = ac._margin_factor(row)
        if f is not None:
            found[str(row.get("market") or "")].append(f)
    every = sorted(f for fs in found.values() for f in fs)
    out = {m: sorted(fs)[len(fs) // 2] for m, fs in found.items()}
    out["*"] = every[len(every) // 2] if every else DEFAULT_MARGIN
    return out


def _alt_rungs(alt_rows: Iterable[Mapping[str, Any]]) -> tuple[dict, dict]:
    """(event, player, market) -> rung -> {book: price} (the latest capture of each book's OVER rung), and each
    event's {home, away, commence_time}."""
    latest: dict[tuple, tuple[str, Any]] = {}
    games: dict[str, dict[str, Any]] = {}
    for r in alt_rows:
        market = ALT_MARKET.get(str(r.get("base_market") or ""))
        if market is None or str(r.get("side") or "").lower() != "over" or r.get("line") is None or r.get("price") is None:
            continue
        event = str(r.get("event_id") or "")
        games.setdefault(event, {"home": r.get("home_team"), "away": r.get("away_team"),
                                 "commence_time": r.get("commence_time")})
        key = (event, str(r.get("player") or ""), market, float(r["line"]), str(r.get("bookmaker") or ""))
        stamp = str(r.get("captured_at") or "")
        if key not in latest or stamp >= latest[key][0]:
            latest[key] = (stamp, r.get("price"))
    rungs: dict[tuple, dict[float, dict[str, Any]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (event, player, market, line, book), (_s, price) in latest.items():
        rungs[(event, player, market)][line][book] = price
    return rungs, games


def legs_by_game(sheet: Mapping[str, Any], data_root: Path, day: str, roles: Mapping[str, str], *,
                 log: GameLog | None = None, alt_rows: Iterable[Mapping[str, Any]] | None = None,
                 means: Mapping[tuple[str, str], float] | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict]:
    """Every rung that passes all three reads, per game; and the counts behind it (what each gate removed)."""
    from syndicate.features.shared import alt_consistency as ac
    from syndicate.features.shared.cheat_sheets import consistency_posterior

    log = log if log is not None else GameLog.load(data_root)
    alt_rows = list(alt_rows) if alt_rows is not None else ac.load_alt_rows(data_root, "nhl", day)
    means = means if means is not None else sim_means(data_root, day)
    margins = _margins(sheet)
    rungs, games = _alt_rungs(alt_rows)
    faces: dict[str, dict[str, Any]] = {}
    for src in list(sheet.get("ladders") or []) + list(sheet.get("rows") or []):
        faces.setdefault(_norm(src.get("player")), {k: src.get(k) for k in ("headshot_src", "headshot_url", "team_logo_src",
                                                                             "team_logo", "team_name", "pos") if src.get(k)})
    counts = collections.Counter()
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
            implied = sorted(x for x in (ac._book_prob(p) for p in books.values()) if x)
            if not implied:
                continue
            p_market = min(0.995, implied[len(implied) // 2] / factor)
            if not (LEG_MIN_MARKET <= p_market <= LEG_MAX_MARKET):
                counts["market_gate"] += 1
                continue
            hits = sum(1 for _pk, v in history if v > rung)
            if hits < LEG_MIN_HITS:
                counts["record_gate"] += 1
                continue
            p_sim = poisson_over(lam, rung) if lam is not None else None
            if p_sim is None or p_sim < LEG_MIN_SIM:
                counts["sim_gate" if p_sim is not None else "no_sim"] += 1
                continue
            p_leg = consistency_posterior(p_market, hits, len(history))
            counts["legs"] += 1
            team = log.team_of(pid)
            out[event].append({
                "player": player, "team": team, "market": market, "side": "over", "line": rung,
                "p_over": p_leg, "p_side": p_leg, "type": f"{market}|{role}", "role": role, "prices": dict(books),
                "event_id": event, "p_market": round(p_market, 4), "p_sim": round(p_sim, 4), "hits": hits,
                "games": len(history), "alt": True, "player_id": pid, "_history": history,
                **faces.get(_norm(player), {})})
    for event, legs in out.items():
        legs.sort(key=lambda x: -x["p_market"])
        out[event] = legs[:POOL_CAP]
    return dict(out), {"counts": dict(counts), "games": games}


# ----------------------------------------------------------------------------- the tickets
def _together(legs: Sequence[Mapping[str, Any]]) -> dict[str, int] | None:
    """Same-team tickets only: in the team's recent games where every player played, how often every leg cleared."""
    if len({leg.get("team") for leg in legs}) != 1:
        return None
    per = [dict(leg.get("_history") or []) for leg in legs]
    shared = set(per[0])
    for h in per[1:]:
        shared &= set(h)
    if not shared:
        return None
    hits = sum(1 for pk in shared if all(h[pk] > leg["line"] for h, leg in zip(per, legs)))
    return {"hits": hits, "games": len(shared)}


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]], *,
            exclude: Any = None) -> list[dict[str, Any]]:
    """The two tiers, per game: every combination of the pool's legs (one rung per player-stat, never a nested pair,
    every leg at one book) that pays at least the tier's floor, priced by the measured correlations; ranked by the
    chance the whole ticket wins; near-duplicates dropped."""
    by_event = {str(g.get("event_id")): g for g in games}
    out: list[dict[str, Any]] = []

    def clash(a, b):
        return (a["player"] == b["player"] and a["market"] == b["market"]) or (exclude is not None and exclude(a, b))

    for event_id, legs in pool.items():
        game = by_event.get(event_id) or {}
        for spec in TIERS:
            cands = []
            for size in spec["sizes"]:
                for combo in itertools.combinations(legs, size):
                    if any(clash(a, b) for a, b in itertools.combinations(combo, 2)):
                        continue
                    indep = math.prod(leg["p_side"] for leg in combo)
                    if indep < spec["min_joint"] * 0.8:
                        continue                  # no measured correlation lifts a joint this far
                    best = core._best_book(list(combo))
                    if not best or best[1] < spec["min_decimal"]:
                        continue
                    cands.append(list(combo))
            built = []
            for start in range(0, len(cands), 400):
                chunk = cands[start:start + 400]
                by_size: dict[int, list[int]] = collections.defaultdict(list)
                for i, t in enumerate(chunk):
                    by_size[len(t)].append(i)
                for size, idx in by_size.items():
                    pjs, levels = core.ticket_joints([chunk[i] for i in idx], cells, core.relation_of)
                    for i, pj, lv in zip(idx, pjs, levels):
                        t = chunk[i]
                        if pj != pj or pj < spec["min_joint"]:
                            continue
                        bk, prod = core._best_book(t)
                        rels = [core.relation_of(t[a], t[b]) for a in range(len(t)) for b in range(a + 1, len(t))]
                        tk = core._ticket(event_id, t, pj, lv, game, bk, prod, rels)
                        tk.update({"family": "hit_rate", "tier": spec["tier"], "tier_label": spec["label"],
                                   "show_estimate": False, "together": _together(t)})
                        built.append((tk, t))
            # Every ticket here clears the tier's hit-rate floor; among them the one whose legs pay closest to (or
            # over) its fair price leads -- heavy favourites stack vig, so a 66% ticket's legs can multiply to -244
            # against a fair -192 (NJ @ WSH, 10-17).
            built.sort(key=lambda x: (-x[0]["p_joint"] * (core.payout(x[0]["legs_product_odds"]) or 0), -x[0]["p_joint"]))
            kept, kept_sets = [], []
            for tk, t in built:
                ids = {(x["player"], x["market"]) for x in t}
                if any(len(ids & other) >= len(ids) - 1 for other in kept_sets):
                    continue
                kept.append(tk)
                kept_sets.append(ids)
                if len(kept) >= spec["per_game"]:
                    break
            out += kept
    final: list[dict[str, Any]] = []
    for spec in TIERS:
        mine = sorted((t for t in out if t["tier"] == spec["tier"]),
                      key=lambda t: (-t["p_joint"] * (core.payout(t["legs_product_odds"]) or 0), -t["p_joint"]))
        final += mine[:spec["per_sheet"]]
    for t in final:
        for leg in t["legs"]:
            leg.pop("_history", None)
    return final


# ----------------------------------------------------------------------------- grading
def leg_actuals(data_root: Path, day: str, tickets_: Iterable[Mapping[str, Any]], *, log: GameLog | None = None) -> dict[str, float]:
    """`prop_result_key` prefix (player|market) -> the player's stat in `day`'s game, from the box-score log, for
    every leg that carries a game-log `player_id` -- the legs the sheet itself never graded."""
    from syndicate.features.shared.cheat_sheets import prop_result_key

    log = log if log is not None else GameLog.load(data_root)
    out: dict[str, float] = {}
    for t in tickets_:
        for leg in t.get("legs") or []:
            pid, market = str(leg.get("player_id") or ""), str(leg.get("market") or "").upper()
            if not pid or market not in STAT_COLUMNS:
                continue
            value = log.actual(pid, market, day)
            if value is not None:
                parts = prop_result_key(leg).split("|")
                out[f"{parts[0]}|{parts[1]}"] = value
    return out
