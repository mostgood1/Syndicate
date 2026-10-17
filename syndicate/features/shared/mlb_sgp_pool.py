"""High-hit-rate MLB same-game parlays from every priced alt rung (lane `basketball-sgp-builder` -- the all-sports SGP
lane, user 2026-10-17: "we need sgp work done for alll sports").

The NHL design (the shared gate, tiers and search in `syndicate.features.shared.sgp_hit_rate`) with MLB's reads:

  market   the books' median price on the alt rung, de-vigged by the market's typical main-line margin
  record   the player's last 10 games before today: hitters with 2+ plate appearances, pitchers' STARTS only (an opener's
           relief outings are another job) -- `derived/mlb_player_game_log_<season>_{hitting,pitching}.csv` (StatsAPI)
  sim      the engine's own distribution for the game (`daily/sims/<date>/sim_*.json`: `hitter_props` /
           `pitcher_props` histograms over its simulations): P(X > rung) read straight off the histogram. These are
           the RAW sim numbers; the board's calibrated ones run lower (Caminero 1+ hit 0.709 raw vs 0.630 calibrated on
           10-17), so the sim is a veto here, never the leg's probability

A hitter must be in the sim's (projected) lineup; a pitcher must be a listed starter. Names are matched accent-folded
("Jose Ramirez" on the books is "José Ramírez" in StatsAPI) within the game's two clubs; the sim's MLBAM id then keys the
game log. Roles are UNK -- MLB correlation cells are market-level (no batting order in the multi-season logs).
"""
from __future__ import annotations

import collections
import csv
import json
import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared import sgp_hit_rate as shared

DATA = Path("mlb_source") / "source_artifacts" / "data"
HITTER = {"batter_hits": ("h",), "batter_total_bases": ("tb",), "batter_home_runs": ("hr",), "batter_rbis": ("rbi",),
          "batter_runs_scored": ("r",), "batter_hits_runs_rbis": ("h", "r", "rbi"), "batter_strikeouts": ("so",)}
PITCHER = {"strikeouts": ("k",), "hits_allowed": ("h",), "earned_runs": ("er",), "outs": ("outs",)}
# the alternate key's base -> the sheet's market name (MLB sheet rows name pitcher markets bare)
ALT_MARKET = {**{m: m for m in HITTER}, "pitcher_strikeouts": "strikeouts", "pitcher_hits_allowed": "hits_allowed",
              "pitcher_earned_runs": "earned_runs", "pitcher_outs": "outs"}
SIM_DIST = {"batter_hits": "hits_dist", "batter_total_bases": "total_bases_dist", "batter_home_runs": "home_runs_dist",
            "batter_rbis": "rbi_dist", "batter_runs_scored": "runs_dist", "batter_hits_runs_rbis": "hits_runs_rbis_dist",
            "batter_strikeouts": "strikeouts_dist", "strikeouts": "so_dist", "hits_allowed": "hits_dist",
            "earned_runs": "earned_runs_dist", "outs": "outs_dist"}
NESTED = frozenset(frozenset(p) for p in (
    ("batter_hits", "batter_total_bases"), ("batter_hits", "batter_hits_runs_rbis"), ("batter_rbis", "batter_hits_runs_rbis"),
    ("batter_runs_scored", "batter_hits_runs_rbis"), ("batter_home_runs", "batter_total_bases"),
    ("batter_home_runs", "batter_rbis"), ("batter_home_runs", "batter_runs_scored"), ("batter_home_runs", "batter_hits_runs_rbis"),
    # 1+ total base IS a hit, so it implies 1+ hits+runs+RBIs: on 10-16 rungs the pair made a "2-leg" ticket that was
    # one bet (Diaz HRR o0.5 + TB o0.5, 63% vs TB alone ~65%). Missing from the study's nested list too.
    ("batter_total_bases", "batter_hits_runs_rbis")))
LOG_SEASONS = 4
LABEL = {"batter_hits": "hits", "batter_total_bases": "total bases", "batter_home_runs": "home runs", "batter_rbis": "RBIs",
         "batter_runs_scored": "runs", "batter_hits_runs_rbis": "hits+runs+RBIs", "batter_strikeouts": "strikeouts (batting)",
         "strikeouts": "strikeouts", "hits_allowed": "hits allowed", "earned_runs": "earned runs", "outs": "outs"}


def fold(name: Any) -> str:
    """'José Ramírez' / 'Jose Ramirez' -> 'joseramirez'; suffixes dropped ('Victor Mesa Jr.' -> 'victormesa')."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    parts = [p for p in re.split(r"[\s.]+", text) if p and p not in ("jr", "sr", "ii", "iii", "iv")]
    return re.sub(r"[^a-z]", "", "".join(parts))


def _canon(team: Any) -> str | None:
    from syndicate.features.shared.team_aliases import canonical_team

    return canonical_team("mlb", team) if team else None


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dist_over(dist: Mapping[str, Any] | None, line: float) -> float | None:
    """P(X > line) off a {count: weight} histogram (pitcher strikeouts carry fractional weights)."""
    if not dist:
        return None
    total = over = 0.0
    for k, w in dist.items():
        kk, ww = _num(k), _num(w)
        if kk is None or ww is None:
            continue
        total += ww
        if kk > line:
            over += ww
    return over / total if total > 0 else None


# ----------------------------------------------------------------------------- the game log
class GameLog:
    """Hitters' games with a plate appearance and pitchers' starts, per MLBAM id, newest first."""

    def __init__(self, hitting: Iterable[Mapping[str, Any]], pitching: Iterable[Mapping[str, Any]]):
        def index(rows, keep):
            games: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
            for row in rows:
                pid, pk = str(row.get("player_id") or "").strip(), str(row.get("game_pk") or "").strip()
                if pid and pk and keep(row):
                    games[pid].setdefault(pk, dict(row))
            return {pid: sorted(g.values(), key=lambda r: str(r.get("date") or ""), reverse=True) for pid, g in games.items()}

        # a hitter's game needs 2+ plate appearances -- the study's "started" rule (PA 1 is mostly a pinch hit)
        self.hit = index(hitting, lambda r: (_num(r.get("pa")) or 0) >= 2)
        self.pit = index(pitching, lambda r: str(r.get("is_starter") or "").strip() in ("1", "1.0", "True", "true"))

    @classmethod
    def load(cls, data_root: Path) -> "GameLog":
        folder = Path(data_root) / DATA / "derived"
        rows: dict[str, list[dict[str, Any]]] = {"hitting": [], "pitching": []}
        for kind in rows:
            for path in sorted(folder.glob(f"mlb_player_game_log_????_{kind}.csv"), reverse=True)[:LOG_SEASONS]:
                try:
                    with open(path, encoding="utf-8") as fh:
                        rows[kind].extend(csv.DictReader(fh))
                except OSError:
                    continue
        return cls(rows["hitting"], rows["pitching"])

    def _rows(self, pid: str, market: str) -> list[dict[str, Any]]:
        return (self.hit if market in HITTER else self.pit).get(pid) or []

    @staticmethod
    def _value(row: Mapping[str, Any], market: str) -> float | None:
        total = 0.0
        for col in (HITTER.get(market) or PITCHER.get(market) or ()):
            v = _num(row.get(col))
            if v is None:
                return None
            total += v
        return total

    def values(self, pid: str, market: str, *, before: str, n: int = shared.LEG_GAMES) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for row in self._rows(pid, market):
            if str(row.get("date") or "")[:10] >= before:
                continue
            v = self._value(row, market)
            if v is None:
                continue
            out.append((str(row.get("game_pk")), v))
            if len(out) >= n:
                break
        return out

    def actual(self, pid: str, market: str, day: str) -> float | None:
        for row in self._rows(pid, market):
            if str(row.get("date") or "")[:10] == day:
                return self._value(row, market)
        return None


# ----------------------------------------------------------------------------- the sim
def sim_games(data_root: Path, day: str) -> list[dict[str, Any]]:
    """One entry per simulated game on `day`: its clubs, and every lineup hitter and listed starter by folded name."""
    out = []
    for path in sorted((Path(data_root) / DATA / "daily" / "sims" / day).glob("sim_*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sim = doc.get("sim") or {}
        players: dict[str, dict[str, Any]] = {}
        for pid, h in (sim.get("hitter_props") or {}).items():
            if isinstance(h, dict) and h.get("is_lineup_batter") and h.get("name"):
                players.setdefault(fold(h["name"]), {"id": str(pid), "kind": "hitter", "props": h})
        starters, names = doc.get("starters") or {}, doc.get("starter_names") or {}
        for side in ("away", "home"):
            pid = starters.get(side)
            props = (sim.get("pitcher_props") or {}).get(str(pid))
            if pid and props and names.get(side):
                players.setdefault(fold(names[side]), {"id": str(pid), "kind": "pitcher", "props": props})
        clubs = {_canon((doc.get(s) or {}).get("name")) for s in ("away", "home")} - {None}
        out.append({"clubs": clubs, "players": players, "game_pk": doc.get("game_pk"), "file": path.name})
    return out


# ----------------------------------------------------------------------------- the legs
def legs_by_game(sheet: Mapping[str, Any], data_root: Path, day: str, *, log: GameLog | None = None,
                 sims: Sequence[Mapping[str, Any]] | None = None,
                 alt_rows: Iterable[Mapping[str, Any]] | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict]:
    """Every rung that passes all three reads, per game; and the counts behind it (what each gate removed)."""
    from syndicate.features.shared import alt_consistency as ac

    log = log if log is not None else GameLog.load(data_root)
    sims = sims if sims is not None else sim_games(data_root, day)
    alt_rows = list(alt_rows) if alt_rows is not None else ac.load_alt_rows(data_root, "mlb", day)
    margins = shared.margins(sheet)
    rungs, games = shared.alt_rungs(alt_rows, ALT_MARKET)
    faces: dict[str, dict[str, Any]] = {}
    for src in list(sheet.get("ladders") or []) + list(sheet.get("rows") or []):
        faces.setdefault(fold(src.get("player")), {k: src.get(k) for k in ("headshot_src", "headshot_url", "team_logo_src",
                                                                            "team_logo", "team_name", "pos") if src.get(k)})
    counts: collections.Counter = collections.Counter()
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for (event, player, market), ladder in rungs.items():
        game = games.get(event) or {}
        clubs = {_canon(game.get("home")), _canon(game.get("away"))} - {None}
        counts["player_stats"] += 1
        sim_game = next((g for g in sims if g["clubs"] == clubs), None)
        if sim_game is None:
            counts["no_sim_game"] += 1
            continue
        who = sim_game["players"].get(fold(player))
        kind = "hitter" if market in HITTER else "pitcher"
        if who is None or who["kind"] != kind:
            counts["not_in_lineup"] += 1
            continue
        history = log.values(who["id"], market, before=day)
        if len(history) < shared.LEG_GAMES:
            counts["short_history"] += 1
            continue
        team = str(who["props"].get("team") or "")
        factor = margins.get(market) or margins["*"]
        for rung, books in ladder.items():
            counts["rungs"] += 1
            p_market = shared.market_prob(books, factor)
            hits = sum(1 for _g, v in history if v > rung)
            p_sim = dist_over(who["props"].get(SIM_DIST[market]), rung)
            if not shared.gate(p_market, hits, p_sim, counts, shared.MLB_RULE):
                continue
            p_leg = shared.leg_prob(p_market, hits, len(history))
            counts["legs"] += 1
            out[event].append({
                "player": player, "team": team or kind, "market": market, "market_label": LABEL.get(market, market),
                "side": "over", "line": rung,
                "p_over": p_leg, "p_side": p_leg, "type": f"{market}|UNK", "role": "UNK", "prices": dict(books),
                "event_id": event, "p_market": round(p_market, 4), "p_sim": round(p_sim, 4), "hits": hits,
                "games": len(history), "alt": True, "player_id": who["id"], "_history": history,
                **faces.get(fold(player), {})})
    return shared.cap(out), {"counts": dict(counts), "games": games}


def exclude(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return a["player"] == b["player"] and frozenset({a["market"], b["market"]}) in NESTED


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return shared.tickets(pool, cells, games, exclude=exclude, tiers=shared.MLB_TIERS)


# ----------------------------------------------------------------------------- the sheet's hooks
def load_cells(data_root: Path) -> dict[str, Any] | None:
    try:
        return json.loads((Path(data_root) / "mlb_source" / "sgp" / "mlb_sgp_correlations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def hook() -> SimpleNamespace:
    """The module shape `build_cheat_sheets.attach_sgp` calls (load_cells / current_roles / suggest)."""
    def suggest(sheet, cells, roles, *, data_root=None, day=None, **_kw):
        if not cells or data_root is None or not day:
            return []
        pool, _info = legs_by_game(sheet, data_root, day)
        return tickets(pool, cells, sheet.get("games") or [])

    return SimpleNamespace(load_cells=load_cells, current_roles=lambda data_root, day: {}, suggest=suggest)


# ----------------------------------------------------------------------------- grading
def leg_actuals(data_root: Path, day: str, tickets_: Iterable[Mapping[str, Any]], *, log: GameLog | None = None) -> dict[str, float]:
    from syndicate.features.shared.cheat_sheets import prop_result_key

    log = log if log is not None else GameLog.load(data_root)
    out: dict[str, float] = {}
    for t in tickets_:
        for leg in t.get("legs") or []:
            pid, market = str(leg.get("player_id") or ""), str(leg.get("market") or "")
            if not pid or market not in SIM_DIST:
                continue
            value = log.actual(pid, market, day)
            if value is not None:
                parts = prop_result_key(leg).split("|")
                out[f"{parts[0]}|{parts[1]}"] = value
    return out
