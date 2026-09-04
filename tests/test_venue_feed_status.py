"""`venue_priced=0` has two opposite causes; the plan line now says which.

THE FAILURE THIS EXISTS FOR, measured 2026-08-25:

    PAPER2_PLAN_WRITTEN venue=kalshi     rows_in=86  venue_priced=0
    PAPER2_PLAN_WRITTEN venue=polymarket rows_in=89  venue_priced=30

...while the fan-in was simultaneously producing 2,344 Kalshi quotes off the same
artifact on the same service. A reader returned `[]`, `[]` became `(None, None)`,
and `(None, None)` is the value that means "this venue has no direct feed" --
indistinguishable from Novig, which genuinely has none. Kalshi silently priced
from the aggregator for weeks and the zero looked ordinary.

So the two readings call for OPPOSITE work:

    capability_gap   nothing to do; the venue cannot be priced and never could
    READER_FAILED    a venue we CAN price is not being priced -- a live defect

`test_a_venue_with_a_feed_reads_READER_FAILED` is the one that matters. The
others exist so it cannot pass vacuously.
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
    _venue_feed_status,
)


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
