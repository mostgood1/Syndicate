"""Same-game parlays for the NHL cheat sheet (lane `nhl-sgp-builder`, user 2026-10-16: "lets build the next logical sport
- NHL", after "Alt-line consistency first").

The joint probability comes from correlations MEASURED on NHL box scores (`scripts/build_nhl_sgp_correlations.py`,
`<data root>/nhl_source/sgp/nhl_sgp_correlations.json`); the pricing, the "worth it at" number and the assumed-discount
estimate are the NFL builder's (`syndicate.features.nfl.sgp.pair_legs`), so the two sports cannot drift apart.

LEGS come from two places:
  * the consistency ladder (`alt_consistency`): every captured alternate rung with a market probability -- "Kadri 3+
    SOG", "MacKinnon 2+ points" -- each with every book's price on that rung, because an SGP is one book's ticket;
  * the sheet's main-line rows, both sides, at the de-vigged consensus.
A rung the market makes nearly certain (or nearly impossible) adds nothing to a ticket but vig, so legs are kept between
`MIN_LEG_P` and `MAX_LEG_P`.

ROLES are tonight's projected lineup (`lineups_<date>.csv`): forward lines L1..L4, defense pairs D1..D3, the goalie G --
the same tiers the correlations were fitted on (prior-TOI rank in the box scores). Paper only: every parlay goes to
`cheatsheets/nhl/sgp_ledger.jsonl` and no edge label is shown (#621).
"""
from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.nfl import sgp as core

CORRELATIONS = Path("nhl_source") / "sgp" / "nhl_sgp_correlations.json"
MARKETS = ("SOG", "POINTS", "GOALS", "ASSISTS", "SAVES")
MIN_LEG_P, MAX_LEG_P = 0.15, 0.85
# lineup slot -> the role names in the correlations file. The fit used the engine's own `line_slot` rule (average TOI
# over the team's last 8 earlier games), so the names are the slots themselves.
ROLE_FROM_SLOT = {s: s for s in ("L1", "L2", "L3", "L4", "D1", "D2", "D3")}
# Same-player pairs where one leg implies the other (a goal IS a point): rho 0.91-0.95, never a ticket. The fit lists
# them in `nested_same_player`; these are the defaults if the file does not.
NESTED_SAME_PLAYER = frozenset({frozenset({"GOALS", "POINTS"}), frozenset({"ASSISTS", "POINTS"})})


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def load_cells(data_root: Path) -> dict[str, Any] | None:
    try:
        return json.loads((Path(data_root) / CORRELATIONS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lineup_roles(data_root: Path, day: str) -> dict[str, str]:
    """player (normalized) -> role from tonight's projected lineup; the goalie with the larger projected TOI per team is G."""
    path = Path(data_root) / "nhl_source" / "data" / "processed" / f"lineups_{day}.csv"
    roles: dict[str, str] = {}
    goalies: dict[str, tuple[float, str]] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = _norm(row.get("full_name"))
                if not name:
                    continue
                if str(row.get("position") or "").upper() == "G":
                    try:
                        toi = float(row.get("proj_toi") or 0)
                    except ValueError:
                        toi = 0.0
                    team = str(row.get("team") or "")
                    if toi > goalies.get(team, (-1.0, ""))[0]:
                        goalies[team] = (toi, name)
                    continue
                role = ROLE_FROM_SLOT.get(str(row.get("line_slot") or "").upper())
                if role:
                    roles[name] = role
    except OSError:
        return {}
    for _toi, name in goalies.values():
        roles[name] = "G"
    return roles


def _leg(player: str, team: Any, market: str, side: str, line: float, p_over: float, prices: Mapping[str, Any],
         event_id: Any, role: str, face: Mapping[str, Any]) -> dict[str, Any]:
    return {"player": player, "team": team, "market": market, "side": side, "line": line, "p_over": p_over,
            "p_side": p_over if side in ("over", "yes") else 1.0 - p_over, "type": f"{market}|{role}", "role": role,
            "prices": dict(prices), "event_id": event_id, **face}


def legs_by_game(sheet: Mapping[str, Any], roles: Mapping[str, str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    seen: set[tuple] = set()
    face_keys = ("headshot_src", "headshot_url", "team_logo_src", "team_logo", "team_name", "pos")
    for lad in sheet.get("ladders") or []:
        market = str(lad.get("market") or "")
        if market not in MARKETS:
            continue
        role = roles.get(_norm(lad.get("player")), "UNK")
        face = {k: lad.get(k) for k in face_keys if lad.get(k)}
        for cell in lad.get("rungs") or []:
            p, prices = cell.get("p_market"), cell.get("prices") or {}
            if p is None or not prices or not (MIN_LEG_P <= p <= MAX_LEG_P):
                continue
            key = (lad.get("event_id"), _norm(lad.get("player")), market, "over", cell["rung"])
            if key in seen:
                continue
            seen.add(key)
            out[str(lad.get("event_id"))].append(_leg(lad.get("player"), lad.get("team"), market, "over", cell["rung"],
                                                      float(p), prices, lad.get("event_id"), role, face))
    for row in sheet.get("rows") or []:
        market = str(row.get("market") or "")
        if market not in MARKETS:
            continue
        try:
            p_side, line = float((row.get("check") or {}).get("p_market")), float(row.get("line"))
        except (TypeError, ValueError):
            continue
        side = str(row.get("side") or "").lower()
        p_over = 1.0 - p_side if side == "under" else p_side
        if not (MIN_LEG_P <= p_side <= MAX_LEG_P) or not row.get("book_prices"):
            continue
        key = (row.get("event_id"), _norm(row.get("player")), market, side, line)
        if key in seen:
            continue
        seen.add(key)
        role = roles.get(_norm(row.get("player")), "UNK")
        face = {k: row.get(k) for k in face_keys if row.get(k)}
        out[str(row.get("event_id"))].append(_leg(row.get("player"), row.get("team"), market, side, line, p_over,
                                                  row.get("book_prices") or {}, row.get("event_id"), role, face))
    return out


def suggest(sheet: Mapping[str, Any], cells: Mapping[str, Any] | None, roles: Mapping[str, str], *,
            per_game: int = core.PER_GAME, per_sheet: int = core.PER_SHEET) -> list[dict[str, Any]]:
    if not cells:
        return []
    nested = set(NESTED_SAME_PLAYER)
    for key in cells.get("nested_same_player") or []:
        parts = str(key).split("~")
        if len(parts) == 3:
            nested.add(frozenset(parts[:2]))

    def exclude(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        return a["player"] == b["player"] and frozenset({a["market"], b["market"]}) in nested

    return core.pair_legs(legs_by_game(sheet, roles), cells, sheet.get("games") or [], per_game=per_game,
                          per_sheet=per_sheet, exclude=exclude)
