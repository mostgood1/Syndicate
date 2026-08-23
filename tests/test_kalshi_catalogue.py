"""Series -> sport, title -> bet, and the refusals that form the work queue."""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as cat


def _market(title, series="KXMLBKS", **kw):
    market = {"ticker": "KXMLBKS-26AUG24ABBOTT-7", "series": series, "title": title}
    market.update(kw)
    return market


# --- the mapping this file owns is series -> sport, and nothing else --------


def test_the_market_name_comes_from_the_shared_vocabulary_not_a_private_table():
    """CLAUDE.md's rule against a third private normaliser, enforced.

    Kalshi's own title wording already resolves through `market_keys`, so this
    module needs one fact per series and the title supplies the rest.
    """
    import inspect

    assert "canonical_market_key" in inspect.getsource(cat.classify_market)

    # No second market table hiding in the module's DATA. Checked against the
    # namespace rather than the source text, so the docstring may name examples
    # without the test mistaking prose for a mapping.
    canonical_names = {"batter_hits", "player_points", "batter_total_bases", "strikeouts", "outs"}
    for name, value in vars(cat).items():
        if name.startswith("__") or not isinstance(value, dict):
            continue
        assert not (set(value.values()) & canonical_names), f"{name} is a private market table"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Andrew Abbott: 7+ strikeouts?", "strikeouts"),
        ("Cal Quantrill: 17+ Outs Recorded?", "outs"),
        ("Pete Crow-Armstrong: 2+ home runs?", "batter_home_runs"),
    ],
)
def test_kalshis_own_wording_resolves_to_our_market_keys(title, expected):
    series = {"strikeouts": "KXMLBKS", "outs": "KXMLBOUTS", "batter_home_runs": "KXMLBHR"}[expected]
    verdict = cat.classify_market(_market(title, series=series))
    assert verdict["status"] == "ok"
    assert verdict["market"] == expected
    assert verdict["sport"] == "mlb"


def test_an_unseen_series_is_refused_by_name_never_guessed_from_its_ticker():
    """Inventing plausible tickers is the false-negative trap: a series that
    does not exist returns an empty page indistinguishable from a venue that
    lists nothing."""
    verdict = cat.classify_market(_market("Somebody: 3+ things?", series="KXNBAPTS"))
    assert verdict["status"] == "refused"
    assert verdict["reason"] == cat.REASON_UNMAPPED_SERIES


def test_a_seen_but_uncovered_series_is_named_separately_from_an_unseen_one():
    verdict = cat.classify_market(_market("Over 7.5 runs scored?", series="KXNPBTOTAL"))
    # "We do not model this" and "we have not looked at this yet" are different
    # states, and the work queue is only useful if it means the second.
    assert verdict["reason"] == cat.REASON_OUT_OF_SCOPE
    assert verdict["detail"] == "npb"


def test_parlay_series_are_refused_before_anything_else():
    verdict = cat.classify_market(_market("yes Houston,yes Texas", series="KXMVECROSSCATEGORY"))
    assert verdict["reason"] == cat.REASON_COMBINATORIAL


def test_a_stat_our_vocabulary_lacks_is_refused_with_the_TEXT_to_add():
    verdict = cat.classify_market(_market("Andrew Abbott: 3+ pickoffs?"))
    assert verdict["reason"] == cat.REASON_UNMAPPED_STAT
    # Verbatim, so the `market_keys` entry to add reads straight off the log.
    assert verdict["detail"] == "pickoffs"


# --- the line conversion, still the most mismatch-prone number -------------


def test_N_plus_becomes_the_half_point_line_below_it():
    # 7+ matched against a line of 7.0 finds nothing; against 7.5 it finds a
    # DIFFERENT bet and prices it confidently.
    assert cat.threshold_to_line(7) == 6.5
    assert cat.classify_market(_market("Andrew Abbott: 7+ strikeouts?"))["line"] == 6.5


# --- grammars --------------------------------------------------------------


def test_a_spread_is_not_read_as_a_moneyline():
    """Ordering, not luck. "Will the Giants win by over 2.5 runs?" contains
    "win", and a looser moneyline pattern would swallow it -- a spread read as a
    moneyline is a bet on a different outcome at a confident price."""
    parsed = cat._parse_title("Will the Yomiuri Giants win by over 2.5 runs?")
    assert parsed["grammar"] == cat.GRAMMAR_TEAM_SPREAD
    assert parsed["subject"] == "Yomiuri Giants"
    assert parsed["line"] == 2.5


def test_a_moneyline_title_is_read_as_one():
    parsed = cat._parse_title("Mexico wins")
    assert parsed["grammar"] == cat.GRAMMAR_MONEYLINE
    assert parsed["subject"] == "Mexico"


def test_a_total_is_read_but_flagged_as_not_identifying_its_game():
    parsed = cat._parse_title("Over 7.5 runs scored?")
    assert parsed["grammar"] == cat.GRAMMAR_TEAM_TOTAL
    assert parsed["line"] == 7.5
    # It names neither team.
    assert parsed["subject"] is None


def test_a_player_prop_does_not_need_an_event_mapping_but_a_game_line_does():
    prop = cat.classify_market(_market("Andrew Abbott: 7+ strikeouts?"))
    assert prop["needs_event_identity"] is False

    # A total joined to the wrong game is a confidently-priced bet on strangers,
    # so the join must refuse these until `event_ticker` is mapped to our ids.
    cat.SERIES_SPORT["KXTESTTOTAL"] = "mlb"
    try:
        total = cat.classify_market(_market("Over 7.5 runs scored?", series="KXTESTTOTAL"))
        assert total["status"] == "ok"
        assert total["needs_event_identity"] is True
    finally:
        del cat.SERIES_SPORT["KXTESTTOTAL"]


def test_an_unreadable_title_is_refused_rather_than_half_parsed():
    assert cat.classify_market(_market("???"))["reason"] == cat.REASON_UNREADABLE_TITLE


# --- the work queue --------------------------------------------------------


def test_the_work_queue_names_the_series_and_shows_an_example():
    queue = cat.unmapped_series(
        [
            _market("Somebody: 3+ points?", series="KXNBAPTS"),
            _market("Another: 5+ points?", series="KXNBAPTS"),
            _market("Andrew Abbott: 7+ strikeouts?"),
        ]
    )
    # A count of unmapped markets says nothing actionable; a series name beside
    # a sample title says exactly which registry line to add.
    assert set(queue) == {"KXNBAPTS"}
    assert queue["KXNBAPTS"]["count"] == 2
    assert "points" in queue["KXNBAPTS"]["sample_title"]


def test_the_queue_excludes_what_we_have_already_decided_not_to_cover():
    queue = cat.unmapped_series(
        [
            _market("Over 7.5 runs scored?", series="KXNPBTOTAL"),
            _market("yes Houston", series="KXMVECROSSCATEGORY"),
        ]
    )
    # Otherwise the queue drowns in things nobody intends to do.
    assert queue == {}
