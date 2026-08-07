"""#259 -- an absent market must not match every market.

Found while verifying #247 offline against the real evaluation ledger, which
production had never been able to measure because settlement crash-looped every
time it ran.

#247 replaced a keyword-sniffed family gate with a canonical-key comparison, and
gave it a fallback: allow the match when neither side canonicalises, so an
unrecognised market cannot veto a row every other signal says is right. That is
correct for two UNKNOWN vocabularies. It was wrong for an EMPTY one -- and 127
of 1,384 real ledger records (9%) carry an empty market, which under the old
fallback matched outs, home_runs, strikeouts and everything else equally.

Combined with the overlapping identity keys #247's own commit message
documents, that is the failure #247 existed to prevent, reintroduced through
the empty case rather than the mismatched one.
"""

from __future__ import annotations

from syndicate.features.shared.evaluation_settlement import _markets_compatible


def test_an_empty_record_market_matches_nothing():
    for row_market in ("outs", "home_runs", "strikeouts", "h2h", "totals"):
        assert _markets_compatible("", row_market, "mlb") is False
        assert _markets_compatible(None, row_market, "mlb") is False
        assert _markets_compatible("   ", row_market, "mlb") is False


def test_an_empty_graded_market_matches_nothing():
    assert _markets_compatible("pitcher outs", "", "mlb") is False
    assert _markets_compatible("pitcher outs", None, "mlb") is False


def test_two_absent_markets_are_still_allowed():
    """The refusal is ASYMMETRIC on purpose, and this is the case that keeps it
    honest. Two empty sides is #247's own scenario -- neither party claims a
    market, so the gate has no opinion and identity and line decide. Refusing it
    would re-break what #247 fixed; its own test asserts this.

    One empty side against a real market is the dangerous one, and that is the
    only thing #259 refuses."""
    assert _markets_compatible("", "", "mlb") is True
    assert _markets_compatible(None, None, "mlb") is True


def test_247s_real_joins_still_work():
    # Every one of these was blocked before #247 and is confirmed against the
    # real ledger's own vocabulary.
    assert _markets_compatible("pitcher outs", "outs", "mlb") is True
    assert _markets_compatible("outs recorded", "outs", "mlb") is True
    assert _markets_compatible("hitter hits", "hits", "mlb") is True
    assert _markets_compatible("hitter total bases", "total_bases", "mlb") is True
    assert _markets_compatible("pitcher strikeouts", "strikeouts", "mlb") is True
    assert _markets_compatible("moneyline", "h2h", "mlb") is True
    assert _markets_compatible("ats", "spreads", "mlb") is True


def test_a_prop_still_cannot_settle_against_a_game_total():
    """The dangerous case #247 called out: batter_total_bases used to resolve
    to the 'totals' family, so a player prop could have settled against a GAME
    total had their identity keys overlapped."""
    assert _markets_compatible("batter_total_bases", "totals", "mlb") is False
    assert _markets_compatible("hitter total bases", "totals", "mlb") is False


def test_a_display_label_in_the_market_field_matches_nothing():
    # 360 of 1,384 real ledger records (26%) carry "betting card" as their
    # market -- a display label leaking into an identity field. It resolves to
    # no canonical key and must not join, which is correct behaviour over a
    # broken input. The fix belongs upstream at the producer.
    assert _markets_compatible("betting card", "outs", "mlb") is False
    assert _markets_compatible("betting card", "h2h", "mlb") is False
