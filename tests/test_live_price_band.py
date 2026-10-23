"""Live entry price band [user 2026-10-23, "Band: 40c-75c only", lane live-min-stake-five].

price_bucket_audit (dbbf3ebe): under 40c lost ~36% every week, 75c+ lost, 40-75c was
~breakeven. With `SYNDICATE_LIVE_PRICE_BAND="0.40,0.75"` a live entry whose price, as a
probability, falls outside [0.40, 0.75) is refused by name and writes nothing.
Reachability first: the same plan row is SENT with the band absent and REFUSED with it set.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as L
from tests.test_venue_contract_dedupe import _isolated, _row, _run  # noqa: F401 -- fixture reused

_ENV = "SYNDICATE_LIVE_PRICE_BAND"


def _outside_row(price):
    """A plan row the harness keeps: the longshot needs a larger edge to clear the minimum stake."""
    extra = {"ev_pct": 30.0, "model_edge_pct": 10.0} if price > 0 else {}
    return _row("spreads", quote={"price": price, "bookmaker": "kalshi"}, **extra)


@pytest.mark.parametrize("price", [-525, 160])  # 0.84 (heavy favourite), 0.385 (longshot)
def test_off_a_row_outside_the_band_is_sent(monkeypatch, price):
    monkeypatch.delenv(_ENV, raising=False)
    result, sent = _run(monkeypatch, [_outside_row(price)])
    assert len(sent) == 1
    assert "outside_price_band" not in result["refused"]


@pytest.mark.parametrize("price", [-525, 160])
def test_on_a_row_outside_the_band_is_refused_and_nothing_written(monkeypatch, capsys, price):
    monkeypatch.setenv(_ENV, "0.40,0.75")
    result, sent = _run(monkeypatch, [_outside_row(price)])
    assert sent == []
    assert result["refused"].get("outside_price_band") == 1
    assert not [o for o in L._load().get("orders") or [] if o.get("mode") == "live"]
    assert "REFUSED_PRICE_BAND venue=kalshi" in capsys.readouterr().out


def test_on_a_row_inside_the_band_is_sent(monkeypatch):
    """+104 is 0.49: inside [0.40, 0.75)."""
    monkeypatch.setenv(_ENV, "0.40,0.75")
    result, sent = _run(monkeypatch, [_row("spreads")])
    assert len(sent) == 1
    assert "outside_price_band" not in result["refused"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.40,0.75", (0.40, 0.75)),
        (" 0.4 , 0.9 ", (0.40, 0.90)),
        ("", None),
        ("0.75,0.40", None),
        ("abc", None),
        ("0.4", None),
        ("-0.1,0.5", None),
        ("0.4,1.5", None),
    ],
)
def test_the_band_parses_or_is_off(monkeypatch, raw, expected):
    from pipeline import execute_portfolio as runner

    monkeypatch.setenv(_ENV, raw)
    assert runner.live_price_band() == expected
