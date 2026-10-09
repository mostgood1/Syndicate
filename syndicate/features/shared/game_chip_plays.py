"""Our board plays on a game, and how they did -- the games-rail card's FINAL line.

Mockup 4 (lane games-rail-full-detail), user decision 2026-10-09 "Lines now,
props overnight":

* A PLAY is a board card with a positive EV against the fair
  (`ev_vs_fair_pct > 0`). Both sides of one market can each be a row on the
  board; only the +EV side is a play.
* GAME LINES (moneyline / spread / total, full game, including alternates) are
  graded the moment the card is FINAL, from the card's own final score.
* PROPS are graded overnight by the evaluation settlement, which writes a small
  `layer2_pick_results/<date>.json` ({pick_id: result}); until it has, a prop
  reads "pending".

WHY A RECORD FILE. Once a game is final its markets leave the board, so the
shortlist no longer holds the plays that were on it. The WORKER therefore keeps
`layer2_game_plays/<date>.json` -- every play seen on each game while it was on
the board, keyed by pick_id, unioned build after build. The web only reads it.

Display only. Nothing here changes a pick, a price or a settlement.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

_LOCK = threading.Lock()
_GRADEABLE = {"h2h", "spreads", "totals", "h2h_3_way", "spreads_alt", "totals_alt", "alternate_spreads", "alternate_totals"}


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return Path(reports_root())


def _plays_path(date: str) -> Path:
    return _reports_root() / "intelligence" / "layer2_game_plays" / f"{date}.json"


def _results_path(date: str) -> Path:
    return _reports_root() / "intelligence" / "layer2_pick_results" / f"{date}.json"


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _game_key(sport: Any, away: Any, home: Any) -> str | None:
    a, h = str(away or "").strip().lower(), str(home or "").strip().lower()
    return f"{str(sport or '').lower()}|{a}|{h}" if a and h else None


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_worker() -> bool:
    # The web never writes the record (display-only role); it reads it.
    return not os.environ.get("SYNDICATE_WEB_DYNO")


def record_plays(date: str, cards: Iterable[Mapping[str, Any]]) -> int:
    """Union this build's +EV cards into the per-date record. Returns plays added."""
    games: dict[str, dict[str, dict]] = {}
    for card in cards or ():
        ev = _num(card.get("ev_vs_fair_pct"))
        pid = card.get("pick_id")
        key = _game_key(card.get("sport"), card.get("away_key"), card.get("home_key"))
        if ev is None or ev <= 0 or not pid or not key:
            continue
        games.setdefault(key, {})[str(pid)] = {
            "kind": card.get("kind"),
            "market": str(card.get("market") or "").lower(),
            "segment": str(card.get("segment") or "full").lower(),
            "side": str(card.get("side") or "").lower(),
            "line": _num(card.get("line")),
            "home_team": card.get("home_team"),
            "away_team": card.get("away_team"),
        }
    if not games:
        return 0
    path = _plays_path(date)
    with _LOCK:
        current = _read(path)
        stored = current.get("games") if isinstance(current.get("games"), dict) else {}
        added = 0
        for key, plays in games.items():
            bucket = stored.setdefault(key, {})
            for pid, play in plays.items():
                if pid not in bucket:
                    added += 1
                bucket[pid] = play
        if added:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": date, "games": stored}), encoding="utf-8")
            tmp.replace(path)
    return added


def _grade_line(play: Mapping[str, Any], away_score: float, home_score: float, home_team: Any, away_team: Any) -> str | None:
    """win / loss / push for a full-game line play, or None when not gradeable."""
    market = play.get("market") or ""
    if play.get("kind") != "game" or play.get("segment") not in ("full", "", "game") or market not in _GRADEABLE:
        return None
    side = play.get("side") or ""
    if side == str(home_team or "").strip().lower():
        side = "home"
    elif side == str(away_team or "").strip().lower():
        side = "away"
    margin = home_score - away_score
    line = play.get("line")
    if "total" in market:
        if line is None or side not in ("over", "under"):
            return None
        total = home_score + away_score
        if total == line:
            return "push"
        return "win" if (total > line) == (side == "over") else "loss"
    if "spread" in market:
        if line is None or side not in ("home", "away"):
            return None
        own = margin if side == "home" else -margin
        result = own + line  # the card carries the side's OWN line
        return "push" if result == 0 else ("win" if result > 0 else "loss")
    # moneyline (two-way or three-way)
    if side == "draw":
        return "win" if margin == 0 else "loss"
    if side not in ("home", "away"):
        return None
    if margin == 0:
        return "loss" if market == "h2h_3_way" else "push"
    return "win" if (margin > 0) == (side == "home") else "loss"


def _tally(results: Iterable[str | None]) -> dict[str, int]:
    out = {"win": 0, "loss": 0, "push": 0, "pending": 0}
    for r in results:
        out[r if r in out else "pending"] += 1
    return out


def attach_plays(chips: list[dict[str, Any]], date: str, *, cards: Iterable[Mapping[str, Any]] | None = None) -> None:
    """Stamp `plays` on each chip that had plays: counts and, on finals, results."""
    try:
        if cards is not None and _is_worker():
            record_plays(date, cards)
        stored = _read(_plays_path(date)).get("games") or {}
        if not stored:
            return
        prop_results = _read(_results_path(date))
        for chip in chips:
            away, home = chip.get("away") or {}, chip.get("home") or {}
            plays = stored.get(_game_key(chip.get("sport"), away.get("key"), home.get("key")) or "")
            if not plays:
                continue
            lines = [p for p in plays.values() if p.get("kind") == "game"]
            props = [(pid, p) for pid, p in plays.items() if p.get("kind") != "game"]
            out: dict[str, Any] = {"total": len(plays), "lines": len(lines), "props": len(props)}
            if chip.get("state") == "final":
                a, h = _num(away.get("score")), _num(home.get("score"))
                if a is not None and h is not None:
                    out["line_results"] = _tally(
                        _grade_line(p, a, h, home.get("name"), away.get("name")) for p in lines
                    )
                out["prop_results"] = _tally(
                    (prop_results.get(pid) or {}).get("result") if isinstance(prop_results.get(pid), dict) else prop_results.get(pid)
                    for pid, _p in props
                )
            elif chip.get("state") in {"postponed", "cancelled"}:
                out["void"] = True
            chip["plays"] = out
    except Exception:  # noqa: BLE001 -- a results line must never break a chip
        return


def write_pick_results(date: str, records: Iterable[Mapping[str, Any]], *, reports_dir: Path | None = None) -> int:
    """Settlement hook: merge {pick_id: result} for settled Layer 2 records."""
    found = {}
    for record in records or ():
        pid = record.get("pick_id")
        result = str(record.get("result") or "").lower()
        if pid and result in {"win", "loss", "push", "void"}:
            found[str(pid)] = result
    if not found:
        return 0
    path = (reports_dir / "intelligence" / "layer2_pick_results" / f"{date}.json") if reports_dir else _results_path(date)
    with _LOCK:
        current = _read(path)
        current.update(found)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current), encoding="utf-8")
        tmp.replace(path)
    return len(found)
