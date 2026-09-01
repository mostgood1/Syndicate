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
