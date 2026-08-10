"""`#329` — the sport-generic Layer 1 board, and the pregame/live split.

Eight sports had six bespoke market-board builders and two had no route at all
(NHL and NCAAB returned 404 on production 2026-08-10). These cover the parts
that were getting re-decided per sport: how rows group into games, what happens
to a row whose game state failed to join, and whether a game can appear on both
the pregame and the live board at once.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.layer1_board import (
    build_layer1_board,
    partition_board_by_state,
)


def _row(
    event_id="evt-1",
    state="pregame",
    kind="game",
    market="h2h",
    projection=None,
    commence_time="2026-08-10T23:07:00Z",
    **extra,
):
    row = {
        "sport": "mlb",
        "event_id": event_id,
        "kind": kind,
        "market": market,
        "segment": "full",
        "sides": ["away", "home"],
        "away_team": "Boston Red Sox",
        "home_team": "Toronto Blue Jays",
        "commence_time": commence_time,
    }
    if state is not None:
        # `start_time_utc` tracks `commence_time` rather than being pinned: in
        # production `attach_game_state` stamps the scoreboard's kickoff for the
        # SAME fixture, so a fixture where the two disagree tests a state that
        # cannot occur -- and would have hidden the date-scoping bug below.
        row["game"] = {
            "state": state,
            "start_time_utc": commence_time,
            "matchup": "BOS @ TOR",
            "status_token": None,
            "away_score": None,
            "home_score": None,
        }
    if projection is not None:
        row["projection"] = projection
    row.update(extra)
    return row


def test_rows_group_into_one_card_per_game():
    board = build_layer1_board(
        [_row(market="h2h"), _row(market="totals"), _row(market="batter_hits", kind="prop")],
        sport="mlb",
        selected_date="2026-08-10",
    )
    assert board["counts"]["games"] == 1
    card = board["games"][0]
    assert card["market_count"] == 3
    assert card["game_market_count"] == 2
    assert card["prop_market_count"] == 1
    assert card["matchup"] == "BOS @ TOR"


def test_unknown_game_state_is_its_own_bucket_not_pregame():
    # An unresolved game state must NOT ride onto the pregame board. #298/#300
    # established the rule for the staleness floor -- unknown must FAIL, not skip
    # -- and routing is the same decision: a settled market whose state failed to
    # join would otherwise sit on the pregame board looking bettable.
    board = build_layer1_board(
        [_row(event_id="evt-known", state="pregame"), _row(event_id="evt-orphan", state=None)],
        sport="mlb",
        selected_date="2026-08-10",
    )
    assert board["counts"]["by_state"]["pregame"] == 1
    assert board["counts"]["by_state"]["unknown"] == 1

    pregame = partition_board_by_state(board, "pregame")
    assert [g["event_id"] for g in pregame["games"]] == ["evt-known"]


def test_a_live_game_leaves_the_pregame_board_in_the_same_instant():
    # The transition is the requirement: pregame and live are two views of ONE
    # grouping, so a game cannot be on both or neither. Two independent queries
    # would disagree across the flip; this asserts the partition is exhaustive
    # and disjoint over the same build.
    board = build_layer1_board(
        [
            _row(event_id="evt-live", state="live"),
            _row(event_id="evt-pre", state="pregame"),
            _row(event_id="evt-done", state="final"),
        ],
        sport="mlb",
        selected_date="2026-08-10",
    )
    live = {g["event_id"] for g in partition_board_by_state(board, "live")["games"]}
    pregame = {g["event_id"] for g in partition_board_by_state(board, "pregame")["games"]}
    final = {g["event_id"] for g in partition_board_by_state(board, "final")["games"]}

    assert live == {"evt-live"}
    assert pregame == {"evt-pre"}
    assert live & pregame == set()
    assert live | pregame | final == {"evt-live", "evt-pre", "evt-done"}


def test_live_games_sort_above_pregame():
    board = build_layer1_board(
        [_row(event_id="evt-pre", state="pregame"), _row(event_id="evt-live", state="live")],
        sport="mlb",
        selected_date="2026-08-10",
    )
    assert [g["event_id"] for g in board["games"]] == ["evt-live", "evt-pre"]


def test_an_empty_sport_says_why_rather_than_vanishing():
    # #296: a sport with no quotes must say why, not vanish. Out of season, no
    # shard captured, and "the join dropped everything" render as the same empty
    # board, and only the caller knows which it is -- so the reason is threaded
    # in, never guessed.
    board = build_layer1_board([], sport="nhl", selected_date="2026-08-10", grid_absent_reason="no_shard_for_sport_date")
    assert board["games"] == []
    assert board["empty_reason"] == "no_shard_for_sport_date"
    assert board["enrichment"] == "no_rows"


def test_empty_sport_without_a_stated_reason_still_carries_one():
    board = build_layer1_board([], sport="ncaab", selected_date="2026-08-10")
    assert board["empty_reason"] == "no_grid_rows_for_sport_date"


def test_enrichment_state_distinguishes_unenriched_from_no_opinion():
    # The three cases must not render identically. A pre-#328 artifact (no
    # `game` key at all) is not the same fact as an enriched grid whose sim has
    # no opinion on this slate, and neither is the same as a working board.
    #
    # `grid_not_enriched` was the old name AND the old inference -- decided from
    # the absence of a `game` key, which mislabelled a correct NFL run. The
    # state survives under a name that says what it is a fact about (the
    # artifact), and is now only claimed when the rows carry no evidence either.
    unenriched = build_layer1_board([_row(state=None)], sport="mlb", selected_date="2026-08-10")
    assert unenriched["enrichment"] == "artifact_predates_enrichment"

    no_projection = build_layer1_board([_row(state="pregame")], sport="mlb", selected_date="2026-08-10")
    assert no_projection["enrichment"] == "enriched_no_projections"

    working = build_layer1_board(
        [_row(state="pregame", projection={"projected": 0.61, "side": "away"})],
        sport="mlb",
        selected_date="2026-08-10",
    )
    assert working["enrichment"] == "enriched"
    assert working["counts"]["rows_with_projection"] == 1


def test_rows_keep_the_grids_merged_over_under_shape():
    # The reason to build on the grid at all: one row carries BOTH sides. The
    # per-sport boards emit a total as two rows both stamped model_side "over",
    # which the user has to pair up by eye.
    board = build_layer1_board(
        [_row(market="totals", line=8.5, sides=["over", "under"], cells={"draftkings": {"over": {"price": -101}, "under": {"price": -119}}})],
        sport="mlb",
        selected_date="2026-08-10",
    )
    row = board["games"][0]["rows"][0]
    assert row["sides"] == ["over", "under"]
    assert row["cells"]["draftkings"]["over"]["price"] == -101
    assert row["cells"]["draftkings"]["under"]["price"] == -119


def test_rows_without_event_id_fall_back_to_the_team_pair():
    board = build_layer1_board(
        [_row(event_id="", market="h2h"), _row(event_id="", market="totals")],
        sport="nhl",
        selected_date="2026-08-10",
    )
    # One card, not two: a synthesized-per-row key would split one game in half
    # and the board would claim more fixtures than the slate has.
    assert board["counts"]["games"] == 1


def test_partition_rejects_an_unknown_view():
    board = build_layer1_board([_row()], sport="mlb", selected_date="2026-08-10")
    with pytest.raises(ValueError):
        partition_board_by_state(board, "prematch")


def test_rows_for_other_dates_are_excluded_and_counted():
    # The shard is keyed by CAPTURE date, so "every row in today's shard" is not
    # "today's slate". Measured on production 2026-08-10: NFL's 1,381 rows
    # grouped into 288 games because preseason capture covers the whole forward
    # schedule. Invisible on MLB, which captures little beyond today.
    board = build_layer1_board(
        [
            _row(event_id="today", commence_time="2026-08-10T23:07:00Z"),
            _row(event_id="next-week", commence_time="2026-08-17T23:07:00Z"),
            _row(event_id="next-week-2", commence_time="2026-08-17T20:00:00Z"),
        ],
        sport="nfl",
        selected_date="2026-08-10",
    )
    assert board["counts"]["games"] == 1
    assert board["counts"]["rows"] == 1
    assert board["counts"]["rows_in_grid"] == 3
    assert board["counts"]["rows_other_dates"] == 2
    assert board["date_scope"]["other_dates"] == {"2026-08-17": 2}


def test_an_undated_row_is_held_out_of_every_board():
    # A row that cannot be dated must not appear on every date at once. Unknown
    # is not a match.
    board = build_layer1_board(
        [_row(event_id="dateless", commence_time=None, game=None)],
        sport="mlb",
        selected_date="2026-08-10",
    )
    assert board["counts"]["rows"] == 0
    assert board["counts"]["rows_undated"] == 1
    assert board["empty_reason"] == "grid_rows_undated_or_other_dates"


def test_a_board_emptied_by_scoping_says_so_not_no_quotes():
    # "The grid was empty" is a capture question; "the grid was all other days"
    # is a scoping one. Same empty board, different fix, so different reason.
    board = build_layer1_board(
        [_row(event_id="future", commence_time="2026-09-01T23:07:00Z")],
        sport="nfl",
        selected_date="2026-08-10",
    )
    assert board["empty_reason"] == "grid_rows_all_for_other_dates"


def test_soccer_leagues_are_named_not_merged_into_one_sport():
    # Ten leagues share the `soccer` slug and the soccer_source tree, so `sport`
    # cannot say which competition a row belongs to. append_book_quotes stamps
    # `league` on every soccer quote; the pivot used to drop it, so all 922 rows
    # on 2026-08-16 read league=None and the board could only offer one generic
    # soccer tab.
    board = build_layer1_board(
        [
            _row(event_id="epl-1", league="epl"),
            _row(event_id="epl-1", market="totals", league="epl"),
            _row(event_id="mls-1", league="mls"),
            _row(event_id="bund-1", league="bundesliga"),
        ],
        sport="soccer",
        selected_date="2026-08-10",
    )
    # Per GAME, not per row: epl has two markets on one fixture, not two games.
    assert board["leagues"] == {"bundesliga": 1, "epl": 1, "mls": 1}
    assert {g["event_id"]: g["league"] for g in board["games"]} == {
        "epl-1": "epl",
        "mls-1": "mls",
        "bund-1": "bundesliga",
    }


def test_single_competition_sports_report_no_leagues():
    # MLB's competition IS its sport. Echoing the slug back as a league would
    # invent a dimension that does not exist and put a pointless tab on 7 boards.
    board = build_layer1_board([_row()], sport="mlb", selected_date="2026-08-10")
    assert board["leagues"] == {}
    assert board["games"][0]["league"] is None


def test_slate_window_is_forward_only_and_per_sport():
    from syndicate.features.shared.layer1_board import resolve_window_dates, slate_window_days

    # Forward only: a board is what you can still bet. A symmetric window would
    # put yesterday's settled games on a pregame board for any sport whose slate
    # spans days.
    assert resolve_window_dates("mlb", "2026-08-10", window="slate") == ["2026-08-10"]
    assert resolve_window_dates("nfl", "2026-08-10", window="slate") == [
        "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    ]
    assert resolve_window_dates("ncaaf", "2026-08-10", window="slate") == [
        "2026-08-10", "2026-08-11", "2026-08-12",
    ]
    assert len(resolve_window_dates("soccer", "2026-08-10", window="slate")) == 7
    # Explicit day counts override, and an unknown sport gets the safe single day.
    assert resolve_window_dates("nfl", "2026-08-10", window=2) == ["2026-08-10", "2026-08-11"]
    assert resolve_window_dates("kabaddi", "2026-08-10", window="slate") == ["2026-08-10"]
    assert slate_window_days("nfl") == 5


def test_a_window_keeps_fixtures_across_its_whole_span():
    board = build_layer1_board(
        [
            _row(event_id="thu", commence_time="2026-08-13T23:00:00Z"),
            _row(event_id="sun", commence_time="2026-08-16T17:00:00Z"),
        ],
        sport="nfl",
        selected_date="2026-08-13",
        window_dates=["2026-08-13", "2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"],
    )
    assert board["counts"]["games"] == 2
    assert board["date_scope"]["window_days"] == 5
    assert board["date_scope"]["dates"][0] == "2026-08-13"


def test_league_filter_excludes_and_counts_other_leagues():
    board = build_layer1_board(
        [_row(event_id="e1", league="epl"), _row(event_id="m1", league="mls")],
        sport="soccer",
        selected_date="2026-08-10",
        league="epl",
    )
    assert board["league_filter"] == "epl"
    assert [g["event_id"] for g in board["games"]] == ["e1"]
    assert board["counts"]["rows_other_leagues"] == 1


def test_league_filter_never_admits_an_unlabelled_row():
    # "EPL" must not quietly mean "EPL plus everything we failed to label".
    # Soccer rows carried no league at all until #330, so this is the exact case
    # that would have slipped through a permissive-on-unknown filter.
    board = build_layer1_board(
        [_row(event_id="unlabelled", league=None)],
        sport="soccer",
        selected_date="2026-08-10",
        league="epl",
    )
    assert board["counts"]["games"] == 0
    assert board["empty_reason"] == "no_rows_for_league:epl"


def test_enrichment_is_read_from_coverage_not_inferred_from_rows():
    # THE BUG THIS REPLACES. NFL reported `grid_not_enriched` on production
    # 2026-08-10 while its enrichment had run correctly and matched nothing:
    # zero chips because the slate is in September, and no projection source
    # wired at all. `attach_game_state` only stamps `game` on rows it MATCHES,
    # so a correct run over a sport with no fixtures leaves every row bare --
    # indistinguishable, from the rows alone, from a pre-#328 artifact.
    nfl_coverage = {
        "game_state": {"chips": 0, "reason": "no_chips_for_date", "rows_matched": 0},
        "projections": {"supported": False, "reason": "no projection source wired for nfl"},
    }
    board = build_layer1_board(
        [_row(state=None)], sport="nfl", selected_date="2026-08-10", coverage=nfl_coverage
    )
    # An unwired sport must not read as a broken join: the fix is producing a
    # sim, not repairing one, and the two send the work to different places.
    assert board["enrichment"] == "no_projection_source_for_sport"
    assert board["enrichment_detail"]["projection_reason"] == "no projection source wired for nfl"
    assert board["enrichment_detail"]["game_state_reason"] == "no_chips_for_date"


def test_absent_coverage_is_the_only_thing_meaning_not_enriched():
    # And it is a fact about the ARTIFACT, not about the rows.
    board = build_layer1_board([_row(state=None)], sport="mlb", selected_date="2026-08-10")
    assert board["enrichment"] == "artifact_predates_enrichment"


def test_enrichment_ran_and_matched_nothing_is_its_own_state():
    board = build_layer1_board(
        [_row(state=None)],
        sport="mlb",
        selected_date="2026-08-10",
        coverage={"game_state": {"chips": 4, "rows_matched": 0}, "projections": {"supported": True}},
    )
    assert board["enrichment"] == "enriched_no_matches"


def test_a_working_board_still_reads_enriched():
    board = build_layer1_board(
        [_row(state="pregame", projection={"projected": 0.61})],
        sport="mlb",
        selected_date="2026-08-10",
        coverage={"game_state": {"chips": 10, "rows_matched": 1}, "projections": {"supported": True}},
    )
    assert board["enrichment"] == "enriched"


def test_worker_forward_days_track_the_boards_own_window_table():
    # A producer that builds four days while the board asks for seven is exactly
    # the drift this module exists to remove, so the worker derives its forward
    # build count from THIS table rather than restating it.
    from syndicate.features.shared.layer1_board import max_slate_window_days, slate_window_days

    assert max_slate_window_days() == max(slate_window_days(s) for s in ("mlb", "nfl", "ncaaf", "soccer"))
    assert max_slate_window_days() == slate_window_days("soccer") == 7
