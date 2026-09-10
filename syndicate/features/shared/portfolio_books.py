"""More than one portfolio. `[user request 2026-09-10, lane portfolio-login-multibook]`

THE PORTFOLIOS, as the dropdown on every portfolio page lists them:
  * `live`  -- Kalshi + Polymarket, the automated buying engine. `/portfolio`.
  * `paper` -- the model's simulated book. `/portfolio/paper`.
  * MANUAL BOOKS, user-created, each at `/portfolio/books/<id>`: bets the user
    placed at other sportsbooks, entered by hand and settled by hand. `manual`
    ("Other books") is the default one and always exists.
The first two are pages that already exist; they are listed, not stored. Only
manual books are records.

A MANUAL BOOK HAS TWO SOURCES AND ONE TABLE.
  1. Hand-entered bets, stored in THIS module's file.
  2. Bets logged from the Betting Board's bet slip (`POST /api/portfolio/bets`),
     which live in `prediction_ledger.json` and carry `portfolio_id`. Rows logged
     before 2026-09-10 have none and belong to the default book, and so does a
     row whose book was deleted -- a bet never becomes invisible.
They are summed together because they are the same kind of thing, wagers the
user placed. Every row still says which source it came from, because they
settle differently: slip bets carry the board's identity and the
refresh-worker's reconciliation grades them; hand-entered bets are graded by the
user. (The user can also settle a slip bet by hand when the board cannot match
it -- first write wins in `record_result`, so there is no race to lose.)

WHY HAND-ENTERED BETS ARE NOT IN `prediction_ledger.json`. One store would be
simpler, and it would be wrong. `prediction_reconciliation._match_result_row`
accepts the FIRST result row that shares ANY key with a bet -- sport alone
qualifies -- whose market matches or is blank. That is tolerable for slip bets,
which carry an event id; for a typed "NFL / moneyline / Chiefs" it is a way to
be graded off somebody else's game. So typed bets live where the worker cannot
see them.

STORAGE: `data_root()/portfolio_books.json` ON WEB'S DISK, deliberately NOT
through `refresh_state_store`'s keyvalue routing. Only web reads or writes it,
so nothing has to cross a service boundary -- and the shared Redis is a 256MB
instance measured at 96% with LRU eviction, where a user's hand-entered history
could vanish with no error. Web's disk persists across deploys, and a Render
service with a disk runs one instance. It does run TWO gunicorn workers
(`WEB_CONCURRENCY=2`), so every read-modify-write holds an exclusive `flock`
and replaces the file atomically. An UNREADABLE file is refused, never treated
as empty: a mutation that read a corrupt store as blank would write a blank one
over the user's history and report success.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from syndicate.features.shared.ledger_bridge import _american_profit as american_profit
from syndicate.features.shared.refresh_state_store import data_root

SCHEMA_VERSION = 1
DEFAULT_BOOK_ID = "manual"
DEFAULT_BOOK_NAME = "Other books"
MAX_BOOKS = 25
MAX_BETS = 20_000
MAX_STAKE = 1_000_000.0

BUILTIN_PORTFOLIOS: tuple[dict[str, str], ...] = (
    {"id": "live", "name": "Kalshi + Polymarket", "note": "Automated · real money", "url": "/portfolio"},
    {"id": "paper", "name": "Paper", "note": "Automated · simulated, no money moves", "url": "/portfolio/paper"},
)
# Anything that is, or could become, a sibling path under `/portfolio/`.
_RESERVED_IDS = frozenset({"live", "paper", "new", "books", "bets", "login", "logout", "settings", "limits", "api"})

OUTCOMES = ("win", "loss", "push", "void", "cashout")
OUTCOME_LABELS = {"pending": "Open", "win": "Won", "loss": "Lost", "push": "Push", "void": "Void", "cashout": "Cashed out"}
_LEDGER_DECIDED = {"win", "loss", "push", "void"}

SPORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("nfl", "NFL"),
    ("ncaaf", "NCAAF"),
    ("mlb", "MLB"),
    ("nba", "NBA"),
    ("wnba", "WNBA"),
    ("nhl", "NHL"),
    ("ncaab", "NCAAB"),
    ("soccer", "Soccer"),
    ("multi", "Multi-sport"),
    ("other", "Other"),
)
SPORTSBOOK_SUGGESTIONS = (
    "DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET", "Fanatics", "bet365",
    "BetRivers", "Hard Rock Bet", "Pinnacle", "Circa", "Novig", "ProphetX",
)
MARKET_SUGGESTIONS = ("Moneyline", "Spread", "Total", "Player prop", "Team total", "Parlay", "Future")
_ODDS_HELP = "Use American odds, like -110 or +150."


class BookStoreError(RuntimeError):
    """The store could not be read or written. Never a reason to write a blank one."""


class BookNotFound(LookupError):
    pass


class InputError(ValueError):
    """User input refused, field by field, so a form can say what to fix."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(self.errors.values()))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def central_today() -> str:
    from syndicate.features.shared.timezone import central_today_iso

    return central_today_iso()


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


# ---------------------------------------------------------------- storage


def store_path() -> Path:
    return data_root() / "portfolio_books.json"


def _blank() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "books": [], "bets": []}


def _read_file(path: Path) -> dict[str, Any]:
    """Strict: a MISSING file is an empty store; an UNREADABLE one raises."""
    if not path.exists():
        return _blank()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BookStoreError(f"{path.name} is unreadable: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BookStoreError(f"{path.name} is not a JSON object")
    for key in ("books", "bets"):
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise BookStoreError(f"{path.name}: `{key}` is not a list")
        payload[key] = [dict(item) for item in value if isinstance(item, Mapping)]
    payload.setdefault("schema_version", SCHEMA_VERSION)
    return payload


def _write_file(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+") as handle:
        try:
            import fcntl
        except ImportError:  # a Windows dev box: one process, nothing to serialise against
            yield
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _mutate(apply: Callable[[dict[str, Any]], Any]) -> Any:
    path = store_path()
    with _exclusive(path):
        payload = _read_file(path)
        result = apply(payload)
        payload["schema_version"] = SCHEMA_VERSION
        payload["updated_at"] = _utc_now()
        _write_file(path, payload)
    return result


def read_store() -> tuple[dict[str, Any], str | None]:
    """For DISPLAY: never raises. The error string is shown on the page."""
    try:
        return _read_file(store_path()), None
    except Exception as exc:  # BookStoreError, or data_root() refusing
        print(f"[portfolio_books] BOOK_STORE_UNREADABLE {type(exc).__name__}: {exc}", flush=True)
        return _blank(), f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- books


def _books_from(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    stored = [dict(b) for b in payload.get("books") or [] if str(b.get("id") or "").strip()]
    default = {"id": DEFAULT_BOOK_ID, "name": DEFAULT_BOOK_NAME, "created_at": None}
    for book in stored:
        if book["id"] == DEFAULT_BOOK_ID:
            default.update(book)  # a rename of the default is stored like any other
    default["default"] = True
    others = sorted((b for b in stored if b["id"] != DEFAULT_BOOK_ID), key=lambda b: str(b.get("created_at") or ""))
    for book in others:
        book["default"] = False
    return [default, *others]


def list_books() -> list[dict[str, Any]]:
    payload, _ = read_store()
    return _books_from(payload)


def get_book(book_id: Any) -> dict[str, Any] | None:
    wanted = str(book_id or "").strip()
    return next((book for book in list_books() if book["id"] == wanted), None)


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise InputError({"name": "Give the portfolio a name."})
    if len(name) > 60:
        raise InputError({"name": "Keep the name to 60 characters."})
    return name


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return slug or "book"


def create_book(name: Any) -> dict[str, Any]:
    clean = _clean_name(name)

    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        books = _books_from(payload)
        if len(books) >= MAX_BOOKS:
            raise InputError({"name": f"There can be at most {MAX_BOOKS} manual portfolios."})
        if any(book["name"].lower() == clean.lower() for book in books):
            raise InputError({"name": f"There is already a portfolio called {clean}."})
        taken = {book["id"] for book in books} | _RESERVED_IDS
        base = _slugify(clean)
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        book = {"id": candidate, "name": clean, "created_at": _utc_now()}
        payload["books"] = [*payload["books"], book]
        return {**book, "default": False}

    return _mutate(apply)


def rename_book(book_id: str, name: Any) -> dict[str, Any]:
    clean = _clean_name(name)

    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        books = _books_from(payload)
        target = next((book for book in books if book["id"] == book_id), None)
        if target is None:
            raise BookNotFound(book_id)
        if any(book["name"].lower() == clean.lower() and book["id"] != book_id for book in books):
            raise InputError({"name": f"There is already a portfolio called {clean}."})
        for book in payload["books"]:
            if book.get("id") == book_id:
                book["name"] = clean
                break
        else:  # the default book exists implicitly until its first rename
            payload["books"].append({"id": book_id, "name": clean, "created_at": _utc_now()})
        return {**target, "name": clean}

    return _mutate(apply)


def delete_book(book_id: str) -> None:
    if book_id == DEFAULT_BOOK_ID:
        raise InputError({"book": "The default portfolio can't be deleted. Rename it instead."})
    slip_rows, ledger_error = _slip_rows(book_id)
    if ledger_error:
        raise InputError({"book": "Couldn't confirm the portfolio is empty, so it was not deleted."})

    def apply(payload: dict[str, Any]) -> None:
        if not any(book.get("id") == book_id for book in payload["books"]):
            raise BookNotFound(book_id)
        held = sum(1 for bet in payload["bets"] if bet.get("book_id") == book_id) + len(slip_rows)
        if held:
            raise InputError({"book": f"This portfolio still holds {held} bet{'s' if held != 1 else ''}. Delete them first."})
        payload["books"] = [book for book in payload["books"] if book.get("id") != book_id]

    _mutate(apply)


# ---------------------------------------------------------------- bet input


def parse_american_odds(value: Any) -> float:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        raise InputError({"odds": "Enter the odds. " + _ODDS_HELP})
    if text.lower() in {"ev", "even", "evens"}:
        return 100.0
    # A strict shape, not `float()`: float also takes "nan", "1e3" and, after a
    # stripped "+", "+-110" -- none of which is a price anyone meant.
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
        raise InputError({"odds": _ODDS_HELP})
    odds = float(text)
    # -100..+100 exclusive is not a price in American odds -- almost always a
    # decimal price (1.91) typed into the wrong box. Refused, not converted.
    if -100 < odds < 100:
        raise InputError({"odds": f"{text} isn't American odds. {_ODDS_HELP}"})
    if abs(odds) > 100_000:
        raise InputError({"odds": "Those odds look too large. " + _ODDS_HELP})
    return odds


def _money(value: Any, field: str, *, allow_zero: bool = False) -> float:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        raise InputError({field: "Enter an amount."})
    amount = _f(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None
    if amount is None:
        raise InputError({field: "Enter a dollar amount, like 25 or 25.50."})
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InputError({field: "Must be more than $0." if not allow_zero else "Can't be negative."})
    if amount > MAX_STAKE:
        raise InputError({field: "That's over $1,000,000. Check the amount."})
    return round(amount, 2)


def _date(value: Any, field: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise InputError({field: "Use a date like 2026-09-10."}) from None


def _text(value: Any, field: str, *, required: bool = False, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise InputError({field: "Required."})
    if len(text) > limit:
        raise InputError({field: f"Keep it to {limit} characters."})
    return text


def _sport(value: Any) -> str:
    text = _text(value, "sport", required=True, limit=20).lower()
    return text


def validate_bet(form: Mapping[str, Any]) -> dict[str, Any]:
    """Every field checked, every refusal reported -- not just the first."""
    errors: dict[str, str] = {}

    def take(parse: Callable[[], Any]) -> Any:
        try:
            return parse()
        except InputError as exc:
            errors.update(exc.errors)
            return None

    fields = {
        "placed_on": take(lambda: _date(form.get("placed_on"), "placed_on")) or central_today(),
        "event_date": take(lambda: _date(form.get("event_date"), "event_date")),
        "sportsbook": take(lambda: _text(form.get("sportsbook"), "sportsbook", required=True, limit=40)),
        "sport": take(lambda: _sport(form.get("sport"))),
        "event": take(lambda: _text(form.get("event"), "event", limit=120)),
        "market": take(lambda: _text(form.get("market"), "market", limit=60)),
        "selection": take(lambda: _text(form.get("selection"), "selection", required=True, limit=200)),
        "bet_type": "parlay" if str(form.get("bet_type") or "").strip().lower() == "parlay" else "straight",
        "odds": take(lambda: parse_american_odds(form.get("odds"))),
        "stake": take(lambda: _money(form.get("stake"), "stake")),
        "notes": take(lambda: _text(form.get("notes"), "notes", limit=500)),
    }
    if errors:
        raise InputError(errors)
    return fields


def pnl_for(outcome: str, odds: Any, stake: Any, cashout_amount: Any = None) -> float:
    """P/L for a settled bet. `win` prices off the bet's own American odds with
    the same function the ledger bridge settles slip parlays with -- one formula."""
    wager = _f(stake)
    if wager is None:
        raise InputError({"outcome": "This bet has no stake, so it can't be settled."})
    if outcome == "win":
        profit = american_profit(odds, wager)
        if profit is None:
            raise InputError({"outcome": "This bet has no usable odds, so a win can't be priced."})
        return round(profit, 2)
    if outcome == "loss":
        return round(-wager, 2)
    if outcome in ("push", "void"):
        return 0.0
    if outcome == "cashout":
        return round(_money(cashout_amount, "cashout_amount", allow_zero=True) - wager, 2)
    raise InputError({"outcome": "Pick won, lost, push, void or cashed out."})


def _outcome(value: Any) -> str:
    outcome = str(value or "").strip().lower()
    if outcome not in OUTCOMES:
        raise InputError({"outcome": "Pick won, lost, push, void or cashed out."})
    return outcome


# ---------------------------------------------------------------- hand-entered bets


def _find_bet(payload: Mapping[str, Any], book_id: str, bet_id: str) -> dict[str, Any]:
    for bet in payload.get("bets") or []:
        if bet.get("id") == bet_id:
            if bet.get("book_id") != book_id:
                raise BookNotFound(f"bet {bet_id} is not in {book_id}")
            return bet
    raise BookNotFound(f"bet {bet_id}")


def add_bet(book_id: str, form: Mapping[str, Any]) -> dict[str, Any]:
    fields = validate_bet(form)

    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        if not any(book["id"] == book_id for book in _books_from(payload)):
            raise BookNotFound(book_id)
        if len(payload["bets"]) >= MAX_BETS:
            raise InputError({"book": "The manual store is full."})
        bet = {"id": str(uuid.uuid4()), "book_id": book_id, "created_at": _utc_now(), **fields, "result": None}
        payload["bets"].append(bet)
        return dict(bet)

    return _mutate(apply)


def settle_bet(book_id: str, bet_id: str, outcome: Any, cashout_amount: Any = None) -> dict[str, Any]:
    outcome = _outcome(outcome)

    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        bet = _find_bet(payload, book_id, bet_id)
        pnl = pnl_for(outcome, bet.get("odds"), bet.get("stake"), cashout_amount)
        result: dict[str, Any] = {"outcome": outcome, "pnl": pnl, "settled_at": _utc_now()}
        if outcome == "cashout":
            result["cashout_amount"] = round(pnl + float(bet["stake"]), 2)
        bet["result"] = result
        return dict(bet)

    return _mutate(apply)


def reopen_bet(book_id: str, bet_id: str) -> dict[str, Any]:
    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        bet = _find_bet(payload, book_id, bet_id)
        bet["result"] = None
        return dict(bet)

    return _mutate(apply)


def delete_bet(book_id: str, bet_id: str) -> None:
    def apply(payload: dict[str, Any]) -> None:
        _find_bet(payload, book_id, bet_id)
        payload["bets"] = [bet for bet in payload["bets"] if bet.get("id") != bet_id]

    _mutate(apply)


# ---------------------------------------------------------------- slip-logged bets


def _slip_book_id(prediction: Mapping[str, Any], known_ids: set[str]) -> str:
    wanted = str(prediction.get("portfolio_id") or "").strip()
    return wanted if wanted in known_ids else DEFAULT_BOOK_ID


def _slip_rows(book_id: str, known_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from syndicate.features.portfolio_summary import _is_user_placed_bet
        from syndicate.features.prediction_ledger import load_all_predictions

        predictions = load_all_predictions()
    except Exception as exc:
        print(f"[portfolio_books] SLIP_LEDGER_READ_FAILED {type(exc).__name__}: {exc}", flush=True)
        return [], f"{type(exc).__name__}: {exc}"
    if known_ids is None:
        known_ids = {book["id"] for book in list_books()}
    rows = [
        _slip_row(prediction)
        for prediction in predictions
        if _is_user_placed_bet(prediction) and _slip_book_id(prediction, known_ids) == book_id
    ]
    return rows, None


def _find_slip_prediction(book_id: str, prediction_id: str) -> dict[str, Any]:
    from syndicate.features.portfolio_summary import _is_user_placed_bet
    from syndicate.features.prediction_ledger import load_all_predictions

    known_ids = {book["id"] for book in list_books()}
    for prediction in load_all_predictions():
        if str(prediction.get("id") or "") == prediction_id and _is_user_placed_bet(prediction):
            if _slip_book_id(prediction, known_ids) != book_id:
                raise BookNotFound(f"bet {prediction_id} is not in {book_id}")
            return prediction
    raise BookNotFound(f"bet {prediction_id}")


def settle_slip_bet(book_id: str, prediction_id: str, outcome: Any, cashout_amount: Any = None) -> dict[str, Any]:
    from syndicate.features.prediction_ledger import record_result

    outcome = _outcome(outcome)
    prediction = _find_slip_prediction(book_id, prediction_id)
    existing = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
    if existing and str(existing.get("outcome") or "").strip().lower() in _LEDGER_DECIDED:
        raise InputError({"outcome": "Already settled. Reopen it first."})
    pnl = pnl_for(outcome, prediction.get("odds"), prediction.get("stake"), cashout_amount)
    # The ledger's vocabulary is closed ({win, loss, push, void}) and the
    # refresh-worker re-scans any date holding an outcome outside it, forever.
    # A cash-out is stored by the sign of what it returned.
    if outcome == "cashout":
        outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "push"
    return record_result(prediction_id=prediction_id, outcome=outcome, pnl=pnl)


def reopen_slip_bet(book_id: str, prediction_id: str) -> bool:
    from syndicate.features.prediction_ledger import clear_result

    _find_slip_prediction(book_id, prediction_id)
    return clear_result(prediction_id)


def delete_slip_bet(book_id: str, prediction_id: str) -> bool:
    from syndicate.features.prediction_ledger import delete_prediction

    _find_slip_prediction(book_id, prediction_id)
    return delete_prediction(prediction_id)


# ---------------------------------------------------------------- the view


def _quote_book(quote: Mapping[str, Any]) -> str | None:
    for key in ("book", "bookmaker", "book_key", "sportsbook"):
        value = str(quote.get(key) or "").strip()
        if value:
            return value
    return None


def _manual_row(bet: Mapping[str, Any]) -> dict[str, Any]:
    result = bet.get("result") if isinstance(bet.get("result"), Mapping) else None
    status = str((result or {}).get("outcome") or "").strip().lower() or "pending"
    to_win = american_profit(bet.get("odds"), bet.get("stake"))
    return {
        "id": bet.get("id"),
        "source": "manual",
        "placed_on": bet.get("placed_on"),
        "event_date": bet.get("event_date"),
        "created_at": bet.get("created_at"),
        "sportsbook": bet.get("sportsbook"),
        "sport": bet.get("sport"),
        "event": bet.get("event"),
        "market": bet.get("market"),
        "selection": bet.get("selection"),
        "bet_type": bet.get("bet_type") or "straight",
        "legs": None,
        "odds": _f(bet.get("odds")),
        "stake": _f(bet.get("stake")),
        "to_win": round(to_win, 2) if to_win is not None else None,
        "status": status,
        "status_label": OUTCOME_LABELS.get(status, status),
        "pnl": _f((result or {}).get("pnl")),
        "settled_at": (result or {}).get("settled_at"),
        "cashout_amount": _f((result or {}).get("cashout_amount")),
        "notes": bet.get("notes") or "",
    }


def _slip_row(prediction: Mapping[str, Any]) -> dict[str, Any]:
    result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
    status = str((result or {}).get("outcome") or "").strip().lower() or "pending"
    if status not in _LEDGER_DECIDED:
        status = "pending"
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    quote = prediction.get("quote") if isinstance(prediction.get("quote"), Mapping) else {}
    legs = prediction.get("legs") if isinstance(prediction.get("legs"), list) else None
    timestamp = str(prediction.get("timestamp") or "")
    # The market is shown on its own line under the pick, so the pick carries
    # only what was chosen -- plus the side and line for a prop, where
    # `selection` is the player's name and says nothing about Over/Under.
    if legs:
        selection = f"Parlay ({len(legs)} legs)"
    else:
        selection = str(prediction.get("selection") or "").strip() or "—"
        side_and_line = " ".join(str(part) for part in (features.get("pick"), features.get("line")) if part not in (None, ""))
        if side_and_line:
            selection = f"{selection} · {side_and_line}"
    to_win = american_profit(prediction.get("odds"), prediction.get("stake"))
    return {
        "id": prediction.get("id"),
        "source": "slip",
        "placed_on": timestamp[:10] or None,
        "event_date": str(features.get("game_date") or "")[:10] or None,
        "created_at": timestamp,
        "sportsbook": _quote_book(quote),
        "sport": prediction.get("sport"),
        "event": None,
        "market": prediction.get("market"),
        "selection": selection,
        "bet_type": str(prediction.get("bet_type") or "straight").strip().lower() or "straight",
        "legs": legs,
        "odds": _f(prediction.get("odds")),
        "stake": _f(prediction.get("stake")),
        "to_win": round(to_win, 2) if to_win is not None else None,
        "status": status,
        "status_label": OUTCOME_LABELS.get(status, status),
        "pnl": _f((result or {}).get("pnl")),
        "settled_at": None,
        "cashout_amount": None,
        "notes": "",
        "edge": _f(prediction.get("edge")),
        "clv": _f((result or {}).get("clv")),
    }


def _group(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row.get(field) or "").strip() or "Not recorded"
        bucket = buckets.setdefault(
            label.lower(),
            {"key": label, "bets": 0, "open": 0, "wins": 0, "losses": 0, "pushes": 0, "staked_settled": 0.0, "pnl": 0.0},
        )
        bucket["bets"] += 1
        status = row["status"]
        if status == "pending":
            bucket["open"] += 1
            continue
        bucket["wins"] += status == "win"
        bucket["losses"] += status == "loss"
        bucket["pushes"] += status == "push"
        if status != "void":
            bucket["staked_settled"] += row.get("stake") or 0.0
        bucket["pnl"] += row.get("pnl") or 0.0
    for bucket in buckets.values():
        bucket["staked_settled"] = round(bucket["staked_settled"], 2)
        bucket["pnl"] = round(bucket["pnl"], 2)
        bucket["roi"] = bucket["pnl"] / bucket["staked_settled"] if bucket["staked_settled"] else None
    return sorted(buckets.values(), key=lambda b: (-b["bets"], b["key"].lower()))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """ROI here is settled P/L per dollar settled, VOIDS EXCLUDED from the
    denominator (a void returned the stake; it was never really at risk)."""
    pending = [row for row in rows if row["status"] == "pending"]
    settled = [row for row in rows if row["status"] != "pending"]
    counts = {outcome: sum(1 for row in settled if row["status"] == outcome) for outcome in OUTCOMES}
    decisive = counts["win"] + counts["loss"]
    staked_settled = sum(row.get("stake") or 0.0 for row in settled if row["status"] != "void")
    pnl = sum(row.get("pnl") or 0.0 for row in settled)
    return {
        "total": len(rows),
        "pending_count": len(pending),
        "open_stake": round(sum(row.get("stake") or 0.0 for row in pending), 2),
        "open_to_win": round(sum(row.get("to_win") or 0.0 for row in pending), 2),
        "settled_count": len(settled),
        "counts": counts,
        "win_rate": counts["win"] / decisive if decisive else None,
        "staked_settled": round(staked_settled, 2),
        "total_staked": round(sum(row.get("stake") or 0.0 for row in rows), 2),
        "pnl": round(pnl, 2),
        "roi": pnl / staked_settled if staked_settled else None,
        "by_sportsbook": _group(rows, "sportsbook"),
        "by_sport": _group(rows, "sport"),
    }


def build_book_view(book_id: str, *, limit: int = 1000) -> dict[str, Any]:
    payload, store_error = read_store()
    books = _books_from(payload)
    book = next((b for b in books if b["id"] == book_id), None)
    if book is None:
        raise BookNotFound(book_id)
    manual = [_manual_row(bet) for bet in payload["bets"] if bet.get("book_id") == book_id]
    slip, ledger_error = _slip_rows(book_id, {b["id"] for b in books})
    rows = manual + slip
    rows.sort(key=lambda row: (str(row.get("placed_on") or ""), str(row.get("created_at") or "")), reverse=True)
    return {
        "schema": "portfolio_book_v1",
        "book": book,
        "summary": summarize(rows),
        "rows": rows[:limit],
        "row_count": len(rows),
        "sources": {"manual": len(manual), "slip": len(slip)},
        "store_error": store_error,
        "ledger_error": ledger_error,
    }


def portfolio_nav(active_id: str | None) -> dict[str, Any]:
    payload, store_error = read_store()
    builtin = [dict(item) for item in BUILTIN_PORTFOLIOS]
    manual = [
        {
            "id": book["id"],
            "name": book["name"],
            "note": "Manual · default for slip bets" if book.get("default") else "Manual",
            "url": f"/portfolio/books/{book['id']}",
        }
        for book in _books_from(payload)
    ]
    active = next((item for item in builtin + manual if item["id"] == active_id), None)
    return {
        "active": active or {"id": active_id, "name": "Portfolio", "note": "", "url": "/portfolio"},
        "groups": [
            {"label": "Automated", "entries": builtin},
            {"label": "Manual · other sportsbooks", "entries": manual},
        ],
        "store_error": store_error,
    }


def form_options() -> dict[str, Any]:
    return {
        "sports": SPORT_OPTIONS,
        "sportsbooks": SPORTSBOOK_SUGGESTIONS,
        "markets": MARKET_SUGGESTIONS,
        "today": central_today(),
        "outcomes": OUTCOME_LABELS,
    }


__all__ = [
    "BUILTIN_PORTFOLIOS",
    "BookNotFound",
    "BookStoreError",
    "DEFAULT_BOOK_ID",
    "InputError",
    "add_bet",
    "build_book_view",
    "create_book",
    "delete_bet",
    "delete_book",
    "delete_slip_bet",
    "form_options",
    "get_book",
    "list_books",
    "parse_american_odds",
    "pnl_for",
    "portfolio_nav",
    "rename_book",
    "reopen_bet",
    "reopen_slip_bet",
    "settle_bet",
    "settle_slip_bet",
    "summarize",
]
