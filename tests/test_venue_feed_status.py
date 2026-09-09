"""`venue_priced=0` has two opposite causes; the plan line now says which.

THE FAILURE THIS EXISTS FOR, measured 2026-08-25:

    PAPER2_PLAN_WRITTEN venue=kalshi     rows_in=86  venue_priced=0
    PAPER2_PLAN_WRITTEN venue=polymarket rows_in=89  venue_priced=30

...while the fan-in was simultaneously producing 2,344 Kalshi quotes off the same
artifact on the same service. A reader returned `[]`, `[]` became `(None, None)`,
and `(None, None)` is the value that means "this venue has no direct feed" --
indistinguishable from Novig, which genuinely has none. Kalshi silently priced
from the aggregator for weeks and the zero looked ordinary.

So the readings call for OPPOSITE work:

    capability_gap   nothing to do; the venue cannot be priced and never could
    policy_withheld  someone CHOSE this; the token names the flag that undoes it
    READER_FAILED    a venue we CAN price is not being priced -- a live defect

`test_a_venue_with_a_feed_reads_READER_FAILED` is the one that matters. The
others exist so it cannot pass vacuously.

THE FOURTH TOKEN, added 2026-09-09 (lane `reader-failed-policy-stamp`), fixes
the mirror-image mistake: `SYNDICATE_KALSHI_SOCCER_RESOLVERS` and
`SYNDICATE_POLYMARKET_PROP_RESOLVERS` are deliberate gates that strip their
matches out of the order path, and stripping the last one returns the same
`(None, None)` a broken reader returns. Every near-zero Kalshi match tick
observed on 2026-09-09 was a tomorrow-date build whose matches are 100% soccer
-- a system working as designed, stamped as a live defect in the exact field
someone would triage from.

`test_a_registered_venue_with_the_policy_ON_still_reads_READER_FAILED` is the
FALSIFICATION test: a change that quietly reclassifies a real defect as policy
is worse than the mislabel it fixes, so the new branch must be reachable ONLY
by a positive assertion from the code that did the withholding.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.portfolio_commit import (  # noqa: E402
    _VENUE_FEED_GAP,
    _VENUES_WITH_FEEDS,
    _VenueResolvers,
    _venue_feed_status,
)

KALSHI_FLAG = "SYNDICATE_KALSHI_SOCCER_RESOLVERS"
POLYMARKET_FLAG = "SYNDICATE_POLYMARKET_PROP_RESOLVERS"


def test_a_venue_with_a_feed_reads_READER_FAILED():
    """THE ALARM. Kalshi or Polymarket with no resolver is a defect, and the
    stamp must not let it read like Novig's ordinary zero."""
    for venue in _VENUES_WITH_FEEDS:
        got = _venue_feed_status(venue, None)
        assert got.startswith("READER_FAILED"), (venue, got)
        assert "capability_gap" not in got, (
            "%s must never read as a capability gap -- it HAS a feed" % venue)


def test_a_resolver_present_reads_venue_feed():
    """Off != on: the same venue with a resolver is the ordinary case."""
    for venue in _VENUES_WITH_FEEDS:
        assert _venue_feed_status(venue, object()) == "venue_feed"


def test_the_known_gaps_name_their_cause():
    """A reason a reader can act on, not a bare label. Both are MEASURED gaps:
    Novig's public tier is anonymised, ProphetX has no fan-in adapter."""
    novig = _venue_feed_status("novig", None)
    prophetx = _venue_feed_status("prophetx", None)
    assert novig.startswith("capability_gap:")
    assert prophetx.startswith("capability_gap:")
    assert "NOVIG_CLIENT_ID" in novig, "name the credential that would close it"
    assert "sandbox" in prophetx, "name why the host is not usable"


def test_a_gap_venue_with_a_resolver_would_read_as_priced():
    """If Novig ever gets credentials and a resolver, the stamp follows the
    RESOLVER rather than the table -- otherwise the table would go stale and
    keep reporting a gap that had been closed."""
    assert _venue_feed_status("novig", object()) == "venue_feed"


def test_an_unregistered_venue_is_neither_a_gap_nor_an_alarm():
    got = _venue_feed_status("someNewVenue", None)
    assert got == "no_feed:unregistered_venue"
    assert "READER_FAILED" not in got, (
        "a venue nobody registered is not evidence of a broken reader")


def test_it_is_case_and_whitespace_insensitive():
    assert _venue_feed_status("  KALSHI ", None).startswith("READER_FAILED")
    assert _venue_feed_status("Novig", None).startswith("capability_gap:")


def test_the_two_tables_do_not_overlap():
    """A venue in BOTH would make the branch order decide its meaning, which is
    how a gap could silently mask a reader failure."""
    assert not (set(_VENUE_FEED_GAP) & set(_VENUES_WITH_FEEDS))


# ---------------------------------------------------------------------------
# THE FOURTH CASE: a resolver withheld BY POLICY is not a reader failure.
# ---------------------------------------------------------------------------


def test_a_policy_withheld_resolver_names_the_flag_that_undoes_it():
    """The token has to be actionable without a grep. A reader triaging the
    plan line gets the env var, not a mood."""
    got = _venue_feed_status("kalshi", None, withheld_by=KALSHI_FLAG)
    assert got == "policy_withheld:%s" % KALSHI_FLAG
    poly = _venue_feed_status("polymarket", None, withheld_by=POLYMARKET_FLAG)
    assert poly == "policy_withheld:%s" % POLYMARKET_FLAG


def test_the_policy_token_is_not_a_variant_of_the_alarm():
    """DISTINCT, not a prefix, suffix or casing of `READER_FAILED`. Anything
    that matches an alarm grep would re-create the 2026-08-25 ambiguity in the
    other direction -- a triage sweep for the alarm would keep finding policy."""
    policy = _venue_feed_status("kalshi", None, withheld_by=KALSHI_FLAG)
    alarm = _venue_feed_status("kalshi", None)
    assert policy != alarm
    assert "READER_FAILED" not in policy
    assert "reader_failed" not in policy.lower()
    assert not policy.startswith(alarm.split(":", 1)[0])
    assert not alarm.startswith(policy.split(":", 1)[0])


def test_a_registered_venue_with_the_policy_ON_still_reads_READER_FAILED():
    """THE FALSIFICATION TEST. `withheld_by` is set ONLY by the site that
    watched withholding empty the match list. With the gate armed -- or with a
    non-soccer, non-prop slate -- nothing asserts it, and a `None` resolver on
    a venue that HAS a feed is what it has always been: a live defect.

    Byte-for-byte: the string must equal the pre-change one, not merely start
    with `READER_FAILED`."""
    for venue in _VENUES_WITH_FEEDS:
        for signal in (None, "", "   "):
            got = _venue_feed_status(venue, None, withheld_by=signal)
            assert got == "READER_FAILED:has_a_feed_but_resolver_returned_none", (
                venue,
                signal,
                got,
            )


def test_the_default_argument_reproduces_the_old_call_exactly():
    """Every existing two-argument call site keeps its old answer -- the new
    parameter cannot change a stamp by being added."""
    for venue in ("kalshi", "polymarket", "novig", "prophetx", "someNewVenue"):
        assert _venue_feed_status(venue, None) == _venue_feed_status(
            venue, None, withheld_by=None
        )


def test_a_bare_none_none_tuple_still_stamps_the_alarm():
    """UNKNOWN MUST NOT DEFAULT PERMISSIVE. Every other return path in
    `_venue_price_resolver` is a plain `(None, None)` with no attribute, so the
    caller's `getattr` yields None and the alarm survives an unconverted path."""
    plain = (None, None)
    price, _ticker = plain
    got = _venue_feed_status(
        "kalshi", price, withheld_by=getattr(plain, "withheld_by", None)
    )
    assert got == "READER_FAILED:has_a_feed_but_resolver_returned_none"


def test_a_resolver_present_beats_the_policy_signal():
    """If a resolver was built, the venue is priced -- whatever else was
    withheld. The stamp follows the RESOLVER first, as it always has."""
    assert (
        _venue_feed_status("kalshi", object(), withheld_by=KALSHI_FLAG)
        == "venue_feed"
    )


def test_the_policy_signal_does_not_disturb_the_gap_venues():
    """The two `capability_gap` venues have no resolver builder at all, so
    nothing can assert a policy for them -- and if something ever did, the
    stamp must still be actionable rather than silently swallowed."""
    for venue in _VENUE_FEED_GAP:
        assert _venue_feed_status(venue, None) == _VENUE_FEED_GAP[venue]
        assert _venue_feed_status(venue, None, withheld_by=None) == _VENUE_FEED_GAP[
            venue
        ]


def test_an_unregistered_venue_is_unchanged_by_the_new_parameter():
    assert (
        _venue_feed_status("someNewVenue", None, withheld_by=None)
        == "no_feed:unregistered_venue"
    )


def test_venue_resolvers_unpacks_as_the_old_two_tuple():
    """The carrier must not change any caller's shape: `price, ticker = ...`
    is the contract every consumer in the file is written against."""
    carrier = _VenueResolvers(None, None, withheld_by=KALSHI_FLAG)
    price, ticker = carrier
    assert (price, ticker) == (None, None)
    assert carrier == (None, None)
    assert len(carrier) == 2
    assert carrier.withheld_by == KALSHI_FLAG
    assert _VenueResolvers(None, None).withheld_by is None
    assert _VenueResolvers(None, None, withheld_by="").withheld_by is None


def test_every_flag_named_in_a_stamp_is_a_flag_the_code_actually_reads():
    """A token naming a switch that does not exist is worse than no token. Both
    names are asserted against the source that consumes them."""
    source = (REPO_ROOT / "pipeline" / "portfolio_commit.py").read_text(
        encoding="utf-8"
    )
    for flag in (KALSHI_FLAG, POLYMARKET_FLAG):
        assert 'os.environ.get("%s")' % flag in source, flag


def test_every_venue_with_an_order_adapter_has_a_feed():
    """The venues we can PLACE on are the venues we must be able to PRICE from.
    If an adapter is ever added for a gap venue, this fails and asks for the
    pricing question to be answered at the same time."""
    from pipeline.execute_portfolio import _venue_submitter

    for venue in _VENUE_FEED_GAP:
        assert _venue_submitter(venue) is None, (
            "%s gained an order adapter while still having no price feed -- "
            "placing on a venue we price from the aggregator is exactly the "
            "cross-venue mismatch the slippage guard rejects" % venue)


# ---------------------------------------------------------------------------
# REACHABILITY, not just presence. A branch nothing can reach is a comment.
#
# The two tests below drive the REAL producers -- `_resolvers_from_markets` and
# `_polymarket_price_resolver` -- with their joins stubbed, and check the signal
# that actually comes out. Each is paired with its negative: the SAME producer,
# the SAME flag setting, a join that matched nothing, must still hand back a
# bare `None` so the venue stamps READER_FAILED.
# ---------------------------------------------------------------------------


def _kalshi_stub(monkeypatch, matches, series_sport):
    import pipeline.portfolio_commit as pc
    from syndicate.features.shared import kalshi_board_join as kbj
    from syndicate.features.shared import kalshi_catalogue as kc

    monkeypatch.setattr(pc, "_board_rows_for_join", lambda _d: [{"event_id": "e1"}])
    monkeypatch.setattr(kbj, "_row_key", lambda _r: "k1")
    monkeypatch.setattr(
        kbj, "join_kalshi_to_board", lambda *a, **k: {"matches": list(matches)}
    )
    monkeypatch.setattr(kbj, "kalshi_price_resolver", lambda m: object())
    monkeypatch.setattr(kbj, "kalshi_ticker_resolver", lambda m: object())
    monkeypatch.setattr(kc, "sport_for_series", lambda s: series_sport)


def test_kalshi_soccer_withheld_is_reachable_and_names_its_flag(monkeypatch):
    """The policy path, end to end: an all-soccer match list with the gate OFF
    empties the resolver, and the stamp says WHO emptied it."""
    from pipeline.portfolio_commit import _resolvers_from_markets

    monkeypatch.delenv(KALSHI_FLAG, raising=False)
    _kalshi_stub(monkeypatch, [{"series": "KXEPL", "ticker": "t1"}], "soccer")
    got = _resolvers_from_markets([{"ticker": "t1"}], "2026-09-10")
    assert got == (None, None)
    assert getattr(got, "withheld_by", None) == KALSHI_FLAG
    assert _venue_feed_status(
        "kalshi", got[0], withheld_by=getattr(got, "withheld_by", None)
    ) == "policy_withheld:%s" % KALSHI_FLAG


def test_kalshi_an_empty_join_with_the_gate_off_is_still_READER_FAILED(monkeypatch):
    """THE FALSIFICATION, at the producer. Same venue, same gate value, but
    withholding took nothing -- so this zero is the 2026-08-25 defect and must
    keep reading as one. Reading the FLAG instead of the SUPPRESSION would flip
    this to policy and hide the alarm."""
    from pipeline.portfolio_commit import _resolvers_from_markets

    monkeypatch.delenv(KALSHI_FLAG, raising=False)
    _kalshi_stub(monkeypatch, [], "soccer")
    got = _resolvers_from_markets([{"ticker": "t1"}], "2026-09-10")
    assert got == (None, None)
    assert getattr(got, "withheld_by", None) is None
    assert _venue_feed_status(
        "kalshi", got[0], withheld_by=getattr(got, "withheld_by", None)
    ) == "READER_FAILED:has_a_feed_but_resolver_returned_none"


def test_kalshi_a_non_soccer_match_list_is_priced_normally(monkeypatch):
    """Off != on in the other direction: the gate withholds SOCCER, so a
    non-soccer slate must still build a resolver with the gate off."""
    from pipeline.portfolio_commit import _resolvers_from_markets

    monkeypatch.delenv(KALSHI_FLAG, raising=False)
    _kalshi_stub(monkeypatch, [{"series": "KXMLBGAME", "ticker": "t1"}], "mlb")
    got = _resolvers_from_markets([{"ticker": "t1"}], "2026-09-10")
    assert got[0] is not None
    assert _venue_feed_status("kalshi", got[0]) == "venue_feed"


def _polymarket_stub(monkeypatch, matches):
    import pipeline.portfolio_commit as pc
    from syndicate.features.shared import polymarket_board_join as pbj

    monkeypatch.setattr(pc, "_board_rows_for_join", lambda _d: [{"event_id": "e1"}])
    monkeypatch.setattr(pc, "_capture_polymarket_quotes", lambda *a, **k: None)
    monkeypatch.setattr(pbj, "load_polymarket_markets", lambda: ([{"id": "m1"}], None))
    monkeypatch.setattr(
        pbj, "join_polymarket_to_board", lambda *a, **k: {"matches": list(matches)}
    )
    monkeypatch.setattr(pbj, "polymarket_price_resolver", lambda m: object())
    monkeypatch.setattr(pbj, "polymarket_ticker_resolver", lambda m: object())


def test_polymarket_props_withheld_is_reachable_and_names_its_flag(monkeypatch):
    """The SAME shape at the other venue with a policy switch, so the two do
    not drift apart -- the whole reason this defect existed twice."""
    from pipeline.portfolio_commit import _polymarket_price_resolver

    monkeypatch.delenv(POLYMARKET_FLAG, raising=False)
    _polymarket_stub(monkeypatch, [{"player_name": "Aaron Judge"}])
    got = _polymarket_price_resolver("2026-09-10")
    assert got == (None, None)
    assert getattr(got, "withheld_by", None) == POLYMARKET_FLAG
    assert _venue_feed_status(
        "polymarket", got[0], withheld_by=getattr(got, "withheld_by", None)
    ) == "policy_withheld:%s" % POLYMARKET_FLAG


def test_polymarket_an_empty_join_with_the_gate_off_is_still_READER_FAILED(monkeypatch):
    from pipeline.portfolio_commit import _polymarket_price_resolver

    monkeypatch.delenv(POLYMARKET_FLAG, raising=False)
    _polymarket_stub(monkeypatch, [])
    got = _polymarket_price_resolver("2026-09-10")
    assert got == (None, None)
    assert getattr(got, "withheld_by", None) is None
    assert _venue_feed_status(
        "polymarket", got[0], withheld_by=getattr(got, "withheld_by", None)
    ) == "READER_FAILED:has_a_feed_but_resolver_returned_none"


def test_no_other_venue_has_a_resolver_policy_switch():
    """ITEM 4, asserted rather than asserted-in-prose. Only the two venues with
    a direct feed can reach the branch at all, and the source is checked for a
    third `*_RESOLVERS` gate that would need the same treatment. `novig` and
    `prophetx` have no resolver builder, so no switch of theirs could get
    there."""
    import re

    source = (REPO_ROOT / "pipeline" / "portfolio_commit.py").read_text(
        encoding="utf-8"
    )
    gates = set(re.findall(r'os\.environ\.get\("(SYNDICATE_\w*_RESOLVERS)"\)', source))
    assert gates == {KALSHI_FLAG, POLYMARKET_FLAG}, (
        "a new resolver policy gate exists and must set `withheld_by` too, or "
        "it will stamp READER_FAILED on a deliberate policy: %s" % sorted(gates)
    )
