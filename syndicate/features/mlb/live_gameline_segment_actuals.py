"""MLB segment actuals for the live game-line scorer -- first1 / first3 / first5.

WHY THIS EXISTS. `live_gameline_score.score_ledger_records` takes a
`SegmentActualLookup` for every ledger row whose `segment` is not the full
game, and without one it reports the row UNMEASURED under
`segment_actual_unavailable`. The board build never passed one, so on
2026-09-27 **2,061 of 2,955 MLB ledger records** (every first1/first3/first5
row) were unmeasured -- including the first5 h2h OBSERVATIONS the join has
recorded since 2026-09-08 precisely so they could be "SCORED against outcomes
later" (`live_gameline_join.py`, `REFUSAL_KEY`). Nothing ever scored them.

WHERE THE ACTUAL COMES FROM, AND THE TWO SOURCES THAT DO NOT WORK.

  * `raw/statsapi/feed_live/` -- what `bet_status_mlb` reads. Nothing persists
    current-date feeds: web holds none for September (`live_lens_final_pass.py`
    docstring) and `_fetch_mlb_feed_live` returns a payload without writing it.
    A reader over that tree would score nothing in production and look like a
    quiet night.
  * the live lens' `gameLens[*].actualSegment` -- exact while the game is live,
    but the vendor `_build_game_lens` returns `[]` once a game is FINAL, so
    the lane (and its actual) is gone by the time the game can be scored.

  So this reads StatsAPI's `/api/v1/game/<pk>/linescore` -- a few KB, the
  per-inning runs and nothing else -- ONCE PER FINAL GAME, and caches the
  answer in-process for good: a final linescore never changes. Roughly fifteen
  small calls a day. The board chip path already fetches StatsAPI off the
  request path (`blueprints/home._mlb_feed_live_payload`), so this adds no new
  kind of dependency, and a failed fetch is retried no sooner than
  `_RETRY_AFTER_SECONDS` so an outage cannot turn every build into fifteen
  timeouts.

ONLY FINAL GAMES ARE ANSWERED. A first-five segment can be over while the game
is live, and grading it then would be correct -- but "is inning 5 over" is a
live-state question (`currentInning`, `inningState`) this module would have to
get right on a moving feed. The scorer re-reads the whole day's ledger on every
build, so waiting for the final costs nothing but latency, and it removes the
one way to grade an unfinished segment. A final game whose linescore stops
short of inning N (rain-shortened), or has a half-inning <= N with no `runs`,
answers None -- NEVER the whole-game score, which is the defect
`segment_actuals.py` and `bet_status.segment_refusal` exist to stop.

THE JOIN. First-five ledger rows carry `game_pk=None` and an odds `event_id`
only (09-27: 2,061 of 2,061). The grid row for the same event carries
`game.game_key`, the gamePk, so the event -> game map is built from the grid
the scorer already has in hand.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any, Optional

__all__ = [
    "SEGMENT_INNINGS",
    "MlbSegmentActuals",
    "segment_pairs_from_linescore",
    "event_to_game_pk_from_grid",
    "fetch_linescore",
    "segment_score_blocks",
]

# The segment tokens the MLB ledger writes, and how many innings each spans.
# Same table as `bet_status_mlb._SEGMENT_INNINGS`; restated rather than
# imported because this runs on every board build and `bet_status_*` is
# deliberately kept out of that path (`live_gameline_score.SegmentActualLookup`).
SEGMENT_INNINGS: Mapping[str, int] = {"first1": 1, "first3": 3, "first5": 5}

LINESCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/linescore"
_FETCH_TIMEOUT_SECONDS = 5.0
_RETRY_AFTER_SECONDS = 600.0
# A slate is ~15 games; the cap only matters on a cold cache over a big date,
# and the next build picks up where this one stopped.
_MAX_FETCHES_PER_LOOKUP = 30
# Final games only, a few ints each. Bounded so a long-lived worker cannot grow
# it without limit; ~2 months of MLB fits.
_CACHE_MAX = 1024

# game_pk -> {segment: (away, home)} for FINAL games. A game present with an
# empty dict was read and could not answer any segment (e.g. rain-shortened).
_FINAL_PAIRS: "OrderedDict[str, dict[str, tuple[float, float]]]" = OrderedDict()
_FETCH_FAILED_AT: dict[str, float] = {}


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def segment_pairs_from_linescore(linescore: Any) -> dict[str, tuple[float, float]]:
    """`{segment: (away, home)}` from a FINAL game's linescore.

    Accepts the `/linescore` document itself or a `feed/live` payload (whose
    `liveData.linescore` has the same shape). A segment is answered only when
    every inning 1..N is present with BOTH halves' `runs` -- a missing half is a
    data hole or a game that never got there, and is never read as zero.
    """
    if isinstance(linescore, Mapping) and isinstance(linescore.get("liveData"), Mapping):
        linescore = linescore["liveData"].get("linescore")
    if not isinstance(linescore, Mapping):
        return {}
    innings = linescore.get("innings")
    if not isinstance(innings, list):
        return {}
    by_num: dict[int, tuple[Optional[float], Optional[float]]] = {}
    for position, entry in enumerate(innings, start=1):
        if not isinstance(entry, Mapping):
            continue
        num = _int_or_none(entry.get("num")) or position
        away = (entry.get("away") or {}).get("runs") if isinstance(entry.get("away"), Mapping) else None
        home = (entry.get("home") or {}).get("runs") if isinstance(entry.get("home"), Mapping) else None
        try:
            by_num[num] = (
                float(away) if away is not None else None,
                float(home) if home is not None else None,
            )
        except (TypeError, ValueError):
            by_num[num] = (None, None)
    out: dict[str, tuple[float, float]] = {}
    for segment, needed in SEGMENT_INNINGS.items():
        away_sum = home_sum = 0.0
        complete = True
        for num in range(1, needed + 1):
            pair = by_num.get(num)
            if pair is None or pair[0] is None or pair[1] is None:
                complete = False
                break
            away_sum += pair[0]
            home_sum += pair[1]
        if complete:
            out[segment] = (away_sum, home_sum)
    return out


def fetch_linescore(game_pk: str) -> Optional[Mapping[str, Any]]:
    """StatsAPI's per-game linescore, or None. Never raises."""
    try:
        url = LINESCORE_URL.format(game_pk=int(game_pk))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate)"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload if isinstance(payload, Mapping) else None
    except Exception:
        return None


def event_to_game_pk_from_grid(grid: Any) -> dict[str, str]:
    """odds `event_id` -> gamePk, from the book grid's rows.

    A grid row carries the event at top level and the game under
    `game.game_key` (09-27: every first5/first1/full row). `game_pk` at either
    level is honoured when present.
    """
    out: dict[str, str] = {}
    if not isinstance(grid, (list, tuple)):
        return out
    for row in grid:
        if not isinstance(row, Mapping):
            continue
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        pk = next(
            (str(v).strip() for v in (row.get("game_pk"), game.get("game_pk"), game.get("game_key"))
             if str(v or "").strip().isdigit()),
            "",
        )
        if not pk:
            continue
        for ident in (row.get("event_id"), game.get("event_id")):
            key = str(ident or "").strip()
            if key:
                out[key] = pk
    return out


def _remember(game_pk: str, pairs: dict[str, tuple[float, float]]) -> None:
    _FINAL_PAIRS[game_pk] = pairs
    _FINAL_PAIRS.move_to_end(game_pk)
    while len(_FINAL_PAIRS) > _CACHE_MAX:
        _FINAL_PAIRS.popitem(last=False)


class MlbSegmentActuals:
    """`(game_key, segment) -> (away, home)` -- the scorer's `SegmentActualLookup`.

    `game_key` is whatever the ledger row carries: a gamePk, or an odds
    `event_id` mapped through `event_to_game`. Only games in `final_game_pks`
    are answered. `diagnostics` counts every refusal by reason so an empty
    segment block says WHY it is empty.
    """

    def __init__(
        self,
        *,
        event_to_game: Mapping[str, str],
        final_game_pks: set[str],
        fetch: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
        max_fetches: int = _MAX_FETCHES_PER_LOOKUP,
    ) -> None:
        self._event_to_game = dict(event_to_game)
        self._finals = {str(k) for k in final_game_pks}
        # Resolved at CALL time, not bound as a default: a default argument is
        # evaluated once at import, so patching `fetch_linescore` would never
        # reach a lookup built without an explicit `fetch`.
        self._fetch = fetch
        self._max_fetches = max_fetches
        self.diagnostics: dict[str, Any] = {
            "source": "statsapi_linescore_final_games_only",
            "final_games": len(self._finals),
            "games_answered": 0,
            "fetched": 0,
            "fetch_failed": 0,
            "fetch_deferred_retry_window": 0,
            "fetch_budget_exhausted": 0,
            "refused_by_reason": {},
        }
        self._answered: set[str] = set()

    def _refuse(self, reason: str) -> None:
        table = self.diagnostics["refused_by_reason"]
        table[reason] = table.get(reason, 0) + 1

    def _pairs_for(self, game_pk: str) -> Optional[dict[str, tuple[float, float]]]:
        if game_pk in _FINAL_PAIRS:
            return _FINAL_PAIRS[game_pk]
        failed_at = _FETCH_FAILED_AT.get(game_pk)
        if failed_at is not None and time.monotonic() - failed_at < _RETRY_AFTER_SECONDS:
            self.diagnostics["fetch_deferred_retry_window"] += 1
            return None
        if self.diagnostics["fetched"] + self.diagnostics["fetch_failed"] >= self._max_fetches:
            self.diagnostics["fetch_budget_exhausted"] += 1
            return None
        payload = (self._fetch or fetch_linescore)(game_pk)
        if not isinstance(payload, Mapping):
            self.diagnostics["fetch_failed"] += 1
            _FETCH_FAILED_AT[game_pk] = time.monotonic()
            return None
        self.diagnostics["fetched"] += 1
        _FETCH_FAILED_AT.pop(game_pk, None)
        pairs = segment_pairs_from_linescore(payload)
        _remember(game_pk, pairs)
        return pairs

    def __call__(self, game_key: str, segment: str) -> Optional[tuple[float, float]]:
        seg = str(segment or "").strip().lower()
        if seg not in SEGMENT_INNINGS:
            self._refuse("unsupported_segment")
            return None
        key = str(game_key or "").strip()
        game_pk = self._event_to_game.get(key) or (key if key.isdigit() else "")
        if not game_pk:
            self._refuse("no_game_pk_for_key")
            return None
        if game_pk not in self._finals:
            self._refuse("game_not_final")
            return None
        pairs = self._pairs_for(game_pk)
        if pairs is None:
            self._refuse("linescore_unavailable")
            return None
        pair = pairs.get(seg)
        if pair is None:
            self._refuse("segment_incomplete_in_final_linescore")
            return None
        if game_pk not in self._answered:
            self._answered.add(game_pk)
            self.diagnostics["games_answered"] = len(self._answered)
        return pair


# ---------------------------------------------------------------------------
# THE SEGMENT SCORE BLOCKS the board build attaches as `live_gameline_score.segments`.
# ---------------------------------------------------------------------------

# The per-segment block keeps the cuts a pool reads and drops the quote-age
# breakdowns: first5 observation rows carry no `quote_age_seconds` (09-27: 0 of
# 2,061), so those tables would be empty, and this rides on every board build.
_SEGMENT_BLOCK_KEYS = (
    "records_considered", "games_with_outcome", "unscored", "unmeasured",
    "records_by_market", "segment_actuals_supplied",
    "all_records", "last_per_game", "priceable_only", "fresh_quotes_only",
)
_SEGMENT_PF_CUTS = ("all_records", "last_per_game", "priceable_only", "fresh_quotes_only",
                    "games_with_outcome", "records_by_segment")


def _segment_of(rec: Mapping[str, Any]) -> str:
    return str(rec.get("segment") or "full").strip().lower() or "full"


def segment_score_blocks(
    records: Any,
    finals: Any,
    final_scores: Any,
    *,
    grid: Any = None,
    sport: Any = "mlb",
    segment_actuals: Any = None,
) -> Optional[dict[str, Any]]:
    """Score the ledger's SEGMENT rows, one block per segment. NEVER RAISES.

    None for a sport other than MLB or a ledger with no segment row.

    WHY A SEPARATE CALL AND NOT THE SEGMENT HOOK ON THE HEADLINE ONE. Handing
    `score_ledger_records` a reader for the whole ledger scores a first5 h2h
    row into the SAME `all_records` / `fresh_quotes_only` lists as full-game
    h2h -- a first-five coin with its own base rate (it can push) poured into
    the series `history.jsonl` has pooled since 08-30. That would move the
    headline with nothing about the model changing, which is the exact failure
    the scorer-era split exists for. So the headline call stays byte-identical
    and each segment is scored ALONE here: `by_segment.first5.all_records` is
    first5 h2h only, and its `point_forecast` is first5 totals/spreads only.

    WHAT TO EXPECT IN IT, measured on the 09-27 ledger: first5 h2h carries a
    model and market probability on 223 rows -- the observation the join has
    recorded since 2026-09-08. first5 totals/spreads carry NO model mean, and
    first1/first3 carry no model projection at all, so those stay UNMEASURED by
    name. That is a producer gap, not a scoring one, and this block is where it
    shows.

    `segment_actuals` overrides the StatsAPI reader (tests, and the offline
    re-score, which supplies its own).
    """
    try:
        if str(sport or "").strip().lower() != "mlb" or not isinstance(records, (list, tuple)):
            return None
        by_segment: dict[str, list[Any]] = {}
        for rec in records:
            if isinstance(rec, Mapping):
                seg = _segment_of(rec)
                if seg != "full":
                    by_segment.setdefault(seg, []).append(rec)
        if not by_segment:
            return None
        from syndicate.features.shared.live_gameline_score import score_ledger_records

        lookup = segment_actuals
        lookup_diag: Optional[dict[str, Any]] = None
        if lookup is None:
            # `final_scores` is keyed by whatever identifiers a final grid row
            # carries -- on 09-27 that was the odds `event_id` ONLY (no row had
            # `game_pk`; the gamePk sat in `game.game_key`, which the finals
            # index does not read). So a final game is any all-digit key OR any
            # final event mapped through the grid's event -> game table.
            event_to_game = event_to_game_pk_from_grid(grid)
            final_game_pks = set()
            for key in (final_scores or {}):
                key = str(key)
                if key.isdigit():
                    final_game_pks.add(key)
                elif key in event_to_game:
                    final_game_pks.add(event_to_game[key])
            lookup = MlbSegmentActuals(event_to_game=event_to_game,
                                       final_game_pks=final_game_pks)
            lookup_diag = lookup.diagnostics
        elif isinstance(lookup, MlbSegmentActuals):
            lookup_diag = lookup.diagnostics
        out: dict[str, Any] = {}
        for seg in sorted(by_segment):
            full = score_ledger_records(by_segment[seg], finals, final_scores=final_scores,
                                        segment_actuals=lookup)
            block = {k: full.get(k) for k in _SEGMENT_BLOCK_KEYS}
            pf = full.get("point_forecast") or {}
            block["point_forecast"] = {
                fam: {cut: (pf.get(fam) or {}).get(cut) for cut in _SEGMENT_PF_CUTS}
                for fam in ("totals", "spreads")
            }
            out[seg] = block
        return {"by_segment": out, "lookup": lookup_diag}
    except Exception as exc:  # instrumentation must never break the board
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
