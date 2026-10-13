"""Soccer bets could never settle. These pin the resolver that fixes that.

MEASURED 2026-08-25 14:03:02Z, all-time:

    SETTLED date=2026-08-25 orders=2 graded=0 ungraded={'no_resolver_for_soccer': 2}
    PNL_CUT all_time by_sport=[('mlb', 181, ...), ('soccer', 0, ...), ('wnba', 0, ...)]

Zero soccer bets graded, ever, on a board that was ~97% soccer by row count.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_soccer as soccer


def _order(**over):
    base = {
        "sport": "soccer",
        "market": "h2h",
        "side": "home",
        "line": None,
        "home_team": "Chelsea",
        "away_team": "Fulham",
        "event_id": "oddsapi-hash-not-espns",
    }
    base.update(over)
    return base


def _patch_matches(monkeypatch, records):
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: records)


def _patch_boxes(monkeypatch, boxes):
    monkeypatch.setattr(soccer, "_load_player_boxes", lambda _date: boxes)


def _player(name, *, appeared=True, goals=0.0, shots=0.0, sot=0.0, assists=0.0):
    return {"player_name": name, "appeared": appeared, "goals": goals, "shots": shots,
            "shots_on_target": sot, "assists": assists}


def _box(final=True, state="post", **over):
    box = {"home_team": "Chelsea", "away_team": "Fulham", "final": final, "status_state": state,
           "players": {"home": {"players": [_player("Cole Palmer", goals=1.0, shots=4.0, sot=2.0),
                                            _player("Son Heung-Min", shots=1.0),
                                            _player("Unused Sub", appeared=False)]},
                       "away": {"players": [_player("Raúl Jiménez", goals=0.0, shots=2.0, assists=1.0)]}}}
    box.update(over)
    return box


def test_a_finished_match_grades_the_moneyline(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())

    assert verdict["is_final"] is True
    # Home margin +1 against a 0.5 line: `game_line_view` frames a three-way
    # moneyline as over/under a half-goal margin so a level score LOSES rather
    # than pushing, which is what a soccer h2h with a draw leg actually does.
    assert verdict["current_value"] == 1
    assert verdict["side"] == "over"
    assert verdict["line"] == 0.5


def test_a_level_score_is_not_a_home_win(monkeypatch):
    """The draw leg is the whole reason soccer needed its own resolver rather
    than reusing MLB's two-way framing."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())
    # margin 0 < 0.5 -> the over (home win) is NOT satisfied.
    assert verdict["current_value"] == 0
    assert verdict["line"] == 0.5


def test_the_draw_side_grades_as_its_own_outcome(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(side="draw"))
    # |margin| under 0.5 is true for a level score and nothing else.
    assert verdict["current_value"] == 0
    assert verdict["side"] == "under"
    assert verdict["line"] == 0.5


def test_an_in_play_match_reports_a_value_but_NOT_final(monkeypatch):
    """A 2-0 at half time is a real current value and not a result. `is_final`
    is asserted by the artifact, never inferred from a clock -- stoppage time is
    real and routinely decides totals."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 0, "final": False},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())
    assert verdict["current_value"] == 2
    assert verdict["is_final"] is False


def test_the_join_is_on_TEAMS_because_event_id_is_a_different_namespace(monkeypatch):
    """The MLB trap, avoided by construction.

    The order's `event_id` is OddsAPI's hash; the live-state artifact is keyed
    by ESPN's id. `bet_status_wnba` records that this exact mismatch "cost a
    day" on MLB. The record here carries NO event_id at all and must still
    grade.
    """
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 3, "away_score": 0, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(event_id="totally-unrelated")
    )
    assert verdict["current_value"] == 3


def test_an_order_with_no_matchup_refuses_by_name(monkeypatch):
    """There is no id fallback that would be anything but a guess."""
    _patch_matches(monkeypatch, [])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(home_team=None))
    assert verdict["unavailable_reason"] == soccer.REASON_NO_MATCHUP


def test_an_unreadable_live_state_is_NOT_the_same_as_no_matches(monkeypatch):
    """None means we could not read; [] means we read and the match is absent.
    Two different jobs, and the ungraded counts must keep them apart."""
    _patch_matches(monkeypatch, None)
    assert soccer.soccer_status_resolver("2026-08-25")(_order())[
        "unavailable_reason"
    ] == soccer.REASON_NO_LIVE_STATE

    _patch_matches(monkeypatch, [])
    assert soccer.soccer_status_resolver("2026-08-25")(_order())[
        "unavailable_reason"
    ] == soccer.REASON_MATCH_NOT_FOUND


def test_a_player_prop_grades_off_the_match_box_not_the_capped_projections(monkeypatch):
    """Props used to refuse outright: `live_player_props` was capped at twelve players,
    so a player outside it was ABSENT rather than at zero. The match box lists every
    boxed player, so it grades -- and `_load_matches` (the projections' side) is not
    what answers."""
    _patch_matches(monkeypatch, [])
    _patch_boxes(monkeypatch, [_box()])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="over", line=2.5, player_name="Cole Palmer")
    )
    assert verdict == {"current_value": 4.0, "is_final": True, "started": True, "source": "soccer_match_box"}


def test_the_market_check_runs_BEFORE_the_artifact_read(monkeypatch):
    """`bet_status_wnba`'s rule, paid for on the MLB grader: a permanent
    "we cannot grade this market" must not be hidden behind a transient
    "the artifact is not captured yet"."""
    def explode(_date):
        raise AssertionError("the artifact was read for an ungradeable market")

    monkeypatch.setattr(soccer, "_load_matches", explode)
    monkeypatch.setattr(soccer, "_load_player_boxes", explode)
    for market, reason in (("player_first_goal_scorer", soccer.REASON_SCORER_RACE),
                           ("player_to_receive_card", soccer.REASON_PROP_MARKET)):
        verdict = soccer.soccer_status_resolver("2026-08-25")(
            _order(market=market, side="yes", player_name="Cole Palmer")
        )
        assert verdict["unavailable_reason"] == reason


def test_a_non_soccer_order_is_not_reported_as_a_soccer_failure(monkeypatch):
    _patch_matches(monkeypatch, [])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(sport="mlb"))
    assert verdict["unavailable_reason"] == soccer.REASON_NOT_SOCCER


def test_the_artifact_is_read_ONCE_for_a_whole_slate(monkeypatch):
    calls = {"n": 0}

    def counted(_date):
        calls["n"] += 1
        return [{"home_team": "Chelsea", "away_team": "Fulham",
                 "home_score": 1, "away_score": 0, "final": True}]

    monkeypatch.setattr(soccer, "_load_matches", counted)
    resolve = soccer.soccer_status_resolver("2026-08-25")
    for _ in range(5):
        resolve(_order())
    assert calls["n"] == 1


# --- game totals -----------------------------------------------------------
#
# MEASURED 2026-08-25 14:47:23Z, the first production reading of this resolver:
#
#   SETTLED date=2026-08-25 ungraded={'unmapped_market': 1, ...}
#   UNMAPPED_MARKETS date=2026-08-25 {'totals': 1}
#
# Two of the four pending soccer orders were totals, refused by a resolver that
# already held both scores. `is_game_line_market` is the SPREAD and MONEYLINE
# test and is False for `totals` by design.


def test_a_total_grades_off_the_COMBINED_score(monkeypatch):
    """No `game_line_view` translation: a total already speaks the grader's
    over/under vocabulary, so it needs the combined goals and nothing else --
    the same shape `bet_status_mlb._combined_score` returns for its 46 settled
    totals."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="totals", side="over", line=2.5)
    )
    assert verdict.get("unavailable_reason") is None
    assert verdict["current_value"] == 3
    assert verdict["is_final"] is True
    # Deliberately NOT rewritten: the order's own side and line are what the
    # grader compares against, and overwriting them here would be the second
    # copy of a decision this module keeps in one place.
    assert "side" not in verdict
    assert "line" not in verdict


def test_the_ALT_total_families_grade_too(monkeypatch):
    """`totals_alt` is the same market at another line, and a final score
    prices any line. Leaving them out repeated the gap `live_gameline_join`
    records: 53 of 107 live game-line rows unprojected, every one `spreads_alt`
    or `totals_alt`."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 0, "away_score": 0, "final": True},
    ])
    resolve = soccer.soccer_status_resolver("2026-08-25")
    for market in ("totals", "total", "totals_alt", "alternate_totals"):
        verdict = resolve(_order(market=market, side="under", line=1.5))
        assert verdict.get("unavailable_reason") is None, market
        assert verdict["current_value"] == 0, market


def test_a_TEAM_total_is_refused_by_name_not_graded_off_the_scoreline(monkeypatch):
    """The wrong answer this prevents: one team's goals graded against the
    combined score roughly doubles the value and settles overs that lost.
    Nothing here reads which team the side token names, so it refuses."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 3, "away_score": 0, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="team_totals", side="over", line=1.5)
    )
    assert verdict["unavailable_reason"] == soccer.REASON_TEAM_TOTAL
    # And specifically NOT the combined 3, which would have won this bet.
    assert "current_value" not in verdict


def test_an_integral_total_line_pushes_rather_than_needing_a_half_point(monkeypatch):
    """The OPPOSITE of the three-way moneyline case. `game_line_view` shifts a
    moneyline off the integer grid because a draw must not push; a total landing
    exactly on an Asian 3.0 line SHOULD return the stake, so equality is left
    alone and `resolve_bet_status` settles it as a push."""
    from syndicate.features.shared.bet_status import resolve_bet_status
    from syndicate.features.shared.paper_settlement import grade_order

    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="totals", side="over", line=3.0)
    )
    status = resolve_bet_status(
        side="over", line=3.0, market="totals",
        current_value=verdict["current_value"], is_final=verdict["is_final"],
        started=verdict["started"],
    )
    # Asserted through to the MONEY, not on the status string: `live_tied` reads
    # oddly for a finished match and only `grade_order` decides what it pays.
    graded = grade_order(
        {"status": "filled", "fill_price": -110.0, "fill_stake_dollars": 10.0,
         "side": "over", "line": 3.0, "market": "totals"},
        status,
    )
    assert graded["outcome"] == "push"
    assert graded["pnl_dollars"] == 0.0

    # And the control, so the push is not a comparator that never fires: one
    # more goal wins the same bet.
    for goals, expected in ((4.0, "won"), (2.0, "lost")):
        moved = resolve_bet_status(
            side="over", line=3.0, market="totals",
            current_value=goals, is_final=True, started=True,
        )
        assert grade_order(
            {"status": "filled", "fill_price": -110.0, "fill_stake_dollars": 10.0,
             "side": "over", "line": 3.0, "market": "totals"},
            moved,
        )["outcome"] == expected


def test_a_total_on_an_UNFINISHED_match_reports_its_value_and_waits(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 1, "final": False},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="totals", side="under", line=2.5)
    )
    assert verdict["current_value"] == 2
    assert verdict["is_final"] is False


def test_a_half_known_score_refuses_rather_than_reading_as_a_clean_sheet(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": None, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="totals", side="over", line=1.5)
    )
    assert verdict["unavailable_reason"] == soccer.REASON_NO_SCORES


def test_string_scores_are_coerced_because_ESPN_ships_them(monkeypatch):
    """`board_enrichment` records this for the same field: ESPN sends "1", and a
    string compares wrong downstream without ever raising."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": "2", "away_score": "1", "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="totals", side="over", line=2.5)
    )
    assert verdict["current_value"] == 3.0


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    return tmp_path


def _live_state(records):
    """Stand in for the rolling aggregate: a list, or None once it has rolled."""
    return None if records is None else ([dict(r) for r in records], 0.0)


def _aggregate(monkeypatch, records):
    from syndicate.features.shared import board_enrichment

    monkeypatch.setattr(
        board_enrichment, "_soccer_live_state_games", lambda _d: _live_state(records)
    )


def _chelsea_final():
    return {
        "home": {"name": "Chelsea"}, "away": {"name": "Fulham"},
        "home_score": 2, "away_score": 1, "state": "final",
    }


def test_a_finished_match_survives_the_aggregate_rolling_to_the_next_date(_isolated, monkeypatch):
    """THE GAP THIS FIX EXISTS FOR.

    `live/soccer_live_lens.json` is a ROLLING SINGLE-DATE snapshot and both of
    its readers gate on `snapshot["date"] == selected_date` -- correctly. But
    `settle_orders` runs for TODAY AND YESTERDAY, and the moment the aggregate
    rolls, the yesterday pass could read nothing at all: the per-league
    `match_box` tree is a filesystem write on live-odds-worker while settlement
    runs on refresh-worker. So yesterday's pass was structurally impossible for
    soccer -- the sport that needs it most, since European matches finish within
    hours of the UTC date roll.

    MEASURED 2026-08-26: soccer had settled ZERO orders all-time, and the 14:57Z
    pass for 2026-08-25 reported `no_soccer_live_state_for_date: 3` while the
    aggregate had already moved to 2026-08-26.
    """
    # Tick one: the aggregate still holds this date, and the match has ended.
    _aggregate(monkeypatch, [_chelsea_final()])
    first = soccer.soccer_status_resolver("2026-08-25")(_order())
    assert first["is_final"] is True

    # Tick two: the aggregate has rolled. Nothing else on this service can see
    # a finished soccer match -- and the bet must still grade.
    _aggregate(monkeypatch, None)
    second = soccer.soccer_status_resolver("2026-08-25")(_order())
    assert second.get("unavailable_reason") is None, second
    assert second["is_final"] is True
    assert second["current_value"] == 1


def test_the_kept_record_never_answers_for_another_date(_isolated, monkeypatch):
    """Answering one date out of another date's match state grades the wrong
    scoreline, which is the reason the aggregate is date-gated to begin with.
    """
    _aggregate(monkeypatch, [_chelsea_final()])
    soccer.soccer_status_resolver("2026-08-25")(_order())

    _aggregate(monkeypatch, None)
    verdict = soccer.soccer_status_resolver("2026-08-26")(_order())
    assert verdict["unavailable_reason"] == soccer.REASON_NO_LIVE_STATE


def test_a_later_tick_cannot_erase_an_earlier_tick_s_finals(_isolated, monkeypatch):
    """The poller rebuilds nothing it has already marked final, so a late tick
    legitimately carries only some of the day's finished matches. Replacing
    rather than unioning would drop the rest.
    """
    _aggregate(monkeypatch, [_chelsea_final()])
    soccer.soccer_status_resolver("2026-08-25")(_order())

    # A later tick that can see a DIFFERENT finished match and not Chelsea's.
    _aggregate(monkeypatch, [{
        "home": {"name": "Arsenal"}, "away": {"name": "Everton"},
        "home_score": 3, "away_score": 0, "state": "final",
    }])
    soccer.soccer_status_resolver("2026-08-25")(_order(home_team="Arsenal", away_team="Everton"))

    _aggregate(monkeypatch, None)
    resolve = soccer.soccer_status_resolver("2026-08-25")
    assert resolve(_order())["is_final"] is True                       # Chelsea survived
    assert resolve(_order(home_team="Arsenal", away_team="Everton"))["is_final"] is True


def test_an_unfinished_match_is_never_kept(_isolated, monkeypatch):
    """Only a decided match may be remembered. Keeping an in-play scoreline and
    replaying it after the aggregate rolls would settle a bet against a
    half-time score, which is worse than not settling it.
    """
    _aggregate(monkeypatch, [{
        "home": {"name": "Chelsea"}, "away": {"name": "Fulham"},
        "home_score": 1, "away_score": 0, "state": "live",
    }])
    soccer.soccer_status_resolver("2026-08-25")(_order())

    _aggregate(monkeypatch, None)
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())
    assert verdict["unavailable_reason"] == soccer.REASON_NO_LIVE_STATE


# ---------------------------------------------------------------------------- player props off the match box

def test_anytime_scorer_grades_goals_against_half_a_goal(monkeypatch):
    _patch_boxes(monkeypatch, [_box()])
    resolve = soccer.soccer_status_resolver("2026-08-25")
    scored = resolve(_order(market="player_goal_scorer_anytime", side="yes", player_name="Cole Palmer"))
    assert scored["current_value"] == 1.0 and scored["line"] == 0.5 and scored["is_final"]
    blank = resolve(_order(market="player_goal_scorer_anytime", side="yes", player_name="Raul Jimenez"))
    assert blank["current_value"] == 0.0 and blank["line"] == 0.5     # accents folded


def test_a_reordered_name_still_finds_the_player(monkeypatch):
    _patch_boxes(monkeypatch, [_box()])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="over", line=0.5, player_name="Heung-Min Son"))
    assert verdict["current_value"] == 1.0


def test_a_player_not_in_the_box_is_refused_not_zero(monkeypatch):
    _patch_boxes(monkeypatch, [_box()])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="under", line=0.5, player_name="Somebody Else"))
    assert verdict["unavailable_reason"] == soccer.REASON_PLAYER_NOT_IN_BOX


def test_a_boxed_player_who_never_appeared_is_void_once_final_and_zero_while_live(monkeypatch):
    _patch_boxes(monkeypatch, [_box()])
    final = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="under", line=0.5, player_name="Unused Sub"))
    assert final["unavailable_reason"] == soccer.REASON_DNP_VOID
    _patch_boxes(monkeypatch, [_box(final=False, state="in")])
    live = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="under", line=0.5, player_name="Unused Sub"))
    assert live == {"current_value": 0.0, "is_final": False, "started": True, "source": "soccer_match_box"}


def test_before_kickoff_a_prop_has_not_started(monkeypatch):
    _patch_boxes(monkeypatch, [_box(final=False, state="pre")])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_assists", side="over", line=0.5, player_name="Cole Palmer"))
    assert verdict == {"current_value": None, "is_final": False, "started": False}


def test_no_box_for_the_match_is_named(monkeypatch):
    _patch_boxes(monkeypatch, [])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="over", line=0.5, player_name="Cole Palmer"))
    assert verdict["unavailable_reason"] == soccer.REASON_NO_BOX


def test_a_prop_settles_end_to_end_through_paper_settlement(monkeypatch):
    """Reachability: the resolver output reaches the grader and a WON / LOST comes out."""
    from syndicate.features.shared.paper_settlement import _our_verdict

    _patch_boxes(monkeypatch, [_box()])
    resolve = soccer.soccer_status_resolver("2026-08-25")
    filled = {"status": "filled", "fill_stake_dollars": 10.0, "fill_price": 0.5}
    won, _, why = _our_verdict(
        _order(market="player_goal_scorer_anytime", side="yes", player_name="Cole Palmer", **filled), resolve)
    lost, _, why2 = _our_verdict(
        _order(market="player_shots", side="over", line=2.5, player_name="Raul Jimenez", **filled), resolve)
    assert not why and not why2
    assert won["outcome"] == "won" and lost["outcome"] == "lost"


def test_a_books_full_name_finds_espns_playing_name_only_when_unique(monkeypatch):
    box = _box()
    box["players"]["home"]["players"].append(_player("Erling Haaland", shots=5.0))
    _patch_boxes(monkeypatch, [box])
    resolve = soccer.soccer_status_resolver("2026-08-25")
    found = resolve(_order(market="player_shots", side="over", line=2.5, player_name="erling braut haaland"))
    assert found["current_value"] == 5.0
    box["players"]["away"]["players"].append(_player("Erling Braut", shots=1.0))
    assert soccer._names_nest("erling braut haaland", "erling braut")
    twice = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="over", line=2.5, player_name="erling braut haaland"))
    assert twice["unavailable_reason"] == soccer.REASON_PLAYER_AMBIGUOUS


def test_one_word_espn_names_match_only_the_books_first_word():
    assert soccer._names_nest("estevao oliveira goncalves", "estevao")
    assert not soccer._names_nest("joao estevao", "estevao")


def test_the_box_is_read_from_the_orders_date_first_then_its_neighbours(monkeypatch, tmp_path):
    """Measured 2026-10-13: 1,410 prop rows dated 10-11 had their box only in the 10-10 file."""
    import json
    from syndicate.features.shared import refresh_state_store

    def write(stamp, score):
        path = tmp_path / "soccer_source" / "epl" / "api" / "live_state" / f"live_state_{stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"match_box": {"1": dict(_box(), score_home=score)}}), encoding="utf-8")

    monkeypatch.setattr(refresh_state_store, "data_root", lambda: tmp_path)
    write("2026-10-10", "9")
    boxes = soccer._load_player_boxes("2026-10-11")
    assert [b["score_home"] for b in boxes] == ["9"]
    write("2026-10-11", "1")
    assert [b["score_home"] for b in soccer._load_player_boxes("2026-10-11")][0] == "1"   # own date first
