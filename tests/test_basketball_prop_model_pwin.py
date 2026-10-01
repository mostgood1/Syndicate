"""A prop pick's published win probability is the MODEL's, never the bare price.

/wnba/picks, 2026-10-01: "Jackie Young UNDER 20.5 @ +103 -- Win prob 49.3%, EV
30.8%". 49.3% is 100/203, the price-implied probability: `top_play` carried no
`p_win`, so the writer fell back to the PRICE and labelled it the model's. At
49.3% that bet's EV is ~0, not 30.8%. The model's own probability is recoverable
exactly from the EV it did carry: EV = q/p - 1, so q = p * (1 + ev) -> 0.6445.
(The additive `p + ev` is a different, already-fixed defect -- see
tests/test_nba_props_integrity.py.) Lane basketball-prop-model-pwin.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import refresh_nba_oddsapi_props as nba
from scripts import refresh_wnba_oddsapi_props as wnba

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("refresh_nba_oddsapi_props.py", "refresh_wnba_oddsapi_props.py")


@pytest.mark.parametrize("module", [nba, wnba], ids=["nba", "wnba"])
class TestModelPWin:
    def test_inverts_the_ev_the_play_carries(self, module):
        # The live 2026-10-01 row, verbatim.
        play = {"price": 103.0, "ev": 0.3083966100391583, "ev_pct": 30.83966100391583, "edge": 0.15191951233456075}
        q = module._model_p_win(play)
        assert q == pytest.approx(0.64453, abs=1e-4)
        # Consistency: the probability reproduces the EV it is published beside.
        assert q * (1 + 103 / 100) - 1 == pytest.approx(play["ev"], abs=1e-9)
        # ...and it agrees with the edge the same row carries (q = implied + edge).
        assert q == pytest.approx(100 / 203 + play["edge"], abs=1e-6)

    def test_negative_price(self, module):
        play = {"price": -122.0, "ev_pct": 16.577687574758894}
        assert module._model_p_win(play) == pytest.approx(122 / 222 * 1.16577687574758894, abs=1e-9)

    def test_own_p_win_wins_including_a_real_zero(self, module):
        assert module._model_p_win({"p_win": 0.61, "price": 103.0, "ev_pct": 30.8}) == 0.61
        assert module._model_p_win({"p_win": 0.0, "price": 103.0, "ev_pct": 30.8}) == 0.0

    def test_no_ev_is_absent_not_the_price(self, module):
        assert module._model_p_win({"price": 103.0}) is None

    def test_implausible_ev_is_absent(self, module):
        assert module._model_p_win({"price": 103.0, "ev_pct": 2264.8}) is None

    def test_no_price_is_absent(self, module):
        assert module._model_p_win({"ev_pct": 30.8}) is None


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_site_publishes_the_bare_price_as_the_model_probability(name):
    source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
    assert 'p_win_value = _american_price_to_prob(top_play.get("price"))' not in source, name


def test_wnba_slate_summary_names_the_projection_the_row_carries():
    # The summary read only top_play["proj"]; the row's `projection` falls back
    # to top_play_baseline / model[stat], so it printed "Pts projection -" beside
    # a published projection of 14.48.
    source = (REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8-sig")
    assert "projection {_format_plain_line(_float_or_none(top_play.get('proj')))}" not in source
