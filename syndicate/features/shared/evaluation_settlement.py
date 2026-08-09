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
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS
from syndicate.features.shared.graded_outcomes import graded_rows_for_date
from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
from syndicate.features.shared.intelligence_evaluation import _is_chunked_ledger_path
from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path
from syndicate.features.shared.intelligence_evaluation import _ledger_record_chunk_name
from syndicate.features.shared.intelligence_evaluation import _record_sport
from syndicate.features.shared.intelligence_evaluation import settle_result


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
    hold one date at a time rather than accumulating all 21.
    """
    if not chunk_path.exists():
        return []
    records: list[dict[str, Any]] = []
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
                    records.append(payload)
    except Exception:
        return records
    return records


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


def match_graded_row(record: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Loose "shared normalized token" match, mirroring
    prediction_reconciliation._match_result_row: first row whose key-set
    overlaps the record's and whose market agrees (when both sides have one)
    wins. Not a scored/best-match search -- same known limitation as the
    reconciliation module this mirrors.
    """
    record_keys = _evaluation_record_keys(record)
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    record_market_family = _market_family(recommendation.get("market") or recommendation.get("market_family"))
    record_line = _record_line(record)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_keys = _graded_row_keys(row)
        if record_keys and row_keys and record_keys.isdisjoint(row_keys):
            continue
        if not _markets_compatible(
            recommendation.get("market") or recommendation.get("market_family"),
            row.get("market"),
            record.get("sport") or recommendation.get("sport") or row.get("sport"),
        ):
            continue
        if record_line is not None and row.get("line") is not None:
            try:
                if abs(record_line - float(row.get("line"))) > 1e-6:
                    continue
            except Exception:
                pass
        return row
    return None


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


def _pnl_for_settlement(row: Mapping[str, Any], result: str) -> float:
    if row.get("pnl") is not None:
        try:
            return round(float(row.get("pnl")), 4)
        except Exception:
            pass
    if result in {"push", "void"}:
        return 0.0
    profit = _american_profit(row.get("odds"))
    if profit is None:
        return 1.0 if result == "win" else -1.0
    return profit if result == "win" else -1.0


def settle_ledger_for_date(
    date_value: str,
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    date_token = str(date_value or "").strip()[:10]
    if len(date_token) != 10 or date_token[4] != "-" or date_token[7] != "-":
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")

    sport_slug = str(sport or "").strip().lower() or None
    if sport_slug and sport_slug not in _SUPPORTED_SPORTS:
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

    target_ledger_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    records = _read_ledger_records_for_date(target_ledger_path, date_token)

    # Visibility-only counters (2026-08-03): "pending" below is necessarily
    # zero on a day this function has already fully settled, which reads
    # identically to "nothing was ever recorded here" from the autorun
    # status file alone -- these disambiguate the two from the web service,
    # which has no other way to see this worker-local ledger chunk.
    recommendation_records = [
        record
        for record in records
        if str(record.get("record_type") or "").strip().lower() == "recommendation"
        and (sport_slug is None or _record_sport(record) == sport_slug)
    ]
    already_resolved_records = [
        record for record in recommendation_records if str(record.get("result") or "pending").strip().lower() != "pending"
    ]

    pending_records = [
        record
        for record in records
        if str(record.get("record_type") or "").strip().lower() == "recommendation"
        and str(record.get("result") or "pending").strip().lower() == "pending"
        and (sport_slug is None or _record_sport(record) == sport_slug)
    ]

    graded_rows_by_sport: dict[str, list[dict[str, Any]]] = {}
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
        if record_sport not in graded_rows_by_sport:
            graded_rows_by_sport[record_sport] = _graded_rows_for_date(record_sport, date_token)
        candidate_rows = graded_rows_by_sport[record_sport]
        if not candidate_rows:
            unmatched += 1
            unmatched_no_graded_rows += 1
            continue
        row = match_graded_row(record, candidate_rows)
        if row is None:
            unmatched += 1
            unmatched_no_key_match += 1
            if len(unmatched_samples) < _MAX_SAMPLES:
                recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
                unmatched_samples.append(
                    {
                        "sport": record_sport,
                        "reason": "no_key_match",
                        "record_keys": sorted(_evaluation_record_keys(record)),
                        "record_market_family": _market_family(recommendation.get("market") or recommendation.get("market_family")),
                        "record_line": _record_line(record),
                        "graded_rows_available": len(candidate_rows),
                        "graded_row_market_families_sample": sorted({_market_family(row.get("market")) for row in candidate_rows[:25] if _market_family(row.get("market"))}),
                    }
                )
            continue
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
        settle_result(
            record=record,
            result=result,
            pnl=_pnl_for_settlement(row, result),
            closing_line=closing_line,
            closing_price=closing_price,
            implied_probability=recommendation.get("model_probability") or record.get("implied_probability"),
            persist=True,
            ledger_path=target_ledger_path,
        )
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
        "unmatched_bad_result": unmatched_bad_result,
        "unmatched_samples": unmatched_samples,
        "graded_rows_available": {sport_key: len(rows) for sport_key, rows in graded_rows_by_sport.items()},
        "dry_run": dry_run,
        "total_ledger_records": len(records),
        "total_recommendation_records": len(recommendation_records),
        "already_resolved_records": len(already_resolved_records),
    }


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
        for sport in sport_list:
            results.append(
                settle_ledger_for_date(date_value, sport=sport, ledger_path=ledger_path, dry_run=dry_run)
            )
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
            "unmatched_bad_result": sum(int(r.get("unmatched_bad_result") or 0) for r in results),
            # Bounded across the whole call, not per-date/sport, so this
            # never grows with the number of (date, sport) pairs settled.
            "unmatched_samples": [sample for r in results for sample in (r.get("unmatched_samples") or [])][:5],
            "graded_rows_available": {
                f"{r.get('sport')}:{r.get('date')}": r.get("graded_rows_available")
                for r in results
                if r.get("graded_rows_available")
            },
        },
    }


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
