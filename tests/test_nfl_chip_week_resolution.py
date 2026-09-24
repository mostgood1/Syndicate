"""NFL week enumeration must see every root, and a substitution must be audible.

THE DEFECT THESE PIN (2026-09-24, lane `nfl-chip-week-resolution`). On
refresh-worker `available_weeks(2026)` was `[1]` while the mounted disk carried
week-3 SmartSim2 projections, because `week_summaries` and
`_smartsim2_standalone_seasons_and_weeks` enumerated only
`default_nfl_source_root()` -- a root chosen by probing for
`upcoming_recs_*.csv`, a GIT-TRACKED file the ephemeral checkout has and the
disk may not (`#672`, which fixed `data_path` per-file and left the
enumeration). So `cards._resolved_week(3)` returned 1, the chip builder built
week-1 chips against current-week cards, and the Layer 2 board showed
`CHIP_JOIN_COVERAGE sport=nfl cards=1223 by_id=0 by_matchup=0 by_canonical=0` --
0 of 1,223 joined, every NFL compact card rendering its chip-less fallback,
with nothing logged.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl import cards as nfl_cards
from syndicate.features.nfl import sources as nfl_sources


@pytest.fixture()
def two_roots(tmp_path, monkeypatch):
    """A checkout-shaped root (recs only, week 1) and a disk-shaped root
    (projections only, weeks 1-3) -- the production shape that broke."""
    checkout = tmp_path / "checkout" / "nfl_source"
    disk = tmp_path / "disk" / "nfl_source"
    checkout.mkdir(parents=True)
    disk.mkdir(parents=True)

    (checkout / "upcoming_recs_2026_wk1_publish.csv").write_text("game_id\n2026_01_ATL_PIT\n", encoding="utf-8")
    for week in (1, 2, 3):
        (disk / f"smartsim2_projections_2026_wk{week}.csv").write_text("game_id\nx\n", encoding="utf-8")

    monkeypatch.setattr(nfl_sources, "_source_roots", lambda: [checkout, disk])
    monkeypatch.setattr(nfl_sources, "is_preseason_backfill_projection", lambda path: False)
    return checkout, disk


def test_the_root_probe_still_picks_the_checkout(two_roots):
    """The precondition. If this ever stops being true the defect is gone for a
    different reason and these tests would pass vacuously."""
    checkout, _disk = two_roots
    assert nfl_sources.default_nfl_source_root() == checkout


def test_projection_weeks_are_found_in_a_root_the_probe_did_not_pick(two_roots):
    weeks = nfl_sources._smartsim2_standalone_seasons_and_weeks()
    assert weeks.get(2026) == [1, 2, 3], weeks


def test_available_weeks_unions_both_roots(two_roots):
    assert nfl_sources.available_weeks(2026) == [1, 2, 3]


def test_resolved_week_returns_the_week_it_was_asked_for(two_roots, monkeypatch):
    monkeypatch.setattr(nfl_cards, "latest_season", lambda: 2026)
    assert nfl_cards._resolved_week(3, season=2026) == 3


def test_a_substitution_is_announced(tmp_path, monkeypatch, capsys):
    """The silence is the other half of the defect: week 3 -> week 1 with no
    signal is what let 1,223 unjoined cards go unreported."""
    monkeypatch.setattr(nfl_cards, "_available_card_weeks", lambda season=None: [1])
    monkeypatch.setattr(nfl_cards, "default_week", lambda season=None: 1)
    monkeypatch.setattr(nfl_cards, "latest_season", lambda: 2026)

    assert nfl_cards._resolved_week(3, season=2026) == 1
    out = capsys.readouterr().out
    assert "WEEK_SUBSTITUTED" in out
    assert "requested=3" in out and "resolved=1" in out


def test_no_line_when_the_week_resolves_cleanly(tmp_path, monkeypatch, capsys):
    """A correct resolve must stay silent, or the signal becomes noise and the
    next reader filters it out."""
    monkeypatch.setattr(nfl_cards, "_available_card_weeks", lambda season=None: [1, 2, 3])
    monkeypatch.setattr(nfl_cards, "default_week", lambda season=None: 3)
    monkeypatch.setattr(nfl_cards, "latest_season", lambda: 2026)

    assert nfl_cards._resolved_week(3, season=2026) == 3
    assert "WEEK_SUBSTITUTED" not in capsys.readouterr().out


def test_upcoming_recs_are_enumerated_across_roots(tmp_path, monkeypatch):
    """The recs family has the same single-root blindness as the projections."""
    a = tmp_path / "a" / "nfl_source"
    b = tmp_path / "b" / "nfl_source"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "upcoming_recs_2026_wk1.csv").write_text("game_id\nx\n", encoding="utf-8")
    (b / "upcoming_recs_2026_wk2.csv").write_text("game_id\nx\n", encoding="utf-8")
    monkeypatch.setattr(nfl_sources, "_source_roots", lambda: [a, b])

    names = [p.name for p in nfl_sources._upcoming_recs_paths()]
    assert names == ["upcoming_recs_2026_wk1.csv", "upcoming_recs_2026_wk2.csv"]


def test_a_duplicate_name_keeps_the_nearest_root(tmp_path, monkeypatch):
    """`data_path`'s rule: nearest root wins. Two copies must not double-count."""
    a = tmp_path / "a" / "nfl_source"
    b = tmp_path / "b" / "nfl_source"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "upcoming_recs_2026_wk1.csv").write_text("game_id\nnear\n", encoding="utf-8")
    (b / "upcoming_recs_2026_wk1.csv").write_text("game_id\nfar\n", encoding="utf-8")
    monkeypatch.setattr(nfl_sources, "_source_roots", lambda: [a, b])

    paths = nfl_sources._upcoming_recs_paths()
    assert len(paths) == 1
    assert paths[0].parent == a
