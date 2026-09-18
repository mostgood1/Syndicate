"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Settles pending syndicate.features.shared.intelligence_evaluation ledger
  records (recommendations shown by intelligence queries) against each
  sport's own already-graded market-accuracy rows, so downstream calibration
  (adjust_confidence/build_reliability_profile) and policy promotion
  (recommendation_engine.compare_policies) receive real settled data instead
  of a permanently-empty ledger.

Constraints:
- State-driven execution
- Avoid redundant computation
- Read-only against each sport's own market-accuracy artifacts; this module
  never recomputes a settlement join that a sport's own module already does.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS
from syndicate.features.shared.graded_outcomes import PLAYER_BOX_ROW_MARKET
from syndicate.features.shared.graded_outcomes import SCORE_ROW_MARKET
from syndicate.features.shared.graded_outcomes import graded_rows_for_date
from syndicate.features.shared.graded_outcomes import is_player_box_row
from syndicate.features.shared.graded_outcomes import is_score_row
from syndicate.features.shared.graded_outcomes import score_row_diagnostics
from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
from syndicate.features.shared.intelligence_evaluation import _canonical_payload
from syndicate.features.shared.intelligence_evaluation import _is_chunked_ledger_path
from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path
from syndicate.features.shared.intelligence_evaluation import _ledger_record_chunk_name
from syndicate.features.shared.intelligence_evaluation import _ledger_record_identity
from syndicate.features.shared.intelligence_evaluation import _load_chunk_index
from syndicate.features.shared.intelligence_evaluation import _record_sport
from syndicate.features.shared.intelligence_evaluation import _slim_record_response_for_persist
from syndicate.features.shared.intelligence_evaluation import _update_evaluation_ledger_record
from syndicate.features.shared.intelligence_evaluation import _utc_now
from syndicate.features.shared.intelligence_evaluation import _write_chunk_index
from syndicate.features.shared.intelligence_evaluation import settle_result
import functools
from syndicate.features.shared.intelligence_evaluation import ledger_index_session
from syndicate.features.shared.settlement_identity import GradedRowIndex
from syndicate.features.shared.settlement_identity import NO_KEY_MATCH_REASONS
from syndicate.features.shared.settlement_identity import find_graded_row
from syndicate.features.shared.settlement_identity import record_identity
from syndicate.features.shared.settlement_identity import record_segment


# "Supported" now means "has a registered grader in graded_outcomes.py",
# not a hardcoded two-sport list. A sport whose grader is still a stub
# (returns []) is correctly supported-but-empty -- settlement's own
# unmatched_no_graded_rows diagnostic already reports that distinctly from
# "sport not recognized at all". See graded_outcomes.py for which sports
# currently have a real grader vs. a documented placeholder.
_SUPPORTED_SPORTS = tuple(sorted(GRADED_OUTCOME_GRADERS.keys()))


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _market_family(value: Any) -> str | None:
    """Bucket a raw market label into a coarse family, mirroring
    intelligence_evaluation._record_market_family's keyword rules, so
    naming variance between the ledger's free-form `market` field and each
    sport's own market-accuracy labels ("totals" vs "total", "ml" vs
    "moneyline") doesn't block an otherwise-correct match.
    """
    market = str(value or "").strip().lower()
    if not market:
        return None
    if any(token in market for token in ("prop", "player", "point", "rebound", "assist", "steal", "block", "shot", "hitter", "pitcher")):
        return "props"
    if any(token in market for token in ("moneyline", "ml", "money line")):
        return "moneyline"
    if any(token in market for token in ("spread", "ats", "spreads")):
        return "spread"
    if any(token in market for token in ("total", "over", "under", "o/u")):
        return "totals"
    return market


def _markets_compatible(record_market: Any, row_market: Any, sport: Any) -> bool:
    """Do these two market labels describe the same market? (#247)

    THE reason 4,560 settlement records were `no_key_match`. The two sides speak
    different vocabularies -- the ledger carries the board's display label
    ("pitcher outs"), the graded row carries the sport's own stat label
    ("outs") -- and `_market_family` resolved them by keyword-sniffing free
    text, which mapped them to `props` and `outs` respectively. Never equal, so
    the gate meant to prevent WRONG matches blocked every RIGHT one:

        _market_family("pitcher outs")       -> "props"
        _market_family("outs")               -> "outs"          -> blocked
        _market_family("batter_total_bases") -> "totals"        -> a player prop
                                                                   filed as a
                                                                   game total

    That second case is the dangerous one: it would have permitted a prop to
    match a game total had their keys overlapped.

    So compare CANONICAL keys when both sides resolve to one -- the same
    `canonical_market_key` the pricing join already uses, which is what makes
    settlement and pricing agree by construction rather than by coincidence.
    Fall back to the coarse family only when canonicalisation cannot answer, and
    allow the match when neither can: an unknown market must not silently veto a
    row that every other signal says is right.
    """
    # Hoisted out of the try: #259's check below reads these, and leaving them
    # scoped to a block that can raise makes a NameError the failure mode of an
    # import problem.
    record_key: str | None = None
    row_key: str | None = None
    try:
        from syndicate.features.shared.market_keys import canonical_market_key

        record_key = canonical_market_key(sport, record_market)
        row_key = canonical_market_key(sport, row_market)
        if record_key and row_key:
            return record_key == row_key
    except Exception:
        pass
    record_family = _market_family(record_market)
    row_family = _market_family(row_market)
    if record_family and row_family:
        return record_family == row_family

    # #259: an ABSENT market is not a compatible one.
    #
    # #247's fallback ("allow when neither side can answer") is right for two
    # UNKNOWN vocabularies -- an unrecognised market must not veto a row every
    # other signal says is right. It is wrong when a side is simply EMPTY.
    # Measured on the real ledger 2026-08-07:
    #
    #     _markets_compatible("", "outs")      -> True
    #     _markets_compatible("", "home_runs") -> True
    #
    # An empty market matched EVERY market, and 127 of 1,384 ledger records
    # (9%) carry one. Combined with the overlapping identity keys #247 itself
    # documents, that is precisely the failure #247 was written to prevent --
    # a record settling against the wrong market -- reintroduced through the
    # empty case rather than the mismatched one.
    #
    # "I don't recognise this market" and "there is no market here" are
    # different states, and only the first deserves the benefit of the doubt.
    #
    # The refusal is narrow on purpose -- it fires only when one side is EMPTY
    # and the other resolves to a REAL canonical market. Everything else keeps
    # #247's benefit of the doubt, and its own tests pin both:
    #
    #   ("", "")                      -> allow. Neither party claims a market,
    #                                    so the gate has no opinion and identity
    #                                    and line decide.
    #   ("some_unknown_market", "")   -> allow. An unrecognised vocabulary must
    #                                    not veto a row every other signal says
    #                                    is right. That is what #247 fixed.
    #   ("", "outs")                  -> REFUSE. `outs` is a known market; the
    #                                    record names none. There is nothing to
    #                                    agree with, so "compatible" is a claim
    #                                    nobody made.
    #
    # Only the third case is new, and it is the one measured on real data:
    # 127 of 1,384 ledger records (9%) carry an empty market, and each matched
    # outs, home_runs, strikeouts and every other market equally.
    record_present = bool(str(record_market or "").strip())
    row_present = bool(str(row_market or "").strip())
    if record_present != row_present:
        known_side = row_key if record_present is False else record_key
        if known_side:
            return False
    return True


# Market values that are not markets. A SURFACE name ("betting card") leaked
# into the market identity field on WNBA pregame-prop rows until 2026-07-22;
# these are matched exactly rather than by pattern, so a real market that
# happens to contain one of these words is unaffected.
_NON_MARKET_LABELS = frozenset({"betting card", "props", "prop", "board", "rank card", "-", "?", "n/a"})


def _is_unsettleable_legacy_record(record: Mapping[str, Any]) -> bool:
    """True when a record's market identity is structurally unusable (#260).

    Not "we failed to match it" -- "there is nothing here that could ever
    match". Two shapes, both pre-fix debris:

      * an EMPTY market. 127 of 1,384 real records, last written 2026-08-01.
      * a SURFACE name where a market should be ("betting card"). 360 records,
        last written 2026-07-22, from WNBA pregame props whose builder
        force-labelled every row with its heading.

    Deliberately conservative: an unrecognised-but-present market is NOT legacy.
    It might be a market we simply have no mapping for yet, and #247's whole
    point is that an unknown market must not be treated as a failure. Only a
    market that is absent, or is a known non-market label, qualifies.
    """
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    raw = record.get("market")
    if not str(raw or "").strip() and isinstance(recommendation, Mapping):
        raw = recommendation.get("market") or recommendation.get("market_label")
    text = str(raw or "").strip().lower()
    if not text:
        return True
    return text in _NON_MARKET_LABELS


def _read_chunk_records(chunk_path: Path) -> list[dict[str, Any]]:
    """Every record in a ledger chunk, streamed.

    #256. This was `read_text()` + `splitlines()` with **no size ceiling of any
    kind** -- a whole-file string plus a list holding every line of it as its
    own string, before a single record was parsed. It is the reader the
    settlement autorun actually uses, and it is why #254 (which streamed seven
    readers in `intelligence_evaluation.py`) had no effect: settlement does not
    call any of them.

    The measurement that makes this concrete: production logged
    `SKIP_OVERSIZED_LEDGER_CHUNK ... bytes=367229260` and `bytes=480112146`
    against a 256,000,000 ceiling on 2026-08-07. Those skip lines come from the
    CEILINGED readers -- so the log was reporting the size of chunks that this
    function was reading whole at the same moment, on the same worker.

    Still returns a full list, because callers index and filter it. The caller
    that mattered (`run_refresh_worker`'s ledger bridge) has been changed to
    hold one date at a time rather than accumulating all 21. Settlement itself
    no longer calls this: it streams `_iter_chunk_records` and keeps only the
    pending recommendations.
    """
    return list(_iter_chunk_records(chunk_path))


def _iter_chunk_records(chunk_path: Path) -> Iterator[dict[str, Any]]:
    """Every record in a ledger chunk, one at a time. A read error ends the
    stream with what was read so far, as `_read_chunk_records` always did."""
    if not chunk_path.exists():
        return
    try:
        with chunk_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield payload
    except Exception:
        return


def _read_ledger_records_for_date(target_ledger_path: Path, date_token: str) -> list[dict[str, Any]]:
    """Read a date's ledger records, honouring the SAME chunked-vs-flat
    decision the write side (`_append_evaluation_ledger_record` /
    `_update_evaluation_ledger_record`) makes via `_is_chunked_ledger_path`.

    Before this, this function always read via `_ledger_chunk_path`
    regardless of path shape -- correct for the production default path
    (which is always chunked), but silently wrong for any other path: a
    custom `ledger_path=` writes FLAT (one file, no date split), so a
    per-date chunk read against it always returns zero rows even when the
    flat file holds real records for that date. That made every settlement
    test/repro against a temp ledger vacuously pass (`todo.md` "OPEN
    2026-08-04 (3)") and would silently break any deployment pointing at a
    non-default ledger path.
    """
    if _is_chunked_ledger_path(target_ledger_path):
        return _read_chunk_records(_ledger_chunk_path(target_ledger_path, date_token))
    records = _read_chunk_records(target_ledger_path)
    return [record for record in records if _ledger_record_chunk_name(record) == date_token]


def _graded_rows_for_date(sport: str, date_str: str) -> list[dict[str, Any]]:
    return graded_rows_for_date(sport, date_str)


def normalize_portfolio_event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    """Make a logged bet joinable against graded rows. #297.

    Lives next to `_evaluation_record_keys` deliberately: it exists only to
    satisfy that extractor, and separating them is how the two drift apart.

    A board row names teams `home_team`/`away_team` and the player
    `player_name`. `_evaluation_record_keys` reads `home`/`away`/`team`/`player`
    (among others). Those never collide, so a bet logged straight from a board
    row contributes NO team or player value to its key set -- and
    `_graded_row_keys` emits only `selection/player/team/home/away/title`, so
    the intersection is empty and the record can never be settled. It logs 200
    and dies silently weeks later, which is #258 returning through a new door.

    Measured on production L2-A rows, 2026-08-09:
        GAME row -> {event_id, market}   <- neither type is EVER emitted by a
                                            graded row: unsettleable, always
        PROP row -> {event_id, market, 'sonia citron'}   <- the player name is
                                            the ONLY viable key

    The join is on normalized VALUES, not key names, so the fix is to place the
    names the grader also carries under the keys the extractor reads. Team and
    player names are the shared vocabulary; `event_id` is not, because the
    graded side has no event identifier at all (its MLB source carries
    `game_pk`, a different namespace entirely -- see #299).

    Deliberately NOT added: anything category-shaped. A market token like `h2h`
    is shared by every row of that type, so adding it would let a record overlap
    a graded row for a DIFFERENT game, pass `_markets_compatible` (same market),
    and skip the line check (h2h has no line) -- a silently WRONG settlement,
    which is worse than no match because it looks identical to a right one.

    Non-destructive: only fills keys that are absent, so a caller that already
    speaks the ledger's vocabulary is left alone.
    """
    out = dict(event)
    recommendation = dict(out.get("recommendation")) if isinstance(out.get("recommendation"), Mapping) else None
    target = recommendation if recommendation is not None else out

    def _fill(key: str, value: Any) -> None:
        text = str(value or "").strip()
        if text and not str(target.get(key) or "").strip():
            target[key] = text

    home = target.get("home") or target.get("home_team") or out.get("home_team")
    away = target.get("away") or target.get("away_team") or out.get("away_team")
    _fill("home", home)
    _fill("away", away)
    _fill("player", target.get("player") or target.get("player_name") or out.get("player_name"))

    # `team` is the side actually backed, which is what a graded row records for
    # a game market. For a prop it is the player's team when known -- absent on
    # every sport's prop rows today (#270), and that absence removes a JOIN key
    # rather than a display field.
    side = str(target.get("side") or out.get("side") or "").strip().lower()
    if side == "home":
        _fill("team", home)
    elif side == "away":
        _fill("team", away)
    _fill("team", target.get("player_team") or out.get("player_team"))

    if recommendation is not None:
        out["recommendation"] = recommendation
    return out


def _evaluation_record_keys(record: Mapping[str, Any]) -> set[str]:
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    keys = {
        _normalize_text(recommendation.get("market") or recommendation.get("market_family")),
        _normalize_text(recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name")),
    }
    for key in ("event_id", "game_id", "player", "player_name", "team", "name", "home", "away"):
        keys.add(_normalize_text(recommendation.get(key)))
    return {item for item in keys if item}


def _graded_row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(row.get("selection")),
        _normalize_text(row.get("player")),
        _normalize_text(row.get("team")),
        _normalize_text(row.get("home")),
        _normalize_text(row.get("away")),
        _normalize_text(row.get("title")),
    }
    return {item for item in keys if item}


def _record_line(record: Mapping[str, Any]) -> float | None:
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    value = recommendation.get("line") or recommendation.get("projected")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def match_graded_row(record: Mapping[str, Any], rows: "GradedRowIndex | Iterable[Mapping[str, Any]]") -> Mapping[str, Any] | None:
    """The graded row this record settles against, or None.

    WP8 (2026-09-08): was a loose "shared normalized token" match -- first row
    whose key set overlapped the record's, whose market agreed and whose line
    agreed. On production it settled 0 of 29,630, because the two sides never
    spelled the same fact the same way (`settlement_identity` has the
    side-by-side). Now joins on ONE identity, in order: same game id, then
    canonical club + side within the same fixture, then the old loose overlap
    as a last resort. `rows` may be a `GradedRowIndex` (built once per sport by
    `settle_ledger_for_date`) or any iterable of rows.
    """
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    sport = _record_sport(record) or str(recommendation.get("sport") or "").strip().lower() or None
    return find_graded_row(record, rows, sport=sport, markets_compatible=_markets_compatible).row


def _american_profit(odds: Any, stake: float = 1.0) -> float | None:
    try:
        value = float(str(odds).replace(",", ""))
    except Exception:
        return None
    if value == 0:
        return None
    if value > 0:
        return round(stake * (value / 100.0), 4)
    return round(stake * (100.0 / abs(value)), 4)


def _pnl_for_settlement(row: Mapping[str, Any], result: str, recommendation: Mapping[str, Any] | None = None) -> float:
    """The row's own pnl, else its odds, else the RECORD's odds.

    The last fallback exists for rows graded from a final score: they carry no
    price of their own, deliberately -- a price on the row would also become the
    record's `closing_price` and zero its CLV. The record's odds are the price it
    was recorded at, which is exactly what the stake returns.
    """
    if row.get("pnl") is not None:
        try:
            return round(float(row.get("pnl")), 4)
        except Exception:
            pass
    if result in {"push", "void"}:
        return 0.0
    odds = row.get("odds")
    if odds is None and isinstance(recommendation, Mapping):
        odds = recommendation.get("odds") if recommendation.get("odds") is not None else recommendation.get("price")
    profit = _american_profit(odds)
    if profit is None:
        return 1.0 if result == "win" else -1.0
    return profit if result == "win" else -1.0


def _with_ledger_index_session(fn):
    """Parse the 10.63MB chunk index ONCE for the whole settlement pass (`#275`).

    A decorator rather than a `with` around the loop, deliberately: the loop body
    is ~100 lines and re-indenting it would bury a one-line semantic change in a
    hundred-line diff on the function that `#256` already had to fix once.

    Why it matters, measured on this module's own diagnostic: the index is
    re-read AND fully re-serialised (`indent=2, sort_keys=True`) once per settled
    record, at **27.4 MB RSS and 0.616 s each**. A ~150-record night is ~3.2 GB
    of IO and 150 repeated 27 MB allocations on a 4 GB worker -- which is `#256`'s
    110 OOM kills over eleven hours. `#256` stopped the loop from repeating; it
    did not remove the cost, and that cost is why this autorun is still off.

    Benchmarked on a 5.98 MB index (production is 10.63 MB, so this understates
    it): 50 records went from **50 reads / 50 writes / 17.15 s** to
    **1 read / 1 write / 0.40 s**.

    A dry run costs nothing here: it never persists, so the session is never
    marked dirty and no write happens on exit.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ledger_path = kwargs.get("ledger_path")
        # Resolved exactly as the function body resolves `target_ledger_path`,
        # because the session is keyed on the index path and a mismatch would
        # silently fall back to per-record IO rather than fail.
        target = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
        with ledger_index_session(target):
            return fn(*args, **kwargs)

    return wrapper


def _date_token(date_value: str) -> str:
    date_token = str(date_value or "").strip()[:10]
    if len(date_token) != 10 or date_token[4] != "-" or date_token[7] != "-":
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")
    return date_token


def _unsupported_sport_result(date_token: str, sport_slug: str) -> dict[str, Any]:
    return {
        "ok": True,
        "date": date_token,
        "sport": sport_slug,
        "pending": 0,
        "matched": 0,
        "settled": 0,
        "unmatched": 0,
        "note": f"sport '{sport_slug}' is not yet supported by evaluation_settlement",
    }


@_with_ledger_index_session
def settle_ledger_for_date(
    date_value: str,
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return _settle_date_for_sports(date_value, sports=[sport], ledger_path=ledger_path, dry_run=dry_run)[0]


class _ScopeRecords:
    """One sport scope's view of a date chunk: counts, and the pending records
    themselves (the only records settlement holds)."""

    __slots__ = ("recommendations", "already_resolved", "pending")

    def __init__(self) -> None:
        self.recommendations = 0
        self.already_resolved = 0
        self.pending: list[dict[str, Any]] = []


def _read_date_for_scopes(
    target_ledger_path: Path, date_token: str, scopes: Sequence[str | None]
) -> tuple[int, dict[str | None, _ScopeRecords]]:
    """ONE streamed read of a date's records for every sport scope at once.

    Replaces a whole-chunk read PER SPORT. Measured 2026-09-17: chunks run
    45-258 MB, materialise at ~4x file bytes, and the autorun read each date
    once for mlb and again for wnba -- 14 full reads for a 7-day, 2-sport pass,
    multiplying with every sport added. Only PENDING recommendations are kept;
    every other record is counted and dropped as it streams past, so the peak is
    the pending set rather than the chunk.

    Chunked-vs-flat is decided exactly as `_read_ledger_records_for_date`
    decides it, including the flat ledger's per-record date filter.
    """
    chunked = _is_chunked_ledger_path(target_ledger_path)
    source = _ledger_chunk_path(target_ledger_path, date_token) if chunked else target_ledger_path
    views: dict[str | None, _ScopeRecords] = {scope: _ScopeRecords() for scope in scopes}
    total = 0
    for record in _iter_chunk_records(source):
        if not chunked and _ledger_record_chunk_name(record) != date_token:
            continue
        total += 1
        if str(record.get("record_type") or "").strip().lower() != "recommendation":
            continue
        record_sport = _record_sport(record)
        is_pending = str(record.get("result") or "pending").strip().lower() == "pending"
        for scope, view in views.items():
            if scope is not None and record_sport != scope:
                continue
            view.recommendations += 1
            if is_pending:
                view.pending.append(record)
            else:
                view.already_resolved += 1
    return total, views


class _GradedCache:
    """Graded rows and their index, built once per sport for the whole date
    pass and shared by every scope that needs that sport."""

    def __init__(self, date_token: str) -> None:
        self.date_token = date_token
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.index: dict[str, GradedRowIndex] = {}
        self.family_counts: dict[str, dict[str, int]] = {}

    def rows_for(self, sport: str) -> list[dict[str, Any]]:
        if sport not in self.rows:
            self.rows[sport] = _graded_rows_for_date(sport, self.date_token)
        return self.rows[sport]

    def index_for(self, sport: str) -> GradedRowIndex:
        if sport not in self.index:
            self.index[sport] = GradedRowIndex(self.rows_for(sport))
        return self.index[sport]

    def families_for(self, sport: str) -> dict[str, int]:
        if sport not in self.family_counts:
            self.family_counts[sport] = _graded_row_family_counts(self.rows_for(sport))
        return self.family_counts[sport]


def _graded_row_family_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """What the graded rows actually cover, counted over EVERY row.

    Replaces a sample of the first 25 rows, which were sorted by market and so
    always read `["props"]` -- on a date whose score rows covered every game.
    """
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if is_score_row(row):
            family = f"{SCORE_ROW_MARKET}:{row.get('segment') or 'full'}"
        elif is_player_box_row(row):
            family = PLAYER_BOX_ROW_MARKET
        else:
            family = _market_family(row.get("market")) or "unknown"
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


@_with_ledger_index_session
def _settle_date_for_sports(
    date_value: str,
    *,
    sports: Sequence[str | None],
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Settle one date for every sport scope from ONE read of its chunk, and
    persist every settlement with ONE rewrite per chunk file.

    Results are one dict per entry of `sports`, in order, each identical in
    shape and value to what a separate `settle_ledger_for_date` call per sport
    returned. Scopes are processed in order, and a record an earlier scope
    settled is counted as already resolved by a later overlapping scope --
    exactly what the old re-read would have seen.
    """
    date_token = _date_token(date_value)
    scopes = [str(sport or "").strip().lower() or None for sport in sports]
    results: list[dict[str, Any] | None] = [None] * len(scopes)
    active: list[int] = []
    for position, scope in enumerate(scopes):
        if scope and scope not in _SUPPORTED_SPORTS:
            results[position] = _unsupported_sport_result(date_token, scope)
        else:
            active.append(position)
    if not active:
        return [result for result in results if result is not None]

    target_ledger_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    total_ledger_records, views = _read_date_for_scopes(
        target_ledger_path, date_token, list(dict.fromkeys(scopes[position] for position in active))
    )
    graded = _GradedCache(date_token)
    writes: list[dict[str, Any]] = []
    settled_record_ids: set[int] = set()
    for position in active:
        results[position] = _settle_scope(
            date_token=date_token,
            sport_slug=scopes[position],
            view=views[scopes[position]],
            total_ledger_records=total_ledger_records,
            target_ledger_path=target_ledger_path,
            dry_run=dry_run,
            graded=graded,
            writes=writes,
            settled_record_ids=settled_record_ids,
        )
    if writes and not dry_run:
        _persist_settled_records(target_ledger_path, writes, date_token=date_token)
    return [result for result in results if result is not None]


def _settle_scope(
    *,
    date_token: str,
    sport_slug: str | None,
    view: _ScopeRecords,
    total_ledger_records: int,
    target_ledger_path: Path,
    dry_run: bool,
    graded: _GradedCache,
    writes: list[dict[str, Any]],
    settled_record_ids: set[int],
) -> dict[str, Any]:
    # Visibility-only counters (2026-08-03): "pending" below is necessarily
    # zero on a day this function has already fully settled, which reads
    # identically to "nothing was ever recorded here" from the autorun
    # status file alone -- these disambiguate the two from the web service,
    # which has no other way to see this worker-local ledger chunk.
    #
    # A record an earlier scope in this pass settled is RESOLVED for this one,
    # as a fresh read after that scope's writes would have reported it.
    pending_records = [record for record in view.pending if id(record) not in settled_record_ids]
    already_resolved_count = view.already_resolved + (len(view.pending) - len(pending_records))

    # Sports this scope asked a grader about, in first-use order.
    graded_sports: list[str] = []
    matched = 0
    settled = 0
    unmatched = 0
    # Diagnostic breakdown (2026-08-04): "unmatched" alone conflates three
    # structurally different failures -- an unsupported/missing sport label,
    # a sport with zero graded rows for the date (games not yet finalized
    # upstream), and a real key-mismatch inside match_graded_row. Production
    # showed pending=35/matched=0/unmatched=35 with no way to tell which of
    # the three that was, so this disambiguates it without needing a second
    # deploy-and-wait cycle to find out. Bounded sample only -- never a full
    # record dump.
    unmatched_unsupported_sport = 0
    unmatched_no_graded_rows = 0
    unmatched_no_key_match = 0
    # WP8: WHY a key match failed, because the counters are the only
    # production instrument for this join. `team_unresolved` -- the record's
    # club token is not in the sport's alias map; `selection_unmapped` -- its
    # selection text names neither a side nor a club; `game_absent` -- no
    # graded row carries the record's game id; `market_not_graded` -- the game
    # IS graded but no row settles this market/segment/line/side (these two
    # replaced `game_not_graded` 2026-09-17, which counted both);
    # `game_id_absent` -- the record carries no game id and the club path
    # found nothing either. The parent counter is unchanged and is the sum.
    unmatched_no_key_match_reasons: dict[str, int] = {reason: 0 for reason in NO_KEY_MATCH_REASONS}
    # Why `market_not_graded` fired (`MatchOutcome.detail`): a prop the card
    # did not grade, a game with no final score on disk, a refused line, ...
    unmatched_market_not_graded_detail: dict[str, int] = {}
    # Which join phase settled each record; `game_score` = from the final score.
    matched_by_phase: dict[str, int] = {}
    unmatched_bad_result = 0
    # #260: records that CANNOT settle because their market identity was
    # malformed at write time. Counted separately so `settled` is measured
    # against an ACHIEVABLE denominator.
    unsettleable_legacy = 0
    unmatched_samples: list[dict[str, Any]] = []
    _MAX_SAMPLES = 5
    # Shared across every settled record in this call so repeated closes for
    # the same sport/shard don't each re-read the odds-history shard payload
    # from disk -- same pattern (and same documented cost motivation) as the
    # odds_payload_cache in recommendation_engine.filter_candidates/rank_recommendations.
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

    for record in pending_records:
        # #260: classify structurally-unsettleable records BEFORE anything else,
        # so they leave the achievable denominator instead of masquerading as a
        # matching failure.
        #
        # Measured on the real ledger 2026-08-07: 487 of 1,384 records (35%)
        # carry a market that cannot resolve -- 360 say "betting card" (a
        # SURFACE name that leaked into the market field) and 127 are empty.
        # Both are PRE-FIX debris: the last "betting card" record was written
        # 2026-07-22 and the last empty one 2026-08-01, and every record since
        # carries a real market. The producer is already fixed; these can never
        # settle no matter how correct the gate is.
        #
        # Left in `unmatched` they permanently depress the settled rate and make
        # a working settlement look broken -- which is the "count without a
        # denominator" error this codebase has now paid for repeatedly. They are
        # NOT deleted: they are real history, just not settleable history.
        if _is_unsettleable_legacy_record(record):
            unmatched += 1
            unsettleable_legacy += 1
            continue
        record_sport = _record_sport(record) or sport_slug
        if not record_sport or record_sport not in _SUPPORTED_SPORTS:
            unmatched += 1
            unmatched_unsupported_sport += 1
            continue
        if record_sport not in graded_sports:
            graded_sports.append(record_sport)
        candidate_rows = graded.rows_for(record_sport)
        if not candidate_rows:
            unmatched += 1
            unmatched_no_graded_rows += 1
            continue
        sport_index = graded.index_for(record_sport)
        outcome = find_graded_row(record, sport_index, sport=record_sport, markets_compatible=_markets_compatible)
        row = outcome.row
        if row is None:
            unmatched += 1
            unmatched_no_key_match += 1
            reason_token = str(outcome.reason or NO_KEY_MATCH_REASONS[-1])
            unmatched_no_key_match_reasons[reason_token] = unmatched_no_key_match_reasons.get(reason_token, 0) + 1
            if outcome.detail:
                unmatched_market_not_graded_detail[outcome.detail] = unmatched_market_not_graded_detail.get(outcome.detail, 0) + 1
            if len(unmatched_samples) < _MAX_SAMPLES:
                recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
                family_counts = graded.families_for(record_sport)
                unmatched_samples.append(
                    {
                        "sport": record_sport,
                        "reason": f"no_key_match:{reason_token}",
                        "detail": outcome.detail,
                        "record_keys": sorted(_evaluation_record_keys(record)),
                        "record_identity": record_identity(record, sport=record_sport).summary(),
                        "record_market_family": _market_family(recommendation.get("market") or recommendation.get("market_family")),
                        "record_segment": record_segment(record),
                        "record_line": _record_line(record),
                        "graded_rows_available": len(candidate_rows),
                        # DEPRECATED name, kept one release: this has always
                        # counted GAMES (`len(by_game_id)`), never rows.
                        "graded_rows_with_game_id": sport_index.games_indexed,
                        "graded_games_indexed": sport_index.games_indexed,
                        "graded_rows_carrying_game_id": sport_index.rows_with_game_id,
                        # Every family present across ALL rows (was: the first
                        # 25 rows sorted by market, which always read ["props"]).
                        "graded_row_market_families_sample": sorted(family_counts),
                        "graded_row_market_family_counts": family_counts,
                    }
                )
            continue
        matched_by_phase[str(outcome.phase)] = matched_by_phase.get(str(outcome.phase), 0) + 1
        matched += 1
        result = str(row.get("result") or "").strip().lower()
        if result not in {"win", "loss", "push", "void"}:
            unmatched += 1
            unmatched_bad_result += 1
            matched -= 1
            continue
        if dry_run:
            settled += 1
            continue
        recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
        # The graded row's own price is a fallback, not the market close --
        # it's whatever the sport's own accuracy module happened to record,
        # which is frequently the SAME price the bet was taken at (since both
        # are commonly sourced from the same pregame snapshot), making price
        # CLV silently ~0 for nearly every settled row (plan doc "P6",
        # 2026-08-03). odds_refresh_tracking.py stamps a real closing_line/
        # closing_price on market_state at the actual pregame->live
        # transition -- prefer that when it's available. Only trust it when
        # build_market_history_view found real history (history_points > 0);
        # its own no-history fallback returns the RECOMMENDATION's own
        # opening line/price relabeled as "closing", which would make CLV
        # compute as a fake zero instead of correctly staying unmeasured.
        closing_line = row.get("line")
        closing_price = row.get("closing_price") or row.get("price") or row.get("odds")
        try:
            from syndicate.features.shared.odds_lifecycle import build_market_history_view

            market_history = build_market_history_view(recommendation, sport=record_sport, payload_cache=odds_payload_cache)
            if int(market_history.get("history_points") or 0) > 0:
                stamped_closing_price = market_history.get("closing_price")
                stamped_closing_line = market_history.get("closing_line")
                if stamped_closing_price is not None:
                    closing_price = stamped_closing_price
                if stamped_closing_line is not None:
                    closing_line = stamped_closing_line
        except Exception:
            pass
        # NOT persisted here. Persisting one record rewrote its whole chunk
        # (`_replace_ledger_line` streams every line to a temp file), so a
        # 258 MB chunk was rewritten once PER SETTLED RECORD -- the refresh
        # worker's stack dumps during the 09-17 run sat on exactly this call.
        # `_persist_settled_records` applies the whole date in one rewrite.
        writes.append(
            settle_result(
                record=record,
                result=result,
                pnl=_pnl_for_settlement(row, result, recommendation),
                closing_line=closing_line,
                closing_price=closing_price,
                implied_probability=recommendation.get("model_probability") or record.get("implied_probability"),
                persist=False,
                ledger_path=target_ledger_path,
            )
        )
        settled_record_ids.add(id(record))
        settled += 1

    # #260: the achievable denominator. `pending` counts everything in the
    # ledger, including pre-fix records whose market identity was malformed at
    # write time and which can never settle. Reporting `settled / pending`
    # makes a working settlement look broken forever -- a count without a
    # denominator, the error this codebase has paid for repeatedly.
    settleable = max(0, len(pending_records) - unsettleable_legacy)
    return {
        "ok": True,
        "date": date_token,
        "sport": sport_slug,
        "pending": len(pending_records),
        # Records that COULD settle: pending minus the structurally unusable.
        # This is the denominator to quote.
        "settleable": settleable,
        "unsettleable_legacy": unsettleable_legacy,
        "settled_rate_of_settleable": (
            round(100.0 * (settled if not dry_run else 0) / settleable, 1) if settleable else None
        ),
        "matched": matched,
        "settled": settled if not dry_run else 0,
        "would_settle": settled if dry_run else None,
        "unmatched": unmatched,
        "unmatched_unsupported_sport": unmatched_unsupported_sport,
        "unmatched_no_graded_rows": unmatched_no_graded_rows,
        "unmatched_no_key_match": unmatched_no_key_match,
        "unmatched_no_key_match_reasons": unmatched_no_key_match_reasons,
        "unmatched_market_not_graded_detail": dict(sorted(unmatched_market_not_graded_detail.items())),
        "matched_by_phase": dict(sorted(matched_by_phase.items())),
        "unmatched_bad_result": unmatched_bad_result,
        "unmatched_samples": unmatched_samples,
        "graded_rows_available": {sport_key: len(graded.rows_for(sport_key)) for sport_key in graded_sports},
        # DEPRECATED name, kept one release for readers of the status file: it
        # counts GAMES with a graded row, not rows. Read the two below instead.
        "graded_rows_with_game_id": {
            sport_key: graded.index_for(sport_key).games_indexed for sport_key in graded_sports if graded.rows_for(sport_key)
        },
        "graded_games_indexed": {
            sport_key: graded.index_for(sport_key).games_indexed for sport_key in graded_sports if graded.rows_for(sport_key)
        },
        "graded_rows_carrying_game_id": {
            sport_key: graded.index_for(sport_key).rows_with_game_id for sport_key in graded_sports if graded.rows_for(sport_key)
        },
        "graded_row_market_family_counts": {
            sport_key: graded.families_for(sport_key) for sport_key in graded_sports if graded.rows_for(sport_key)
        },
        "score_row_diagnostics": {
            sport_key: diagnostics
            for sport_key in graded_sports
            for diagnostics in (score_row_diagnostics(sport_key, date_token),)
            if diagnostics
        },
        "dry_run": dry_run,
        "total_ledger_records": total_ledger_records,
        "total_recommendation_records": view.recommendations,
        "already_resolved_records": already_resolved_count,
    }


# ---------------------------------------------------------------------------
# Persisting a date's settlements: ONE rewrite per chunk file
# ---------------------------------------------------------------------------


def _replace_ledger_lines(file_path: Path, updates: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Rewrite every record in `updates` (identity -> settled payload) in ONE
    streamed pass; returns the identities replaced.

    The batch form of `intelligence_evaluation._replace_ledger_line`, with the
    same semantics per identity -- the FIRST line carrying it is replaced, the
    record is slimmed and written canonically, and a file with nothing to
    replace is left byte-for-byte untouched. Differences, all for safety:

    * CRASH-SAFE: written to a sibling temp file in the SAME directory, flushed
      and fsynced, then `os.replace`d over the original. A deploy that kills the
      worker mid-rewrite leaves the original chunk intact and a stale temp file
      the next run truncates -- never a half-written chunk.
    * Byte-stream, one line in memory at a time; nothing holds the chunk.
    * APPENDS DURING THE PASS ARE KEPT. The recorder appends to today's chunk
      while settlement runs. Bytes past the offset this pass consumed are copied
      onto the temp file before the replace (a trailing line with no newline yet
      is treated as unconsumed), which the per-record path never did.
    """
    wanted = {identity: payload for identity, payload in updates.items() if str(identity or "").strip()}
    if not wanted or not file_path.exists():
        return set()
    tmp_path = file_path.with_name(file_path.name + ".settle-batch.tmp")
    replaced: set[str] = set()
    try:
        with file_path.open("rb") as source, tmp_path.open("wb") as sink:
            consumed = 0
            for raw in source:
                if not raw.endswith(b"\n"):
                    # A line still being appended. Leave it to the tail copy.
                    break
                consumed += len(raw)
                stripped = raw.strip()
                if not stripped:
                    continue
                if len(replaced) < len(wanted):
                    try:
                        existing = json.loads(stripped)
                    except Exception:
                        existing = None
                    identity = _ledger_record_identity(existing) if isinstance(existing, dict) else None
                    if identity and identity in wanted and identity not in replaced:
                        record = _slim_record_response_for_persist(wanted[identity])
                        sink.write(_canonical_payload(dict(record)).encode("utf-8"))
                        sink.write(b"\n")
                        replaced.add(identity)
                        continue
                sink.write(stripped)
                sink.write(b"\n")
            copied_to = consumed
            if replaced:
                current_size = os.path.getsize(file_path)
                if current_size > consumed:
                    source.seek(consumed)
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        sink.write(block)
                        copied_to += len(block)
            sink.flush()
            os.fsync(sink.fileno())
            # An append can land while the fsync above runs. Re-copy the tail until the
            # source stops growing, so the replace below never drops a line appended
            # after the first tail copy (bounded: a writer that never pauses keeps the
            # last few bytes for the next run's rewrite, which re-reads the file).
            for _ in range(5):
                if not replaced or os.path.getsize(file_path) <= copied_to:
                    break
                source.seek(copied_to)
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    sink.write(block)
                    copied_to += len(block)
                sink.flush()
                os.fsync(sink.fileno())
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    if not replaced:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return set()
    os.replace(tmp_path, file_path)
    return replaced


def _persist_settled_records(target_ledger_path: Path, settled_records: Sequence[Mapping[str, Any]], *, date_token: str) -> dict[str, Any]:
    """Write a date's settlements: one rewrite per chunk file, then the index
    once (inside the caller's `ledger_index_session`).

    Each record goes where `_update_evaluation_ledger_record` would have put it:
    the index entry's path for a chunked ledger, the ledger file itself for a
    flat one. A record the batch cannot place -- no identity, not in the index,
    or not found in its file -- takes that per-record path, including its
    append-if-missing safety net. If the batch RAISES, every record it had not
    already written falls back to the per-record path. Both are logged with
    which path ran, because a silent fallback is a 4-5x runtime regression that
    nothing else would show.
    """
    started = time.monotonic()
    chunked = _is_chunked_ledger_path(target_ledger_path)
    written: set[str] = set()
    per_record: list[Mapping[str, Any]] = []
    files_rewritten = 0
    error_text: str | None = None
    try:
        index = _load_chunk_index(target_ledger_path) if chunked else None
        by_path: dict[Path, dict[str, Mapping[str, Any]]] = {}
        chunk_by_identity: dict[str, str] = {}
        for payload in settled_records:
            identity = _ledger_record_identity(payload)
            if not identity:
                per_record.append(payload)
                continue
            if chunked:
                existing = index.get(identity) if isinstance(index, dict) else None
                if not isinstance(existing, dict):
                    per_record.append(payload)
                    continue
                chunk_name = str(existing.get("chunk") or "") or _ledger_record_chunk_name(payload)
                path_value = existing.get("path")
                path = Path(str(path_value)) if path_value else _ledger_chunk_path(target_ledger_path, chunk_name)
                chunk_by_identity[identity] = chunk_name
            else:
                path = target_ledger_path
            # Later settlements of the same identity win, as sequential
            # per-record writes would have left it.
            by_path.setdefault(path, {})[identity] = payload
        for path, updates in by_path.items():
            replaced = _replace_ledger_lines(path, updates)
            if replaced:
                files_rewritten += 1
            now = _utc_now()
            for identity, payload in updates.items():
                if identity in replaced:
                    written.add(identity)
                    if chunked and isinstance(index, dict):
                        index[identity] = {"chunk": chunk_by_identity[identity], "path": str(path), "updated_at": now}
                else:
                    per_record.append(payload)
        if chunked and written and isinstance(index, dict):
            _write_chunk_index(target_ledger_path, index)
    except Exception as exc:  # noqa: BLE001
        error_text = f"{type(exc).__name__}: {exc}"
        per_record = [payload for payload in settled_records if _ledger_record_identity(payload) not in written]
    for payload in per_record:
        _update_evaluation_ledger_record(target_ledger_path, payload)
    summary = {
        "path": "per_record_fallback" if error_text else "batch",
        "records": len(settled_records),
        "batch_written": len(written),
        "per_record_written": len(per_record),
        "files_rewritten": files_rewritten,
        "elapsed_s": round(time.monotonic() - started, 2),
        "error": error_text,
    }
    print(
        f"[evaluation_settlement] SETTLE_PERSIST date={date_token} path={summary['path']} "
        f"records={summary['records']} batch_written={summary['batch_written']} "
        f"per_record_written={summary['per_record_written']} files_rewritten={files_rewritten} "
        f"elapsed_s={summary['elapsed_s']}" + (f" error={error_text}" if error_text else ""),
        flush=True,
    )
    return summary


def settle_ledger_for_dates(
    dates: Sequence[str],
    *,
    sports: Sequence[str] | None = None,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    sport_list = list(sports) if sports else [None]
    results: list[dict[str, Any]] = []
    for date_value in dates:
        # ONE read of the date's chunk for every sport (was one per sport).
        results.extend(_settle_date_for_sports(date_value, sports=sport_list, ledger_path=ledger_path, dry_run=dry_run))
    return {
        "ok": True,
        "results": results,
        "totals": {
            "pending": sum(int(r.get("pending") or 0) for r in results),
            # #260. Quote `settled_rate_of_settleable`, not settled/pending:
            # pre-fix records with a malformed market identity can never settle
            # and would otherwise cap the rate below 100% forever.
            "settleable": sum(int(r.get("settleable") or 0) for r in results),
            "unsettleable_legacy": sum(int(r.get("unsettleable_legacy") or 0) for r in results),
            "settled_rate_of_settleable": (
                round(
                    100.0
                    * sum(int(r.get("settled") or 0) for r in results)
                    / max(1, sum(int(r.get("settleable") or 0) for r in results)),
                    1,
                )
                if sum(int(r.get("settleable") or 0) for r in results)
                else None
            ),
            "matched": sum(int(r.get("matched") or 0) for r in results),
            "settled": sum(int(r.get("settled") or 0) for r in results),
            "unmatched": sum(int(r.get("unmatched") or 0) for r in results),
            # total_ledger_records is deliberately NOT summed here: it counts
            # every record in a date's whole ledger chunk file regardless of
            # sport, so calling this once per sport for the same date (as the
            # refresh-worker autorun does for mlb+wnba) would double-count it.
            # The other two counters are sport-scoped per call, so summing
            # them across sports/dates is correct.
            "total_recommendation_records": sum(int(r.get("total_recommendation_records") or 0) for r in results),
            "already_resolved_records": sum(int(r.get("already_resolved_records") or 0) for r in results),
            "unmatched_unsupported_sport": sum(int(r.get("unmatched_unsupported_sport") or 0) for r in results),
            "unmatched_no_graded_rows": sum(int(r.get("unmatched_no_graded_rows") or 0) for r in results),
            "unmatched_no_key_match": sum(int(r.get("unmatched_no_key_match") or 0) for r in results),
            "unmatched_no_key_match_reasons": {
                reason: sum(int((r.get("unmatched_no_key_match_reasons") or {}).get(reason) or 0) for r in results)
                for reason in NO_KEY_MATCH_REASONS
            },
            "unmatched_bad_result": sum(int(r.get("unmatched_bad_result") or 0) for r in results),
            # WP8: a sport ABSENT from `graded_rows_available` below is
            # ambiguous -- its grader is only called when a pending record for
            # that sport exists, so "no wnba entry" reads identically for "the
            # grader returned nothing" and "the ledger holds no wnba records".
            # This says which. Every (sport, date) pair, zeros included.
            "pending_by_sport": {
                f"{r.get('sport')}:{r.get('date')}": int(r.get("pending") or 0)
                for r in results
                if r.get("sport")
            },
            # Bounded across the whole call, not per-date/sport, so this
            # never grows with the number of (date, sport) pairs settled.
            "unmatched_samples": [sample for r in results for sample in (r.get("unmatched_samples") or [])][:5],
            "graded_rows_available": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_rows_available")
                for r in results
                if r.get("graded_rows_available")
            },
            # DEPRECATED name (counts games); kept one release.
            "graded_rows_with_game_id": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_rows_with_game_id")
                for r in results
                if r.get("graded_rows_with_game_id")
            },
            "graded_games_indexed": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_games_indexed")
                for r in results
                if r.get("graded_games_indexed")
            },
            "graded_rows_carrying_game_id": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_rows_carrying_game_id")
                for r in results
                if r.get("graded_rows_carrying_game_id")
            },
            "graded_row_market_family_counts": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_row_market_family_counts")
                for r in results
                if r.get("graded_row_market_family_counts")
            },
            "score_row_diagnostics": {
                f"{r.get('sport')}:{r.get('date')}": r.get("score_row_diagnostics")
                for r in results
                if r.get("score_row_diagnostics")
            },
            "unmatched_market_not_graded_detail": _sum_counter_maps(r.get("unmatched_market_not_graded_detail") for r in results),
            "matched_by_phase": _sum_counter_maps(r.get("matched_by_phase") for r in results),
        },
    }


def _sum_counter_maps(maps: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in maps:
        if not isinstance(item, Mapping):
            continue
        for key, value in item.items():
            try:
                out[str(key)] = out.get(str(key), 0) + int(value or 0)
            except (TypeError, ValueError):
                continue
    return dict(sorted(out.items()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Settle pending evaluation-ledger records for a date")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--sport", action="append", default=[], help="Sport slug to scope settlement to (repeat for multiple); default: all supported sports")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path override")
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing settled results")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    sports = list(args.sport) if args.sport else None
    payload = settle_ledger_for_dates([args.date], sports=sports, ledger_path=ledger_path, dry_run=bool(args.dry_run))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
