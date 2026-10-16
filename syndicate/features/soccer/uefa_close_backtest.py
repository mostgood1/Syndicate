"""UEFA pricing vs the de-vigged close: the join, the close and the blend (todo #699 Stage 1 step 3).

Research code for the go/no-go gate before any sim is enabled for UCL / UEL / UECL. Nothing in
the sim, the board or a worker imports it. The registration that fixes every rule here (the
60-minute window, the 0.60 / 0.05 name thresholds, Pinnacle-else-average, the blend grid and its
tie rule) is `.syndicate/findings_2026-10-16_uefa_close_backtest.md` section 1, committed before
any close was pulled.

PIECES:
- `join_event`: one ESPN match -> one OddsAPI event in a historical snapshot, by kickoff window and
  normalised-name similarity, in either orientation (OddsAPI's home/away order can differ from
  ESPN's, e.g. at a neutral final).
- `close_1x2`: the event's 1X2 close in ESPN's home/draw/away order. Pinnacle if it quotes all three
  outcomes, else the mean of every book that does, each normalised by
  `market_anchoring.devig_decimal_odds`.
- `blend` / `choose_weight`: the linear pool `w*model + (1-w)*close` and its walk-forward weight.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from syndicate.features.soccer.features.market_anchoring import devig_decimal_odds

WINDOW_MINUTES = 60
MIN_SCORE = 0.60
AMBIGUITY_MARGIN = 0.05
WEIGHT_GRID: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(21))
_DROP = {"fc", "cf", "ac", "sc", "ssc", "as", "afc", "club", "de", "fk", "sk", "nk", "cd", "sv",
         "bk", "if", "rc", "ud", "ca", "sl", "us", "vfb", "vfl", "tsg", "the", "calcio", "1"}


# Letters NFKD does not decompose into a base letter plus an accent.
_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "ł": "l", "Ł": "L",
                           "đ": "d", "Đ": "D", "ı": "i", "þ": "th", "ð": "d"})


def normalise_name(name: str) -> str:
    text = str(name or "").translate(_TRANSLIT).replace(".", "")  # "F.C." -> "FC", then dropped
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _DROP]
    return " ".join(tokens)


def name_score(a: str, b: str) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _ts(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass
class JoinResult:
    event: Mapping[str, Any] | None
    swapped: bool
    score: float
    runner_up: float
    reason: str  # "ok" | "no_candidate" | "low_score" | "ambiguous"


def join_event(home: str, away: str, kickoff: str, events: Sequence[Mapping[str, Any]], *,
               window_minutes: int = WINDOW_MINUTES, min_score: float = MIN_SCORE,
               margin: float = AMBIGUITY_MARGIN) -> JoinResult:
    """The registered join of one ESPN match to one OddsAPI event in a snapshot."""
    ko = _ts(kickoff)
    scored: list[tuple[float, bool, Mapping[str, Any]]] = []
    for ev in events:
        try:
            if abs((_ts(ev["commence_time"]) - ko).total_seconds()) > window_minutes * 60:
                continue
        except (KeyError, ValueError):
            continue
        straight = min(name_score(home, ev.get("home_team", "")), name_score(away, ev.get("away_team", "")))
        swapped = min(name_score(home, ev.get("away_team", "")), name_score(away, ev.get("home_team", "")))
        scored.append((max(straight, swapped), swapped > straight, ev))
    if not scored:
        return JoinResult(None, False, 0.0, 0.0, "no_candidate")
    scored.sort(key=lambda x: -x[0])
    best, runner = scored[0], (scored[1][0] if len(scored) > 1 else 0.0)
    if best[0] < min_score:
        return JoinResult(None, False, best[0], runner, "low_score")
    if runner > best[0] - margin:
        return JoinResult(None, False, best[0], runner, "ambiguous")
    return JoinResult(best[2], best[1], best[0], runner, "ok")


def close_1x2(event: Mapping[str, Any], *, swapped: bool) -> tuple[tuple[float, float, float], str, int] | None:
    """(ESPN home, draw, ESPN away) close, its source ('pinnacle' / 'average') and the book count."""
    home, away = event.get("home_team"), event.get("away_team")
    per_book: dict[str, tuple[float, float, float]] = {}
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            prices = {o.get("name"): float(o.get("price") or 0) for o in market.get("outcomes") or []}
            if not all(prices.get(k, 0) > 1.0 for k in (home, away, "Draw")):
                continue
            fair = devig_decimal_odds({"h": prices[home], "d": prices["Draw"], "a": prices[away]})
            if len(fair) == 3:
                per_book[str(book.get("key"))] = (fair["h"], fair["d"], fair["a"])
    if not per_book:
        return None
    if "pinnacle" in per_book:
        probs, source = per_book["pinnacle"], "pinnacle"
    else:
        n = len(per_book)
        probs = tuple(sum(p[i] for p in per_book.values()) / n for i in range(3))  # type: ignore[assignment]
        source = "average"
    if swapped:
        probs = (probs[2], probs[1], probs[0])
    return probs, source, len(per_book)


def log_loss(probs: Sequence[float], outcome: int) -> float:
    return -math.log(max(float(probs[outcome]), 1e-15))


def blend(model: Sequence[float], close: Sequence[float], w: float) -> tuple[float, float, float]:
    return tuple(w * m + (1.0 - w) * c for m, c in zip(model, close))  # type: ignore[return-value]


def choose_weight(history: Sequence[tuple[Sequence[float], Sequence[float], int]], *,
                  grid: Sequence[float] = WEIGHT_GRID) -> float:
    """The registered w: lowest mean log loss of the pool over `history` (model, close, outcome).

    Ties go to the SMALLER w (closer to the close). Empty history returns 0.0 (the close).
    """
    if not history:
        return 0.0
    best_w, best_ll = 0.0, math.inf
    for w in sorted(grid):
        ll = sum(log_loss(blend(m, c, w), y) for m, c, y in history) / len(history)
        if ll < best_ll - 1e-12:
            best_w, best_ll = w, ll
    return best_w
