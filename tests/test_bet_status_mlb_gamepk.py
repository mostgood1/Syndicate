"""Recovering a StatsAPI gamePk from the matchup — the 100% grading blocker.

MEASURED IN PRODUCTION 2026-08-23T16:00:06Z:

    SETTLED date=2026-08-22 orders=58 graded=0 ungraded={'no_game_pk': 58}
    SETTLED date=2026-08-23 orders=45 graded=0 ungraded={'no_game_pk': 45}

The board row sets `game_pk` from `row.get("event_id")` — the OddsAPI hash, not
StatsAPI's numeric id. `int()` cannot parse a hash, so every bet was
unidentifiable and nothing could ever be graded.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_mlb as mod


def _game(pk, home, away, game_date="2026-08-22T23:10:00Z"):
    return {
        "gamePk": pk,
        "gameDate": game_date,
        "teams": {"home": {"team": {"name": home}}, "away": {"team": {"name": away}}},
    }


@pytest.fixture
def schedule(monkeypatch):
    games: list[dict] = []
    monkeypatch.setattr(
        "syndicate.features.mlb.cards._schedule_raw_games", lambda date: list(games)
    )
    return games


def _order(**kw):
    order = {
        "game_pk": None,
        "home_team": "Houston Astros",
        "away_team": "Seattle Mariners",
        "commence_time": "2026-08-22T23:10:00Z",
    }
    order.update(kw)
    return order


def test_the_matchup_recovers_the_game_pk(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    index = mod._schedule_index("2026-08-22")

    game_pk, reason = mod._resolve_game_pk(_order(), index)
    assert game_pk == 777001
    assert reason is None


def test_an_oddsapi_hash_does_not_block_recovery(schedule):
    """The actual production shape: `game_pk` present, unparseable, and wrong."""
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    index = mod._schedule_index("2026-08-22")

    game_pk, _reason = mod._resolve_game_pk(_order(game_pk="a1b2c3d4e5f6"), index)
    assert game_pk == 777001


def test_a_real_numeric_id_short_circuits_the_lookup(schedule):
    # No schedule at all, and it still resolves: the fast path costs no file read
    # once the upstream stamps a genuine gamePk.
    game_pk, reason = mod._resolve_game_pk(_order(game_pk=999), {})
    assert (game_pk, reason) == (999, None)


def test_tri_codes_and_full_names_both_resolve(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    index = mod._schedule_index("2026-08-22")

    # `team_aliases.canonical_team` accepts either direction, which is why this
    # reuses it rather than adding a fifth private name map.
    game_pk, _ = mod._resolve_game_pk(_order(home_team="HOU", away_team="SEA"), index)
    assert game_pk == 777001


def test_a_matchup_not_on_the_schedule_is_named_separately(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    index = mod._schedule_index("2026-08-22")

    _pk, reason = mod._resolve_game_pk(
        _order(home_team="Boston Red Sox", away_team="New York Yankees"), index
    )
    assert reason == mod.REASON_NO_TEAM_MATCH


def test_a_missing_schedule_file_is_named_separately_from_a_missing_matchup():
    _pk, reason = mod._resolve_game_pk(_order(), {})
    # "We have no slate for this date" and "this game is not on the slate" are
    # different jobs: one is a missing artifact, the other a name mismatch.
    assert reason == mod.REASON_NO_SCHEDULE


# --- doubleheaders ---------------------------------------------------------


def test_a_doubleheader_is_split_by_start_time(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners", "2026-08-22T17:10:00Z"))
    schedule.append(_game(777002, "Houston Astros", "Seattle Mariners", "2026-08-22T23:10:00Z"))
    index = mod._schedule_index("2026-08-22")

    early, _ = mod._resolve_game_pk(_order(commence_time="2026-08-22T17:10:00Z"), index)
    late, _ = mod._resolve_game_pk(_order(commence_time="2026-08-22T23:10:00Z"), index)
    assert (early, late) == (777001, 777002)


def test_a_doubleheader_with_no_start_time_is_REFUSED_not_guessed(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners", "2026-08-22T17:10:00Z"))
    schedule.append(_game(777002, "Houston Astros", "Seattle Mariners", "2026-08-22T23:10:00Z"))
    index = mod._schedule_index("2026-08-22")

    _pk, reason = mod._resolve_game_pk(_order(commence_time=None), index)
    # Picking a half at random is a confident wrong verdict, and the two games
    # of a doubleheader routinely disagree.
    assert reason == mod.REASON_AMBIGUOUS


def test_a_start_time_that_matches_neither_half_is_refused(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners", "2026-08-22T17:10:00Z"))
    schedule.append(_game(777002, "Houston Astros", "Seattle Mariners", "2026-08-22T23:10:00Z"))
    index = mod._schedule_index("2026-08-22")

    _pk, reason = mod._resolve_game_pk(_order(commence_time="2026-08-22T04:00:00Z"), index)
    # The halves are hours apart, so a near-miss means the matchup matched
    # something else entirely.
    assert reason == mod.REASON_AMBIGUOUS


def test_the_schedule_is_read_once_per_resolver_not_once_per_order(schedule, monkeypatch):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    reads = {"n": 0}

    def counted(date):
        reads["n"] += 1
        return list(schedule)

    monkeypatch.setattr("syndicate.features.mlb.cards._schedule_raw_games", counted)
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed", lambda *a, **k: None
    )

    resolve = mod.mlb_status_resolver("2026-08-22")
    for _ in range(5):
        resolve(_order())
    # 58 orders must not mean 58 file reads for one unchanging answer.
    assert reads["n"] == 1


def test_an_order_with_no_matchup_is_named_apart_from_one_the_slate_lacks(schedule):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    index = mod._schedule_index("2026-08-22")

    _pk, thin = mod._resolve_game_pk(_order(home_team=None, away_team=None), index)
    _pk2, absent = mod._resolve_game_pk(
        _order(home_team="Boston Red Sox", away_team="New York Yankees"), index
    )
    # Opposite fixes: one means the ledger record is too thin to recover from,
    # the other means the names or the slate disagree. Orders written before
    # `home_team` joined `_LEAN_FIELDS` land in the first, and lumping them
    # together would hide how much of the backlog is recoverable.
    assert thin == mod.REASON_NO_MATCHUP_ON_ORDER
    assert absent == mod.REASON_NO_TEAM_MATCH


def test_a_non_mlb_order_says_so_instead_of_blaming_the_record(monkeypatch):
    """Every other refusal is a statement about MLB data.

    A Liverpool match run through `canonical_team("mlb", ...)` returns None and
    would have been reported as `no_matchup_on_order` — "the ledger record is
    too thin" — which is false, and would have sent the next fix at the wrong
    problem.
    """
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed", lambda *a, **k: None
    )
    resolve = mod.mlb_status_resolver("2026-08-22")
    verdict = resolve(
        {"sport": "soccer", "home_team": "Liverpool", "away_team": "Arsenal", "market": "h2h"}
    )
    assert verdict["unavailable_reason"] == mod.REASON_NOT_MLB


def test_an_mlb_order_is_still_resolved(schedule, monkeypatch):
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed", lambda *a, **k: None
    )
    resolve = mod.mlb_status_resolver("2026-08-22")
    verdict = resolve({**_order(), "sport": "mlb", "market": "strikeouts"})
    # Gets past the sport gate and the id lookup; stops at the absent feed.
    assert verdict["unavailable_reason"] == mod.REASON_NO_FEED


def test_a_market_we_can_never_grade_says_so_BEFORE_the_game_is_played(schedule, monkeypatch):
    """The ordering that decides whether "is this slate trackable" is answerable.

    "We have no stat for this market" is PERMANENT. "The feed is not cached yet"
    is TEMPORARY. Checked feed-first, the temporary reason swallows the
    permanent one -- production read `no_live_feed: 50` while an unknown share
    of those 50 could never grade at all, so "50 pending" and "50 trackable"
    looked identical.
    """
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    # No feed at all -- exactly the pre-game state.
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed", lambda *a, **k: None
    )
    resolve = mod.mlb_status_resolver("2026-08-22")

    unmappable = resolve({**_order(), "sport": "mlb", "market": "batter_doubles"})
    assert unmappable["unavailable_reason"] == mod.REASON_UNMAPPED_MARKET

    # A market we CAN grade still reports the feed as the blocker, because for
    # that one the feed genuinely is the only thing missing.
    mappable = resolve({**_order(), "sport": "mlb", "market": "strikeouts"})
    assert mappable["unavailable_reason"] == mod.REASON_NO_FEED


def test_a_game_total_is_still_graded_from_the_scoreboard(schedule, monkeypatch):
    """`totals` has no per-player stat and must not be caught by the new check."""
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed",
        lambda *a, **k: {
            "gameData": {"status": {"abstractGameState": "Final"}},
            "liveData": {"linescore": {"teams": {"home": {"runs": 5}, "away": {"runs": 3}}}},
        },
    )
    resolve = mod.mlb_status_resolver("2026-08-22")
    verdict = resolve({**_order(), "sport": "mlb", "market": "totals"})
    assert verdict.get("unavailable_reason") is None
    assert verdict["current_value"] == 8.0


# --------------------------------------------------------------------------
# Game lines, end to end through the real resolver
# --------------------------------------------------------------------------
#
# MEASURED 2026-08-24, every settlement cycle:
#
#     UNMAPPED_MARKETS date=2026-08-23
#       {'spreads': 41, 'h2h': 31, 'h2h_3_way': 6, 'spreads_alt': 2}
#
# Scoreboard bets went through a lookup that only ever knew player stats.


def _feed(home_runs, away_runs, *, state="Final",
          home="Houston Astros", away="Seattle Mariners"):
    return {
        "gameData": {
            "status": {"abstractGameState": state},
            "teams": {"home": {"name": home}, "away": {"name": away}},
        },
        "liveData": {
            "linescore": {"teams": {"home": {"runs": home_runs},
                                    "away": {"runs": away_runs}}}
        },
    }


@pytest.fixture
def resolver(schedule, monkeypatch):
    """The real resolver, with only the FEED READ stubbed.

    The schedule join, the market dispatch, the team resolution and the
    translation all run for real -- stubbing further up would test the stub.
    """
    schedule.append(_game(777001, "Houston Astros", "Seattle Mariners"))
    feeds: dict = {}

    def build(feed):
        feeds["payload"] = feed
        monkeypatch.setattr(
            "syndicate.features.mlb.box_score_stats.load_final_feed",
            lambda date, pk, fetch_if_missing=True: feeds.get("payload"),
        )
        return mod.mlb_status_resolver("2026-08-22")

    return build


def _mlb_order(**kw):
    order = {
        "sport": "mlb",
        "home_team": "Houston Astros",
        "away_team": "Seattle Mariners",
        "commence_time": "2026-08-22T23:10:00Z",
    }
    order.update(kw)
    return order


def test_a_spread_resolves_instead_of_refusing_as_unmapped(resolver):
    """The exact refusal that produced `spreads: 41`."""
    resolve = resolver(_feed(6, 3))
    out = resolve(_mlb_order(market="spreads", side="Houston Astros", line=-1.5))

    assert out.get("unavailable_reason") is None
    # RESTATED for the grader: the order still records `side="Houston Astros"`.
    assert out["side"] == "over"
    assert out["line"] == 1.5
    assert out["current_value"] == 3
    assert out["is_final"] is True


def test_a_moneyline_resolves(resolver):
    resolve = resolver(_feed(6, 3))
    out = resolve(_mlb_order(market="h2h", side="Houston Astros", line=None))
    assert out.get("unavailable_reason") is None
    assert out["current_value"] == 3 and out["line"] == 0.0


def test_the_losing_side_of_the_same_game_reads_negative(resolver):
    resolve = resolver(_feed(6, 3))
    out = resolve(_mlb_order(market="h2h", side="Seattle Mariners", line=None))
    assert out["current_value"] == -3


def test_the_scores_are_paired_with_the_FEED_s_own_team_names(resolver):
    """The scores come from this payload, so the names must too. Pairing a
    score with a name from the odds provider is how a game gets graded
    backwards -- and the two sources genuinely disagree on club naming."""
    resolve = resolver(_feed(6, 3, home="Seattle Mariners", away="Houston Astros"))
    # The FEED says Seattle is home and won 6-3, whatever the order believes.
    out = resolve(_mlb_order(market="h2h", side="Seattle Mariners", line=None))
    assert out["current_value"] == 3


def test_a_game_with_no_linescore_yet_is_a_named_absence(resolver):
    """Not a zero-zero draw."""
    resolve = resolver(_feed(None, None, state="Preview"))
    out = resolve(_mlb_order(market="spreads", side="Houston Astros", line=-1.5))
    assert out["unavailable_reason"] == mod.REASON_NO_STAT


def test_an_in_progress_game_line_is_not_final(resolver):
    resolve = resolver(_feed(8, 0, state="Live"))
    out = resolve(_mlb_order(market="spreads", side="Houston Astros", line=-1.5))
    assert out["is_final"] is False
    assert out["started"] is True


def test_a_player_prop_still_takes_the_player_path(resolver, monkeypatch):
    """The game-line branch must not swallow the props that already worked."""
    # Patched BEFORE the resolver is built: it binds `final_stat_value` at
    # closure-construction time, so a later patch never reaches it.
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.final_stat_value",
        lambda feed, group, stat, player_name: 7,
    )
    resolve = resolver(_feed(6, 3))
    out = resolve(_mlb_order(market="strikeouts", side="over", line=4.5,
                             player_name="Framber Valdez"))
    assert out["current_value"] == 7


def test_an_unknown_market_is_still_refused_by_name(resolver):
    resolve = resolver(_feed(6, 3))
    out = resolve(_mlb_order(market="batter_stolen_bases", side="over", line=0.5))
    assert out["unavailable_reason"] == mod.REASON_UNMAPPED_MARKET
