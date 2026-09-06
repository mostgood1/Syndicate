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
from syndicate.features.nfl.fantasy import build_fantasy_page_context
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


def _isolate_source_root(monkeypatch, root):
    """Point the NFL source root at *root* AND stop the repo mirror answering.

    REPOINTING THE ENV VAR ALONE DOES NOT SIMULATE ABSENCE.
    `source_roots.preferred_artifact_roots` appends the repo `data/nfl_source`
    mirror as a candidate root unless strict hosted storage is enabled -- by
    design, as `CLAUDE.md`'s cold-start safety net. And
    `nfl_fantasy_projections_<season>.json` is UNTRACKED: absent from
    `origin/main`, present only on a machine where someone has run the build.

    So these three tests were machine-dependent. They passed on CI and on a
    fresh dyno, where the file genuinely does not exist, and failed on any
    developer box that had generated it -- the result turned on untracked local
    state rather than on the behaviour under test.

    Measured 2026-09-05 on a box that had the artifact: with the env repointed
    at an empty tmp dir, `load_projection_artifact(2026)` still returned the
    real checkout artifact; with the mirror fallback disabled it correctly
    returned None. That is the whole defect.

    `RENDER` is cleared as well because `preferred_artifact_roots` re-appends
    the mirror when RENDER is set even under strict mode -- so setting strict
    alone would leave the fallback live on exactly the substrate these tests
    are modelling.
    """
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(root))
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "1")


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
    _isolate_source_root(monkeypatch, tmp_path / "nfl_source")
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
    _isolate_source_root(monkeypatch, tmp_path / "nfl_source")
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
    _isolate_source_root(monkeypatch, root)
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


# ---------------------------------------------------------------------------
# Positional groupings
# ---------------------------------------------------------------------------

@requires_artifact
def test_position_view_filters_server_side_and_keeps_league_wide_replacement():
    """A position view is a different question from the board, not a scroll
    position -- and its VOR must stay comparable to the all-up board's, which
    means replacement level is computed over the FULL pool either way."""
    everything = build_fantasy_page_context(SEASON, scoring_key="ppr")
    running_backs = build_fantasy_page_context(SEASON, scoring_key="ppr", position="RB")

    assert everything["showing_all_positions"] is True
    assert running_backs["selected_positions"] == ["RB"]

    # Only the selected group is rendered.
    assert set(running_backs["by_position"]) == {"RB"}
    assert set(everything["by_position"]) == set(everything["positions"])

    # The board narrows to the position...
    assert running_backs["board"], "expected a filtered board"
    assert {row["position"] for row in running_backs["board"]} == {"RB"}

    # ...but the pricing does not change, because replacement level is a
    # property of the league, not of what is on screen.
    board_by_id = {row["player_id"]: row for row in everything["board"]}
    for row in running_backs["board"]:
        twin = board_by_id.get(row["player_id"])
        if twin is None:
            continue
        assert row["draft"]["value_over_replacement"] == twin["draft"]["value_over_replacement"]
        assert row["draft"]["replacement_points"] == twin["draft"]["replacement_points"]


@requires_artifact
def test_position_counts_report_the_full_pool_not_the_rendered_slice():
    """The heading says "showing N of M". M must be the real pool, or the page
    quietly under-reports how many players it knows about."""
    context = build_fantasy_page_context(SEASON, scoring_key="ppr", position="RB")
    rendered = len(context["by_position"]["RB"])
    total = context["position_counts"]["RB"]
    assert total >= rendered
    assert total > 100, f"expected a real RB pool, got {total}"


@requires_artifact
def test_unknown_position_falls_back_to_all_rather_than_emptying_the_page():
    context = build_fantasy_page_context(SEASON, scoring_key="ppr", position="quarterbackish")
    assert context["showing_all_positions"] is True
    assert context["board"]


@requires_artifact
@pytest.mark.parametrize(
    "position,expected",
    [
        ("QB", {"passing_yards", "passing_tds", "interceptions"}),
        ("RB", {"carries", "rushing_yards", "rushing_tds", "receptions"}),
        ("WR", {"targets", "receptions", "receiving_yards", "receiving_tds"}),
        ("TE", {"targets", "receptions", "receiving_yards"}),
        ("K", {"fg_made_0_39", "fg_made_40_49", "fg_made_50_plus", "pat_made"}),
        ("DST", {"dst_sacks", "dst_interceptions", "dst_touchdowns", "dst_points_allowed"}),
    ],
)
def test_every_position_carries_real_projected_STATS_not_just_points(position, expected):
    """The surface projects STAT LINES, not only fantasy scores.

    This is the property that lets one artifact serve three scoring profiles,
    and it is worth asserting per position because each reads a different
    subset and a missing key scores silently as zero.
    """
    context = build_fantasy_page_context(SEASON, scoring_key="ppr", position=position)
    rows = context["by_position"][position]
    assert rows, f"no {position} rows"
    top = rows[0]
    missing = [key for key in expected if key not in top["stat_line"]]
    assert not missing, f"{position} top row missing {missing}"
    assert any(top["stat_line"][key] for key in expected), f"{position} stats all zero"


@requires_artifact
def test_full_stat_view_shows_only_columns_that_carry_a_value():
    """A quarterback has no field goals. Rendering all 28 columns for every
    group would be mostly zeros, so the column set is derived from the DATA --
    which also means it adapts if a stat starts being populated later."""
    from syndicate.features.nfl.fantasy import FULL_STAT_COLUMNS

    for position, expected_present, expected_absent in (
        ("QB", "passing_yards", "fg_made_0_39"),
        ("RB", "carries", "dst_sacks"),
        ("K", "fg_made_0_39", "targets"),
        ("DST", "dst_sacks", "carries"),
    ):
        context = build_fantasy_page_context(
            SEASON, scoring_key="ppr", position=position, stat_view="full"
        )
        keys = [key for key, _ in context["stat_columns"][position]]
        assert keys, f"{position} produced no stat columns"
        assert expected_present in keys, f"{position} missing {expected_present}"
        assert expected_absent not in keys, f"{position} should not show {expected_absent}"
        assert set(keys) <= {key for key, _ in FULL_STAT_COLUMNS}


@requires_artifact
def test_full_stat_view_is_wider_than_the_key_view():
    key_view = build_fantasy_page_context(SEASON, scoring_key="ppr", position="RB")
    full_view = build_fantasy_page_context(
        SEASON, scoring_key="ppr", position="RB", stat_view="full"
    )
    assert not key_view["full_stats"]
    assert full_view["full_stats"]
    assert len(full_view["stat_columns"]["RB"]) >= 10


@requires_artifact
@pytest.mark.parametrize("week", [1, 5, 12])
def test_weekly_view_carries_per_week_projected_stats_and_an_opponent(week):
    """The artifact breaks stats out by week, so the weekly view is a real
    per-game stat line against a named opponent -- not the season line divided
    by seventeen."""
    context = build_fantasy_page_context(
        SEASON, scoring_key="ppr", position="RB", week=week, stat_view="full"
    )
    rows = context["by_position"]["RB"]
    assert rows, f"no RB rows in week {week}"
    top = rows[0]
    assert top["week"] == week
    assert top["opponent"], "weekly row has no opponent"
    # A single game, not a season: a lead back carries ~10-25 times.
    assert 0 < top["stat_line"]["carries"] < 40, top["stat_line"]["carries"]
    assert 0 < top["stat_line"]["rushing_yards"] < 200


@requires_artifact
def test_weekly_stats_differ_by_opponent():
    """If every week were identical the weekly view would be decoration."""
    lines = []
    for week in (1, 5, 12):
        context = build_fantasy_page_context(
            SEASON, scoring_key="ppr", position="RB", week=week, stat_view="full"
        )
        top = context["by_position"]["RB"][0]
        lines.append((top["opponent"], round(top["fantasy_points"], 2)))
    assert len({value for _, value in lines}) > 1, f"weekly projections are identical: {lines}"


@requires_artifact
def test_positions_are_multiselect():
    """"RB,WR" is one question -- what is left in my flex -- not two pages."""
    both = build_fantasy_page_context(SEASON, scoring_key="ppr", position="RB,WR")
    assert both["selected_positions"] == ["RB", "WR"]
    assert set(both["by_position"]) == {"RB", "WR"}
    assert {row["position"] for row in both["board"]} == {"RB", "WR"}
    # Order in the query must not change the answer.
    reversed_order = build_fantasy_page_context(SEASON, scoring_key="ppr", position="WR,RB")
    assert reversed_order["selected_positions"] == ["RB", "WR"]


@requires_artifact
def test_a_partly_unknown_selection_keeps_the_positions_it_recognises():
    """An unknown token must widen or be ignored -- never empty the board."""
    context = build_fantasy_page_context(SEASON, scoring_key="ppr", position="RB,notaposition")
    assert context["selected_positions"] == ["RB"]
    assert context["board"]


@requires_artifact
def test_the_all_up_draft_board_gains_stat_columns_in_the_full_view():
    """THE BUG THIS PINS: "all projected stats" widened only the per-position
    tables, so clicking it on the default view -- where the draft board is the
    first and largest table -- appeared to do nothing at all."""
    key_view = build_fantasy_page_context(SEASON, scoring_key="ppr")
    full_view = build_fantasy_page_context(SEASON, scoring_key="ppr", stat_view="full")
    assert key_view["board_stat_columns"] == []
    assert len(full_view["board_stat_columns"]) >= 20, "the board must widen too"
    keys = [key for key, _ in full_view["board_stat_columns"]]
    assert "rushing_yards" in keys and "receiving_yards" in keys and "passing_yards" in keys


@requires_artifact
def test_board_stat_columns_narrow_with_the_position_selection():
    """Columns come from the rows on screen, so a defence-only board should not
    carry rushing columns."""
    defense = build_fantasy_page_context(
        SEASON, scoring_key="ppr", position="DST", stat_view="full"
    )
    keys = [key for key, _ in defense["board_stat_columns"]]
    assert "dst_sacks" in keys
    assert "carries" not in keys


# ---------------------------------------------------------------------------
# The publish guard
# ---------------------------------------------------------------------------

def _load_build_script():
    import importlib.util
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parents[1] / "scripts" / "build_nfl_fantasy_projection_artifact.py"
    spec = importlib.util.spec_from_file_location("_ff_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Row:
    def __init__(self, points):
        self.fantasy_points = points


def test_guard_refuses_the_artifact_that_actually_reached_production():
    """THE REGRESSION. The first worker run published an artifact with
    `weeks: []`, 318KB against a normal 2.83MB, and a top player at 525.5 PPR
    points against a correct ~270 -- because the worker had no
    `schedules_games.csv`, so there were no game environments.

    Nothing raised. It overwrote a correct artifact and served a board that
    looked entirely plausible. The pre-flight INPUT check could not see it: it
    verifies the roster and the usage documents, and the schedule was not on
    its list. An input checklist only covers the inputs someone thought of.
    """
    build = _load_build_script()
    reasons = build.degenerate_reasons([_Row(525.5), _Row(300.0)], {}, list(range(1, 19)))
    assert len(reasons) == 2, reasons
    assert any("0 produced" in reason for reason in reasons)
    assert any("outside the plausible" in reason for reason in reasons)


def test_guard_lets_a_healthy_artifact_through():
    build = _load_build_script()
    assert build.degenerate_reasons([_Row(326.4), _Row(311.4)], {1: [_Row(20.0)]}, [1]) == []


def test_guard_band_is_tight_enough_to_have_caught_it():
    """A band wide enough to admit the failure it was written for is not a
    check. The first version ran to 600 and waved 525.5 straight through."""
    build = _load_build_script()
    low, high = build.PLAUSIBLE_TOP_SEASON_POINTS
    assert high < 525.5, "the ceiling must exclude the value that reached production"
    assert high > 400.0, "but must still admit a genuinely exceptional season"
    assert low > 0


def test_guard_catches_an_empty_projection():
    build = _load_build_script()
    assert build.degenerate_reasons([], {}, []) == ["no season projections produced"]


@requires_artifact
def test_basis_describes_what_BUILT_the_numbers_not_what_serves_them():
    """A payload that probes its own substrate for provenance lies on the web.

    Measured on production: the served basis reported `depth_chart_as_of: null`,
    `games_with_line: 0 of 0` and `history_seasons: []` for an artifact actually
    built from a 2026-08-21 depth chart, 112 of 272 lined games, and three
    seasons of play-by-play. The web dyno holds none of those inputs by design,
    so every zero was a fact about the reader rather than about the projection.
    """
    payload = build_fantasy_payload(SEASON, scoring_key="ppr", limit=3)
    basis = payload["basis"]
    assert basis["roster"]["depth_chart_as_of"], "build-time depth chart must survive to the payload"
    assert basis["market"]["games_with_line"] > 0
    assert basis["history_seasons"], "build-time usage seasons must survive"
    # And the serving process's own view is kept, clearly labelled as such.
    assert basis["served_by"]["mode"] == "artifact"
    assert "reads the published artifact" in basis["served_by"]["note"]


@requires_artifact
def test_news_reports_itself_as_off_and_unfitted():
    """The one claim the news block must never overstate."""
    payload = build_fantasy_payload(SEASON, scoring_key="ppr", limit=1)
    news = payload["basis"]["news"]
    assert news["applied"] is False
    assert news["fitted"] is False
