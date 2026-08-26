"""WNBA live values — the resolver that makes WNBA bets gradeable at all."""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import bet_status_wnba as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield tmp_path


def _write_box(tmp_path, date="2026-08-23", games=None):
    path = tmp_path / "wnba_source" / "data" / "live" / f"live_player_box_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"payload": {"games": games or []}}), encoding="utf-8")
    return path


def _game(event_id="evt-1", players=None):
    return {"event_id": event_id, "players": players or []}


def _player(name="A'ja Wilson", pts=22, reb=9, ast=3, threes=1, team_tri="LVA"):
    # `team_tri` is on every row the real capture writes
    # (`_public_live_player_boxscore_payload`), and it is the ONLY place that
    # artifact records a team -- so it is what matchup recovery keys on.
    return {"player": name, "pts": pts, "reb": reb, "ast": ast,
            "threes_made": threes, "mp": "30:12", "team_tri": team_tri}


def _order(**kw):
    # A REAL ORDER CARRIES ITS MATCHUP. `home_team`/`away_team` are on every row
    # the live book writes, and leaving them off the fixture is what let the
    # id-only lookup look sufficient for as long as it did.
    order = {
        "sport": "wnba",
        "event_id": "evt-1",
        "market": "player_points",
        "player_name": "A'ja Wilson",
        "side": "over",
        "line": 19.5,
        "away_team": "Las Vegas Aces",
        "home_team": "Phoenix Mercury",
    }
    order.update(kw)
    return order


def test_the_event_id_on_the_order_finds_the_game_directly(_isolated):
    """MLB cost a day because the board stamps game_pk from the OddsAPI hash and
    StatsAPI wants a numeric id. The WNBA box is keyed by event_id — the SAME id
    the order carries."""
    _write_box(_isolated, games=[_game(players=[_player()])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order())

    assert verdict.get("unavailable_reason") is None
    assert verdict["current_value"] == 22.0


@pytest.mark.parametrize(
    "market,expected",
    [("player_points", 22.0), ("player_rebounds", 9.0), ("player_assists", 3.0), ("player_threes", 1.0)],
)
def test_each_single_stat_market_reads_its_own_key(_isolated, market, expected):
    _write_box(_isolated, games=[_game(players=[_player()])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(market=market))
    assert verdict["current_value"] == expected


def test_combination_markets_are_summed_from_named_parts(_isolated):
    _write_box(_isolated, games=[_game(players=[_player()])])
    resolve = mod.wnba_status_resolver("2026-08-23")
    # Listed explicitly, never parsed from the name: player_points_rebounds and
    # player_points_rebounds_assists differ by one token.
    assert resolve(_order(market="player_points_rebounds"))["current_value"] == 31.0
    assert resolve(_order(market="player_points_rebounds_assists"))["current_value"] == 34.0


def test_a_partial_combination_refuses_rather_than_summing_what_it_has(_isolated):
    _write_box(_isolated, games=[_game(players=[_player(reb=None)])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(market="player_points_rebounds"))
    # A partial sum is a smaller number that looks like a real one.
    assert verdict["unavailable_reason"] == mod.REASON_NO_STAT


def test_the_market_check_runs_BEFORE_the_artifact_read(_isolated):
    """The ordering the MLB grader got wrong this morning.

    "No box key for this market" is permanent; "the box is not captured yet" is
    temporary. Checking the transient one first hides the structural one — it
    concealed 40 orders that could never grade behind `no_live_feed: 50`.
    """
    # No box written at all, and still the market is the reported blocker.
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(market="player_blocks"))
    assert verdict["unavailable_reason"] == mod.REASON_UNMAPPED_MARKET


def test_a_missing_box_and_a_missing_game_are_different_reasons(_isolated):
    absent = mod.wnba_status_resolver("2026-08-23")(_order())
    assert absent["unavailable_reason"] == mod.REASON_NO_BOX

    # A different game AND a different matchup, or recovery would correctly
    # find it and this would no longer be testing what it says it tests.
    _write_box(
        _isolated,
        games=[_game(event_id="other", players=[_player(team_tri="SEA"), _player(name="Skylar Diggins", team_tri="MIN")])],
    )
    missing_game = mod.wnba_status_resolver("2026-08-23")(_order())
    assert missing_game["unavailable_reason"] == mod.REASON_GAME_NOT_IN_BOX


def test_a_player_who_is_not_in_the_box_is_NEVER_treated_as_zero(_isolated):
    _write_box(_isolated, games=[_game(players=[_player(name="Kelsey Plum")])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order())
    # "0 points, Under is fine" when we simply failed to find her is the worst
    # possible wrong answer.
    assert verdict["unavailable_reason"] == mod.REASON_PLAYER_NOT_FOUND
    assert "current_value" not in verdict


def test_names_join_across_punctuation(_isolated):
    _write_box(_isolated, games=[_game(players=[_player(name="Aja Wilson")])])
    # `A'ja Wilson` and `Aja Wilson` must land on the same key or the bet is
    # simply absent with no reason attached.
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(player_name="A'ja Wilson"))
    assert verdict["current_value"] == 22.0


def test_a_non_wnba_order_says_so_rather_than_blaming_the_box(_isolated):
    _write_box(_isolated, games=[_game(players=[_player()])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(sport="mlb"))
    assert verdict["unavailable_reason"] == "not_a_wnba_order"


# --- the final-flag decision ----------------------------------------------


def test_is_final_is_never_claimed_because_the_artifact_has_no_status(_isolated):
    _write_box(_isolated, games=[_game(players=[_player()])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order())
    # Claiming final on a guess would settle UNDERS at halftime — a confident
    # wrong answer on a bet that was still live.
    assert verdict["is_final"] is False


def test_an_over_still_decides_the_moment_it_crosses(_isolated):
    """What the missing final flag costs, and what it does not.

    Points are a counting stat, so the over is won permanently once crossed —
    no game-status field required.
    """
    from syndicate.features.shared.bet_status import resolve_bet_status

    _write_box(_isolated, games=[_game(players=[_player(pts=22)])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order())
    status = resolve_bet_status(
        market="player_points", side="over", line=19.5,
        current_value=verdict["current_value"], is_final=verdict["is_final"],
    )
    assert status["decided"] is True
    assert status["status"] == "won"


def test_an_under_waits_rather_than_being_settled_early(_isolated):
    from syndicate.features.shared.bet_status import resolve_bet_status

    _write_box(_isolated, games=[_game(players=[_player(pts=4)])])
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(side="under"))
    status = resolve_bet_status(
        market="player_points", side="under", line=19.5,
        current_value=verdict["current_value"], is_final=verdict["is_final"],
    )
    # Alive, not won. Waiting is recoverable; settling early is not.
    assert status["decided"] is False
    assert status["status"] == "live_ahead"


def test_the_box_is_read_once_per_resolver_not_once_per_order(_isolated, monkeypatch):
    _write_box(_isolated, games=[_game(players=[_player()])])
    reads = {"n": 0}
    real = mod._load_box_index

    def counted(date, normalize):
        reads["n"] += 1
        return real(date, normalize)

    monkeypatch.setattr(mod, "_load_box_index", counted)
    resolve = mod.wnba_status_resolver("2026-08-23")
    for _ in range(6):
        resolve(_order())
    # Forty orders must not mean forty reads of one unchanging artifact.
    assert reads["n"] == 1


def test_a_game_line_names_the_CAPTURE_as_the_blocker_not_the_vocabulary(monkeypatch):
    """`unmapped_market` on a spread would send the next person to add four
    market names to a table, which would not work: `game_line_bet` already
    grades spreads for any sport that can supply two team scores, and this
    artifact is a PLAYER box that carries none.

    MLB gained game-line grading on 2026-08-24 and WNBA did not. The reason
    string is the difference between the two fixes."""
    from syndicate.features.shared import bet_status_wnba as mod

    resolve = mod.wnba_status_resolver("2026-08-22")
    for market in ("spreads", "h2h", "h2h_3_way", "spreads_alt"):
        out = resolve({"sport": "wnba", "market": market, "side": "Las Vegas Aces"})
        assert out["unavailable_reason"] == mod.REASON_NO_TEAM_SCORES, market


def test_an_actually_unknown_market_still_says_so(monkeypatch):
    from syndicate.features.shared import bet_status_wnba as mod

    resolve = mod.wnba_status_resolver("2026-08-22")
    out = resolve({"sport": "wnba", "market": "player_double_double", "side": "over"})
    assert out["unavailable_reason"] == mod.REASON_UNMAPPED_MARKET


def test_the_board_hash_is_recovered_from_the_matchup(_isolated):
    """THE BUG THIS FIX EXISTS FOR, in the exact shape production had it.

    WNBA had settled ZERO orders all-time while MLB had settled 157, and every
    refusal was `game_not_in_live_box`. The order carries the board's OddsAPI
    hash; the box carries an ESPN id. The two namespaces can never meet, so the
    id lookup could never hit -- for ANY WNBA order, on any date.

    The old fixture concealed it by setting both ids to the same string.
    """
    _write_box(
        _isolated,
        games=[
            _game(
                event_id="401857177",  # ESPN's id, as the real capture writes it
                players=[_player(team_tri="LVA"), _player(name="Kahleah Copper", team_tri="PHX")],
            )
        ],
    )
    verdict = mod.wnba_status_resolver("2026-08-23")(
        _order(event_id="1fb615886a5e9855f01b8c3824e8d937")  # the board hash
    )

    assert verdict.get("unavailable_reason") is None
    assert verdict["current_value"] == 22.0
    # Stated explicitly: if this ever silently reverts to an id match the test
    # would still pass on the value alone.
    assert verdict["matched_by"] == "matchup"


def test_a_thin_order_says_so_instead_of_blaming_the_capture(_isolated):
    """"The ledger row has no teams" and "the game is not in the capture" send
    the next person to two different jobs, so they get two different reasons.
    """
    _write_box(_isolated, games=[_game(event_id="401857177", players=[_player()])])
    verdict = mod.wnba_status_resolver("2026-08-23")(
        _order(event_id="hash", away_team=None, home_team=None)
    )
    assert verdict["unavailable_reason"] == mod.REASON_NO_MATCHUP_ON_ORDER


def test_recovery_survives_a_swapped_home_and_away(_isolated):
    """The key is order-independent on purpose.

    Home/away is the convention most likely to be written the other way round on
    one of the two sides, and a swapped pair that fails to join is
    indistinguishable from a game that is genuinely absent.
    """
    _write_box(
        _isolated,
        games=[_game(event_id="401857177", players=[_player(team_tri="LVA"), _player(name="Kahleah Copper", team_tri="PHX")])],
    )
    verdict = mod.wnba_status_resolver("2026-08-23")(
        _order(event_id="hash", away_team="Phoenix Mercury", home_team="Las Vegas Aces")
    )
    assert verdict["current_value"] == 22.0


def test_a_doubleheader_never_recovers_into_the_wrong_game(_isolated):
    """Two games, one matchup. Grading against the wrong one of a pair is worse
    than not grading, so the second game keeps only its event id.
    """
    _write_box(
        _isolated,
        games=[
            _game(event_id="game-1", players=[_player(pts=22, team_tri="LVA"), _player(name="Kahleah Copper", team_tri="PHX")]),
            _game(event_id="game-2", players=[_player(pts=99, team_tri="LVA"), _player(name="Kahleah Copper", team_tri="PHX")]),
        ],
    )
    verdict = mod.wnba_status_resolver("2026-08-23")(_order(event_id="hash"))
    # The FIRST game's value, never the second's, and never a blend.
    assert verdict["current_value"] == 22.0
