"""Provenance and line-plausibility guards for WNBA card evaluation.

Numbers measured 2026-08-31 (lane `wnba-accuracy-assessment`): the vendor root's
market lines correlate -0.0396 with actual margin against +0.6785 on the
Syndicate root, and pooling the two turns a +16.5% Brier skill into -21.5%.
"""
from __future__ import annotations

from syndicate.features.shared import wnba_card_provenance as prov


def test_roots_are_distinguished():
    assert prov.root_of("/opt/render/project/data/wnba_source/data/processed/game_cards_2026-08-30.csv") == prov.SYNDICATE
    assert prov.root_of("/opt/render/project/data/wnba_source/source_artifacts/data/processed/x.csv") == prov.VENDOR
    assert prov.root_of(r"C:\data\wnba_source\source_artifacts\data\processed\x.csv") == prov.VENDOR


def test_unknown_provenance_does_not_default_to_trusted():
    """An unknown must not silently join the trusted pile."""
    for value in (None, "", "   "):
        assert prov.root_of(value) == prov.UNKNOWN
    buckets = prov.split_by_root([{"source_path": None}])
    assert buckets[prov.UNKNOWN] and not buckets[prov.SYNDICATE]


def test_the_measured_impossible_lines_are_caught():
    """The literal outliers from the audit."""
    assert prov.implausible_line_reasons({"home_spread": -55.0})
    assert prov.implausible_line_reasons({"total": 253.0})
    assert prov.implausible_line_reasons({"home_spread_price": -89.125})
    assert prov.implausible_line_reasons({"away_spread_price": -94.375})


def test_real_lines_pass_including_lopsided_ones():
    """Wide on purpose -- catching 55.0 must not reject a real 18.5."""
    clean = {"home_spread": -18.5, "total": 185.5, "home_spread_price": -110.0,
             "total_over_price": 100.0, "home_ml": -2057.0}
    assert prov.implausible_line_reasons(clean) == []
    assert prov.implausible_line_reasons({"home_spread": 20.5, "total": 145.0}) == []


def test_missing_and_garbage_values_do_not_raise():
    assert prov.implausible_line_reasons(None) == []
    assert prov.implausible_line_reasons({}) == []
    assert prov.implausible_line_reasons({"home_spread": "n/a", "total": None}) == []


def test_coverage_note_names_what_was_excluded():
    """A silently filtered sample reads as a complete one."""
    buckets = prov.split_by_root(
        [{"source_path": "a/wnba_source/data/processed/x"}] * 106
        + [{"source_path": "a/wnba_source/source_artifacts/data/processed/x"}] * 79
    )
    note = prov.coverage_note(buckets)
    assert "185 rows" in note and "syndicate 106" in note and "vendor 79" in note
    assert "42.7%" in note, "the vendor share must be stated, not implied"


# ------------------------------------------------- read-time confidence hygiene
def test_read_time_refuses_certainty():
    """The producer clamp does not reach artifacts that already exist.

    Verified on the served payload 2026-09-01, AFTER the producer fix deployed:
    a 2026-08-30 card still showed p_win = 1.0, because p_win is baked into
    recommendations_slate_*.json and copied verbatim.
    """
    assert prov.sane_win_probability(1.0) == prov.CONFIDENCE_CEILING
    assert prov.sane_win_probability(0.0) == prov.CONFIDENCE_FLOOR
    assert prov.sane_win_probability(0.732) == 0.732
    assert prov.sane_win_probability(None) is None
    assert prov.sane_win_probability("n/a") is None


def test_read_time_refuses_impossible_ev_rather_than_clamping():
    assert prov.sane_ev_pct(2264.8) is None
    assert prov.sane_ev_pct(57.8) == 57.8
    assert prov.sane_ev_pct(None) is None


def test_card_builder_applies_both():
    """The wiring: a stale artifact's impossible values must not reach a reader."""
    from syndicate.features.wnba import cards

    rows = cards._source_game_market_recommendations([
        {"market": "TOTAL", "selection": "UNDER", "line": 185.5,
         "price": -110, "p_win": 1.0, "ev_pct": 2264.8},
    ])
    assert rows, "fixture must produce a row"
    assert rows[0]["p_win"] == prov.CONFIDENCE_CEILING
    assert rows[0]["ev_pct"] is None
