"""The $5 minimum on a Polymarket order priced at the ask [user 2026-10-21, "Lift to $5",
lane live-min-stake-five].

`_price_at_ask` scales the planned stake by the Kelly ratio at the ask, which turned
$5-10 plan stakes into sub-$1 orders. With `SYNDICATE_POLYMARKET_AT_ASK_MIN_STAKE_DOLLARS`
set, the stake is lifted back to min(floor, planned): never above the planned stake,
which `check_order` has already charged against every cap. Absent is today's build.

The shape used throughout: plan +122 (p = 0.45045) at 10% EV gives fair 0.4955. At a
0.48 ask that is +3.2% (clears the 2% minimum); the Kelly ratio is 0.0298 / 0.0820 =
0.363, so the plan's $10 shrinks to $3.63.
"""

from __future__ import annotations

from tests.test_polymarket_us_orders import _ask_build, _book, _priced

_FLOOR_ENV = "SYNDICATE_POLYMARKET_AT_ASK_MIN_STAKE_DOLLARS"
_WORSE_ASK = _book(offers=(("0.4800", "5000.0"),))


def test_off_the_kelly_shrink_stands(monkeypatch, capsys):
    """Reachability, off side: absent floor leaves the $3.63 shrink."""
    monkeypatch.delenv(_FLOOR_ENV, raising=False)
    sent, refused = _ask_build(_priced(), monkeypatch, price=0.48, book=_WORSE_ASK)
    assert refused is None
    assert sent["stake_dollars"] == 3.63
    assert "min_stake_lifted_from" not in capsys.readouterr().out


def test_on_the_shrunk_stake_is_lifted_to_the_floor(monkeypatch, capsys):
    """Reachability, on side: the same build sends $5.00 and logs what it lifted from."""
    monkeypatch.setenv(_FLOOR_ENV, "5")
    sent, refused = _ask_build(_priced(), monkeypatch, price=0.48, book=_WORSE_ASK)
    assert refused is None
    assert sent["stake_dollars"] == 5.0
    assert sent["price_dollars"] == 0.48
    out = capsys.readouterr().out
    assert "decision=place" in out and "stake=5.0" in out and "min_stake_lifted_from=3.63" in out


def test_the_floor_never_exceeds_the_planned_stake(monkeypatch):
    """A $3 plan stake (already charged against the caps) lifts to $3, not to $5."""
    monkeypatch.setenv(_FLOOR_ENV, "5")
    request = _priced()
    request.requested_stake_dollars = 3.0
    sent, refused = _ask_build(request, monkeypatch, price=0.48, book=_WORSE_ASK)
    assert refused is None
    assert sent["stake_dollars"] == 3.0


def test_a_stake_already_above_the_floor_is_unchanged(monkeypatch):
    """At a 0.45 ask the ratio is 1.0 and the plan's $10 goes out whole."""
    monkeypatch.setenv(_FLOOR_ENV, "5")
    sent, refused = _ask_build(_priced(), monkeypatch)
    assert refused is None
    assert sent["stake_dollars"] == 10.0


def test_a_refusal_still_refuses_with_the_floor_on(monkeypatch):
    """The floor lifts a placed stake; it never rescues an order the EV check refused."""
    monkeypatch.setenv(_FLOOR_ENV, "5")
    sent, refused = _ask_build(_priced(), monkeypatch, price=0.48, book=_WORSE_ASK, min_ev=11.0)
    assert sent is None and refused == "ask_ev_below_min"


def test_an_unusable_floor_is_off_not_guessed(monkeypatch):
    for raw in ("abc", "0", "-5", "inf"):
        monkeypatch.setenv(_FLOOR_ENV, raw)
        sent, refused = _ask_build(_priced(), monkeypatch, price=0.48, book=_WORSE_ASK)
        assert refused is None and sent["stake_dollars"] == 3.63, raw
