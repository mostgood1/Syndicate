"""MLB SEGMENT game lines grade off `linescore.innings`, not the nine-inning total.

`segment_refusal` stopped a first-five-innings UNDER 3.5 being settled against
a whole-game total of 8. This is the other half: the same `feed/live` payload
carries the per-inning linescore one key over from the cumulative runs, and
`first1` / `first3` / `first5` totals, spreads and moneylines are now graded
off it. The refusal is the FALLBACK -- a segment MLB does not play, or a
player prop with a segment -- and a feed whose linescore cannot answer refuses
BY NAME rather than reading the full game.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_mlb as mod
from syndicate.features.shared.bet_status import resolve_bet_status
from syndicate.features.shared.segment_actuals import REASON_SEGMENT_ACTUAL_PREFIX

HOME = "Houston Astros"
AWAY = "Seattle Mariners"


def _inning(number, home, away):
    entry = {"num": number, "ordinalNum": f"{number}th", "away": {"runs": away} if away is not None else {}}
    entry["home"] = {"runs": home} if home is not None else {}
    return entry


def _feed(innings, *, state="Final", current=None, inning_state=None):
    """`innings` is a list of (home, away) per inning; None for a half not played."""
    entries = [_inning(i + 1, h, a) for i, (h, a) in enumerate(innings)]
    home_total = sum(h or 0 for h, _ in innings)
    away_total = sum(a or 0 for _, a in innings)
    linescore = {
        "innings": entries,
        "teams": {"home": {"runs": home_total}, "away": {"runs": away_total}},
    }
    if current is not None:
        linescore["currentInning"] = current
    if inning_state is not None:
        linescore["inningState"] = inning_state
    return {
        "gameData": {
            "status": {"abstractGameState": state},
            "teams": {"home": {"name": HOME}, "away": {"name": AWAY}},
        },
        "liveData": {"linescore": linescore},
    }


# Home 1-0-2-0-3 | 0-1-0-0 = 6, away 0-2-0-1-0 | 3-0-0-0 = 6. Level after five
# (6-3? no: home 6, away 3 through five) -- see the per-test arithmetic.
NINE = [(1, 0), (0, 2), (2, 0), (0, 1), (3, 0), (0, 3), (1, 0), (0, 0), (0, 0)]
# first5: home 6, away 3, total 9. Full game: home 7, away 6, total 13.


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.mlb.cards._schedule_raw_games",
        lambda date: [{
            "gamePk": 777001, "gameDate": "2026-08-22T23:10:00Z",
            "teams": {"home": {"team": {"name": HOME}}, "away": {"team": {"name": AWAY}}},
        }],
    )

    def build(feed):
        monkeypatch.setattr(
            "syndicate.features.mlb.box_score_stats.load_final_feed",
            lambda date, pk, fetch_if_missing=True: feed,
        )
        return mod.mlb_status_resolver("2026-08-22")

    return build


def _order(**kw):
    order = {
        "sport": "mlb", "home_team": HOME, "away_team": AWAY,
        "commence_time": "2026-08-22T23:10:00Z",
        "market": "totals", "side": "over", "line": 8.5,
        "status": "filled", "fill_price": -110, "fill_stake_dollars": 10.0,
    }
    order.update(kw)
    return order


def _status(out, order):
    assert out.get("unavailable_reason") is None, out
    return resolve_bet_status(
        market=order["market"], side=out.get("side", order.get("side")),
        line=out.get("line", order.get("line")), current_value=out["current_value"],
        is_final=out["is_final"], started=out.get("started", True),
    )


@pytest.mark.parametrize("segment_kw", [{}, {"segment": "full"}])
def test_a_full_game_total_is_unchanged(resolver, segment_kw):
    """REGRESSION: the whole game still reads the cumulative nine-inning runs."""
    out = resolver(_feed(NINE))(_order(**segment_kw))
    assert out["current_value"] == 13
    assert "settled_segment" not in out


def test_a_first5_total_grades_over_under_and_push(resolver):
    resolve = resolver(_feed(NINE))
    over = _order(segment="first5", side="over", line=8.5)
    out = resolve(over)
    assert out["current_value"] == 9
    assert out["settled_segment"] == "first5"
    assert out["home_score"] == 6 and out["away_score"] == 3
    assert out["matched_by"] == "feed_live_linescore_innings"
    assert _status(out, over)["status"] == "won"

    under = _order(segment="first5", side="under", line=8.5)
    assert _status(resolve(under), under)["status"] == "lost"

    level = _order(segment="first5", side="over", line=9)
    tied = _status(resolve(level), level)
    assert tied["status"] == "live_tied" and tied["decided"] is True


def test_first3_and_first1_read_their_own_innings(resolver):
    resolve = resolver(_feed(NINE))
    assert resolve(_order(segment="first3", side="over", line=4.5))["current_value"] == 5
    assert resolve(_order(segment="first1", side="over", line=0.5))["current_value"] == 1


def test_a_first5_spread_grades_on_the_five_inning_margin(resolver):
    """Home 6 / away 3 through five: home -2.5 wins, away +2.5 loses, home -3 pushes."""
    resolve = resolver(_feed(NINE))
    for side, line, expected in ((HOME, -2.5, "won"), ("away", 2.5, "lost"), ("home", -3, "live_tied")):
        order = _order(market="spreads", segment="first5", side=side, line=line)
        status = _status(resolve(order), order)
        assert status["status"] == expected, (side, line, status)
        assert status["decided"] is True


def test_a_first5_moneyline_wins_loses_and_PUSHES_two_way(resolver):
    from syndicate.features.shared.paper_settlement import _our_verdict

    resolve = resolver(_feed(NINE))
    for side, expected in (("home", "won"), ("away", "lost")):
        order = _order(market="h2h", segment="first5", side=side, line=None)
        assert _status(resolve(order), order)["status"] == expected, side

    # Level after five: home 3, away 3.
    level = resolver(_feed([(1, 0), (0, 2), (2, 0), (0, 1), (0, 0), (0, 3), (1, 0), (0, 0), (0, 0)]))
    verdict, resolved, refusal = _our_verdict(_order(market="h2h", segment="first5", side="home", line=None), level)
    assert not refusal, refusal
    assert verdict["outcome"] == "push"
    assert resolved["settled_segment"] == "first5"


def test_a_level_first5_LOSES_the_three_way_moneyline(resolver):
    level = resolver(_feed([(1, 0), (0, 2), (2, 0), (0, 1), (0, 0), (0, 3), (1, 0), (0, 0), (0, 0)]))
    home = _order(market="h2h_3_way", segment="first5", side="home", line=None)
    assert _status(level(home), home)["status"] == "lost"
    draw = _order(market="h2h_3_way", segment="first5", side="draw", line=None)
    assert _status(level(draw), draw)["status"] == "won"


def test_a_live_game_completes_the_segment_when_the_fifth_inning_ENDS(resolver):
    """Complete = decided while the game plays on; not complete = a running
    total that only the monotone over can decide."""
    through_four_and_a_half = resolver(_feed(NINE[:5], state="Live", current=5, inning_state="Bottom"))
    out = through_four_and_a_half(_order(segment="first5", side="under", line=8.5))
    assert out["is_final"] is False and out["started"] is True

    ended = resolver(_feed(NINE[:5], state="Live", current=5, inning_state="End"))
    assert ended(_order(segment="first5", side="under", line=8.5))["is_final"] is True

    sixth = resolver(_feed(NINE[:6], state="Live", current=6, inning_state="Top"))
    assert sixth(_order(segment="first5", side="under", line=8.5))["is_final"] is True
    assert sixth(_order(segment="first5", side="under", line=8.5))["current_value"] == 9


def test_a_final_game_short_of_the_fifth_inning_refuses_by_name(resolver):
    """Rain-shortened after four: there is no first-five actual, and the
    whole-game score is not one."""
    out = resolver(_feed(NINE[:4]))(_order(segment="first5", side="over", line=8.5))
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}first5"
    assert out.get("current_value") is None


def test_a_half_inning_never_played_refuses_rather_than_reading_zero(resolver):
    """Called after the top of the fifth with the home side ahead: the bottom
    half carries no `runs`, and a zero there is a fact that did not happen."""
    out = resolver(_feed(NINE[:4] + [(None, 0)]))(_order(segment="first5", side="over", line=8.5))
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}first5"


def test_a_feed_with_no_innings_list_refuses_by_name(resolver):
    feed = _feed(NINE)
    del feed["liveData"]["linescore"]["innings"]
    out = resolver(feed)(_order(segment="first5", side="over", line=8.5))
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}first5"


def test_no_feed_is_the_same_transient_absence_as_the_full_game(resolver):
    out = resolver(None)(_order(segment="first5", side="over", line=8.5))
    assert out["unavailable_reason"] == mod.REASON_NO_FEED


def test_a_segment_this_sport_does_not_play_falls_back_to_the_refusal(resolver):
    out = resolver(_feed(NINE))(_order(segment="h1", side="over", line=8.5))
    assert out["unavailable_reason"] == "actual_is_full_game_not_h1"


def test_a_segment_PLAYER_prop_still_refuses(resolver):
    out = resolver(_feed(NINE))(_order(market="strikeouts", segment="first5", player_name="Someone", side="over", line=3.5))
    assert out["unavailable_reason"] == "actual_is_full_game_not_first5"


def test_the_scores_travel_with_the_feed_s_own_names(resolver):
    out = resolver(_feed(NINE))(_order(segment="first5", side="over", line=8.5))
    assert (out["home_name"], out["away_name"]) == (HOME, AWAY)
