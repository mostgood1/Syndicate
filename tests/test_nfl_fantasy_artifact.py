"""Tests for the published projection artifact and the serving path.

Two properties, and both are things that were BROKEN and shipped-looking-fine
before these tests existed:

1. **PARITY** -- serving from the artifact must reproduce what the engine
   computes directly, for every scoring profile and for weeks as well as the
   season. Three separate defects were found by this comparison and by nothing
   else, each of which produced a plausible board.
2. **DEGRADATION** -- with no artifact and no raw inputs, the routes must
   return an empty state, not raise. On production the web dyno has neither,
   and the pre-artifact version 500'd all three routes.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.nfl.fantasy import build_draft_board_payload
from syndicate.features.nfl.fantasy import build_fantasy_payload
from syndicate.features.nfl.fantasy_artifact import ARTIFACT_VERSION
from syndicate.features.nfl.fantasy_artifact import artifact_path
from syndicate.features.nfl.fantasy_artifact import load_projection_artifact
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG
from syndicate.features.nfl.fantasy_projection import project_season
from syndicate.features.nfl.fantasy_scoring import resolve_scoring

SEASON = 2026

#: Rounding floor. Per-game stats are stored at 4dp and multiplied by up to ~17
#: games, so a few hundredths of a point is the exact-parity band.
TOLERANCE = 0.10


requires_artifact = pytest.mark.skipif(
    not artifact_path(SEASON).is_file(),
    reason="no published projection artifact on this substrate -- UNMEASURED",
)


@requires_artifact
def test_artifact_is_well_formed_and_within_the_publish_ceiling():
    artifact = load_projection_artifact(SEASON)
    assert artifact is not None
    assert artifact.players
    assert artifact.season_rows
    # `artifact_publisher._PUBLISH_MAX_BYTES`. A build over this is refused at
    # publish time and the worker log says only `too_large`, so check it here.
    assert artifact_path(SEASON).stat().st_size < 12 * 1024 * 1024


@requires_artifact
def test_version_mismatch_reads_as_absent_rather_than_as_garbage(tmp_path, monkeypatch):
    """A future schema change must degrade, not decode wrongly."""
    payload = json.loads(artifact_path(SEASON).read_text(encoding="utf-8"))
    payload["artifact_version"] = ARTIFACT_VERSION + 99
    target = tmp_path / "nfl_source" / "fantasy"
    target.mkdir(parents=True)
    (target / f"nfl_fantasy_projections_{SEASON}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(tmp_path / "nfl_source"))
    load_projection_artifact.cache_clear()
    try:
        assert load_projection_artifact(SEASON) is None
    finally:
        load_projection_artifact.cache_clear()


@requires_artifact
@pytest.mark.parametrize("scoring_key", ["ppr", "half_ppr", "standard"])
def test_season_parity_with_the_engine(scoring_key):
    """The artifact must reproduce the engine, not merely resemble it.

    This comparison caught, in order: every row +10.1 too high (a columnar
    artifact made `dst_points_allowed` present as 0.0 for every player, and
    zero points allowed is the ladder's +10 shutout bonus); every D/ST 8.5 too
    low (a season-total points-allowed run through a per-game ladder); and a
    ~1-point rounding drift from storing per-game rates at 2dp.
    """
    scoring = resolve_scoring(scoring_key)
    direct = {row.player_id: row.fantasy_points for row in project_season(SEASON, scoring, DEFAULT_CONFIG)}
    served = {
        row["player_id"]: row["fantasy_points"]
        for row in build_fantasy_payload(SEASON, scoring_key=scoring_key, limit=5000)["rows"]
    }
    common = set(direct) & set(served)
    assert len(common) > 300, f"only {len(common)} rows matched"
    worst = max((abs(direct[key] - served[key]), key) for key in common)
    assert worst[0] <= TOLERANCE, f"{worst[1]} differs by {worst[0]:.3f}"


@requires_artifact
@pytest.mark.parametrize("week", [1, 9, 18])
def test_weekly_parity_with_the_engine(week):
    """Weeks are checked separately because they scale differently -- and one
    row shape (a weekly D/ST) scales differently again, which is exactly the
    special case a re-derived rule got wrong while the season looked perfect."""
    scoring = resolve_scoring("ppr")
    direct = {
        row.player_id: row.fantasy_points
        for row in project_season(SEASON, scoring, DEFAULT_CONFIG, week=week)
    }
    served = {
        row["player_id"]: row["fantasy_points"]
        for row in build_fantasy_payload(SEASON, scoring_key="ppr", week=week, limit=5000)["rows"]
    }
    common = set(direct) & set(served)
    assert len(common) > 300
    worst = max((abs(direct[key] - served[key]), key) for key in common)
    assert worst[0] <= TOLERANCE, f"week {week}: {worst[1]} differs by {worst[0]:.3f}"


@requires_artifact
def test_defense_rows_survive_the_round_trip():
    """D/ST is the only non-linear scoring term and every artifact bug so far
    has landed on it, so it gets its own assertion rather than relying on the
    aggregate worst-case."""
    scoring = resolve_scoring("ppr")
    direct = {
        row.player_id: row.fantasy_points
        for row in project_season(SEASON, scoring, DEFAULT_CONFIG)
        if row.position == "DST"
    }
    served = {
        row["player_id"]: row["fantasy_points"]
        for row in build_fantasy_payload(SEASON, scoring_key="ppr", limit=5000)["rows"]
        if row["position"] == "DST"
    }
    assert len(direct) == 32 and len(served) == 32
    for key in direct:
        assert abs(direct[key] - served[key]) <= TOLERANCE, key
        # A defense scoring the shutout bonus every week would be ~10/game.
        assert 0 < served[key] < 250, f"{key} scored {served[key]}"


def test_routes_degrade_to_empty_rather_than_raising(tmp_path, monkeypatch):
    """THE PRODUCTION CASE. The web dyno has no artifact and none of the raw
    nflverse inputs, and `CLAUDE.md` requires a degraded state there, not a
    backfill and not a 500."""
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(tmp_path / "nfl_source"))
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NFL_FANTASY_ALLOW_REQUEST_COMPUTE", raising=False)
    (tmp_path / "nfl_source").mkdir(parents=True)
    load_projection_artifact.cache_clear()
    try:
        payload = build_fantasy_payload(SEASON, scoring_key="ppr", limit=10)
        assert payload["rows"] == []
        assert payload["available"] is False
        assert payload["source"]["mode"] == "unavailable"
        assert "reason" in payload["source"]

        board = build_draft_board_payload(SEASON, scoring_key="ppr", limit=10)
        assert board["rows"] == []
        assert board["available"] is False
    finally:
        load_projection_artifact.cache_clear()


@requires_artifact
def test_served_payload_names_its_source():
    payload = build_fantasy_payload(SEASON, scoring_key="ppr", limit=5)
    assert payload["source"]["mode"] == "artifact"
    assert payload["source"]["generated_at"]
    assert payload["available"] is True
    assert payload["basis"]["artifact"]["exists"] is True


@requires_artifact
def test_a_newly_published_artifact_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    """THE PRODUCTION BUG THIS EXISTS TO PREVENT A SECOND TIME.

    Artifacts arrive by being PUSHED from the worker at any moment, so a cache
    keyed only on the season memoises the pre-publish answer and serves the
    empty state until the process restarts. Measured on production: publish
    returned PUBLISH_OK, /api/ops/artifacts/export showed the file on disk with
    count 1, and the route still reported `available: false`.
    """
    import shutil

    source = artifact_path(SEASON)  # resolved BEFORE the env is repointed
    root = tmp_path / "nfl_source"
    root.mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(root))
    load_projection_artifact.cache_clear()
    try:
        assert load_projection_artifact(SEASON) is None, "expected absent to start"
        # ASK THE CODE WHERE IT LOOKS rather than assuming the layout. The NFL
        # source root probes several candidates and, in an empty directory,
        # settles on a `source_artifacts/` variant -- so a test that hardcodes
        # `<root>/fantasy/` writes somewhere nothing reads and "fails" for a
        # reason that has nothing to do with the behaviour under test.
        destination = artifact_path(SEASON)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        after = load_projection_artifact(SEASON)
        assert after is not None, "a published artifact was not picked up without a restart"
        assert after.season_rows
    finally:
        load_projection_artifact.cache_clear()
