"""The NCAAF `pace` block: fed from real data, prior-season, and REACHABLE.

`state.md` recorded `pace` as "NULL AT SOURCE -- all 4 keys are `None`". The
measured reality was worse, and it is what these tests pin: an absent pace block
is NOT neutral. `drive_priors._pace_index` falls through to a hardcoded 24.0
s/play, so every NCAAF game ran at

    pace_index = clamp((28.0 - 24.0) / 10.0, -1, 1) = +0.400

while the real 2025 league mean is 26.56 -> +0.144. Measured through the engine,
that is 151.6 s/drive against 179.5 for an average team, ~18% too fast. Faster
drives fit more drives into a game, inflating possessions and TOTALS -- the
surface `state.md` records this engine getting wrong (margins calibrated,
totals not).

A neutral default is exactly what `model_engine_standard.md` warns about: it
makes an unfed field indistinguishable from a working one. Here the default was
not even neutral, it was *wrong in a specific direction*, which is why the
reachability test below asserts `off != on` rather than merely `on is not None`.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2 import drive_priors as dp
from syndicate.features.ncaaf import feature_payload as fp


# --------------------------------------------------------------------------
# The engine side. These need no snapshot and no network -- they pin the
# CONSTANT that made this worth fixing.
# --------------------------------------------------------------------------

def test_absent_pace_block_is_not_neutral():
    """The whole premise. An absent block pins +0.400, it does not mean 'unknown'."""
    priors = dp.build_drive_priors({}).to_dict()
    assert priors["pace_seconds_per_play"] == pytest.approx(24.0)
    assert priors["pace_index"] == pytest.approx(0.400, abs=1e-6), (
        "an absent pace block should still be the hardcoded 24.0 -> +0.4; if this "
        "changed, the premise of the pace snapshot changed with it"
    )


def test_league_mean_pace_moves_the_engine_off_the_default():
    """off != on, stated as the two numbers that differ rather than 'it is set'."""
    off = dp.build_drive_priors({}).to_dict()
    on = dp.build_drive_priors({"pace": {"pace_seconds_per_play": 26.56}}).to_dict()
    assert on["pace_index"] != off["pace_index"]
    assert on["expected_clock_seconds"] > off["expected_clock_seconds"], (
        "the average team plays SLOWER than the 24.0 default, so feeding real "
        "pace must lengthen the modelled drive, not shorten it"
    )
    # ~18% too fast, the figure the snapshot builder's docstring cites.
    assert off["expected_clock_seconds"] / on["expected_clock_seconds"] < 0.90


@pytest.mark.parametrize("seconds_per_play", [21.0, 24.0, 26.56, 29.0, 33.4])
def test_real_pace_range_never_hits_a_clamp_bound(seconds_per_play):
    """Raw values are safe to feed -- CHECKED, because centring is not cosmetic.

    `sp_offense_defense_rating`'s docstring records a whole class of bug from
    feeding an uncentred rating into an engine whose neutral is 0. The same
    question applies to pace, and the answer is different: over 266 teams the
    real span (21.0..33.4) maps inside the engine's own clamp with 0% at a
    bound, so the 28.0 pivot already covers the distribution.
    """
    priors = dp.build_drive_priors({"pace": {"pace_seconds_per_play": seconds_per_play}}).to_dict()
    assert -1.0 < priors["pace_index"] < 1.0


def test_pace_changes_clock_and_plays_but_not_scoring_rates():
    """The effect must be ISOLATED, or a totals re-fit cannot attribute anything."""
    fast = dp.build_drive_priors({"pace": {"pace_seconds_per_play": 21.0}}).to_dict()
    slow = dp.build_drive_priors({"pace": {"pace_seconds_per_play": 33.4}}).to_dict()
    assert fast["expected_clock_seconds"] != slow["expected_clock_seconds"]
    assert fast["expected_play_count"] != slow["expected_play_count"]
    assert fast["drive_success_probability"] == pytest.approx(slow["drive_success_probability"])
    assert fast["touchdown_probability"] == pytest.approx(slow["touchdown_probability"])


# --------------------------------------------------------------------------
# The payload side, on a synthetic snapshot root so these never depend on
# which season happens to be built on the machine running them.
# --------------------------------------------------------------------------

def _write_snapshot(root: Path, block: str, filename: str, rows: list[dict[str, object]]) -> None:
    target = root / block
    target.mkdir(parents=True, exist_ok=True)
    with open(target / filename, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture()
def snapshot_root(tmp_path):
    root = tmp_path / "processed"
    _write_snapshot(root, "team_registry", "ncaaf_team_registry_snapshot.csv", [
        {"team_id": "T1", "school": "Fast State", "mascot_name": "Jets",
         "canonical_team_name": "Fast State", "display_name": "Fast State", "abbreviation": "FST"},
        {"team_id": "T2", "school": "Slow Tech", "mascot_name": "Anchors",
         "canonical_team_name": "Slow Tech", "display_name": "Slow Tech", "abbreviation": "SLW"},
    ])
    _write_snapshot(root, "pace", "ncaaf_pace_snapshot.csv", [
        # PRIOR season relative to the 2026 games asked for below.
        {"team": "Fast State", "season": 2025, "offensive_plays": 900, "offensive_drives": 140,
         "offensive_seconds": 18900, "seconds_per_play": 21.0, "plays_per_drive": 6.43},
        {"team": "Slow Tech", "season": 2025, "offensive_plays": 800, "offensive_drives": 130,
         "offensive_seconds": 24720, "seconds_per_play": 30.9, "plays_per_drive": 6.15},
        # SAME season as the games -- must be ignored. See the leakage test.
        {"team": "Fast State", "season": 2026, "offensive_plays": 900, "offensive_drives": 140,
         "offensive_seconds": 27000, "seconds_per_play": 30.0, "plays_per_drive": 6.43},
    ])
    fp.set_snapshot_root(root)
    fp.reset_caches()
    yield root
    fp.set_snapshot_root(None)
    fp.reset_caches()


def test_pace_block_is_emitted_from_the_snapshot(snapshot_root):
    payload = fp.build_payload(home_team="Fast State", away_team="Slow Tech", season=2026)
    pace = payload.get("pace")
    assert pace, "pace block missing -- the snapshot is present and should have resolved"
    assert pace["home_pace_secs_play"] == pytest.approx(21.0)
    assert pace["away_pace_secs_play"] == pytest.approx(30.9)
    # The engine reads ONE game-level number: the mean of the two offences.
    assert pace["pace_seconds_per_play"] == pytest.approx(25.95)


def test_pace_reads_the_PRIOR_season_not_the_game_s_own(snapshot_root):
    """The leakage guard, and it is why pace is keyed differently to its siblings.

    Returning production, coach continuity and the portal are PRESEASON facts,
    so season S is as-of for a season-S game. Pace is an IN-SEASON aggregate:
    season 2026 pace contains the 2026 game being predicted. `state.md` records
    that shape costing 30% of apparent skill (r 0.663 vs 0.509 as-of, 558
    games). The fixture seeds a 2026 row at 30.0 s/play precisely so that
    reading the wrong season is a visible, failing number rather than a subtle
    optimism in a backtest.
    """
    payload = fp.build_payload(home_team="Fast State", away_team="Slow Tech", season=2026)
    assert payload["pace"]["home_pace_secs_play"] == pytest.approx(21.0), (
        "read the 2026 row (30.0) instead of the 2025 row (21.0) -- this is "
        "lookahead leakage, not a lookup bug"
    )


def test_absent_list_is_computed_and_stops_naming_pace(snapshot_root):
    """A stale self-description is the failure the named list exists to prevent."""
    payload = fp.build_payload(home_team="Fast State", away_team="Slow Tech", season=2026)
    absent = payload["adapter_metadata"]["blocks_deliberately_absent"]
    assert "pace" not in absent, "pace is being FED; claiming it absent is worse than silence"
    assert "defensive_metrics" in absent and "player_usage" in absent, (
        "the other two blocks are still genuinely unfed and must stay named"
    )


def test_payload_pace_reaches_the_engine_and_changes_it(snapshot_root):
    """The end-to-end claim: snapshot -> payload -> priors, off != on."""
    payload = fp.build_payload(home_team="Fast State", away_team="Slow Tech", season=2026)
    without = {k: v for k, v in payload.items() if k != "pace"}
    on = dp.build_drive_priors(payload).to_dict()
    off = dp.build_drive_priors(without).to_dict()
    assert off["pace_index"] == pytest.approx(0.400, abs=1e-6)
    assert on["pace_index"] != pytest.approx(off["pace_index"])
    assert on["expected_clock_seconds"] != pytest.approx(off["expected_clock_seconds"])


def test_a_team_missing_from_the_snapshot_yields_no_pace_block(snapshot_root):
    """Absent stays ABSENT rather than becoming a neutral-looking number.

    Emitting a league-mean default for an unknown team would make "we have no
    pace for this team" read identically to "this team plays at league pace".
    """
    payload = fp.build_payload(home_team="Unknown School", away_team="Slow Tech", season=2026)
    assert "pace" not in payload
