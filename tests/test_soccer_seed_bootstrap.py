"""The soccer seed bootstrap, and the live-odds-worker gap it exists to close.

Background, measured on production 2026-08-15: `live-odds-worker` is the
service that runs `scripts/build_soccer_artifacts.py`, its entrypoint ran no
seed bootstrap, and its disk therefore had no `players_*.csv`. Every published
`recommendations_*.json` carried `player_props: 0`, which blanked all 107
player-prop rows on the soccer board.

These tests pin the two properties that matter and one that is easy to lose:
the copy happens, the copy NEVER overwrites, and the live-odds-worker entrypoint
actually calls it. That last one is the regression that already happened four
times -- the helper being correct has never been the failing part.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from syndicate.features.soccer import seed_bootstrap
from syndicate.features.soccer.seed_bootstrap import (
    SEED_FAMILIES,
    bootstrap_soccer_seed_family,
    bootstrap_soccer_seed_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_players_csv(path: Path, *, player_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["league", "player_id", "player_name", "team"])
        writer.writerow(["testleague", player_id, "A Player", "A Team"])


@pytest.fixture
def fake_checkout(tmp_path, monkeypatch):
    """A stand-in git checkout, so these tests do not depend on real league data."""
    checkout = tmp_path / "checkout"
    source_root = checkout / "data" / "soccer_source"
    _write_players_csv(source_root / "alpha_league" / "players" / "players_2025.csv", player_id="a1")
    _write_players_csv(source_root / "beta_league" / "players" / "players_2025.csv", player_id="b1")
    # A league with no players file at all -- must be reported, not crashed on.
    (source_root / "gamma_league" / "history").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(seed_bootstrap, "REPO_ROOT", checkout)
    return checkout


@pytest.fixture
def runtime_disk(tmp_path, monkeypatch):
    disk = tmp_path / "runtime"
    disk.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(disk))
    return disk


def test_seeds_leagues_whose_runtime_disk_has_no_players_file(fake_checkout, runtime_disk):
    """The #145 case: committed CSVs exist, the runtime disk has none."""
    seeded = bootstrap_soccer_seed_family(
        relative_subdir="players", glob_pattern="players_*.csv", log_prefix="test"
    )

    assert sorted(seeded) == ["alpha_league", "beta_league"]
    copied = runtime_disk / "soccer_source" / "alpha_league" / "players" / "players_2025.csv"
    assert copied.is_file()
    assert "a1" in copied.read_text(encoding="utf-8")


def test_never_overwrites_a_file_the_pipeline_already_wrote(fake_checkout, runtime_disk):
    """The safety property the whole design rests on.

    A league with ANY matching file on the runtime disk is skipped wholesale.
    Without this the seeder could clobber freshly fetched pipeline output with a
    git artifact of unknown vintage -- the same first-root-wins mistake
    `load_soccer_projections` was fixed for in `#360`.
    """
    live = runtime_disk / "soccer_source" / "alpha_league" / "players" / "players_2025.csv"
    _write_players_csv(live, player_id="LIVE_PIPELINE_ROW")

    seeded = bootstrap_soccer_seed_family(
        relative_subdir="players", glob_pattern="players_*.csv", log_prefix="test"
    )

    assert seeded == ["beta_league"], "alpha_league already had a file and must be skipped"
    assert "LIVE_PIPELINE_ROW" in live.read_text(encoding="utf-8")


def test_reports_rather_than_raises_when_the_checkout_has_no_soccer_tree(tmp_path, runtime_disk, monkeypatch):
    monkeypatch.setattr(seed_bootstrap, "REPO_ROOT", tmp_path / "nonexistent")

    assert bootstrap_soccer_seed_family(
        relative_subdir="players", glob_pattern="players_*.csv", log_prefix="test"
    ) == []


def test_bootstrap_covers_every_family_the_sim_reads(fake_checkout, runtime_disk):
    """Seeding only the family someone measured is how this bug recurred.

    `_load_team_ratings` alone has TWO disk branches (`history` for the
    goals-based leagues, `team_history` for the Understat ones), and `#361`
    records that seeding one left the other silently broken for a session.
    """
    seeded = bootstrap_soccer_seed_files(log_prefix="test")

    assert set(seeded) == {"players", "api/schedule", "history", "team_history"}
    assert {family[0] for family in SEED_FAMILIES} == set(seeded)


def test_the_real_checkout_carries_players_for_the_leagues_that_went_dark():
    """Guards the premise, not the code.

    The four leagues that published `player_props: 0` on 2026-08-15 all have
    real, committed roster CSVs. If this ever fails, the bug is upstream in the
    checkout and copying harder will not fix it.
    """
    for league in ("eredivisie", "primeira_liga", "championship", "belgian_pro_league"):
        files = sorted((REPO_ROOT / "data" / "soccer_source" / league / "players").glob("players_*.csv"))
        assert files, f"{league} has no committed players CSV"
        rows = files[-1].read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) > 100, f"{league} roster looks empty: {len(rows)} lines"


def test_live_odds_worker_entrypoint_calls_the_bootstrap():
    """The actual regression. The helper was never the part that broke.

    `run_refresh_worker.py` had a working bootstrap the whole time; the soccer
    sim simply moved to a service that did not call one. Asserted against the
    entrypoint source because there is no way to boot the real worker in a test,
    and because a passing unit test on the helper is exactly what this bug wore
    as a disguise.
    """
    source = (REPO_ROOT / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")

    assert "bootstrap_soccer_seed_files" in source
    assert "syndicate.features.soccer.seed_bootstrap" in source
    # It must not sit after the loop starts, and it needs the state backend up
    # first because it resolves the destination through `data_root()`.
    assert source.index("assert_refresh_state_backend_ready") < source.index("bootstrap_soccer_seed_files")
    assert source.index("bootstrap_soccer_seed_files") < source.index("_acquire_process_lock()")
