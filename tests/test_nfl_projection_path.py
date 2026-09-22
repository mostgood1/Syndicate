"""The NFL weekly projection file must resolve to the pipeline's copy, and the
live-odds-worker must actually HAVE that copy.

Measured 2026-09-22: `/nfl/api/live-lens` -- a snapshot built by `live_lens_loop`
on live-odds-worker -- matched the repo checkout's 2026-08-01 week-3 file on 16/16
games and the live file on 0/16, while web's own `/nfl/api/cards?week=3` served the
live file. Two causes, one per half of this file: the cards builder loaded the
file from `default_nfl_source_root()` (whose `upcoming_recs_*.csv` probe lands on
the checkout when the disk lacks that file), and live-odds-worker's disk never got
the projection file at all (the generator publishes to web only).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl import cards, picks, sources
from syndicate.features.shared import live_lens_loop, source_roots


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    """The live-odds-worker shape: the disk holds the pipeline's file, the checkout
    holds git's copy AND the `upcoming_recs_*.csv` the old resolver probes for."""
    disk = tmp_path / "disk" / "nfl_source"
    checkout = tmp_path / "src" / "data" / "nfl_source"
    for root, marker in ((disk, "live"), (checkout, "checkout")):
        root.mkdir(parents=True)
        (root / "smartsim2_projections_2026_wk3.csv").write_text(marker, encoding="utf-8")
    (checkout / "upcoming_recs_2026.csv").write_text("x", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "disk"))
    monkeypatch.delenv("SYNDICATE_NFL_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(sources, "_source_roots", lambda: [disk, checkout])
    monkeypatch.setattr(sources, "nfl_artifact_output_root", lambda: disk)
    source_roots.clear_source_root_caches()
    yield {"disk": disk, "checkout": checkout}
    source_roots.clear_source_root_caches()


def test_the_old_resolver_lands_on_the_checkout(two_roots):
    # The trap, reproduced -- this is what every loader used to pass.
    assert sources.default_nfl_source_root() == two_roots["checkout"]


def test_projection_path_prefers_the_disk_copy(two_roots):
    path = sources.smartsim2_projection_path(2026, 3)
    assert path.read_text(encoding="utf-8") == "live"


def test_projection_path_still_finds_a_checkout_only_week(two_roots):
    (two_roots["checkout"] / "smartsim2_projections_2026_wk9.csv").write_text("checkout", encoding="utf-8")
    assert sources.smartsim2_projection_path(2026, 9).read_text(encoding="utf-8") == "checkout"


@pytest.mark.parametrize("call", [
    lambda: cards.build_nfl_market_board(2026, 3),
    lambda: picks._standalone_smartsim2_pick_cards(2026, 3),
])
def test_loaders_read_the_disk_copy(two_roots, monkeypatch, call):
    seen = []

    def capture(*, season, week, data_root):
        seen.append(Path(data_root))
        return []

    monkeypatch.setattr(cards, "read_projection_artifact", capture)
    monkeypatch.setattr(picks, "read_projection_artifact", capture)
    try:
        call()
    except Exception:
        pass  # only the path handed to the loader is under test
    assert seen and seen[0] == two_roots["disk"]


def test_cards_page_reads_the_disk_copy(two_roots, monkeypatch):
    seen = []

    def capture(*, season, week, data_root):
        seen.append(Path(data_root))
        return []

    monkeypatch.setattr(cards, "read_projection_artifact", capture)
    monkeypatch.setattr(cards, "_resolved_week", lambda week, season: week)
    try:
        # The exact call the live lens makes (`nfl/live_lens.py`).
        cards.build_cards_page_context(3, season=2026)
    except Exception:
        pass  # only the path handed to the loader is under test
    assert two_roots["disk"] in seen


def test_the_lens_pulls_the_projection_before_building(monkeypatch):
    pulls, builds = [], []
    import syndicate.features.shared.artifact_publisher as publisher

    monkeypatch.setattr(publisher, "pull_streamed_artifact", lambda path, timeout_seconds=0: (pulls.append(path) or (True, 1)))
    monkeypatch.setattr(live_lens_loop, "_nfl_latest_season", lambda: 2026)
    monkeypatch.setattr(live_lens_loop, "_nfl_preseason_target_week", lambda season: None)
    monkeypatch.setattr(live_lens_loop, "_nfl_default_week", lambda season: 3)
    monkeypatch.setattr(live_lens_loop, "_nfl_build", lambda week, season: builds.append((season, week)) or {})
    monkeypatch.setattr(live_lens_loop, "_NFL_PROJECTION_PULL_AT", {}, raising=False)
    live_lens_loop._nfl_build_wrapper("2026-09-22")
    live_lens_loop._nfl_build_wrapper("2026-09-22")  # inside the throttle window
    assert pulls == ["nfl_source/smartsim2_projections_2026_wk3.csv"]
    assert builds == [(2026, 3), (2026, 3)]


def test_the_lens_does_not_pull_in_preseason(monkeypatch):
    pulls = []
    import syndicate.features.shared.artifact_publisher as publisher

    monkeypatch.setattr(publisher, "pull_streamed_artifact", lambda path, timeout_seconds=0: (pulls.append(path) or (True, 0)))
    monkeypatch.setattr(live_lens_loop, "_nfl_latest_season", lambda: 2026)
    monkeypatch.setattr(live_lens_loop, "_nfl_preseason_target_week", lambda season: 2)
    monkeypatch.setattr(live_lens_loop, "_nfl_build", lambda week, season: {})
    monkeypatch.setattr(live_lens_loop, "_NFL_PROJECTION_PULL_AT", {}, raising=False)
    live_lens_loop._nfl_build_wrapper("2026-08-15")
    assert pulls == []
