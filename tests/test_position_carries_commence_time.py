"""A position's IDENTITY and its PAYLOAD are two different lists.

`commence_time` was removed from `_POSITION_IDENTITY_FIELDS` on 2026-08-30 and
that removal was CORRECT: a restated kickoff minted a second position key and
put ~$9.12 on the board where one bet was intended.

But the position payload is built by PROJECTING over that same tuple —

    position = {field: row.get(field) for field in _POSITION_IDENTITY_FIELDS}

— so the field also vanished from the position, from the `OrderRequest` built
from it, and from every ledger row written afterwards. MEASURED 2026-08-31
across 59 live orders, a perfect temporal split with zero overlap:

    WITH commence_time    28   submitted 16:41:53 .. 18:59:26
    WITHOUT               31   submitted 19:05:14 .. 03:40:39

It presents as a SOCCER gap (18 of 19 missing) purely because soccer's orders
are the recent ones. MLB and WNBA lose it identically after the cutover, which
is why the test below checks a NON-soccer row too.

The consequence is not cosmetic: anything reasoning about time-to-event —
staleness, live-vs-pregame, hours-to-kickoff — is blind on every order placed
after the cutover.
"""
from __future__ import annotations

from syndicate.features.shared import portfolio_commit as pc


def test_commence_time_is_not_in_the_identity():
    """The double-bet fix must STAY fixed. If this fails, a restated kickoff
    mints a second position key again and the money goes out twice."""
    assert "commence_time" not in pc._POSITION_IDENTITY_FIELDS


def test_the_legacy_identity_still_carries_it():
    """Recognising a pre-fix order depends on the old tuple being intact."""
    assert "commence_time" in pc._LEGACY_POSITION_IDENTITY_FIELDS


def test_two_rows_differing_only_in_commence_time_share_one_key():
    """The measured incident, as an assertion: identical bet, restated kickoff
    (17:41:00Z -> 18:11:00Z), ONE position."""
    base = {
        "sport": "mlb", "event_id": "e1", "kind": "game", "market": "totals",
        "segment": "full", "player_name": None,
        "home_team": "Tigers", "away_team": "Dodgers",
    }
    a = dict(base, commence_time="2026-08-30T17:41:00Z")
    b = dict(base, commence_time="2026-08-30T18:11:00Z")
    assert pc.position_key(a) == pc.position_key(b)
    # ...and the LEGACY key still separates them, which is how a pre-fix order
    # is recognised rather than re-placed.
    assert pc.legacy_position_key(a) != pc.legacy_position_key(b)


def test_the_identity_projection_does_not_define_the_payload():
    """THE REGRESSION GUARD. `commence_time` must be reachable from the built
    position even though it is absent from the identity tuple — that is the
    exact combination that broke, and a projection-only build cannot satisfy
    both assertions at once."""
    src = "".join(open(pc.__file__, encoding="utf-8").readlines())
    assert '"commence_time": row.get("commence_time")' in src, (
        "the position payload no longer carries commence_time -- every order "
        "written after this point is blind to time-to-event"
    )
    i_ident = src.index("_POSITION_IDENTITY_FIELDS = (")
    i_close = src.index(")", i_ident)
    assert "commence_time" not in src[i_ident:i_close], (
        "commence_time is back in the IDENTITY tuple -- that is the double-bet"
    )
