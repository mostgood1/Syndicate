"""Build the Layer 2 shortlist from the Layer 1 grid, worker-side.

WHY THIS IS A SEPARATE MODULE. `layer2_board.py` turns a grid into ranked
candidates but does not know where grids come from; `_build_candidate_pool`
knows the slate but should not grow another 60 lines of market plumbing. This is
the join, and keeping it out of `intelligence_state.py` means the OOM-sensitive
function gains one call, not a new subsystem.

ARTIFACT-BASED, NOT REQUEST-BASED. Its output goes into the candidate-pool
payload, which is persisted and read by web via `read_intelligence_board_state`.
Web computes nothing. Beyond CLAUDE.md's rule, there is a Layer-2-specific
reason: a board recomputed per request cannot be settled -- there is no record
of what was recommended at what price, so `settled: 0` would stay 0 structurally.

SCOPED TO SPORTS THAT ARE ACTUALLY ON. All eight sports are never active at
once -- 4 today, 7 at the October peak, 6 in December -- and only sports with a
manifest in this build have a shard worth reading. The caller passes the sports
it already resolved, so this never widens the read set.

MEMORY, already measured (postmortem §1.1d, docs/ai_context/): the cost of a
shard is its FIRST read -- ~6.3x file size, never returned to the OS -- and
repeated reads are free. `_collect_candidates` has already read these same
shards earlier in the same build (via `enrich_prop_rows` -> `quote_ref_for_bet`
-> `read_book_quotes`), so this adds grid/candidate structures on top of an
already-paid read, not a new one. That is why this is safe to run here and would
not have been safe as a separate sweep over sports nobody had read.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


_UNSET = object()


def _quote_age_percentiles(values: list[float]) -> tuple[float, float, float] | None:
    """(p50, p90, max) over a sorted copy, or None when there is nothing to report."""
    if not values:
        return None
    ordered = sorted(values)
    def _at(fraction: float) -> float:
        # Nearest-rank. No interpolation on purpose: these are observation ages
        # in seconds and an interpolated age is not an age anything actually had.
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return ordered[index]
    return (_at(0.5), _at(0.9), ordered[-1])


# `_KEY_FIELDS` positions in `odds_book_quotes._quote_key`'s "|"-joined string.
# The GROUP is every field that identifies the market; bookmaker, selection and
# line are what VARY within it. Mirrors `book_grid._line_group_key` plus the
# `kind` term, and is asserted against the real `_KEY_FIELDS` at call time so a
# reordering there cannot silently mis-slice this.
_QUOTE_KEY_ORDER = ("sport", "kind", "event_id", "bookmaker", "segment", "market", "selection", "player_name", "line")
_QUOTE_GROUP_FIELDS = ("sport", "kind", "event_id", "segment", "market", "player_name")

# NO ABSOLUTE STALENESS THRESHOLD LIVES HERE, and the first two attempts both
# had one. `#569`.
#
# A flat 900s was wrong because sweep cadence is PER SPORT and fixture-aware
# (`#440` Phase 1b): measured 2026-08-26, nfl runs a 28800s interval when its
# next fixture is 26h out, ncaaf 86400s, wnba 7200s. Against a 900s bar every
# one of those reads "frozen" ALWAYS, which made the label a fact about config
# rather than about health -- and produced a false outage report on nfl.
#
# Comparing against the sport's own interval is the obvious repair and is ALSO
# wrong here: `_pregame_sweep_interval_for_tick` is fixture-aware, and the
# decision that produced this sidecar was made on LIVE-ODDS-WORKER with that
# service's fixture data. Recomputing it on refresh-worker can disagree --
# verified locally, where the same call returns 7200 for nfl against
# production's 28800, because the fixture lookup finds nothing here.
#
# So the comparison is to the SIDECAR'S OWN AGE, which needs no interval and no
# cross-service agreement: a row roughly as old as the newest stamp in the file
# was seen at the last sweep and is as fresh as that sport gets, however rarely
# it sweeps. A row MUCH older was skipped by sweeps that demonstrably happened,
# which is the real defect and the only case worth classifying.


def _classify_stale_row(
    row: Mapping[str, Any],
    last_seen: Mapping[str, str],
    now_iso: str,
    sidecar_newest_age: float | None = None,
) -> str:
    """`sidecar_frozen` / `orphaned_line` / `market_gone` for one stale row. `#569`.

    **`sidecar_frozen` IS THE FIRST QUESTION, and it was missing from the first
    version — which produced a WRONG ANSWER in production, not a near miss.**
    Measured 2026-08-26 19:15Z: wnba read `orphaned_line=2 of 3` while its
    sidecar was not being written AT ALL (`ODDS_SWEEP_OUTCOME wrote=False`).

    Why the old test had to fail there: when a sidecar stops being written every
    key freezes, but at STAGGERED moments — whichever instant each was last
    observed before writes stopped. A key frozen 10 minutes before the stop
    looks hours fresher than one frozen 4 hours before it, and a
    "fresher sibling exists" test reads that as supersession. **A staggered
    freeze and a live line move are indistinguishable from sibling stamps
    alone.** The only thing that separates them is whether the FILE is still
    advancing, which is a property of the sidecar and not of any row in it.

    So: if nothing in the whole sidecar is recent, the answer is "we stopped
    looking", and neither of the other two labels may be returned.

    THE DISCRIMINATOR, and it is the whole point of this function. A row whose
    `seen_age` grows at 1.0x wall clock got there one of two ways, and they have
    OPPOSITE fixes:

      orphaned_line  the market is LIVE and still being quoted, but this row's
                     (bookmaker, selection, line) triple was superseded. `line`
                     is in `_KEY_FIELDS`, so a book moving its line MINTS A NEW
                     KEY and the old one can never be observed again --
                     documented as intended at `odds_book_quotes.py:120`.
                     `drop_superseded_lines` is supposed to catch these and did
                     not.  ->  the GRID is serving a superseded line.

      market_gone    NOTHING in the group has been seen recently. The feed
                     stopped quoting this market entirely, so there is no
                     fresher sibling for `drop_superseded_lines` to compare
                     against and nothing drops it.  ->  the FEED stopped, and
                     only the 14-hour ceiling bounds it.

    Decided by asking the STATE FILE, not the grid: the grid has already had
    superseded lines dropped, so the orphan we are looking for may not be in it.
    The state file keeps every key ever observed, which is exactly why it can
    answer this and the grid cannot.
    """
    # FIRST, before anything reads a sibling stamp.
    if sidecar_newest_age is None:
        return "unknown_no_sidecar_age"

    row_quote = row.get("quote")
    row_seen = row_quote.get("quote_seen_age_seconds") if isinstance(row_quote, Mapping) else None
    if not isinstance(row_seen, (int, float)) or isinstance(row_seen, bool):
        return "unknown_no_row_age"
    if float(row_seen) <= sidecar_newest_age * 1.5 + 300.0:
        return "as_fresh_as_sweep"

    try:
        from syndicate.features.shared.odds_book_quotes import _KEY_FIELDS

        if tuple(_KEY_FIELDS) != _QUOTE_KEY_ORDER:
            return "unknown_key_order_changed"
    except Exception:
        return "unknown_no_key_fields"

    want = {f: str(row.get(f) or "") for f in _QUOTE_GROUP_FIELDS}
    idx = {f: _QUOTE_KEY_ORDER.index(f) for f in _QUOTE_GROUP_FIELDS}
    row_line = str(row.get("line") or "")

    freshest_other_line = ""
    for key, stamp in last_seen.items():
        parts = key.split("|")
        if len(parts) != len(_QUOTE_KEY_ORDER):
            continue
        if any(parts[idx[f]] != want[f] for f in _QUOTE_GROUP_FIELDS):
            continue
        if parts[-1] == row_line:
            continue  # same line, different book/selection -- not the orphan test
        if stamp > freshest_other_line:
            freshest_other_line = str(stamp)

    if not freshest_other_line:
        return "market_gone"
    # A sibling line observed materially more recently than this row means the
    # market is live and this row is the orphan. 15 min mirrors
    # `_STALE_ALT_LINE_LAG_SECONDS`, so a "yes" here is a row that guard should
    # have dropped.
    try:
        from datetime import datetime, timezone

        def _dt(v: str):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=timezone.utc) if v else None

        now = _dt(now_iso)
        sib = _dt(freshest_other_line)
        if now is None or sib is None:
            return "unknown_unparsable_stamp"
        sib_age = (now - sib).total_seconds()
    except Exception:
        return "unknown_unparsable_stamp"

    row_age = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    seen = row_age.get("quote_seen_age_seconds") if isinstance(row_age, Mapping) else None
    if not isinstance(seen, (int, float)) or isinstance(seen, bool):
        return "unknown_no_row_age"
    return "orphaned_line" if (float(seen) - sib_age) > 900 else "market_gone"


def _report_stale_row_causes(rows: Any, selected_date: Any, *, per_sport: int = 3) -> None:
    """Attribute the WORST never-refreshing rows to a cause. `#569`.

    Bounded to the `per_sport` worst rows per sport: this reads a per-sport
    state file (MLB's is ~2MB) and the question is about the tail, not the
    distribution. The distribution is already on `QUOTE_AGE_SERVED`.

    Never raises, and every failure mode reports as its own `unknown_*` label
    rather than defaulting into `market_gone` -- a diagnostic that guesses when
    it cannot tell is worse than one that says so, because the guess is what
    gets quoted back.
    """
    try:
        if not isinstance(rows, list) or not rows:
            return
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        worst: dict[str, list[tuple[float, Mapping[str, Any]]]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            quote = row.get("quote")
            if not isinstance(quote, Mapping):
                continue
            seen = quote.get("quote_seen_age_seconds")
            if not isinstance(seen, (int, float)) or isinstance(seen, bool):
                continue
            if float(seen) < 900:
                continue  # only rows a reader would call stale
            slug = str(row.get("sport") or row.get("sport_slug") or "?").strip().lower() or "?"
            worst.setdefault(slug, []).append((float(seen), row))
        if not worst:
            print("[layer2_shortlist] STALE_ROW_CAUSE none_over_900s", flush=True)
            return

        from syndicate.features.shared.odds_book_quotes import read_quote_last_seen

        parts: list[str] = []
        for slug, entries in sorted(worst.items()):
            entries.sort(key=lambda kv: kv[0], reverse=True)
            try:
                last_seen = read_quote_last_seen(slug, str(selected_date or ""))
            except Exception:
                parts.append(f"{slug}:unknown_no_state_file={len(entries)}")
                continue
            if not last_seen:
                parts.append(f"{slug}:unknown_empty_state_file={len(entries)}")
                continue
            # The sidecar's OWN freshness, computed once per sport. Reported on
            # the line whether or not it changes the labels: a reader must be
            # able to see that a sport was judged against a live file.
            sidecar_age: float | None = None
            try:
                newest = max(last_seen.values())
                parsed = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                sidecar_age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
            except Exception:
                sidecar_age = None

            counts: dict[str, int] = {}
            for _age, row in entries[:per_sport]:
                label = _classify_stale_row(row, last_seen, now_iso, sidecar_age)
                counts[label] = counts.get(label, 0) + 1
            age_txt = "unknown" if sidecar_age is None else f"{sidecar_age:.0f}s"
            parts.append(
                f"{slug}[stale={len(entries)} worst={entries[0][0]:.0f}s sidecar={age_txt} "
                + ",".join(f"{k}={v}" for k, v in sorted(counts.items()))
                + "]"
            )
        print("[layer2_shortlist] STALE_ROW_CAUSE " + " ".join(parts), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[layer2_shortlist] STALE_ROW_CAUSE_FAILED {type(exc).__name__}: {exc}", flush=True)


def _report_served_quote_ages(rows: Any) -> None:
    """Report how old the QUOTES on the published board were AT PUBLISH TIME.

    THE QUESTION THIS EXISTS TO ANSWER, asked by syndicate-43 on 2026-08-26 and
    which nothing in this repo could answer: **when the board looks stale, is
    the BOARD stale or is the QUOTE stale?**

    Everything the `board-staleness-visibility` lane measured was artifact
    PUBLICATION time -- `written_at` on the chip artifact, artifact stamps on
    `state_meta`. None of it touches the age of the quote INSIDE the artifact.
    A board republished every 60 seconds carrying twenty-minute-old venue
    quotes reads fresh on every one of those instruments: recent `written_at`,
    recent `published_at`, `is_fresh` true, no stale badge. That failure mode
    was invisible, and it is exactly the one a direct Kalshi/Polymarket feed
    would fix while a publication fix would not.

    **BOTH CLOCKS, REPORTED SEPARATELY, because they answer different questions**
    -- `_row_quote_age_seconds`'s own docstring (`layer2_board.py`, `#370`)
    establishes this with production measurements, and collapsing them here
    would throw away the distinction it was written to draw:

        seen_age   how long since WE LOOKED at this market
        book_age   how long since the PRICE MOVED

    Its 2026-08-11 reading: wnba `book` median 376.2m against `seen` median
    68.5m. A motionless market ages without limit on the book clock while our
    observation of it stays current, so `book_age` alone would read as an
    outage that is not there -- and `seen_age` alone would miss a feed that has
    genuinely stopped.

    **HOW TO READ IT.** These ages are measured at PUBLISH time, so `seen_p50`
    is how old our observation already was at the instant the board shipped.
    Set against the publish cadence (`written_at` age at serve, ~60s):

        seen_p50 small  + board looks stale  -> PUBLICATION. This lane's ground.
        seen_p50 large  + board looks fresh  -> UPSTREAM. The direct-feed case.

    Read-only over rows this function does not own. `layer2_board.py` belongs to
    the OPEN lane `layer2-sim-view-and-live-projection`, so the fields are read
    from the row contract here rather than computed there. Never raises: an
    instrument must not be able to take down the build it measures.
    """
    try:
        if not isinstance(rows, list) or not rows:
            return
        seen: list[float] = []
        book: list[float] = []
        no_clock = 0
        worst_seen_sport: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            quote = row.get("quote")
            if not isinstance(quote, Mapping):
                no_clock += 1
                continue
            got = False
            raw_seen = quote.get("quote_seen_age_seconds")
            if isinstance(raw_seen, (int, float)) and not isinstance(raw_seen, bool):
                seen.append(float(raw_seen))
                got = True
                slug = str(row.get("sport_slug") or row.get("sport") or "?").strip().lower() or "?"
                if float(raw_seen) > worst_seen_sport.get(slug, -1.0):
                    worst_seen_sport[slug] = float(raw_seen)
            raw_book = quote.get("book_age_seconds")
            if isinstance(raw_book, (int, float)) and not isinstance(raw_book, bool):
                book.append(float(raw_book))
                got = True
            if not got:
                no_clock += 1

        seen_stats = _quote_age_percentiles(seen)
        book_stats = _quote_age_percentiles(book)

        def _fmt(label: str, stats: tuple[float, float, float] | None, count: int) -> str:
            if stats is None:
                # ABSENT, never zero. A zero here would read as "our observation
                # is current", which is the opposite of "we have no clock".
                return f"{label}_n={count} {label}_p50=absent {label}_p90=absent {label}_max=absent"
            p50, p90, worst = stats
            return (
                f"{label}_n={count} {label}_p50={p50:.0f} "
                f"{label}_p90={p90:.0f} {label}_max={worst:.0f}"
            )

        worst_by_sport = " ".join(
            f"{slug}={age:.0f}"
            for slug, age in sorted(worst_seen_sport.items(), key=lambda kv: kv[1], reverse=True)
        )
        print(
            "[layer2_shortlist] QUOTE_AGE_SERVED at=publish "
            f"rows={len(rows)} no_clock={no_clock} "
            + _fmt("seen", seen_stats, len(seen)) + " "
            + _fmt("book", book_stats, len(book))
            + (f" worst_seen_by_sport {worst_by_sport}" if worst_by_sport else ""),
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[layer2_shortlist] QUOTE_AGE_SERVED_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def _reprice_grid_from_venues(grid: Any, sport: Any, selected_date: Any) -> dict:
    """Move a sport's grid onto the live venues, and never take the board down.

    Extracted from the enrichment tuple only so the import stays local: a
    `venue_quote_fanin` that is a deploy behind must cost this sport's re-price
    and nothing else. The caller's own try/except would catch the raise, but it
    would record `{"error": "ImportError"}` with no name in it, and "the module
    is missing" and "the venue refused" need different fixes.
    """
    try:
        from syndicate.features.shared.venue_quote_fanin import (
            apply_venue_quotes_to_grid,
        )
    except ImportError as exc:  # pragma: no cover - deploy-skew guard
        return {"supported": False, "error": f"ImportError: {exc}"}
    try:
        return apply_venue_quotes_to_grid(grid, sport, str(selected_date or ""))
    except Exception as exc:  # noqa: BLE001 - a venue failure is not a board failure
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_layer2_shortlist(
    selected_date: str,
    sport_slugs: Iterable[str],
    *,
    max_grid_rows_per_sport: int | None = None,
    horizon_days: Any = _UNSET,
) -> dict[str, Any]:
    """Layer 1 grid -> ranked one-side candidates -> persisted shortlist.

    Never raises. A failure here must not take down the candidate pool: Layer 2
    is additive to a board that already works without it, and the whole point of
    wiring it into this function was to avoid a second heavy path.
    """
    from syndicate.features.shared.layer2_board import build_layer2_rows, select_shortlist

    # LOADED ONCE, BEFORE ANY SPORT IS PROCESSED. See `_movement_from_opening`
    # for why this is not read per row: `#372` stalled the whole build by doing
    # exactly that with a ~20MB shard. This reads one small JSONL of the rows
    # THIS board published today.
    #
    # Read BEFORE `record_openings` appends today's rows, deliberately: movement
    # must compare against the FIRST time we published a row, not against the
    # copy being written this instant.
    # KEYED WITHOUT `line` AND `bookmaker`, AND THAT IS THE WHOLE POINT.
    #
    # `_opening_key` puts BOTH in the key, correctly, because CLV must not
    # collapse home -1.5 and home -2.5, nor two books' prices. But **movement
    # IS the detection of line and book change**, so joining on that key can
    # only ever match rows that did NOT move -- the metric becomes conditioned
    # on the absence of the thing it measures.
    #
    # MEASURED across two artifacts 20 minutes apart, 2026-08-16 21:01 -> 21:21:
    #
    #     stable key (event·market·player·segment·side) matched   20
    #     full key   (+ line + bookmaker)               matched   14
    #        of the 20: line changed 6, book changed 5, either 7
    #
    # So ~a third of matchable rows were dropped, and they were precisely the
    # rows with something to report. It also explains why steam never fired: a
    # sharp move is usually accompanied by a line move or a best-book switch,
    # which breaks the key and erases the evidence of the move.
    #
    # The opening RECORD already carries `line`, `price`, `bookmaker` and
    # `book_prices`, so nothing is lost by keying loosely and reading the
    # detail off the record -- `book_prices` is what still makes the price
    # comparison same-book even when the best book has changed.
    #
    # `_opening_key` itself is NOT changed: it is right for the settlement join
    # it was built for, and this is a different question asked of the same data.
    openings_index: dict[str, Any] = {}
    openings_error: str | None = None
    openings_records = 0
    try:
        from syndicate.features.shared.clv_opening_ledger import load_openings
        from syndicate.features.shared.layer2_board import movement_join_key

        for record in load_openings(selected_date) or []:
            if not isinstance(record, Mapping):
                continue
            openings_records += 1
            key = movement_join_key(record)
            # FIRST WRITE WINS -- the ledger is append-only, so a key recurs and
            # the earliest occurrence is the opening by definition. Doubly so
            # now: under the loose key, later records for the same bet are
            # exactly the moved versions we are measuring against.
            if key and key not in openings_index:
                openings_index[key] = record
    except Exception as exc:
        openings_error = f"{type(exc).__name__}: {exc}"

    # `#563`. PUBLISH THE CHIPS FIRST, BEFORE ANY SPORT IS INGESTED.
    #
    # This block used to sit at the BOTTOM of this function, beside the
    # chip-join telemetry that needs `cards`. Measured 2026-08-25/26: that put
    # the only write of the artifact the WEB serves roughly **21 minutes** after
    # boot -- `-fzb6v` booted 00:45:38Z and printed its first
    # `GAME_CHIPS_PUBLISHED` at 01:06:19Z. Over the same evening refresh-worker
    # took 15 deploys and logged 15 `SIGTERM` shutdowns with a **median uptime
    # of 1202 s (20.0 min)**, five of them under 8 minutes. So the median
    # instance died within a minute of its first publish, and five published
    # nothing at all: the scoreboard the user was looking at had been frozen for
    # ~20 minutes while the worker restarted, rebuilt from zero, and was killed
    # again. `WORKER_SHUTDOWN_KILLED_BOARD_BUILD frame=collect_candidates --
    # this build's work is lost and will restart from zero on the next boot`
    # fired three times saying exactly that.
    #
    # THE CHIPS DO NOT DEPEND ON ANY OF THE WORK THAT FOLLOWS. They are built
    # from the per-sport provider payloads, not from the grid, the candidates or
    # the cards -- so the ~21 minutes they used to wait bought nothing. Moving
    # them here makes the scoreboard survive a kill at minute 19, which is where
    # tonight's kills actually landed.
    #
    # DELIBERATELY NOT MOVING THE JOIN TELEMETRY. `chip_join_coverage` asks
    # whether a CARD can find its chip, so it cannot run before cards exist. It
    # stays at the bottom and reads `_published_chips` from here rather than
    # rebuilding, so the coverage line describes the chips web is actually
    # serving instead of a second, later build of them.
    #
    # WHOLLY GUARDED, as before: a bad slate, a missing league or a slow read
    # must leave the shortlist exactly as it found it.
    _published_chips: list[Any] = []
    try:
        from syndicate.features.shared.game_chip_scoreboard import (
            GAME_CHIP_DEFAULT_SPORTS,
            build_game_chips,
        )

        # `#545`. BUILT FOR THE FULL DEFAULT SPORT LIST, not just the sports on
        # today's board, because this build is also what the WEB SERVES. Scoping
        # it to the board's sports would mean a sport with no rows today loses
        # its scoreboard strip entirely -- and a chip-less strip is
        # indistinguishable from a sport with no games.
        #
        # `sport_slugs` is an Iterable and is consumed downstream, so it is NOT
        # read here: draining a generator to widen a set nobody widened would
        # take the board's sports away from the loop below. The default list is
        # a superset of what the board can carry anyway.
        _chip_sports = sorted(set(GAME_CHIP_DEFAULT_SPORTS))
        _published_chips = build_game_chips(selected_date, _chip_sports) or []
        try:
            from pipeline.intelligence_state import write_game_chips

            _published = write_game_chips(selected_date, _published_chips)
            print(
                f"[layer2_shortlist] GAME_CHIPS_PUBLISHED date={selected_date} "
                f"chips={len(_published_chips)} sports={len(_chip_sports)} "
                f"ok={bool(_published)} stage=pre_ingest",
                flush=True,
            )
        except Exception as _pub_exc:
            # Named, not silent. The web falls back to its own build, so this
            # degrades rather than breaks -- but a permanent failure here means
            # the request-path fan-out never actually went away, which is the
            # whole point of `#545`.
            print(
                f"[layer2_shortlist] GAME_CHIPS_PUBLISH_FAILED date={selected_date} "
                f"error={type(_pub_exc).__name__}: {_pub_exc}",
                flush=True,
            )
    except Exception as _chip_exc:  # pragma: no cover - never costs the board
        print(
            f"[layer2_shortlist] GAME_CHIPS_BUILD_UNAVAILABLE date={selected_date} "
            f"error={type(_chip_exc).__name__}: {_chip_exc}",
            flush=True,
        )

    opportunities: list[dict[str, Any]] = []
    per_sport_stats: dict[str, Any] = {}

    for sport_slug in sport_slugs:
        sport = str(sport_slug or "").strip().lower()
        if not sport:
            continue
        try:
            from syndicate.features.shared.board_enrichment import (
                attach_game_state,
                attach_margin_model,
                attach_projections,
            )

            # THE LIVE JOINS ARE IMPORTED SEPARATELY AND OPTIONALLY.
            #
            # Same cross-file hazard as the card builder below: if
            # `board_enrichment.py` on this worker predates them, naming them in
            # the import block above turns an ImportError into the loss of THIS
            # SPORT'S ENTIRE ENRICHMENT -- game state, projections and margin
            # model all die with it, because they share the try. A missing live
            # tier should cost the live tier and nothing else.
            #
            # They are on every service today (verified 2026-08-16), so this
            # guards a future rollback rather than a present gap. It is here
            # because `c324447d` proved these files do not move together.
            try:
                from syndicate.features.shared.board_enrichment import (
                    attach_live_game_state_from_lens,
                    attach_live_gamelines_for_sport,
                    attach_live_projections_for_sport,
                )
            except ImportError:
                attach_live_game_state_from_lens = None  # type: ignore[assignment]
                attach_live_gamelines_for_sport = None  # type: ignore[assignment]
                attach_live_projections_for_sport = None  # type: ignore[assignment]
            from syndicate.features.shared.book_grid import build_book_grid
            from syndicate.features.shared.odds_book_quotes import read_book_quotes_latest, read_quote_last_seen

            # WINDOW-SCOPED, NOT SINGLE-DATE (`#379`).
            #
            # Measured live 2026-08-12: soccer reported `quote_rows: 0` to Layer 2
            # while its Layer 1 board served 3,298 rows with a 60-minute seen-age.
            # Both readings were current and they contradicted each other.
            #
            # Soccer shards by KICKOFF date, not capture date, so today's captures
            # land in `2026-08-15.jsonl`, `2026-08-16.jsonl` and beyond -- and
            # `2026-08-12.jsonl` really is empty, because almost nothing kicks off
            # today. Asking one date for a sport that does not store by that date
            # returns nothing forever, not just on quiet days. Layer 1 has scoped
            # by `resolve_window_dates` since `#329`; Layer 2 never did, so soccer
            # could not reach it on ANY day.
            #
            # Single-date sports resolve to a one-element window, so this is a
            # no-op for mlb/nba/wnba/nhl/ncaab and additive for nfl (5) and
            # ncaaf (3), whose fixtures also span days.
            from syndicate.features.shared.layer1_board import resolve_window_dates

            window_dates = resolve_window_dates(sport, selected_date, window="slate") or [selected_date]
            quote_rows = []
            dates_with_rows: list[str] = []
            # A CORRUPT SHARD AND AN EMPTY ONE MUST NOT RENDER AS THE SAME ZERO.
            #
            # `#379` wrapped this read in a per-date `try/except: continue` so one
            # bad date could not lose the other six -- correct, and still the
            # behaviour below. But the exception it swallows used to propagate to
            # the whole-sport handler, which records `{"error": ...}` into
            # `per_sport_stats` (:387). Nothing recorded it after that, so a sport
            # whose shard raised on EVERY date reported a clean `quote_rows: 0`
            # and was indistinguishable from a sport with no slate.
            #
            # Caught by `test_one_sport_failing_does_not_lose_the_others`, which
            # asserts both halves: the other sport survives AND the failure is
            # visible. The first half passed throughout; only the reporting was
            # lost.
            read_errors: dict[str, str] = {}
            for window_date in window_dates:
                try:
                    # `#435`. LATEST-PER-KEY. `build_book_grid` below already
                    # keeps only the freshest row per key (`book_grid.py:156`,
                    # `:225`) and its reduce key equals `_KEY_FIELDS`, so the
                    # grid cannot tell this from the full shard -- verified
                    # byte-for-byte against the real 207MB 2026-08-09 shard.
                    #
                    # This loop is why it matters here most: it EXTENDS across a
                    # window, so NFL accumulated five shards at once.
                    chunk = read_book_quotes_latest(sport, window_date)
                except Exception as exc:
                    # Recorded, then skipped -- resilience unchanged.
                    read_errors[str(window_date)] = f"{type(exc).__name__}: {exc}"
                    continue
                if chunk:
                    quote_rows.extend(chunk)
                    dates_with_rows.append(window_date)
            if not quote_rows:
                # #296. Zero quotes means one of two things and they must not
                # look alike: the sweep has NOT RUN YET, or it ran and the sport
                # has no slate. The board is quote-driven, so a sport in the
                # first state does not degrade -- it VANISHES, which is
                # indistinguishable from being broken.
                #
                # Measured 2026-08-09 02:58Z: MLB had 15 scheduled games and no
                # quote log at all, because MLB capture for a date begins
                # ~06:43Z (first captured_at on the 08-08 log). So for ~6 hours
                # nightly the biggest sport is simply missing from the board
                # with no marker -- exactly when someone is most likely looking.
                #
                # The schedule is known hours before the odds are, so the chip
                # count is what separates the two. Asked with an empty grid: it
                # loads the same chips and reports `rows_matched: 0`, which is
                # the honest answer here.
                try:
                    scheduled = int(
                        (attach_game_state([], sport=sport, selected_date=selected_date) or {}).get("chips") or 0
                    )
                except Exception:
                    scheduled = 0
                per_sport_stats[sport] = {
                    "quote_rows": 0,
                    "grid_rows": 0,
                    "opportunities": 0,
                    "scheduled_games": scheduled,
                    # WHICH dates were asked. A zero against a 7-day window is a
                    # different fact from a zero against one date, and the old
                    # payload could not tell them apart.
                    "window_dates": list(window_dates),
                    # A zero must be attributable -- same contract as
                    # `rows_stale_kickoff` and audit_slate_coverage's THIN.
                    "sweep_state": "pending" if scheduled > 0 else "no_slate",
                }
                if read_errors:
                    # `error` is the key the whole-sport handler (:387) uses, so a
                    # consumer checks one key regardless of where the failure was
                    # caught. `read_errors` keeps the per-date detail, because
                    # "one date of seven failed" and "all seven failed" are
                    # different operational facts.
                    per_sport_stats[sport]["error"] = (
                        f"quote read failed for {len(read_errors)} of "
                        f"{len(window_dates)} window dates: "
                        + "; ".join(f"{d} -> {e}" for d, e in sorted(read_errors.items()))
                    )
                    per_sport_stats[sport]["read_errors"] = dict(read_errors)
                continue
            # Last-seen turns the grid's single age into two: time since the
            # price MOVED, and time since we LOOKED. Only the second is
            # staleness, and scoring was discounting stable markets for the
            # first. Empty for dates whose state predates the tracking, which
            # leaves `seen_age_seconds` absent and the old behaviour intact.
            last_seen_error: str | None = None
            try:
                # `#569`. MERGED ACROSS THE SAME DATES THE ROWS CAME FROM, and
                # reading only `selected_date` here was a real defect.
                #
                # `quote_rows` above EXTENDS across `window_dates` -- its own
                # comment says so ("NFL accumulated five shards at once") -- while
                # this read covered ONE date. Every row from any other window date
                # therefore had no entry, so `_seen_age_seconds` returned None,
                # and a row with no clock is INVISIBLE to
                # `drop_superseded_lines`: that guard requires `seen_age_seconds`
                # on the row AND on its group's freshest, by design, because
                # pruning on absence would empty the board.
                #
                # So a line the market had moved off could never be dropped on a
                # forward date. MEASURED 2026-08-26 21:17:19Z, one grid build:
                # `SUPERSEDED_SURVIVORS no_seen_age=7553` against
                # `SUPERSEDED_LINES_DROPPED kept=15672` -- 48% of the grid
                # carrying no clock, and every one of them exempt from the guard.
                # The same absence also pins `_freshness_factor` at its harshest
                # discount for those rows.
                #
                # NEWEST WINS on a key seen on more than one date: this answers
                # "when did we last look at this market", and the latest look is
                # the answer regardless of which shard recorded it.
                last_seen = {}
                for _seen_date in (dates_with_rows or [selected_date]):
                    for _key, _stamp in (read_quote_last_seen(sport, str(_seen_date)) or {}).items():
                        if _stamp and _stamp > last_seen.get(_key, ""):
                            last_seen[_key] = _stamp
            except Exception as exc:
                # Swallowing this is correct -- last-seen is an enhancement and
                # its absence must not fail the build -- but swallowing it
                # SILENTLY is not. Measured 2026-08-09: `quote_seen_age_seconds`
                # was null on 200/200 served rows and `freshness_factor` sat at
                # 0.25 (the harshest discount) on every one, and nothing in the
                # payload could distinguish "the sidecar never reached this
                # service" from "it loaded and matched nothing".
                last_seen = {}
                last_seen_error = f"{type(exc).__name__}: {exc}"
            grid = build_book_grid(quote_rows, max_rows=max_grid_rows_per_sport, last_seen=last_seen)

            # ENRICH BEFORE RANKING. Without these three the persisted board is
            # unusable, and each failure is silent rather than empty:
            #
            #   game state  -> opportunity_gate reads `game_state`/`is_live`.
            #                  Absent, every row looks pregame and a SETTLED
            #                  MARKET CAN RANK.
            #   projections -> `edge_vs_market_pct`, the only probability-space
            #                  model view. Absent, `model_edge_pct` is null on
            #                  every row (#263) and blended_score falls back to
            #                  EV alone -- which under proportional devig is
            #                  `1/overround - 1`, IDENTICAL for every side of a
            #                  market. The board then ranks markets by hold and
            #                  picks a side by tie-break.
            #   margin      -> fair value for one-sided rows; without it they
            #                  carry none at all.
            #
            # Same functions the serve-time endpoint calls, so the board a user
            # reads and the board that is persisted cannot drift.
            #   live        -> the LIVE re-sim's number. Absent, every live row
            #                  on the board shows its PREGAME full-game
            #                  projection beside a live line, which is two
            #                  different quantities. Measured 2026-08-16 19:16Z:
            #                  54 live rows, all carrying
            #                  `projection.source = "game_simulation"` (pregame)
            #                  and none carrying a live one, because THESE TWO
            #                  JOINS WERE NEVER CALLED HERE -- they ran only for
            #                  the serve-time `/api/board/book-grid` endpoint.
            #                  That is the drift this loop's own comment below
            #                  says must not happen.
            enrichment: dict[str, object] = {}
            for step, fn in (
                ("game_state", lambda: attach_game_state(grid, sport=sport, selected_date=selected_date)),
                # `#523`. THE THIRD MISSING JOIN, and the comment above this loop
                # already names the shape: two joins "ran only for the serve-time
                # endpoint" and were added here. `attach_live_game_state_from_lens`
                # is the one that was left, and it is the one the other two depend
                # on.
                #
                # `book_grid_artifact.py:221` runs it and says why the POSITION
                # matters (`#413`): `live_edge_policy` decides whether a row may
                # carry an edge by reading `game.state`, so the correction has to
                # land while it can still change an answer. Same position here --
                # after the chip join, before projections.
                #
                # WHY IT WAS INVISIBLE, and why MLB never showed it: MLB's chips
                # are StatsAPI-derived and already carry a real live status, so
                # `attach_game_state` alone is enough and MLB's live tier worked.
                # Soccer's chips come from `_unsimulated_game`, which defaults
                # `status_state` to `"pre"` for every league the sim does not
                # cover -- nine of ten. Only this correction ever makes those rows
                # live, and it was not running.
                #
                # MEASURED 2026-08-22 23:58:21Z, the reading that found it:
                #
                #     LIVE_PROJECTION_JOIN sport=soccer considered=0 projected=0
                #                          lens_indexed=864 lens_live_games=6
                #
                # Six live matches indexed and ZERO rows considered.
                # `attach_live_gamelines` counts a row only after
                # `game.state in {live, in_progress}` (`live_gameline_join.py:807`),
                # so `considered=0` is not a join that priced nothing -- it is a
                # join no row reached. Soccer `live_rows` had been 0 on the board
                # across three separate readings while its quote age fell 32x.
                (
                    "live_game_state",
                    (
                        (lambda: attach_live_game_state_from_lens(grid, sport=sport, selected_date=selected_date))
                        if attach_live_game_state_from_lens is not None
                        else None
                    ),
                ),
                # PRICE BEFORE ANYTHING THAT READS PRICE.
                #
                # `7799abf9c` moved this ahead of `build_layer2_rows` so a row
                # the lane gate had already killed could still be rescued by a
                # venue quote. It was still too late for the four steps below,
                # and that left ONE ROW CARRYING TWO VINTAGES:
                #
                #   `best.price`            LIVE   (Polymarket / Kalshi)
                #   `cells` / `consensus`   PREGAME (OddsAPI, before first pitch)
                #
                # Every fair value on the row is de-vigged from the second pair
                # -- `_fair_by_side` from `cells`, `market_fair_prob_over` from
                # `consensus` -- and `live_gameline_join` then subtracts that
                # pregame fair from the LIVE re-sim's win probability. On a game
                # three runs in, that difference is mostly the gap between two
                # clocks, and `_MODEL_EDGE_MAX_POINTS` drops it. Measured
                # 2026-08-25 03:5xZ, and this is the guard working correctly:
                #
                #     LAYER2_BOARD_HEALTH sport=mlb rows=14 edged=10
                #     PAPER2_PLAN_WRITTEN venue=polymarket rows_in=14
                #       positions=0 venue_priced=12
                #       refusals={'no_model_edge_pct': 14}
                #
                # Ten rows carried an edge and none survived the bound. So the
                # re-price runs HERE: after the two state joins, which read no
                # price and are what tell it a game is live, and before every
                # step that reads one.
                (
                    "venue_reprice",
                    lambda: _reprice_grid_from_venues(grid, sport, selected_date),
                ),
                # `#587`. JOINED ACROSS THE SAME DATES THE ROWS CAME FROM.
                #
                # This is `#569`'s defect exactly, one join later and unfixed:
                # `quote_rows` EXTENDS across `window_dates` (see its own
                # comment above -- "NFL accumulated five shards at once"), so
                # the grid holds rows from every date in the window, while this
                # join asked for `selected_date` ALONE. Rows from any other
                # window date could not be projected, because the index built
                # for one date does not contain the other dates' games.
                #
                # NCAAF is where it is total rather than partial, and the
                # measurement is unambiguous:
                #
                #     PREGAME_PROJECTION_JOIN sport=ncaaf considered=None
                #       projected=0 reason=no NCAAF SmartSim2 projections for
                #       this date
                #
                #     /api/board/game-chips?date=2026-08-29
                #       total=250  ncaaf=0  {nfl: 16, soccer: 234}
                #
                # Zero NCAAF chips on its own opening Saturday, while NFL --
                # also out of season -- carries 16. NCAAF's slate window is 3
                # days and its games are 2-3 days out, so every NCAAF row in
                # the grid comes from a date that is NOT `selected_date`, and
                # the join therefore matched nothing on every single build.
                #
                # NOT AN NCAAF-ONLY FIX, deliberately. The same shape applies to
                # any sport whose window spans days -- nfl (5) and soccer -- and
                # `#569` already established that the correct scope for a
                # window-spanning grid is the window. Single-date sports
                # (mlb/nba/wnba/nhl/ncaab) resolve to a one-element window, so
                # this is a strict no-op for them.
                #
                # LAST DATE WINS ON A COLLISION, which cannot occur in practice:
                # a row belongs to exactly one kickoff date, so two dates'
                # indexes never claim the same row. Coverage counters are summed
                # rather than overwritten so the diagnostic still reports the
                # whole window.
                ("projections", lambda: _attach_projections_over_window(
                    grid, sport=sport, selected_date=selected_date, window_dates=window_dates
                )),
                ("margin_model", lambda: attach_margin_model(grid)),
                # Same functions the serve-time endpoint calls
                # (`_attach_book_grid_*` in `blueprints/intelligence.py`), for
                # the reason stated above the loop. Both read a PUBLISHED
                # snapshot and neither triggers a re-sim -- that path is
                # `refuse_if_compute_in_request_path` and belongs to
                # live-odds-worker's tick, so this stays a read.
                (
                    "live_projections",
                    (
                        (lambda: attach_live_projections_for_sport(grid, sport=sport, selected_date=selected_date))
                        if attach_live_projections_for_sport is not None
                        else None
                    ),
                ),
                (
                    "live_gamelines",
                    (
                        (lambda: attach_live_gamelines_for_sport(grid, sport=sport, selected_date=selected_date))
                        if attach_live_gamelines_for_sport is not None
                        else None
                    ),
                ),
            ):
                if fn is None:
                    # ABSENT, and say which absence it is. "not on this deploy"
                    # and "ran and matched nothing" need different fixes, and
                    # `#296`'s whole point is that they must not look alike.
                    enrichment[step] = {"supported": False, "reason": "not present on this deploy"}
                    continue
                try:
                    enrichment[step] = fn()
                except Exception as exc:  # never let enrichment break the build
                    enrichment[step] = {"error": f"{type(exc).__name__}"}

            # SAY, IN THE LOGS, WHY THE LIVE COLUMNS ARE BLANK.
            #
            # `attach_live_projections` already returns everything needed to
            # attribute a blank Live cell -- `rows_live_projected` against
            # `snapshot_rows_indexed`, plus the three named miss reasons -- and
            # it all went into the shortlist payload and nowhere else. So the
            # only way to answer "is the live re-sim reaching the board" was to
            # fetch and parse the served artifact, which is exactly the question
            # a user asks when they see an em dash next to a game in progress.
            #
            # The distinction this makes readable, and it is the whole point:
            #   projected == 0, indexed == 0  -> the LIVE LENS produced nothing
            #   projected == 0, indexed  > 0  -> the lens has rows, the JOIN missed
            #   projected  > 0, edged   == 0  -> joined, and declined to price
            # Those three have completely different fixes and, until now, one
            # identical symptom. Same contract as `#296`: a zero must be
            # attributable, never bare.
            #
            # print(), not logger.info -- CLAUDE.md: logger.info never reaches
            # Render's log collector from this process.
            try:
                live_stats = enrichment.get("live_projections")
                if isinstance(live_stats, Mapping) and live_stats.get("supported") is not False:
                    print(
                        f"[layer2_shortlist] LIVE_PROJECTION_JOIN sport={sport} "
                        f"considered={live_stats.get('rows_live_considered')} "
                        f"projected={live_stats.get('rows_live_projected')} "
                        f"edged={live_stats.get('rows_live_edged')} "
                        # `#539`. NEXT TO `edged`, never added to it. The two are
                        # different strengths of evidence -- a two-sided de-vig
                        # versus one book's measured hold -- and the whole point
                        # of the modelled path is that soccer's live tier could
                        # otherwise never carry a number. Printed even when zero,
                        # because "the rule is live and matched nothing" and "the
                        # rule is not deployed" must not look alike.
                        f"edged_modelled={live_stats.get('rows_live_edged_modelled')} "
                        f"prob_withheld={live_stats.get('rows_live_prob_withheld')} "
                        f"lens_indexed={live_stats.get('snapshot_rows_indexed')} "
                        f"lens_live_games={live_stats.get('live_games_in_snapshot')} "
                        f"miss_player={live_stats.get('miss_no_player')} "
                        f"miss_market={live_stats.get('miss_no_market_alias')} "
                        f"miss_line={live_stats.get('miss_no_line')} "
                        # The two causes `miss_market` used to absorb. The first
                        # production reading of this line (23:37Z 2026-08-21)
                        # was `miss_market=428` with player and line both 0,
                        # which named a vocabulary gap it could not actually
                        # distinguish from a line mismatch.
                        f"miss_line_match={live_stats.get('miss_no_line_match')} "
                        f"miss_not_live={live_stats.get('miss_player_not_live')} "
                        # `projected > 0, edged == 0` is the case this line
                        # could name but not explain -- measured on soccer
                        # 2026-08-22 16:46Z: 114 projected, 0 edged, 0
                        # prob_withheld. The withhold count and its per-reason
                        # split are where that answer lives, and neither was
                        # printed.
                        f"edge_withheld={live_stats.get('rows_live_edge_withheld')} "
                        f"edge_why={live_stats.get('edge_withheld_by_reason')} "
                        f"sample={live_stats.get('unmatched_samples')} "
                        # The soccer live path returns EARLY with a stated
                        # reason and none of the counters above, so every field
                        # on this line read `None` and the line said nothing.
                        # `reason` is where its answer lives.
                        f"reason={live_stats.get('reason')} "
                        f"soccer_live_games={live_stats.get('live_games')} "
                        f"soccer_rows_seen={live_stats.get('rows_seen')}",
                        flush=True,
                    )
            except Exception:
                # An instrument that can break the build is worse than none.
                pass

            # AND THE SAME FOR THE PREGAME TIER, which had no log line at all.
            #
            # `attach_projections` returns a full coverage payload per sport and
            # it went into the shortlist artifact and nowhere else -- so the only
            # way to answer "is the SIM reaching the board" was to fetch and
            # parse the served artifact. Soccer has been at
            # `rows_with_projection: 4` of ~1,142 for days and the shape of that
            # zero was never readable from the logs.
            #
            # Deliberately for EVERY sport, not soccer alone: the same blank
            # column, produced by the same absent join, currently looks
            # identical on all eight.
            try:
                proj_stats = enrichment.get("projections")
                if isinstance(proj_stats, Mapping) and proj_stats.get("supported") is not False:
                    print(
                        f"[layer2_shortlist] PREGAME_PROJECTION_JOIN sport={sport} "
                        f"considered={proj_stats.get('rows_considered')} "
                        f"projected={proj_stats.get('rows_with_projection')} "
                        f"with_prob={proj_stats.get('rows_with_true_probability')} "
                        f"matches_in_source={proj_stats.get('matches_in_source')} "
                        f"unmatched_match={proj_stats.get('unmatched_match_rows')} "
                        f"unmatched_player={proj_stats.get('unmatched_player_rows')} "
                        # The player bucket is now the LARGEST and had no
                        # attribution at all -- same contract the league split
                        # already meets one level up.
                        f"player_no_roster={proj_stats.get('player_miss_no_roster')} "
                        f"player_name_miss={proj_stats.get('player_miss_name')} "
                        f"matches_with_players={proj_stats.get('matches_with_players')} "
                        f"board_players={proj_stats.get('unmatched_player_sample')} "
                        f"sim_players={proj_stats.get('sim_roster_sample')} "
                        f"unsupported_market={proj_stats.get('unsupported_market_rows')} "
                        f"reason={proj_stats.get('reason')} "
                        f"error={proj_stats.get('error')} "
                        # Soccer-only attribution. Absent on other sports, which
                        # is why they print as None rather than being a second
                        # log line nobody greps for.
                        f"dates_read={proj_stats.get('dates_read')} "
                        f"leagues_indexed={proj_stats.get('leagues_indexed')} "
                        f"ambiguous_keys={proj_stats.get('ambiguous_team_keys')} "
                        f"rows_by_league={proj_stats.get('rows_by_league')} "
                        f"unmatched_by_league={proj_stats.get('unmatched_by_league')} "
                        f"unmatched_fixtures={proj_stats.get('unmatched_fixtures_count')} "
                        f"board_names={proj_stats.get('unmatched_fixture_sample')} "
                        f"sim_names={proj_stats.get('indexed_fixture_sample')}",
                        flush=True,
                    )
            except Exception:
                pass

            # THE RE-PRICE'S OWN NUMBERS. It runs as an enrichment step above
            # (see the comment there for why its position moved twice); this is
            # the instrument, printed here beside the other join diagnostics.
            #
            # `benchmark_*` is the second half `#563` added: `repriced` counts
            # sides whose PRICE moved to a venue, `benchmark_rows` counts rows
            # whose FAIR VALUE moved with it. The two being different numbers is
            # the whole finding -- the first was non-zero and the second did not
            # exist, which is how a live price came to be scored against a
            # pregame benchmark.
            try:
                grid_reprice = enrichment.get("venue_reprice")
                if isinstance(grid_reprice, Mapping):
                    print(
                        f"[layer2_shortlist] GRID_REPRICE sport={sport}"
                        f" sides_seen={grid_reprice.get('sides_seen')}"
                        f" repriced={grid_reprice.get('repriced')}"
                        f" by_source={grid_reprice.get('by_source')}"
                        f" benchmark_rows={grid_reprice.get('benchmark_rows')}"
                        f" benchmark_skipped={grid_reprice.get('benchmark_skipped')}"
                        f" error={grid_reprice.get('error')}",
                        flush=True,
                    )
            except Exception:
                pass

            # AND THE LIVE GAME-LINE JOIN, which has never printed anything.
            #
            # `attach_live_gamelines` returns a full coverage payload -- index
            # size, rows projected, priceable, and the per-reason withhold split
            # -- and every field of it went into the shortlist artifact and
            # nowhere else. That is the same computed-but-unprinted gap as the
            # seven drop counters and the three joins above it, and it is why
            # "the live moneyline join produced nothing" and "it produced
            # something the board then dropped" looked identical from the logs.
            try:
                gl_stats = enrichment.get("live_gamelines")
                if isinstance(gl_stats, Mapping) and gl_stats.get("supported") is not False:
                    print(
                        f"[layer2_shortlist] LIVE_GAMELINE_JOIN sport={sport} "
                        f"index={gl_stats.get('index_size')} "
                        f"considered={gl_stats.get('rows_live_gameline_considered')} "
                        f"projected={gl_stats.get('rows_live_gameline_projected')} "
                        f"priceable={gl_stats.get('rows_live_gameline_priceable')} "
                        f"withheld={gl_stats.get('rows_live_gameline_withheld')} "
                        f"why={gl_stats.get('withheld_by_reason')} "                        # WHY AN EMPTY INDEX IS EMPTY. `index=0` reads as "no
                        # producer wired" and that reading was WRONG for WNBA on
                        # 2026-08-25: the lens builds every 60s and its lane was
                        # stamped `pregame`, which this join correctly refuses.
                        # `sources_seen` is the discriminator.
                        f"index_why={gl_stats.get('index_diagnostics')} "
                        f"reason={gl_stats.get('reason')} "
                        f"error={gl_stats.get('error')}",
                        flush=True,
                    )
            except Exception:
                pass

            result = build_layer2_rows(grid, openings=openings_index)
            sport_opportunities = list(result.get("opportunities") or [])
            # `sport` is carried on the grid row already, but stamp defensively:
            # select_shortlist buckets per sport and a missing slug would
            # collapse every sport into one bucket.
            for row in sport_opportunities:
                if not str(row.get("sport") or "").strip():
                    row["sport"] = sport
            opportunities.extend(sport_opportunities)
            # BOTH numbers, because either alone is ambiguous. `last_seen_keys`
            # is what this service could READ (0 => the `.state.json` sidecar
            # never crossed to this disk, or predates the 3-element format);
            # `cells_with_seen_age` is what actually JOINED (>0 keys but 0 cells
            # => the sidecar is here and the key shapes disagree). Reporting one
            # without the other cannot tell a delivery gap from a join gap.
            # Counted defensively: an instrument that can raise is worse than no
            # instrument, and this one walks a nested shape it does not own.
            cells_with_seen_age = 0
            try:
                for grid_row in grid:
                    if not isinstance(grid_row, Mapping):
                        continue
                    for by_side in (grid_row.get("cells") or {}).values():
                        if not isinstance(by_side, Mapping):
                            continue
                        for cell in by_side.values():
                            if isinstance(cell, Mapping) and cell.get("seen_age_seconds") is not None:
                                cells_with_seen_age += 1
            except Exception:
                cells_with_seen_age = -1  # walked and failed, distinct from a real 0
            per_sport_stats[sport] = {
                "quote_rows": len(quote_rows),
                "window_dates": list(window_dates),
                "dates_with_rows": list(dates_with_rows),
                # Stated even when rows DID come back: a window that lost 3 of 7
                # dates to unreadable shards still serves a board, and silently
                # serving a partial one is the failure mode this whole block
                # exists to prevent.
                **(
                    {
                        "error": (
                            f"quote read failed for {len(read_errors)} of "
                            f"{len(window_dates)} window dates: "
                            + "; ".join(f"{d} -> {e}" for d, e in sorted(read_errors.items()))
                        ),
                        "read_errors": dict(read_errors),
                    }
                    if read_errors
                    else {}
                ),
                "grid_rows": int(result.get("rows_in") or 0),
                # Stated on BOTH branches on purpose: a consumer that has to
                # infer "swept" from the absence of a key cannot tell it from a
                # payload written before this field existed.
                "sweep_state": "swept",
                "scheduled_games": int(
                    ((enrichment.get("game_state") or {}) if isinstance(enrichment.get("game_state"), dict) else {}).get("chips")
                    or 0
                ),
                "last_seen_keys": len(last_seen),
                "cells_with_seen_age": cells_with_seen_age,
                **({"last_seen_error": last_seen_error} if last_seen_error else {}),
                # Visible on purpose: "rows_with_projection: 0" is the signal that
                # #263 has regressed, and it is invisible from a row count.
                "enrichment": enrichment,
                "rows_with_model_edge": sum(
                    1 for row in sport_opportunities if row.get("model_edge_pct") is not None
                ),
                "sides_priced": int(result.get("sides_priced") or 0),
                "candidates": int(result.get("candidates") or 0),
                "scored": int(result.get("scored") or 0),
                "opportunities": len(sport_opportunities),
                "by_lane": result.get("by_lane") or {},
                # `#444`. BOTH halves of the bettable-book restriction, for the
                # reason every other rejection counter in this pipeline is
                # reported: a rule that trims silently cannot be told apart
                # from a thin slate.
                #
                # ADDED AFTER THE FILTER SHIPPED, which is the whole lesson.
                # `build_layer2_rows` returned these from the same commit that
                # introduced the rule -- and they still reached nobody, because
                # THIS dict is an explicit key list and a new key on the
                # producer does not appear in it. Measured on the served
                # payload 2026-08-16 18:52:57Z: the filter was demonstrably
                # working (best-book-outside-the-list 27 -> 0) and both of its
                # counters read `None` at every level of the payload. The
                # filter worked and was invisible.
                #
                # `#397`'s discipline says add the counter in the same commit
                # as the rule. It is not enough: the counter has to be added
                # everywhere the payload is ASSEMBLED, and on this path that is
                # three places, not one.
                "no_bettable_book": int(result.get("no_bettable_book") or 0),
                "repriced_to_bettable": int(result.get("repriced_to_bettable") or 0),
            }
        except Exception as exc:
            per_sport_stats[sport] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

    # Selection policy is layer2_board's, not re-specified here: 100 per sport,
    # floor 30 per kind, remainder on merit, unused floor flowing to the other
    # kind. That floor is load-bearing -- without it MLB's 1,221 prop rows would
    # plausibly take all 100 slots from its 229 game rows, and a hard 50/50
    # would drop a better prop to seat a worse game line.
    #
    # `horizon_days` is the ONE knob passed through: the default (1 = today and
    # tomorrow) scopes the shortlist, and None gives the Forward view over the
    # same rows. Sentinel rather than None-as-default, because None is a
    # MEANINGFUL value here and a plain `horizon_days=None` default would make
    # the Forward view unreachable while looking like it was the default.
    # RE-PRICE FROM THE VENUES BEFORE THE GATES RUN.
    #
    # MEASURED 2026-08-24 23:23Z, once the drop counters were made visible:
    #
    #   LAYER2_SHORTLIST rows=0 considered=8600
    #     beyond_horizon=2416 beyond_quote_age=6184 stale_kickoff=0
    #
    # 71.9% of the board died on `beyond_quote_age` -- a 14h ceiling
    # (`SHORTLIST_MAX_QUOTE_AGE_SECONDS`) against OddsAPI quotes that were 13.9h
    # old. The board was not broken and the model was not starved; the prices
    # were simply too old to act on, and every sport but soccer has a tighter
    # ceiling than soccer's 24h.
    #
    # Kalshi and Polymarket US both publish their own `fetched_at` and both
    # refresh on minutes, not hours (Polymarket measured `slate_age_s=857`
    # against a 900s cadence). So a row priced from a venue is MINUTES old and
    # clears both ceilings ON MERIT -- which is the difference between fixing
    # the freshness and widening a gate to admit stale prices onto games that
    # have already started.
    #
    # ONLY ROWS ACTUALLY PRICED FROM A VENUE ARE RESTAMPED. `apply_venue_quotes`
    # returns everything else untouched, still carrying its real age, so this
    # cannot launder staleness through the gate built to catch it.
    try:
        from syndicate.features.shared.venue_quote_fanin import apply_venue_quotes

        repriced = apply_venue_quotes(opportunities, str(selected_date or ""))
        opportunities = list(repriced.get("rows") or opportunities)
        print(
            f"[layer2_shortlist] VENUE_REPRICE rows_in={repriced.get('rows_in')} "
            f"stamped={repriced.get('stamped')} unstamped={repriced.get('unstamped')} "
            # `unstamped` is the number that predicts whether this helped: those
            # rows keep whatever age they had and will still be gated on it.
            f"sports={repriced.get('sports')} "
            f"ceiling_s={repriced.get('ceiling_seconds_by_sport')} "
            f"by_source={repriced.get('by_source')} "
            f"selected_by_source={repriced.get('selected_by_source')}",
            flush=True,
        )
        # SEPARATE LINE, because it answers a different question and is the one
        # worth reading when `stamped` is low. `selected_by_source` says who
        # WON; this says whether the two sides of the join are even the same
        # shape. Measured 2026-08-25T00:02Z, polymarket_us offered 3,106 quotes
        # and won none of 237 -- which freshness cannot explain, since Kalshi
        # quotes no game lines at all.
        # WHICH SPORT PRODUCED WHAT, on the line that reports the board.
        #
        # MEASURED 2026-08-25: three consecutive builds logged
        # `VENUE_REPRICE rows_in=4296 sports=['nfl','soccer']` -- byte-identical
        # -- while MLB independently generated 411 candidates (44 game, 367
        # prop) and logged `GAME_CANDIDATES_EXIT sport=mlb rows=68`. MLB is
        # KEPT by the manifest gate and IS iterated here, so it was reaching
        # this loop and yielding zero opportunities, and nothing said so.
        #
        # `per_sport_stats` has carried `candidates`/`scored`/`sides_priced`/
        # `opportunities` per sport the entire time and was stored on the
        # result where only an artifact reader could see it. This is the same
        # computed-but-unprinted gap as the seven drop counters on
        # LAYER2_SHORTLIST: the number that identifies the sport at fault
        # existed and never reached a log line.
        print(
            "[layer2_shortlist] PER_SPORT_INGEST "
            + " ".join(
                f"{name}(cand={stat.get('candidates')},scored={stat.get('scored')},"
                f"priced={stat.get('sides_priced')},opps={stat.get('opportunities')},"
                f"lanes={stat.get('by_lane')})"
                for name, stat in sorted((per_sport_stats or {}).items())
            ),
            flush=True,
        )
        # THE ENRICHMENT STEP THAT DECIDES THE LANE.
        #
        # MEASURED 2026-08-25T02:59:03Z:
        #   mlb  cand=1302 scored=1300 priced=1390 opps=0
        #   wnba cand=1225 scored=1225 priced=1247 opps=0
        #   nfl  cand=2642 ... opps=112     soccer cand=9041 ... opps=4184
        #
        # Everything prices and scores, then MLB and WNBA emit nothing. The
        # filter is `board_lane == LANE_OPPORTUNITY`, and `opportunity_gate`
        # demotes to LANE_WATCHLIST when demotion is enabled AND the row has no
        # game state AND kickoff has passed. Only the two LIVE sports meet all
        # three -- nfl (08-28) and soccer have not kicked off, which is exactly
        # why they are unaffected.
        #
        # So the question is why `attach_game_state` matches zero MLB/WNBA rows
        # (`game_candidate_inputs` shows game_state="" is_live=false). That
        # join already RETURNS `chips`/`rows_matched`/`unmatched_teams` for this
        # purpose -- the 2026-08-06 soccer gap sat at 0 matched through nine
        # hypotheses for want of exactly this sample -- and it was being stored
        # where only an artifact reader could see it.
        #
        # The demotion itself is CORRECT and is not being touched: a started
        # game with unknown state may already be settled, and Polymarket is
        # armed with real money. The fix belongs upstream, in the join.
        for name, stat in sorted((per_sport_stats or {}).items()):
            step = ((stat or {}).get("enrichment") or {}).get("game_state")
            if isinstance(step, dict):
                print(
                    f"[layer2_shortlist] GAME_STATE_JOIN sport={name}"
                    f" chips={step.get('chips')} rows_matched={step.get('rows_matched')}"
                    f" unmatched={str(step.get('unmatched_teams'))[:200]}"
                    f" reason={step.get('reason')} error={step.get('error')}",
                    flush=True,
                )
            # THE STEP THAT CORRECTS A FROZEN CHIP, AND THE ONLY ONE THAT NEVER
            # PRINTED. `#413` records the mechanism: the chip reader uses
            # PRESENCE where freshness was meant, so whenever a game's feed was
            # first captured becomes its state for the rest of the day -- MIL@SD
            # read `live / TOP 9` off a FIVE-MINUTE-OLD artifact while the lens
            # read `Final`. `attach_live_game_state_from_lens` is the overlay
            # that fixes it, and its coverage payload went to the artifact and
            # nowhere else.
            #
            # MEASURED 2026-08-25 04:21:24Z, which is why this is here:
            # `basketball_momentum` reported wnba `post=2 live_events=0` on every
            # tick from 04:18:50Z, and the same build counted 184 wnba rows past
            # `attach_live_gamelines`' live-state check. Both games final, 184
            # rows live. `game.state` gates BOTH live guards --
            # `opportunity_gate`'s 900s clock and `live_edge_policy`'s refusal of
            # a settled market -- so a chip frozen at `live` means that refusal
            # never fires.
            #
            # `supported` is the field that matters: `_LIVE_GAME_STATE_SPORTS` is
            # `{mlb, soccer}`, so this returns `supported: False` for wnba and
            # always has. That is a stated refusal nobody could read.
            live_step = ((stat or {}).get("enrichment") or {}).get("live_game_state")
            if isinstance(live_step, dict):
                print(
                    f"[layer2_shortlist] LIVE_GAME_STATE_JOIN sport={name}"
                    f" supported={live_step.get('supported')}"
                    f" corrected={live_step.get('rows_corrected')}"
                    f" transitions={live_step.get('transitions')}"
                    f" snapshot_age_s={live_step.get('snapshot_age_seconds')}"
                    f" reason={live_step.get('reason')} error={live_step.get('error')}",
                    flush=True,
                )
        print(
            "[layer2_shortlist] VENUE_REPRICE_KEYS "
            f"unmatched_by_sport={repriced.get('unmatched_by_sport')} "
            f"board_wanted={repriced.get('unmatched_sample')} "
            f"sources_offered={repriced.get('offered_sample')}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 -- never fatal to the build
        # A venue feed being unreachable must cost the reprice, not the board.
        print(f"[layer2_shortlist] VENUE_REPRICE_FAILED {type(exc).__name__}: {exc}", flush=True)

    try:
        if horizon_days is _UNSET:
            shortlist = select_shortlist(opportunities)
        else:
            shortlist = select_shortlist(opportunities, horizon_days=horizon_days)
    except Exception as exc:
        return {
            "rows": [],
            "error": f"select_shortlist failed: {type(exc).__name__}: {exc}",
            "per_sport_ingest": per_sport_stats,
        }

    # `per_sport_ingest`, NOT `per_sport`: select_shortlist already returns a
    # per_sport report (what was SELECTED per sport) and overwriting it would
    # silently destroy the selection accounting. These stats are the other half
    # -- what came IN per sport -- and the two together are what makes a sport
    # showing zero rows attributable to its slate rather than to a broken read.
    shortlist["per_sport_ingest"] = per_sport_stats
    shortlist["opportunities_considered"] = len(opportunities)

    # `#569`. Measured on the SELECTED rows, not on `opportunities`: the served
    # board is what a user calls stale, and the quote-age gate has already
    # dropped rows past `max_quote_age_seconds` by here -- so this reports the
    # ages that SURVIVED, which is the number the board actually shows.
    _report_served_quote_ages(shortlist.get("rows"))
    _report_stale_row_causes(shortlist.get("rows"), selected_date)

    # BOARD CARDS ARE BUILT HERE, ON THE WORKER, AND PERSISTED.
    #
    # They were briefly translated at serve time instead, inside
    # `_hydrate_board_response_payload`. That was wrong twice over: it put a
    # per-request transformation over every shortlist row into the web service,
    # which reads artifacts and does not compute; and it meant the artifact was
    # not what the board actually showed, which defeats the reason L2-A is
    # worker-side at all -- settlement needs a record of what was RECOMMENDED,
    # and a card derived per request is not recorded anywhere.
    #
    # Web now reads `cards` and slices them by sport. A slice is a read-time
    # narrowing of persisted data, which is what
    # slice_intelligence_board_state_for_request already does; a field mapping
    # is not.
    # MOVEMENT IS JOINED FROM THE OPENING LEDGER, AND THE LOAD HAPPENS HERE --
    # ONCE PER BUILD, OUTSIDE THE PER-ROW LOOP.
    #
    # That placement IS the fix for `#372`. The previous movement
    # implementation called `load_odds_history_payload_for_sport` inside the
    # per-row card builder; the MLB shard is ~20MB and `#370` made a miss load a
    # second one, which stalled the whole shortlist build -- 70 minutes of no
    # `LAYER2_SHORTLIST` line, no exception, no failure log. The disabled
    # function's own docstring named the remedy: use the place that already
    # holds the data.
    #
    # `load_openings` reads one small JSONL of the rows THIS BOARD published
    # today (~100/sport), which `record_openings` writes a few lines below. So
    # the read is of our own output, not of the full quote history, and
    # `_movement_from_opening` does no IO at all.
    #
    # Read BEFORE `record_openings` runs, deliberately: that call appends
    # today's rows, and movement must compare against the FIRST time we
    # published a row, not against the copy we are writing this instant.
    # THE CALLER MUST TOLERATE AN OLDER CALLEE, AND THIS COST A PRODUCTION
    # INCIDENT TO LEARN (2026-08-16 20:34Z).
    #
    # These two files deploy as separate blobs onto a long-lived worker, so
    # there is no instant at which they are guaranteed to be the same vintage.
    # Deploy `c324447d` shipped THIS file carrying `openings=` while
    # `layer2_board.py` on the worker still had the one-argument signature:
    # `TypeError: unexpected keyword argument 'openings'` -> caught by the
    # `except` below -> `cards = []` -> and because `layer2_is_primary` is True
    # with `legacy_candidate_count` 0, **a blank board**, announced only by a
    # `cards_error` string nobody reads.
    #
    # The guard for that was a message to the deploying session. A message is
    # not a guard. So: ASK THE CALLEE WHAT IT ACCEPTS, then call it that way.
    # `inspect.signature` rather than `except TypeError`, because a bare
    # TypeError retry cannot tell "that parameter does not exist" from a real
    # TypeError raised INSIDE the function, and would silently drop movement on
    # a genuine bug.
    #
    # Degrading to a board WITHOUT movement is the correct failure: movement is
    # an enrichment, the rows are already correct, and a board that ranks
    # without a movement term is the board that shipped for months.
    cards_compat_note = None
    try:
        import inspect

        from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

        rows_for_cards = shortlist.get("rows") or []
        try:
            accepts = "openings" in inspect.signature(layer2_rows_to_board_cards).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            shortlist["cards"] = layer2_rows_to_board_cards(rows_for_cards, openings=openings_index)
        else:
            # Older `layer2_board.py` on this worker. Build the board it CAN
            # build rather than no board at all, and say so -- an unexplained
            # empty movement column is `#368`'s defect over again.
            shortlist["cards"] = layer2_rows_to_board_cards(rows_for_cards)
            cards_compat_note = (
                "layer2_board.layer2_rows_to_board_cards has no `openings` parameter on this "
                "deploy; cards built WITHOUT movement/steam. Ship layer2_board.py alongside "
                "pipeline/layer2_shortlist.py to restore it."
            )
    except Exception as exc:
        shortlist["cards"] = []
        shortlist["cards_error"] = f"{type(exc).__name__}: {exc}"
    if cards_compat_note:
        shortlist["cards_compat_note"] = cards_compat_note

    # `#565`. DID THE SOCCER CONTEXT MEMO ACTUALLY DEDUPE, AND AT WHAT COST?
    #
    # Printed at the end of the build so the counts describe a complete cycle,
    # and reset immediately after so each build's line stands alone.
    #
    # `hits` is the saving. `misses` is the floor -- the number of DISTINCT
    # league-weeks this build genuinely had to construct, which is the number
    # that matters if the build is still slow afterwards. A high miss count with
    # near-zero hits means the live vintage is churning every cycle and the
    # memo cannot help; that is a real possible outcome on a busy match evening
    # and it must be visible rather than inferred from the clock.
    try:
        from syndicate.features.soccer.cards import (
            reset_soccer_cards_context_cache_stats,
            soccer_cards_context_cache_stats,
        )

        _cc = soccer_cards_context_cache_stats()
        _cc_total = int(_cc.get("hits") or 0) + int(_cc.get("misses") or 0)
        print(
            f"[layer2_shortlist] SOCCER_CONTEXT_CACHE hits={_cc.get('hits')} "
            f"misses={_cc.get('misses')} calls={_cc_total} "
            f"seconds_saved={round(float(_cc.get('seconds_saved') or 0.0), 1)}",
            flush=True,
        )
        reset_soccer_cards_context_cache_stats()
    except Exception as _cc_exc:  # pragma: no cover - telemetry must never cost the board
        print(
            f"[layer2_shortlist] SOCCER_CONTEXT_CACHE_UNAVAILABLE "
            f"{type(_cc_exc).__name__}: {_cc_exc}",
            flush=True,
        )

    # `#541`. CAN EVERY CARD FIND ITS CHIP? Twice this defect has been found by
    # a person looking at the board -- MLS 2026-08-22, La Liga 2026-08-24 --
    # and both times every count on this line was healthy while some cards
    # printed full club names because they resolved no chip. The join runs in
    # the BROWSER, so nothing server-side ever saw it. This is the reading that
    # makes it visible without a user noticing first.
    #
    # WHOLLY GUARDED. Coverage telemetry must never be able to cost the board:
    # a bad slate or a slow read has to leave the shortlist exactly as it found
    # it.
    #
    # `#563`: THE PUBLISH THAT USED TO LIVE HERE HAS MOVED to the top of this
    # function -- see the `_published_chips` block there for the measurement.
    # What remains is only the join question, which genuinely cannot run any
    # earlier because it needs `cards`. It now MEASURES THE CHIPS THAT WERE
    # ACTUALLY PUBLISHED rather than building a second set: `build_game_chips`
    # holds a 30-second TTL cache and this point is ~20 minutes downstream of
    # the publish, so a rebuild here would silently describe a DIFFERENT set of
    # chips from the ones web is serving -- and a coverage line that does not
    # describe the served artifact is worse than none.
    #
    # THE CONSEQUENCE, STATED: if the early build failed, this reports every
    # card as `no_chip_available` rather than retrying. That is the honest
    # reading -- web IS serving no chips for this cycle -- and the cause is named
    # on its own line (`GAME_CHIPS_BUILD_UNAVAILABLE`) so it is separable from a
    # join failure, which is the distinction this telemetry exists to draw.
    try:
        from syndicate.features.shared.chip_join_coverage import chip_join_coverage

        _cards = shortlist.get("cards") or []
        _chips = _published_chips
        if _chips or _cards:
            # Per-sport, because one sport's healthy window says nothing about
            # another's -- MLB reads 400/400 in the same breath as soccer's 222
            # misses, and a single total would let one hide the other.
            _chip_counts: dict[str, int] = {}
            _chip_dates: dict[str, list[str]] = {}
            for _chip in _chips or ():
                if not isinstance(_chip, Mapping):
                    continue
                _cs = str(_chip.get("sport") or "").strip().lower()
                _chip_counts[_cs] = _chip_counts.get(_cs, 0) + 1
                _start = str(_chip.get("start_time_utc") or "")[:10]
                if _start:
                    _seen = _chip_dates.setdefault(_cs, [])
                    if _start not in _seen:
                        _seen.append(_start)
            for _dates in _chip_dates.values():
                _dates.sort()
            _coverage = chip_join_coverage(_cards, _chips) if _cards else {"by_sport": {}}
            shortlist["chip_join_coverage"] = _coverage
            for _sport, _b in sorted((_coverage.get("by_sport") or {}).items()):
                print(
                    f"[layer2_shortlist] CHIP_JOIN_COVERAGE sport={_sport} "
                    # HOW MANY CHIPS EXISTED AT ALL, and over WHAT DATES.
                    # Without these, `no_chip_available=222` is uninterpretable:
                    # it reads identically for "the board's horizon runs past
                    # the chip window" (expected, cosmetic) and "the chip build
                    # returned almost nothing" (an outage). The first reading
                    # (2026-08-24 15:34:53Z) was exactly that ambiguous, which
                    # is how this line earned the extra two fields.
                    f"chips={_chip_counts.get(_sport, 0)} "
                    f"chip_dates={_chip_dates.get(_sport) or None} "
                    f"cards={_b.get('cards')} by_id={_b.get('by_id')} "
                    f"by_matchup={_b.get('by_matchup')} by_canonical={_b.get('by_canonical')} "
                    # THE TWO THAT MATTER, and they have different owners:
                    # `no_chip_available` is the chip window (the card WILL
                    # print its matchup verbatim), `needs_fallback` is the
                    # alias map (it is one spelling away from that).
                    f"needs_fallback={_b.get('needs_fallback')} "
                    f"no_chip_available={_b.get('no_chip_available')} "
                    # Should be 0 forever after the canonical keys shipped. A
                    # non-zero value means cards are reaching the board from a
                    # path that does not stamp them, which is a different bug
                    # from either of the two above.
                    f"unknown_no_key={_b.get('unknown_no_key')} "
                    # The SPELLINGS. Every fix here has been an alias entry,
                    # and an alias entry needs the exact string each feed used
                    # -- "Athletic Bilbao" vs "Athletic Club" was the entire
                    # finding, and no count could have said it.
                    f"samples={_b.get('samples')}",
                    flush=True,
                )
    except Exception as exc:  # pragma: no cover - telemetry must never break the board
        print(
            f"[layer2_shortlist] CHIP_JOIN_COVERAGE_UNAVAILABLE {type(exc).__name__}: {exc}",
            flush=True,
        )

    # Both numbers, so "no movement on the board" is attributable: 0 openings
    # loaded is a different fact from openings loaded and nothing having moved.
    # BOTH numbers, because either alone is unattributable -- the third time
    # this lesson has been paid for in this file. `openings_records` is what the
    # ledger HELD; `openings_loaded` is how many distinct bets that collapsed
    # to. Thin movement is then separable into "the ledger is sparse" (records
    # low) versus "the key does not join" (records high, matched low), which is
    # exactly the distinction I had to infer by hand at 21:02Z because neither
    # number was published.
    shortlist["openings_records"] = openings_records
    shortlist["openings_loaded"] = len(openings_index)
    # The join's own hit rate, computed over the rows actually published. A
    # coverage number that lives only in my head is how "movement is thin" went
    # three hours without a cause.
    try:
        # Imported HERE, not reused from the loader block above: those names are
        # bound inside a `try` that can fail, and a NameError raised while
        # computing an instrument would take the build down for the sake of a
        # counter.
        from syndicate.features.shared.layer2_board import (
            _movement_is_tracked,
            movement_join_key as _movement_key,
        )

        published = shortlist.get("rows") or []
        eligible = [r for r in published if _movement_is_tracked(r.get("market"))]
        matched = sum(1 for r in eligible if _movement_key(r) in openings_index)
        shortlist["movement_eligible_rows"] = len(eligible)
        shortlist["movement_rows_matched"] = matched
    except Exception:
        # An instrument that can break the build is worse than no instrument.
        shortlist["movement_eligible_rows"] = -1
        shortlist["movement_rows_matched"] = -1
    if openings_error:
        shortlist["openings_error"] = openings_error

    # PER-SPORT HEALTH OF THE ROWS ACTUALLY PUBLISHED (`#505`).
    #
    # Every counter above describes a STAGE — the join, the ledger, the grid.
    # None of them describes THE BOARD, and three separate user reports on
    # 2026-08-22 were about the board: stale lines, blank projections, no
    # movement. Each was answerable only by eyeballing the served page, which
    # is the position `#296` exists to prevent.
    #
    # Counted over `shortlist["rows"]` — what a reader actually sees — and split
    # per sport, because soccer's answer and MLB's are different and a combined
    # number hides both.
    try:
        # Imported here for the same reason the movement helpers are: a
        # NameError raised while computing an instrument must not take the
        # build down.
        from syndicate.features.shared.layer2_board import (
            _row_quote_age_seconds as _row_quote_age,
        )

        published_rows = shortlist.get("rows") or []
        health: dict[str, dict[str, object]] = {}
        ages_by_sport: dict[str, list[float]] = {}
        for row in published_rows:
            slug = str(row.get("sport") or "?").strip().lower() or "?"
            bucket = health.setdefault(
                slug,
                {"rows": 0, "pregame_proj": 0, "live_proj": 0, "no_proj": 0, "edged": 0, "live_rows": 0},
            )
            bucket["rows"] = int(bucket["rows"]) + 1  # type: ignore[call-overload]
            projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else None
            basis = str((projection or {}).get("basis") or "").strip()
            if not projection:
                bucket["no_proj"] = int(bucket["no_proj"]) + 1  # type: ignore[call-overload]
            elif basis == "live_resim":
                bucket["live_proj"] = int(bucket["live_proj"]) + 1  # type: ignore[call-overload]
            else:
                bucket["pregame_proj"] = int(bucket["pregame_proj"]) + 1  # type: ignore[call-overload]
            if (projection or {}).get("edge_vs_market_pct") is not None:
                bucket["edged"] = int(bucket["edged"]) + 1  # type: ignore[call-overload]
            # `age_seconds` IS NOT ON A PUBLISHED ROW. The first reading came
            # back `age_p50s=None` on all four sports, which read as "no ages"
            # and actually meant "wrong field". The grid row has
            # `age_seconds`; the BOARD row carries it under
            # `quote.book_age_seconds` / `quote.quote_seen_age_seconds`, and
            # `_row_quote_age_seconds` is the existing resolver that prefers
            # seen-age and falls back to book age. Reusing it rather than
            # reaching into `quote` here, so the staleness the board REPORTS
            # and the staleness its own max-age gate ENFORCES cannot diverge.
            age = _row_quote_age(row)
            if age is not None:
                ages_by_sport.setdefault(slug, []).append(float(age))
            # WHY `live_proj` IS ZERO — the counter alone cannot say whether no
            # live row reached the board or live rows reached it unprojected.
            # Measured 2026-08-22 20:1xZ: `live_proj=0` on ALL FOUR sports
            # including MLB, whose live re-sim demonstrably works, so the
            # distinction decides whether this is a projection failure or a
            # SELECTION one (a live row with no edge is dropped by the A3
            # filter before it is ever published).
            if str(row.get("market_state") or "").strip().lower() == "live":
                bucket["live_rows"] = int(bucket.get("live_rows") or 0) + 1  # type: ignore[call-overload]
        for slug, bucket in health.items():
            ages = sorted(ages_by_sport.get(slug) or [])
            if ages:
                # p50/p90/max rather than a mean: one dead line among fresh ones
                # barely moves a mean, and a dead line is exactly the complaint.
                bucket["age_p50_s"] = int(ages[len(ages) // 2])
                bucket["age_p90_s"] = int(ages[min(len(ages) - 1, int(len(ages) * 0.9))])
                bucket["age_max_s"] = int(ages[-1])
        for slug, bucket in sorted(health.items()):
            print(
                f"[layer2_shortlist] LAYER2_BOARD_HEALTH sport={slug} "
                f"rows={bucket.get('rows')} "
                f"pregame_proj={bucket.get('pregame_proj')} "
                f"live_proj={bucket.get('live_proj')} "
                f"no_proj={bucket.get('no_proj')} "
                f"live_rows={bucket.get('live_rows')} "
                f"edged={bucket.get('edged')} "
                f"age_p50s={bucket.get('age_p50_s')} "
                f"age_p90s={bucket.get('age_p90_s')} "
                f"age_maxs={bucket.get('age_max_s')} "
                # Cross-sport, stated as such so nobody reads them as this
                # sport's: they are computed once over the whole shortlist.
                f"all_openings_loaded={shortlist.get('openings_loaded')} "
                f"all_movement_eligible={shortlist.get('movement_eligible_rows')} "
                f"all_movement_matched={shortlist.get('movement_rows_matched')}",
                flush=True,
            )
        shortlist["board_health_by_sport"] = health
    except Exception:
        pass

    # RECORD THE OPENING PRICE OF EVERY ROW WE ARE ABOUT TO PUBLISH (audit §7 #1).
    #
    # The comment above says settlement needs a record of what was RECOMMENDED.
    # It does, and until now that record existed in exactly one place --
    # `evaluation_ledger_chunks/<date>.jsonl` -- which is unreadable in
    # practice. Measured 2026-08-14: its 2026-08-05 chunk is 367,229,260 bytes
    # and refresh-worker SKIPS it (`SKIP_OVERSIZED_LEDGER_CHUNK ...
    # ceiling=256000000`), and 19 of the 21 dates in the window do not exist at
    # all. Meanwhile the CLOSE for those same markets is recoverable for ~100%
    # of them from odds history. So the opening was the missing half, and every
    # build that published rows without recording them lost that day's CLV
    # permanently. Unrecorded is unrecoverable.
    #
    # HERE rather than in `intelligence_state`, because both the heavy path and
    # `_refresh_layer2_shortlist_only` reach the board through this function --
    # wiring the two call sites separately is how one of them silently stops
    # recording. First-sighting-only, so this appends the number of NEW markets
    # per day (kilobytes), not one row per tick.
    #
    # Never raises, per this function's contract: a board that already works
    # must not be taken down by instrumentation added beside it.
    try:
        from syndicate.features.shared.clv_opening_ledger import (
            opening_ledger_enabled,
            record_openings,
        )

        if opening_ledger_enabled():
            shortlist["clv_openings"] = record_openings(
                shortlist.get("rows") or [], date=str(selected_date or "")
            )
    except Exception as exc:
        shortlist["clv_openings_error"] = f"{type(exc).__name__}: {exc}"
    return shortlist


# ---------------------------------------------------------------------------
# DEFINED AT THE END OF THE MODULE ON PURPOSE.
#
# `tests/test_shortlist_enrichment_parity.py::test_the_state_correction_runs_
# before_projections` pins `#413`'s ordering rule by finding the FIRST
# `attach_projections(` CALL in this file and requiring it to come after
# `attach_live_game_state_from_lens(`. `live_edge_policy` reads the state the
# correction writes, so stamping projections first would leave a settled game's
# edges standing.
#
# The enrichment tuple's order is unchanged and still correct -- but a helper
# defined ABOVE that tuple puts an `attach_projections(` call earlier in the
# source than the state correction, and the guard reads source order. It failed
# exactly that way when this helper sat above `build_layer2_shortlist`. Keeping
# the definition down here keeps the guard measuring what it means to measure
# instead of being weakened to accommodate a helper.
# ---------------------------------------------------------------------------
def _attach_projections_over_window(
    grid: list,
    *,
    sport: str,
    selected_date: str,
    window_dates: Iterable[str],
) -> dict[str, Any]:
    """`attach_projections` across every date the grid's rows came from.

    See the call site for why. Summing rather than replacing matters: a caller
    reading `rows_with_projection` off the last date alone would report a
    fraction of the window and look like a partial join.

    A per-date failure is recorded and skipped rather than raised -- the
    enrichment loop already treats an exception as fatal to the step, and
    losing six dates because one shard is unreadable is the failure mode
    `#379` fixed on the quote side.
    """
    from syndicate.features.shared.board_enrichment import attach_projections

    dates = [str(d)[:10] for d in (window_dates or []) if str(d or "").strip()]
    if selected_date and selected_date[:10] not in dates:
        dates.insert(0, selected_date[:10])
    if not dates:
        dates = [selected_date]

    merged: dict[str, Any] = {}
    per_date: dict[str, Any] = {}
    errors: dict[str, str] = {}
    summable = ("rows_considered", "rows_with_projection", "rows_with_true_probability")

    for date_key in dates:
        try:
            coverage = attach_projections(grid, sport=sport, selected_date=date_key)
        except Exception as exc:  # noqa: BLE001 - one bad date must not lose the rest
            errors[date_key] = f"{type(exc).__name__}: {exc}"
            continue
        if not isinstance(coverage, Mapping):
            continue
        # The per-date REASON is kept alongside the counts, not just the
        # counts: "which dates were empty and why" is the whole diagnostic
        # value of a windowed join, and a summed zero cannot express it.
        per_date[date_key] = {k: coverage.get(k) for k in summable if coverage.get(k) is not None}
        if coverage.get("reason"):
            per_date[date_key]["reason"] = coverage.get("reason")
        for key, value in coverage.items():
            if key in summable and isinstance(value, (int, float)):
                merged[key] = (merged.get(key) or 0) + value
            elif key not in merged or merged.get(key) in (None, 0, False, ""):
                merged[key] = value

    if len(dates) > 1:
        merged["window_dates"] = list(dates)
        merged["per_date"] = per_date
    if errors:
        merged["date_errors"] = errors
    # A window that produced nothing anywhere must not inherit the LAST date's
    # reason as though it were the whole story -- that is how "no projections
    # for this date" came to describe a seven-date window.
    if len(dates) > 1 and not merged.get("rows_with_projection"):
        reasons = {str(v.get("reason")) for v in per_date.values() if isinstance(v, Mapping) and v.get("reason")}
        # OVERWRITE, not `or`. The per-date reason is inherited into `merged`
        # by the copy loop above, and keeping it is precisely the bug: "no
        # NCAAF SmartSim2 projections for this date" is what a seven-date
        # window reported on production, naming a date when the question was
        # about a window. The per-date reasons are preserved below.
        merged["reason"] = f"no projections across {len(dates)} window dates"
        if reasons:
            merged["reasons_by_date"] = sorted(reasons)
    return merged
