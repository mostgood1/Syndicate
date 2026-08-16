"""L1 board — ONE sport-generic presentation of the Layer 1 market grid (`#329`).

WHY THIS EXISTS. Layer 1 had eight implementations of the same idea. Measured on
production 2026-08-10, `/<sport>/api/market-board` against `/api/board/book-grid`
for the same date:

    sport    page  api    games  board rows   grid rows
    mlb       200  200       10         531         839
    nba       200  200        0           0           0   out of season
    wnba      200  200        2         228         202
    nhl       404  404        -           -           0   NO ROUTE AT ALL
    nfl       200  200       16          84       1,381   16x gap
    ncaaf     200  200       16           0           0   games, zero rows
    ncaab     404  404        -           -           0   NO ROUTE AT ALL
    soccer    200  200        1           1           7

Six bespoke builders (`build_mlb_market_board`, `build_nba_market_board`,
`build_ncaaf_market_board`, `build_nfl_market_board`,
`build_nfl_preseason_market_board`, `build_soccer_market_board`,
`build_wnba_market_board`) and two sports with nothing. Adding a seventh and
eighth builder would have made the divergence permanent.

The grid is already sport-generic -- `/api/board/book-grid?sport=` serves all
eight from one code path -- and `layer2_board.build_layer2_rows` ALREADY consumes
it. So the grid is Layer 1's row contract in fact, and the per-sport boards are a
*view* of it. This module is that view, written once.

THE ROW MODEL IS THE GRID'S, AND THAT IS THE POINT
--------------------------------------------------
A grid row is one market INSTANCE with every side on it (`sides`, `cells[book][side]`,
`best`, `consensus`). The per-sport boards emit one row per side instead, so a
total arrives as two rows both stamped `model_side: "over"`. Merging them is the
difference between "over 8.5 at -101 / under 8.5 at -119, six books" being one
readable line and being two rows you have to pair up by eye.

The vocabularies also disagree, three ways, and translating them is `#329`'s job
rather than something each consumer redoes:

    concept        grid              per-sport board
    game vs prop   kind              market_type
    period         segment "full"    period "full_game"
    market name    h2h / totals      Moneyline / Total

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not fetch, and it does not compute a projection. It reshapes an ALREADY
ENRICHED grid -- `board_enrichment` attaches `game`, `projection` and
`modelled_fair` upstream (`#328`), and a grid that arrives without them produces
a board that says so rather than one that looks sim-less.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

# THE SHARD IS KEYED BY CAPTURE DATE, NOT BY GAME DATE, and that difference is
# visible on the board. `book_quotes/<date>.jsonl` holds every quote OBSERVED
# that day, including quotes for fixtures weeks out, so a grid built from it is
# "what we saw today", not "today's slate".
#
# Measured 2026-08-10 by running this builder over the live production grid:
# NFL's 1,381 rows grouped into **288 games**, because preseason capture covers
# the whole forward schedule. MLB looked right (10 games) only because MLB
# captures today's slate and little else -- so the defect was invisible on the
# reference sport and obvious on the next one.
#
# Rows for other dates are EXCLUDED and COUNTED, never silently dropped: a board
# that quietly discards rows and a board whose sport genuinely has no slate are
# the same empty board otherwise.
_BOARD_TZ = os.environ.get("SYNDICATE_BOARD_TZ", "America/Chicago")

# SCHEDULING CADENCE, DECLARED — and the honest note about why it is declared.
#
# I set out to derive the window from the fixture calendar and could not, which
# is worth recording so nobody spends the afternoon I did. Every clustering rule
# fails on one sport or the other:
#
#   maximal run of consecutive game days   MLB plays daily, so the run is the
#                                          whole season
#   block bounded by a day with no games   splits NFL's own week: Thu has games,
#                                          Fri and Sat do not, Sun does
#   gap <= median inter-fixture gap        same two failures, one parameter later
#
# The reason is that MLB's window is one day because that is the useful unit,
# not because the schedule says so -- part of this is a product decision wearing
# a scheduling question's clothes, and inferring it would be arbitrary dressed as
# principled. A schedule-week field WOULD settle it, but neither the grid rows
# nor `build_game_chips` carries one; only the per-sport schedule artifacts do,
# which is the per-sport plumbing this module exists to remove.
#
# So the widths are declared, and MEASURED rather than guessed: taken from the
# fixture dates actually present in production grids on 2026-08-10. What is NOT
# declared is any week NUMBER -- the window is anchored on a date and counted in
# days, so nothing here reads `current_week.json`, which the NFL refresh runner
# rewrites and which `#274` (NFL three weeks from vanishing) and the "week
# self-pins to 1" finding both trace back to.
#
# Overridable per request. A wrong width here shows the wrong days, which is
# visible and cheap; a wrong week number shows an empty board, which is not.
_SLATE_WINDOW_DAYS = {
    "mlb": 1,
    "nba": 1,
    "wnba": 1,
    "nhl": 1,
    # SEVEN, not five, and the number is measured rather than reasoned.
    #
    # Five was "Thu through Mon", taken from where the REGULAR season's fixture
    # dates cluster (Thu/Sun/Mon). It is correct for that and silently wrong for
    # the preseason, whose week runs Fri/Sat/Sun/Mon and which is reached from a
    # Sunday anchor at +5 days -- exactly one day past the edge of a 5-day
    # forward window.
    #
    # Measured against the real schedules on 2026-08-16 (a Sunday), counting
    # games actually inside the window:
    #
    #     width  preseason games   regular season from Thu 2026-09-10
    #       5          1           09-10, 09-13, 09-14
    #       7         15           09-10, 09-13, 09-14      <- unchanged
    #       9         17           ...plus 09-17, the NEXT Thursday
    #
    # So 7 is the only width that gains the preseason slate WITHOUT pulling a
    # second regular-season week onto a "today" board. Nine would: the NFL week
    # is 7 days, so any window wider than 7 anchored on a Thursday reaches the
    # following Thursday's games. Over-inclusion is not free here -- `#329`'s
    # notes record 1,244 NFL rows starting 34-156 days out reaching a today
    # board once already.
    #
    # This does NOT fix NFL's empty board on its own. As of this change the
    # 08-16..08-22 window is quoted for zero of those 15 games; whether that is
    # a capture gap or a vendor that has not posted week-3 lines is the open
    # question the `[nfl_preseason] events_fetched` instrument now answers. The
    # width was a SECOND, independent reason those games could not appear, and
    # it is the half that needed no vendor answer.
    "nfl": 7,
    # Thu through Sat.
    "ncaaf": 3,
    "ncaab": 1,
    # Soccer's own board has been week-scoped since 2026-07-24 for a reason its
    # module records: the odds feed is a single rolling file covering every
    # upcoming fixture days ahead of kickoff, and one date's recommendations
    # snapshot can be empty while the adjacent one covers both days.
    "soccer": 7,
}
_DEFAULT_SLATE_WINDOW_DAYS = 1


def max_slate_window_days() -> int:
    """The widest window any sport asks for.

    Public so the worker can size its forward artifact builds from the SAME
    table the board reads, rather than restating the number. A producer that
    builds four days while the consumer asks for seven is the drift this module
    exists to remove, and it would reappear here first.
    """
    return max(_SLATE_WINDOW_DAYS.values())


def slate_window_days(sport: str) -> int:
    return _SLATE_WINDOW_DAYS.get(str(sport or "").strip().lower(), _DEFAULT_SLATE_WINDOW_DAYS)


def resolve_window_dates(sport: str, anchor_date: str, *, window: str | int = "day") -> list[str]:
    """The dates this board covers, forward from the anchor.

    FORWARD ONLY, deliberately. A board is what you can still bet; yesterday's
    fixtures belong to the archive, and a symmetric window would put settled
    games on the pregame board of a sport whose slate spans days.
    """
    try:
        start = datetime.strptime(str(anchor_date).strip(), "%Y-%m-%d").date()
    except ValueError:
        return [str(anchor_date).strip()]

    if isinstance(window, int) or str(window).isdigit():
        span = max(1, int(window))
    elif str(window).strip().lower() == "slate":
        span = slate_window_days(sport)
    else:
        span = 1
    return [(start + timedelta(days=offset)).isoformat() for offset in range(span)]

# The three states a game can be in, plus the one that matters most here.
#
# `unknown` IS A STATE, not a synonym for pregame. A row whose game state failed
# to join has an unknown state, and folding it into `pregame` would put a
# possibly-settled market on the pregame board -- which is exactly the defect
# `#298`/`#300` fixed for the staleness floor ("an unknown game state must FAIL
# the floor, not skip it"). The same rule applies to routing: unknown must land
# in its own bucket, be counted, and be visible.
BOARD_STATES = ("live", "pregame", "final", "unknown")


def _row_state(row: Mapping[str, Any]) -> str:
    game = row.get("game")
    if not isinstance(game, dict):
        return "unknown"
    state = str(game.get("state") or "").strip().lower()
    return state if state in BOARD_STATES else "unknown"


def _row_is_enriched(row: Mapping[str, Any]) -> bool:
    return isinstance(row.get("game"), dict)


def _odds_freshness(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How old the ODDS are, which is not how old the BOARD is (`#430`).

    THE DEFECT THIS ANSWERS, measured on production 2026-08-14 15:00Z, MLB:
    the artifact's `generated_at` was 14:58:49Z -- 1.6 minutes old -- and the
    board header said so. The freshest quote observation across all 14 games was
    **13:09Z, 1h51m earlier**. A reader looking at "built 2m old" has no way to
    learn that, and the number they need is the one that is missing.

    TWO CLOCKS, AND THE RIGHT ONE IS THE SECOND. `book_grid` computes both and
    its docstring already explains why they differ:

        age_seconds       time since this price last MOVED
        seen_age_seconds  time since we last LOOKED at this market

    `book_quotes` is a change log, so a motionless pregame market reads as hours
    old on the first clock while being perfectly current -- 424-minute NFL
    medians were once read as a capture outage and were nothing of the kind.
    "How old are the odds we have from the last odds refresh" is the SECOND
    clock, so that is what leads here. The first is carried alongside, labelled,
    because a board where nothing has moved in an hour is still worth seeing.

    RELATIVE TO THE BUILD, NOT TO NOW. Both ages were computed against the
    worker's clock at artifact-build time, so a stored 30s in an artifact built
    seven minutes ago means the odds are 7.5 minutes old. This returns the
    build-relative numbers unchanged and leaves the re-anchoring to the caller,
    which is the only layer that knows `generated_at`. Getting that backwards
    would understate every age by exactly the artifact's own age.

    ABSENT IS UNKNOWN, NEVER FRESH. Rows predating last-seen tracking carry no
    `seen_age_seconds` at all, and `rows_missing_seen_age` is reported rather
    than silently excluded: a board whose only datable row is also its freshest
    is a different claim from one where every row agrees.
    """
    seen: list[float] = []
    moved: list[float] = []
    missing_seen = 0
    for row in rows:
        raw_seen = row.get("seen_age_seconds")
        if isinstance(raw_seen, (int, float)) and not isinstance(raw_seen, bool):
            seen.append(float(raw_seen))
        else:
            missing_seen += 1
        raw_moved = row.get("age_seconds")
        if isinstance(raw_moved, (int, float)) and not isinstance(raw_moved, bool):
            moved.append(float(raw_moved))

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    return {
        # MIN is the headline: the single freshest look anywhere on the board.
        # It is the most GENEROUS reading available, which is deliberate -- if
        # even the best row is two hours old, no qualifier rescues the board.
        "seen_age_seconds_min": min(seen) if seen else None,
        # And the median, because one fresh row does not make a fresh board.
        # These were identical on the 08-14 capture (6576.8 both), which is
        # itself the finding: the whole board refreshes in one sweep, so the
        # min is not a lucky row -- it is the sweep.
        "seen_age_seconds_median": _median(seen),
        "seen_age_seconds_max": max(seen) if seen else None,
        "rows_with_seen_age": len(seen),
        "rows_missing_seen_age": missing_seen,
        # The other clock, never mixed into the fields above.
        "price_move_age_seconds_min": min(moved) if moved else None,
    }


def _game_key(row: Mapping[str, Any]) -> str:
    """Group rows into games.

    `event_id` first because it is the grid's own identity and both game lines
    and player props on the same fixture carry it. The team pair is the fallback
    for any producer that omits it -- never a synthesized id, because two rows
    that fall back to different keys would split one game into two cards and the
    board would look like it had more fixtures than the slate.
    """
    event_id = str(row.get("event_id") or "").strip()
    if event_id:
        return event_id
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    if away or home:
        return f"{away}@{home}"
    return "unknown_game"


def _card_for(row: Mapping[str, Any]) -> dict[str, Any]:
    game = row.get("game") if isinstance(row.get("game"), dict) else {}
    return {
        "event_id": str(row.get("event_id") or "") or None,
        "away_team": row.get("away_team"),
        "home_team": row.get("home_team"),
        # `sport` is not the competition for soccer: ten leagues share the slug.
        # None for every other sport, where the sport IS the competition.
        "league": row.get("league"),
        "matchup": game.get("matchup") or _fallback_matchup(row),
        "state": _row_state(row),
        "start_time_utc": game.get("start_time_utc") or row.get("commence_time"),
        "status_token": game.get("status_token"),
        "away_score": game.get("away_score"),
        "home_score": game.get("home_score"),
        # Counted, not listed: a card is a summary and the rows are right there.
        "market_count": 0,
        "game_market_count": 0,
        "prop_market_count": 0,
        "rows_with_projection": 0,
    }


def _row_local_date(row: Mapping[str, Any], tz_name: str) -> str | None:
    """The row's game date in the board's timezone, or None if unknowable.

    Reads `game.start_time_utc` first (the scoreboard's own kickoff, joined by
    `attach_game_state`) and falls back to the grid's `commence_time`. None when
    neither parses -- and an unknown date is NEVER treated as "matches", because
    a row that cannot be dated would then appear on every date's board.
    """
    game = row.get("game") if isinstance(row.get("game"), dict) else {}
    raw = str(game.get("start_time_utc") or row.get("commence_time") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _fallback_matchup(row: Mapping[str, Any]) -> str | None:
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    if away and home:
        return f"{away} @ {home}"
    return None


def _classify_enrichment(
    *,
    coverage: Mapping[str, Any] | None,
    rows: int,
    enriched_rows: int,
    projected_rows: int,
) -> tuple[str, dict[str, Any]]:
    """What the enrichment actually did — READ FROM THE COVERAGE, not inferred.

    THIS FUNCTION EXISTS BECAUSE THE INFERENCE WAS WRONG, and wrong in the exact
    way `#328` was written to prevent. The first version decided "not enriched"
    from the absence of a `game` key on the rows. Measured on production
    2026-08-10, NFL reported `grid_not_enriched` — and the enrichment had run
    perfectly:

        game_state    {"chips": 0, "reason": "no_chips_for_date", "rows_matched": 0}
        projections   {"supported": false, "reason": "no projection source wired for nfl"}

    Zero chips because NFL's slate is in September. `attach_game_state` only
    stamps `game` on a row it MATCHES, so a correct run over a sport with no
    fixtures today leaves every row bare — indistinguishable, from the rows
    alone, from an artifact written before the enrichment existed.

    That is the same defect `#328`'s commit message names: "written before
    anything joined" and "joined, found nothing" must not serialize identically.
    I asserted the rule for the artifact and then broke it one layer up, by
    inferring from a payload instead of reading the report that was sitting
    right there.

    So: the coverage dicts decide. Their ABSENCE is the only thing that means
    "not enriched", and that is a fact about the artifact, not about the rows.
    """
    detail: dict[str, Any] = {}
    if rows == 0:
        return "no_rows", detail

    if not isinstance(coverage, Mapping) or not coverage:
        # No coverage report. Only claim "predates" when the ROWS agree there is
        # no evidence either way -- an enriched row is proof the enrichment ran,
        # whatever the caller did or did not thread through, and reporting
        # "predates enrichment" over rows that visibly carry `game` would be the
        # same over-claim in the opposite direction.
        if enriched_rows == 0:
            return "artifact_predates_enrichment", detail
        detail["coverage"] = "absent_inferred_from_rows"
        return ("enriched" if projected_rows > 0 else "enriched_no_projections"), detail

    game_state = coverage.get("game_state") if isinstance(coverage.get("game_state"), Mapping) else {}
    projections = coverage.get("projections") if isinstance(coverage.get("projections"), Mapping) else {}
    margin = coverage.get("margin_model") if isinstance(coverage.get("margin_model"), Mapping) else {}

    if game_state.get("reason"):
        detail["game_state_reason"] = game_state.get("reason")
    if projections.get("reason"):
        detail["projection_reason"] = projections.get("reason")
    detail["rows_matched_game_state"] = game_state.get("rows_matched")
    detail["rows_modelled_fair"] = margin.get("rows_modelled")

    # An unwired sport is NOT a failure and must not read as one. NFL has no
    # predictions artifacts of any kind in production -- fixing it means
    # producing a sim, not repairing a join -- and a board that says "no
    # projection source wired" sends that work to the right place, while
    # "enriched_no_projections" sends someone to debug a join that is fine.
    if projections.get("supported") is False:
        return "no_projection_source_for_sport", detail

    if projected_rows > 0:
        return "enriched", detail
    if enriched_rows > 0:
        return "enriched_no_projections", detail
    # Enrichment ran, matched nothing at all. Real, and different from both
    # "never ran" and "ran and found some": usually a slate that is not today's.
    return "enriched_no_matches", detail


def build_layer1_board(
    grid: Iterable[Mapping[str, Any]],
    *,
    sport: str,
    selected_date: str,
    grid_absent_reason: str | None = None,
    window_dates: Iterable[str] | None = None,
    league: str | None = None,
    coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Group an enriched grid into per-game cards, partitioned by game state.

    `grid_absent_reason` is threaded from the caller rather than guessed at.
    A SPORT WITH NO ROWS MUST SAY WHY (`#296`): out of season, no shard captured,
    and "the join dropped everything" are three different facts that render as
    the same empty board, and only the caller knows which one it is.
    """
    all_rows = [row for row in grid if isinstance(row, Mapping)]

    # Date scoping, before anything else. See `_BOARD_TZ` -- the shard is keyed
    # by capture date, so "every row in today's shard" is not "today's slate".
    wanted_dates = [str(d).strip() for d in (window_dates or [selected_date]) if str(d).strip()]
    wanted = set(wanted_dates)
    wanted_league = str(league or "").strip().lower() or None

    rows: list[Mapping[str, Any]] = []
    other_dates: dict[str, int] = {}
    undated_rows = 0
    filtered_by_league = 0
    for row in all_rows:
        row_date = _row_local_date(row, _BOARD_TZ)
        if row_date is None:
            # Undated rows are held OUT, not let through. A row that cannot be
            # dated would otherwise appear on every date's board at once.
            undated_rows += 1
            continue
        if wanted and row_date not in wanted:
            other_dates[row_date] = other_dates.get(row_date, 0) + 1
            continue
        if wanted_league is not None:
            # A row with NO league cannot satisfy a league filter. Letting it
            # through would make "EPL" quietly mean "EPL plus everything we
            # failed to label", which is the permissive-on-unknown trap -- and
            # soccer rows were unlabelled entirely until `#330`, so this is the
            # exact case that would have slipped through.
            if str(row.get("league") or "").strip().lower() != wanted_league:
                filtered_by_league += 1
                continue
        rows.append(row)

    cards: dict[str, dict[str, Any]] = {}
    rows_by_game: dict[str, list[Mapping[str, Any]]] = {}
    state_counts = {state: 0 for state in BOARD_STATES}
    enriched_rows = 0
    projected_rows = 0

    for row in rows:
        key = _game_key(row)
        if key not in cards:
            cards[key] = _card_for(row)
            rows_by_game[key] = []
        card = cards[key]
        rows_by_game[key].append(row)

        card["market_count"] += 1
        if str(row.get("kind") or "").lower() == "prop":
            card["prop_market_count"] += 1
        else:
            card["game_market_count"] += 1
        if isinstance(row.get("projection"), dict):
            card["rows_with_projection"] += 1
            projected_rows += 1
        if _row_is_enriched(row):
            enriched_rows += 1

    league_counts: dict[str, int] = {}
    for key, card in cards.items():
        state_counts[card["state"]] += 1
        # Counted per GAME, not per row: 166 prop markets on one fixture is one
        # fixture, and counting rows would make the league with the deepest prop
        # coverage look like it had the most matches.
        league = card.get("league")
        if league:
            league_counts[str(league)] = league_counts.get(str(league), 0) + 1

    games = [
        {**card, "rows": rows_by_game[key]}
        for key, card in sorted(
            cards.items(),
            # Live first, then pregame by start time, then everything else. A
            # board people read top-down should lead with the game that can move.
            key=lambda item: (
                {"live": 0, "pregame": 1, "unknown": 2, "final": 3}.get(item[1]["state"], 4),
                str(item[1].get("start_time_utc") or ""),
                str(item[1].get("matchup") or ""),
            ),
        )
    ]

    # The enrichment state of the WHOLE board, so a sim-less board is
    # attributable. `#328` made the grid carry projections; a grid that arrives
    # without them means the artifact predates that or the join found nothing,
    # and those must not render identically.
    enrichment, enrichment_detail = _classify_enrichment(
        coverage=coverage,
        rows=len(rows),
        enriched_rows=enriched_rows,
        projected_rows=projected_rows,
    )

    payload: dict[str, Any] = {
        "sport": str(sport or "").strip().lower(),
        "date": str(selected_date or "").strip(),
        "games": games,
        "counts": {
            "games": len(games),
            "rows": len(rows),
            "rows_enriched": enriched_rows,
            "rows_with_projection": projected_rows,
            "by_state": state_counts,
            # What the date scope removed, so a thin board is attributable to
            # scoping rather than read as a thin slate.
            "rows_in_grid": len(all_rows),
            "rows_other_dates": sum(other_dates.values()),
            "rows_undated": undated_rows,
            "rows_other_leagues": filtered_by_league,
        },
        "league_filter": wanted_league,
        # Which competitions are on this board, and how many fixtures each has.
        # For soccer this is the dimension the board is actually organised by --
        # "10 games" across EPL, MLS and the Bundesliga is three slates, not one
        # -- and a board that cannot name them can only offer a generic soccer
        # tab. Empty for single-competition sports rather than echoing the slug.
        "leagues": dict(
            sorted(
                ((name, count) for name, count in league_counts.items() if name),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
        "date_scope": {
            "timezone": _BOARD_TZ,
            # The window this board covers, listed rather than described: "5
            # days from the 10th" is a rule the reader has to apply, and the
            # dates are what they actually want to check a fixture against.
            "dates": wanted_dates,
            "window_days": len(wanted_dates),
            # Top few, so "which day did they belong to" is answerable without
            # dumping the whole distribution onto every response.
            "other_dates": dict(sorted(other_dates.items(), key=lambda kv: (-kv[1], kv[0]))[:7]),
        },
        "enrichment": enrichment,
        "enrichment_detail": enrichment_detail,
        # Computed over the DATE-SCOPED rows, not the whole grid. A 7-day soccer
        # window read from one artifact would otherwise report the freshness of
        # days the caller is not looking at.
        "odds_freshness": _odds_freshness(rows),
    }
    if not rows:
        # Never an empty list with no explanation. `#296`: a sport with no quotes
        # must say why, not vanish. "The grid was empty" and "the grid was full
        # of other days" are different facts with different fixes -- the first is
        # a capture question, the second is a scoping one -- so they get
        # different reasons even though both render as an empty board.
        if filtered_by_league and wanted_league:
            # A league filter that empties the board is a DIFFERENT fact from a
            # league with no fixtures: the first says this competition is not on
            # today's slate, the second says we have no odds for it at all.
            payload["empty_reason"] = f"no_rows_for_league:{wanted_league}"
        elif all_rows and not undated_rows:
            payload["empty_reason"] = "grid_rows_all_for_other_dates"
        elif all_rows:
            payload["empty_reason"] = "grid_rows_undated_or_other_dates"
        else:
            payload["empty_reason"] = grid_absent_reason or "no_grid_rows_for_sport_date"
    return payload


def partition_board_by_state(board: Mapping[str, Any], state: str) -> dict[str, Any]:
    """The pregame board and the live board, from one build.

    Two views over ONE payload rather than two fetches: they are the same slate
    filtered, and a game that goes live must LEAVE the pregame board in the same
    instant it joins the live one. Deriving both from a single grouping is what
    makes that atomic -- two independent queries can and will disagree across
    the transition, showing a game on both boards or neither.
    """
    wanted = str(state or "").strip().lower()
    if wanted not in BOARD_STATES:
        raise ValueError(f"unknown board state: {state!r}; expected one of {BOARD_STATES}")
    games = [game for game in (board.get("games") or []) if game.get("state") == wanted]
    out = dict(board)
    out["games"] = games
    out["view"] = wanted
    out["counts"] = {
        **(board.get("counts") or {}),
        "games_in_view": len(games),
        "rows_in_view": sum(len(game.get("rows") or []) for game in games),
    }
    # RECOMPUTED FOR THE VIEW, not inherited. `dict(board)` would carry the whole
    # slate's `odds_freshness` onto a filtered board, and the two genuinely
    # differ: live games are re-quoted on a tighter cadence than pregame ones, so
    # the full board's freshest look is frequently a live row that the pregame
    # view does not contain. Inheriting it would let the pregame board claim a
    # freshness that belongs to a game it is not showing.
    out["odds_freshness"] = _odds_freshness(
        [row for game in games for row in (game.get("rows") or []) if isinstance(row, Mapping)]
    )
    return out
