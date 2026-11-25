"""The board's own picks and verdicts, per sport and game, for the per-sport pages (todo #861, step 1d).

WHY. The NHL and soccer pages ran their own raw sim, with their own price and their own EV, and headlined it. Measured
on the fleet 2026-11-25 16:10-16:15Z:
  * `/nhl/picks` headlined 12 game lines at 3.1-10.9% "EV" from `recommendations_sim_<date>.csv`; the board suggested
    0 of them;
  * the `/nhl/cards` props pulse headlined 12 props at EV +85% to +328% (goals over 1.5 at +3000..+9000, one book);
    0 Suggested, and the 7 the board carries read EV -4.86 to +1.99 there (`single_book_fair`, `one_sided_fair`);
  * soccer and NHL game tiles ("Best 1X2 edge", "Best playable angles") named only the sim.
So a user saw a different pick, price and EV on each page. This module gives every such page ONE answer: the Layer 2
board's own judgement (`suggested` / `suggested_reasons`, stamped by `layer2_board._stamp_suggested`), its price and
its EV. The page headlines the board's picks and keeps the sim's rows as a labelled view, each with the board's verdict
on the same line.

DISPLAY ONLY. Nothing here places, sizes or settles a bet, and nothing is recomputed: every number is read off the
board's row. The read is `read_layer2_shortlist` -- a plain artifact read, legal on the request path (Ask and the board
API make the same read) -- and only a COMPACT copy of the pregame rows is kept, for CACHE_SECONDS per process, so a
page view costs at most one shortlist parse a minute.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

CACHE_SECONDS = 60.0
_CACHE_MAX_DATES = 6
_CACHE: dict[str, tuple[float, "_Snapshot"]] = {}
_LOCK = threading.Lock()

# The board's spellings of the three game markets, and what each page calls them.
_GAME_MARKET_FAMILY = {
    "h2h": "h2h", "h2h_3_way": "h2h", "ml": "h2h", "moneyline": "h2h",
    "spreads": "spreads", "spread": "spreads", "pl": "spreads", "puck_line": "spreads", "puckline": "spreads",
    "handicap": "spreads",
    "totals": "totals", "total": "totals",
}
_SPREAD_LABEL = {"nhl": "Puck line", "soccer": "Handicap", "mlb": "Run line"}
_PROP_LABEL = {"sog": "Shots on goal", "goals": "Goals", "assists": "Assists", "points": "Points", "saves": "Saves"}


def team_key(name: Any) -> str:
    """Accents, case and punctuation folded away: "Montréal Canadiens" == "Montreal Canadiens", "St. Louis Blues" ==
    "St Louis Blues" (the spelling split that cost every Blues game its live lane, #860)."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def game_key(away: Any, home: Any) -> str:
    return f"{team_key(away)}|{team_key(home)}"


def market_family(market: Any) -> str:
    m = str(market or "").strip().lower()
    return _GAME_MARKET_FAMILY.get(m, m)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN -> None


def _line_key(value: Any) -> float | None:
    x = _num(value)
    return None if x is None else round(x * 2) / 2


def _ct_day(stamp: Any) -> str | None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10] or None
    if moment.tzinfo is None:
        return text[:10]
    return moment.astimezone(ZoneInfo("America/Chicago")).date().isoformat()


def american_text(price: Any) -> str:
    x = _num(price)
    if x is None:
        return "-"
    x = round(x)
    return f"+{x:d}" if x > 0 else f"{x:d}"


@dataclass(frozen=True)
class BoardLine:
    """One pregame board row, as compact as a page needs. Every field is the board's own."""

    sport: str
    kind: str  # "game" | "prop"
    market: str  # the board's market name
    family: str  # h2h / spreads / totals for game lines; the prop market otherwise
    side: str  # the board's side (home / away / draw / over / under / yes / no)
    line: float | None
    segment: str
    player: str
    away: str
    home: str
    commence_time: str
    ct_day: str | None
    book: str
    price: float | None
    fair: float | None
    ev_gross: float | None  # the board's EV column (`ev_pct`), at the best price
    ev_net: float | None  # net of the venue fee (`score_v2.ev_net_pct`), what the Suggested gate reads
    fee: float | None
    suggested: bool
    reasons: tuple[str, ...]
    rank: int  # 1-based position in the shortlist's rows
    score: float | None  # the board's own shortlist score (`score.score`), the number it ranks on
    model_prob: float | None  # the card's Win% (`layer2_row_context.board_model_probability`)
    books_quoting: int | None

    @property
    def game_key(self) -> str:
        return game_key(self.away, self.home)

    @property
    def ev(self) -> float | None:
        """The EV the board judged the pick on: net of fee where the board has it."""
        return self.ev_net if self.ev_net is not None else self.ev_gross

    @property
    def ev_label(self) -> str:
        ev = self.ev
        if ev is None:
            return "EV -"
        net = self.ev_net is not None and self.fee is not None and self.fee > 0
        return f"EV {ev:+.1f}%" + (" net of fee" if net else "")

    @property
    def market_label(self) -> str:
        if self.kind == "prop":
            return _PROP_LABEL.get(self.market.lower(), self.market.replace("_", " ").title())
        if self.family == "h2h":
            return "Moneyline"
        if self.family == "spreads":
            return _SPREAD_LABEL.get(self.sport, "Spread")
        if self.family == "totals":
            return "Total"
        for word in ("corners", "cards"):
            if word in self.market.lower():
                return f"{word.title()} total"
        if "btts" in self.market.lower():
            return "Both teams to score"
        text = self.market.replace("alternate_", "").replace("_", " ").strip()
        return text[:1].upper() + text[1:] if text else "Line"

    @property
    def side_label(self) -> str:
        side = self.side.lower()
        line = self.line
        if self.kind == "prop":
            ln = "" if line is None else f" {line:g}"
            return f"{self.player} {side.title()}{ln} {self.market_label.lower()}".strip()
        team = self.home if side == "home" else self.away if side == "away" else ""
        if self.family == "h2h":
            return team or ("Draw" if side == "draw" else side.title())
        if self.family == "spreads":
            ln = "" if line is None else f" {line:+g}"
            return f"{team or side.title()}{ln}"
        if side in ("yes", "no") and "btts" in self.market.lower():
            return f"Both teams to score: {side.title()}"
        ln = "" if line is None else f" {line:g}"
        unit = next((w for w in ("corners", "cards") if w in self.market.lower()), "")
        return f"{side.title()}{ln} {unit}".strip()

    @property
    def price_text(self) -> str:
        return f"{self.book} {american_text(self.price)}" if self.book else american_text(self.price)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "market": self.market,
            "market_label": self.market_label,
            "side": self.side,
            "side_label": self.side_label,
            "line": self.line,
            "player": self.player or None,
            "away": self.away,
            "home": self.home,
            "game_key": self.game_key,
            "commence_time": self.commence_time,
            "book": self.book,
            "price": self.price,
            "price_text": self.price_text,
            "fair": self.fair,
            "ev": self.ev,
            "ev_gross": self.ev_gross,
            "ev_label": self.ev_label,
            "suggested": self.suggested,
            "reasons": list(self.reasons),
            "rank": self.rank,
            "score": self.score,
            "model_prob": self.model_prob,
            "books_quoting": self.books_quoting,
            "verdict": verdict_text(self),
        }


def _pick_order(line: "BoardLine") -> tuple[float, float, int]:
    return (
        -(line.score if line.score is not None else float("-inf")),
        -(line.ev_gross if line.ev_gross is not None else float("-inf")),
        line.rank,
    )


def _is_pregame(row: Mapping[str, Any]) -> bool:
    return str(row.get("game_state") or "pregame").strip().lower() == "pregame" and not row.get("is_live")


def _model_number(row: Mapping[str, Any]) -> float | None:
    try:
        from syndicate.features.shared.layer2_row_context import board_model_probability

        p = board_model_probability(row)
    except Exception:  # noqa: BLE001 -- a missing model number must never cost the page its picks
        return None
    return float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else None


def compact_row(row: Mapping[str, Any], rank: int) -> BoardLine | None:
    """A board row as a BoardLine; None for a row a page cannot place (no sport, teams or side)."""
    sport = str(row.get("sport") or "").strip().lower()
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    side = str(row.get("side") or "").strip()
    if not (sport and away and home and side):
        return None
    kind = str(row.get("kind") or "").strip().lower() or "game"
    market = str(row.get("market") or "").strip()
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    v2 = row.get("score_v2") if isinstance(row.get("score_v2"), Mapping) else {}
    reasons = row.get("suggested_reasons")
    books = quote.get("books_quoting")
    score = row.get("score") if isinstance(row.get("score"), Mapping) else {}
    return BoardLine(
        sport=sport,
        kind=kind,
        market=market,
        family=market_family(market) if kind == "game" else market.lower(),
        side=side.lower(),
        line=_line_key(row.get("line")),
        segment=str(row.get("segment") or "full").strip().lower() or "full",
        player=str(row.get("player_name") or "").strip(),
        away=away,
        home=home,
        commence_time=str(row.get("commence_time") or ""),
        ct_day=_ct_day(row.get("commence_time")),
        book=str(quote.get("bookmaker") or "").strip(),
        price=_num(quote.get("price")),
        fair=_num(quote.get("fair_probability")),
        ev_gross=_num(row.get("ev_pct")),
        ev_net=_num(v2.get("ev_net_pct")),
        fee=_num(v2.get("fee_per_contract")),
        suggested=row.get("suggested") is True,
        reasons=tuple(str(r) for r in reasons) if isinstance(reasons, list) else (),
        rank=int(rank),
        score=_num(score.get("score")),
        model_prob=_model_number(row),
        books_quoting=int(books) if isinstance(books, int) and not isinstance(books, bool) else None,
    )


@dataclass(frozen=True)
class _Snapshot:
    shortlist_date: str
    written_at: str | None
    lines: tuple[BoardLine, ...]
    min_value_pct: float | None = None  # the shortlist's EV floor at the best price (`min_value_pct`)


def _snapshot_from_payload(shortlist_date: str, payload: Mapping[str, Any] | None) -> _Snapshot | None:
    if not isinstance(payload, Mapping):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    lines: list[BoardLine] = []
    for rank, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or not _is_pregame(row):
            continue
        line = compact_row(row, rank)
        if line is not None:
            lines.append(line)
    return _Snapshot(
        shortlist_date=shortlist_date,
        written_at=str(payload.get("index_written_at") or payload.get("written_at") or "") or None,
        lines=tuple(lines),
        min_value_pct=_num(payload.get("min_value_pct")),
    )


def _default_reader(shortlist_date: str) -> Mapping[str, Any] | None:
    from pipeline.intelligence_state import read_layer2_shortlist

    return read_layer2_shortlist(shortlist_date)


def _central_today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Chicago")).date().isoformat()


def _snapshot(shortlist_date: str, reader: Callable[[str], Mapping[str, Any] | None]) -> _Snapshot | None:
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(shortlist_date)
        if hit is not None and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        snap = _snapshot_from_payload(shortlist_date, reader(shortlist_date))
    except Exception as exc:  # noqa: BLE001 -- the board read must never cost a per-sport page
        print(f"[board_game_picks] READ_FAILED date={shortlist_date} error={type(exc).__name__}: {str(exc)[:160]}",
              flush=True)
        snap = None
    if snap is None:
        return None
    with _LOCK:
        _CACHE[shortlist_date] = (now, snap)
        while len(_CACHE) > _CACHE_MAX_DATES:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]))
    return snap


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


@dataclass(frozen=True)
class SportBoardView:
    """The board's pregame lines for one sport on one Central day."""

    sport: str
    day: str
    ok: bool  # a shortlist was read
    shortlist_date: str | None
    written_at: str | None
    lines: tuple[BoardLine, ...] = ()
    min_value_pct: float | None = None
    _by_game: dict[str, tuple[BoardLine, ...]] = field(default_factory=dict, compare=False, repr=False)
    _games_by_away: dict[str, tuple[str, ...]] = field(default_factory=dict, compare=False, repr=False)
    _games_by_home: dict[str, tuple[str, ...]] = field(default_factory=dict, compare=False, repr=False)

    @property
    def picks(self) -> tuple[BoardLine, ...]:
        """The board's Suggested rows, in the board's own order: its shortlist score, then EV. The same key as Ask's
        headline (`ask_the_syndicate_adapter._board_pick_rank_key`), so the two pages cannot rank the board two ways."""
        return tuple(sorted((line for line in self.lines if line.suggested), key=_pick_order))

    def resolve_game(self, away: Any, home: Any) -> str | None:
        """The board's key for the page's game. The exact pair first; failing that ONE side, when exactly one board
        game that day has that away club or that home club. A club plays once a day, and the page and the board
        spell clubs from different feeds: measured 2026-11-25, 3 of 13 soccer games missed on the pair ("Slavia
        Prague" / "Slavia Praha", "Sporting CP" / "Sporting Lisbon", "Internazionale" / "Inter Milan")."""
        key = game_key(away, home)
        if key in self._by_game:
            return key
        candidates = set(self._games_by_away.get(team_key(away), ())) | set(self._games_by_home.get(team_key(home), ()))
        return next(iter(candidates)) if len(candidates) == 1 else None

    def game_lines(self, away: Any, home: Any) -> tuple[BoardLine, ...]:
        key = self.resolve_game(away, home)
        return self._by_game.get(key, ()) if key else ()

    def game_picks(self, away: Any, home: Any) -> tuple[BoardLine, ...]:
        return tuple(line for line in self.game_lines(away, home) if line.suggested)

    def find_game_line(self, away: Any, home: Any, market: Any, side: str, line: Any = None) -> BoardLine | None:
        """The full-game board row for one market side ("home"/"away"/"draw"/"over"/"under"); `line` must match to
        the half point for spreads and totals."""
        fam = market_family(market)
        want = _line_key(line)
        for row in self.game_lines(away, home):
            if row.kind != "game" or row.family != fam or row.side != side.lower():
                continue
            if row.segment not in ("full", "full_game", "game", ""):
                continue
            if fam in ("spreads", "totals") and want is not None and row.line != want:
                continue
            return row
        return None

    def find_prop(self, player: Any, market: Any, side: Any, line: Any) -> BoardLine | None:
        who, mkt, sd, ln = team_key(player), str(market or "").strip().lower(), str(side or "").strip().lower(), _line_key(line)
        for row in self.lines:
            if row.kind == "prop" and team_key(row.player) == who and row.market.lower() == mkt and row.side == sd \
                    and row.line == ln:
                return row
        return None

    def verdict(self, line: BoardLine | None, away: Any = None, home: Any = None) -> str:
        """`verdict_text` with what this view knows: whether the game is on the board, and the shortlist's floor."""
        on_board = bool(self.game_lines(away, home)) if (away and home) else None
        return verdict_text(line, game_on_board=on_board, floor_pct=self.min_value_pct)

    def as_payload(self, *, limit: int = 12, page_games: Iterable[tuple[Any, Any]] = ()) -> dict[str, Any]:
        """What a page's JS needs: the picks (board order), and each of the PAGE's games keyed by `game_key` of the
        page's own spelling (resolved here, so the script needs no alias logic): its picks and its line count."""
        by_game: dict[str, dict[str, Any]] = {}
        for away, home in page_games:
            lines = self.game_lines(away, home)
            by_game[game_key(away, home)] = {
                "lines": len(lines),
                "picks": [line.as_dict() for line in sorted((x for x in lines if x.suggested), key=_pick_order)],
            }
        return {
            "ok": self.ok,
            "sport": self.sport,
            "day": self.day,
            "shortlist_date": self.shortlist_date,
            "written_at": self.written_at,
            "pregame_lines": len(self.lines),
            "picks_total": len(self.picks),
            "picks": [p.as_dict() for p in self.picks[: max(0, int(limit))]],
            "games": by_game,
        }


def sport_view(
    sport: str,
    day: str | None = None,
    *,
    reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> SportBoardView:
    """The board's pregame lines for `sport` whose game is played on Central day `day` (default today).

    The board's shortlist for a date also carries the next days' games (its horizon), so the day's own shortlist is read
    first and today's is the fallback for a later day nothing has built yet."""
    sp = str(sport or "").strip().lower()
    today = _central_today()
    wanted = str(day or today).strip() or today
    read = reader or _default_reader
    snap = _snapshot(wanted, read)
    if snap is None and wanted != today:
        snap = _snapshot(today, read)
    if snap is None:
        return SportBoardView(sport=sp, day=wanted, ok=False, shortlist_date=None, written_at=None)
    lines = tuple(line for line in snap.lines if line.sport == sp and line.ct_day == wanted)
    by_game: dict[str, list[BoardLine]] = {}
    by_away: dict[str, set[str]] = {}
    by_home: dict[str, set[str]] = {}
    for line in lines:
        by_game.setdefault(line.game_key, []).append(line)
        by_away.setdefault(team_key(line.away), set()).add(line.game_key)
        by_home.setdefault(team_key(line.home), set()).add(line.game_key)
    return SportBoardView(
        sport=sp,
        day=wanted,
        ok=True,
        shortlist_date=snap.shortlist_date,
        written_at=snap.written_at,
        lines=lines,
        min_value_pct=snap.min_value_pct,
        _by_game={k: tuple(v) for k, v in by_game.items()},
        _games_by_away={k: tuple(v) for k, v in by_away.items()},
        _games_by_home={k: tuple(v) for k, v in by_home.items()},
    )


def board_tile(view: SportBoardView, away: Any, home: Any) -> dict[str, str]:
    """The FIRST market tile on a game card: the board's pick for this game, or that it has none."""
    if not view.ok:
        return {"label": "Board pick", "title": "Board unavailable",
                "sub": f"No saved board shortlist for {view.day}"}
    lines = view.game_lines(away, home)
    picks = sorted((line for line in lines if line.suggested), key=_pick_order)
    if picks:
        top = picks[0]
        more = f" | +{len(picks) - 1} more" if len(picks) > 1 else ""
        return {"label": "Board pick", "title": top.side_label, "sub": f"{top.ev_label} at {top.price_text}{more}"}
    if lines:
        return {"label": "Board pick", "title": "No board pick",
                "sub": f"The board suggests no bet on this game ({len(lines)} pregame lines judged)"}
    return {"label": "Board pick", "title": "No board pick", "sub": "No pregame line on the board for this game"}


def _team_name(game: Mapping[str, Any], side: str) -> str:
    block = game.get(side)
    if isinstance(block, Mapping) and block.get("name"):
        return str(block.get("name"))
    return str(game.get(f"{side}_name") or "")


def _game_day(game: Mapping[str, Any], fallback: str) -> str:
    odds = game.get("odds") if isinstance(game.get("odds"), Mapping) else {}
    stamp = game.get("scheduled_start_utc") or odds.get("commence_time") or ""
    text = str(stamp or "").strip()
    if len(text) == 10:  # a bare date is already the slate's day
        return text
    return _ct_day(text) or fallback


def attach_board_picks(context: dict[str, Any], sport: str, *, reader: Callable[[str], Mapping[str, Any] | None] | None = None) -> dict[str, Any]:
    """Put the board's pick on every game card of a shared game-board context (#861 step 1d): a "Board pick" tile
    first in `market_tiles`, and the game's picks under `board_picks`. Web routes only -- the worker builds the same
    contexts for the chips and is left alone. The sim's own tiles stay, after it."""
    games = context.get("games") if isinstance(context.get("games"), list) else []
    fallback_day = str(context.get("date") or "").strip() or None
    views: dict[str, SportBoardView] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        away, home = _team_name(game, "away"), _team_name(game, "home")
        if not (away and home):
            continue
        day = _game_day(game, fallback_day or _central_today())
        view = views.get(day)
        if view is None:
            view = views[day] = sport_view(sport, day, reader=reader)
        tiles = game.get("market_tiles") if isinstance(game.get("market_tiles"), list) else []
        tiles = [t for t in tiles if not (isinstance(t, Mapping) and t.get("label") == "Board pick")]
        game["market_tiles"] = [board_tile(view, away, home), *tiles]
        game["board_picks"] = [
            line.as_dict() for line in sorted((x for x in view.game_lines(away, home) if x.suggested), key=_pick_order)
        ]
    if views:
        context["board_view"] = {
            day: {"ok": v.ok, "written_at": v.written_at, "picks_total": len(v.picks), "pregame_lines": len(v.lines)}
            for day, v in views.items()
        }
    return context


def refusal_text(reasons: Iterable[str]) -> str:
    """The board's refusal reasons in the words the cheat sheet uses (one wording on every page)."""
    from syndicate.features.shared.cheat_sheets import board_refusal_text

    return board_refusal_text(list(reasons))


def verdict_text(line: BoardLine | None, *, game_on_board: bool | None = None, floor_pct: float | None = None) -> str:
    """One sentence: the board's verdict on a line. A line the board does not list is said to be absent, with the
    shortlist's own floor when known: measured 2026-11-25, 11 of the 12 sim game lines on `/nhl/picks` were absent,
    and "not on the board" alone did not say why."""
    if line is None:
        if game_on_board is False:
            return "Board: this game has no pregame line on the board."
        if floor_pct is not None:
            return (f"Board: this line is not on the board, which lists lines at EV {floor_pct:+g}% or better "
                    f"at the best price.")
        return "Board: this line is not on the board."
    where = f"{line.ev_label} at {line.price_text}"
    if line.suggested:
        return f"Board pick: {where}."
    return f"Board: not a pick ({refusal_text(line.reasons)}); {where}."
