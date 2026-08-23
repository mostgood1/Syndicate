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
