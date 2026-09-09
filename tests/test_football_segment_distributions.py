"""Package S1: the football sim stops discarding its per-quarter output.

TEST ORDER IS THE POINT, and it is the order the lane brief mandated:

  1. REACHABILITY FIRST -- `off != on`, PROVEN. `model_engine_standard.md`:
     "reachability test before correctness tests for anything behind a flag.
     Four inert features in one session were caught by that and nothing else."
     A correctness test on a feature nothing can reach is green and worthless.
     Here reachability has two halves and BOTH are asserted: with the flag OFF
     the projections CSV is byte-identical to the pre-change writer's and no
     sidecar exists; with it ON the CSV is STILL byte-identical (this package
     changes no served number) and the sidecar appears with the new key.
  2. The `h1`/`h2` binning matches `segment_actuals`' football map on a
     synthetic game that includes an OVERTIME period. A distribution binned
     differently from the way it is graded is worse than no distribution.
  3. Histogram counts sum to the sim count.
  4. A scoreless quarter is a populated `0` bucket, never an absent key.

`simulate_game` needs no `data/` tree, so these run in a data-excluded session
worktree -- the whole engine is pure Python plus a shipped calibration profile.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (  # noqa: E402
    NFL_CALIBRATION_PROFILE,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import (  # noqa: E402
    SmartSim2SimulationInput,
)
from syndicate.features.football.sim_engine.smartsim2.game_simulator import (  # noqa: E402
    simulate_game,
)
from syndicate.features.nfl.smartsim2_projection import (  # noqa: E402
    PROJECTION_CSV_COLUMNS,
    SmartSimNflProjection,
    write_projection_artifact,
)
from syndicate.features.shared.artifact_publisher import (  # noqa: E402
    is_hot_artifact_relative_path,
)
from syndicate.features.shared.football_segment_distributions import (  # noqa: E402
    SEGMENT_DISTRIBUTIONS_ENV,
    SEGMENT_KEYS,
    FootballSegmentAccumulator,
    read_segment_distributions_artifact,
    segment_distributions_artifact_path,
    segment_distributions_enabled,
    segment_points,
    write_segment_distributions_artifact,
)
from syndicate.features.shared.segment_actuals import SEGMENT_PERIODS  # noqa: E402

FIXED_SEED = 20260909


def _projection(**overrides) -> SmartSimNflProjection:
    base = dict(
        game_id="2026_01_BUF_KC",
        season=2026,
        week=1,
        home_team="KC",
        away_team="BUF",
        home_score_mean=24.5,
        away_score_mean=21.25,
        margin_mean=3.25,
        total_mean=45.75,
        margin_stdev=13.1,
        total_stdev=11.4,
        home_win_rate=0.5733,
        seeds_used=300,
        profile_name="nfl_v2",
        rating_source="nflverse_pbp_epa_rolling[a/b]",
        generated_at="2026-09-09T00:00:00+00:00",
    )
    base.update(overrides)
    return SmartSimNflProjection(**base)


def _pre_change_csv_bytes(projections) -> bytes:
    """The EXACT bytes `write_projection_artifact` produced before this package.

    Reconstructed here rather than trusted, so the identity claim rests on an
    independent writer and not on the code under test agreeing with itself.
    The 16 column names are spelled out for the same reason: importing
    `PROJECTION_CSV_COLUMNS` would make a column ADDED by this package
    invisible to the comparison, which is precisely the regression this test
    exists to catch.
    """
    columns = (
        "game_id", "season", "week", "home_team", "away_team",
        "home_score_mean", "away_score_mean", "margin_mean", "total_mean",
        "margin_stdev", "total_stdev", "home_win_rate", "seeds_used",
        "profile_name", "rating_source", "generated_at",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns))
    writer.writeheader()
    for projection in projections:
        payload = projection.to_dict()
        writer.writerow({column: str(payload[column]) for column in columns})
    return buffer.getvalue().encode("utf-8")


def _sim(seed: int):
    return simulate_game(
        SmartSim2SimulationInput(home_team="KC", away_team="BUF", seed=seed),
        profile=NFL_CALIBRATION_PROFILE,
    )


# --------------------------------------------------------------------------
# 1. REACHABILITY. off != on, both halves asserted.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, False),      # ABSENT is OFF. Checked against the code's own
        ("", False),        # default, not assumed (CLAUDE.md: absent != off).
        ("0", False),
        ("false", False),
        ("no", False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("on", True),
        ("yes", True),
    ],
)
def test_flag_default_is_off(monkeypatch, raw, expected) -> None:
    monkeypatch.delenv(SEGMENT_DISTRIBUTIONS_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(SEGMENT_DISTRIBUTIONS_ENV, raw)
    assert segment_distributions_enabled() is expected


def test_flag_off_leaves_the_projection_csv_byte_identical(tmp_path, monkeypatch) -> None:
    """The lane's falsification test. If this ever fails, S1 changed a served
    number and its central claim ("persists more, serves the same") is false."""
    monkeypatch.delenv(SEGMENT_DISTRIBUTIONS_ENV, raising=False)
    projections = [_projection(), _projection(game_id="2026_01_NYJ_MIA", home_team="MIA", away_team="NYJ")]

    path = write_projection_artifact(projections, season=2026, week=1, data_root=tmp_path)

    assert path.read_bytes() == _pre_change_csv_bytes(projections)
    assert tuple(PROJECTION_CSV_COLUMNS) == (
        "game_id", "season", "week", "home_team", "away_team",
        "home_score_mean", "away_score_mean", "margin_mean", "total_mean",
        "margin_stdev", "total_stdev", "home_win_rate", "seeds_used",
        "profile_name", "rating_source", "generated_at",
    )
    # OFF means the sidecar is not merely empty -- it does not exist.
    assert not segment_distributions_artifact_path(season=2026, week=1, data_root=tmp_path).exists()
    assert read_segment_distributions_artifact(season=2026, week=1, data_root=tmp_path) == {}


def test_flag_on_adds_the_sidecar_and_still_leaves_the_csv_identical(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(SEGMENT_DISTRIBUTIONS_ENV, "1")
    assert segment_distributions_enabled() is True

    projections = [_projection()]
    csv_path = write_projection_artifact(projections, season=2026, week=1, data_root=tmp_path)

    accumulator = FootballSegmentAccumulator()
    for seed in range(1, 26):
        assert accumulator.add(_sim(seed)) is True
    block = accumulator.payload()
    assert block is not None
    sidecar = write_segment_distributions_artifact(
        {"2026_01_BUF_KC": block}, season=2026, week=1, data_root=tmp_path
    )

    # ON: the new artifact exists and carries the new key ...
    assert sidecar.exists()
    games = read_segment_distributions_artifact(season=2026, week=1, data_root=tmp_path)
    assert set(games) == {"2026_01_BUF_KC"}
    assert set(games["2026_01_BUF_KC"]["segments"]) == set(SEGMENT_KEYS)
    # ... and the served CSV did NOT move.
    assert csv_path.read_bytes() == _pre_change_csv_bytes(projections)


def test_generators_wire_the_accumulator_behind_the_flag() -> None:
    """PRESENCE IS NOT REACHABILITY. Assert the seam that used to discard
    `quarter_log` now folds it, in BOTH generators, by inspecting the source --
    the scripts themselves need pbp/CFBD inputs a test cannot supply."""
    import inspect

    for module_name in (
        "scripts.generate_smartsim2_nfl_projections",
        "scripts.generate_smartsim2_ncaaf_projections",
    ):
        module = __import__(module_name, fromlist=["build_projection"])
        source = inspect.getsource(module.build_projection)
        assert "segment_accumulator.add(output)" in source, module_name
        signature = inspect.signature(module.build_projection)
        assert signature.parameters["segment_accumulator"].default is None, module_name


def test_the_sidecar_paths_are_allowlisted_for_both_sports() -> None:
    """An artifact written but not in HOT_ARTIFACT_PATTERNS cannot cross the
    worker/web boundary at all, so the payload would be unreachable AND
    unauditable on Render. Both sports, because they write to different roots."""
    assert is_hot_artifact_relative_path("nfl_source/smartsim2_segment_distributions_2026_wk1.json")
    assert is_hot_artifact_relative_path("ncaaf_source/data/smartsim2_segment_distributions_2026_wk3.json")


# --------------------------------------------------------------------------
# 2. BINNING. h1/h2 against `segment_actuals`, overtime included.
# --------------------------------------------------------------------------

class _FakeOutput:
    """A synthetic game, shaped exactly like `SmartSim2SimulationOutput`.

    OVERTIME IS EXPRESSED THE WAY THE REAL ENGINE EXPRESSES IT: `simulate_game`
    scores overtime onto `final_score` without ever appending a quarter record,
    so OT here is the residual between `final_score` and the quarter log --
    not a fifth `quarter_log` entry, which would be a shape the producer never
    emits and a test that proves nothing about it.
    """

    def __init__(self, quarters, *, overtime=(0, 0), seed=1, initial_quarter=1,
                 initial_score=(0, 0), regulation_quarters=4):
        self.seed = seed
        self.quarter_log = tuple(
            {"quarter": index + 1, "home_points": home, "away_points": away,
             "start_clock": 900, "end_clock": 0, "drive_count": 5, "possession_count": 5}
            for index, (home, away) in enumerate(quarters)
        )
        self.final_score = {
            "home": sum(h for h, _ in quarters) + overtime[0],
            "away": sum(a for _, a in quarters) + overtime[1],
        }
        self.input_state = {
            "initial_quarter": initial_quarter,
            "initial_score_home": initial_score[0],
            "initial_score_away": initial_score[1],
            "quarters": regulation_quarters,
        }


def test_h1_and_h2_match_the_segment_actuals_football_map_with_overtime() -> None:
    # q1 7-0, q2 3-7, q3 0-10, q4 14-7, then an overtime TD for home.
    output = _FakeOutput([(7, 0), (3, 7), (0, 10), (14, 7)], overtime=(6, 0))
    points = segment_points(output)
    assert points is not None

    assert SEGMENT_PERIODS["nfl"]["h1"] == (1, 2)
    assert SEGMENT_PERIODS["nfl"]["h2"] == (3, 4, None)
    assert SEGMENT_PERIODS["ncaaf"] == SEGMENT_PERIODS["nfl"]

    assert points["q1"] == (7, 0)
    assert points["q2"] == (3, 7)
    assert points["q3"] == (0, 10)
    assert points["q4"] == (14, 7)
    # h1 = q1 + q2, and NOTHING else.
    assert points["h1"] == (10, 7)
    # h2 = q3 + q4 + EVERY overtime period -- the `None` in the map above.
    # Regulation-only would be (14, 17); the extra 6 is the OT score.
    assert points["h2"] == (20, 17)
    assert points["full"] == (30, 24)
    assert points["h1"][0] + points["h2"][0] == points["full"][0]
    assert points["h1"][1] + points["h2"][1] == points["full"][1]


def test_h2_is_not_labelled_regulation_only_because_it_is_not() -> None:
    accumulator = FootballSegmentAccumulator()
    accumulator.add(_FakeOutput([(7, 0), (0, 7), (7, 0), (0, 7)], overtime=(0, 3)))
    block = accumulator.payload()
    assert block["segments"]["h2"]["h2_regulation_only"] is False
    assert block["overtime_sims"] == 1
    # And the OT points really did land in h2, not vanish. Regulation h2 is
    # 7-7 (margin 0); the away field goal in overtime makes it 7-10, margin -3.
    # The -3 IS the assertion: a regulation-only bin would read 0 here.
    assert block["segments"]["h2"]["margin_dist"] == {-3: 1}
    assert block["segments"]["h2"]["total_points_dist"] == {17: 1}
    assert block["segments"]["h1"]["margin_dist"] == {0: 1}


def test_a_resumed_or_carried_in_game_is_refused_not_mislabelled() -> None:
    """The OT residual is only OT when the sim started 0-0 at kickoff. Anything
    else cannot separate overtime from carried-in points, so it is counted as
    `skipped` rather than binned wrong."""
    accumulator = FootballSegmentAccumulator()
    assert accumulator.add(_FakeOutput([(7, 0), (0, 7), (7, 0), (0, 7)], initial_quarter=3)) is False
    assert accumulator.add(_FakeOutput([(7, 0), (0, 7), (7, 0), (0, 7)], initial_score=(10, 3))) is False
    assert accumulator.sims == 0
    assert accumulator.skipped == 2
    assert accumulator.payload() is None


def test_provenance_is_stamped_on_the_block() -> None:
    accumulator = FootballSegmentAccumulator()
    for seed in range(1, 11):
        accumulator.add(_sim(seed))
    block = accumulator.payload()
    assert block["distribution_version"] == 1
    assert block["segment_source"] == "quarter_log"
    assert block["sims"] == 10
    assert block["seed"] == {"first": 1, "last": 10, "count": 10, "sequential": True}


# --------------------------------------------------------------------------
# 3. Counts sum to the sim count.
# --------------------------------------------------------------------------

def test_every_histogram_sums_to_the_sim_count() -> None:
    accumulator = FootballSegmentAccumulator()
    sims = 40
    for seed in range(1, sims + 1):
        assert accumulator.add(_sim(seed)) is True
    block = accumulator.payload()
    assert block["sims"] == sims
    assert block["skipped_sims"] == 0
    for segment in SEGMENT_KEYS:
        entry = block["segments"][segment]
        assert sum(entry["total_points_dist"].values()) == sims, segment
        assert sum(entry["margin_dist"].values()) == sims, segment


def test_the_histograms_agree_with_the_scalars_the_artifact_already_carried() -> None:
    """`full` must reproduce the numbers the CSV already reports, or the two
    halves of the same artifact disagree about the same run."""
    import statistics

    accumulator = FootballSegmentAccumulator()
    home_scores, away_scores = [], []
    for seed in range(1, 31):
        output = _sim(seed)
        accumulator.add(output)
        home_scores.append(output.final_score["home"])
        away_scores.append(output.final_score["away"])
    block = accumulator.payload()

    full = block["segments"]["full"]
    assert full["home_points_mean"] == pytest.approx(statistics.fmean(home_scores), abs=1e-4)
    assert full["away_points_mean"] == pytest.approx(statistics.fmean(away_scores), abs=1e-4)
    totals = [h + a for h, a in zip(home_scores, away_scores)]
    weighted = sum(int(value) * count for value, count in full["total_points_dist"].items())
    assert weighted == sum(totals)
    # HOME-POSITIVE margin, matching `run_margin_dist` / `margin_dist`.
    weighted_margin = sum(int(value) * count for value, count in full["margin_dist"].items())
    assert weighted_margin == sum(h - a for h, a in zip(home_scores, away_scores))


def test_the_packing_is_walkable_by_the_existing_mlb_pricer(tmp_path) -> None:
    """SHAPE PARITY WITH MLB, asserted against the real consumer rather than
    described in a comment. `prop_projections`' helpers are what will price
    these; if they cannot read the packing, the mirror failed."""
    from syndicate.features.shared.prop_projections import _dist_mean, _dist_prob_over

    accumulator = FootballSegmentAccumulator()
    for seed in range(1, 21):
        accumulator.add(_sim(seed))
    block = accumulator.payload()
    # Round-trip through JSON first: on disk the integer keys become strings,
    # and the pricer has to cope with what is actually persisted.
    block = json.loads(json.dumps(block))

    for segment in ("full", "h1", "h2", "q1"):
        dist = block["segments"][segment]["total_points_dist"]
        mean = _dist_mean(dist)
        assert mean is not None and mean >= 0.0
        # Price at the segment's OWN mean, so the line sits inside the support
        # and the walk returns a real number. `_dist_prob_over` deliberately
        # REFUSES a certainty (returns None when every draw falls one side of
        # the line), so a line outside the support proves nothing about the
        # packing -- it only re-tests that refusal.
        probability = _dist_prob_over(dist, mean)
        assert probability is not None, segment
        assert 0.0 < probability < 1.0, segment

    # The refusal itself, on this packing, for the same reason: a future pricer
    # inherits it and must not read None as "no distribution".
    full_dist = block["segments"]["full"]["total_points_dist"]
    assert _dist_prob_over(full_dist, -0.5) is None


# --------------------------------------------------------------------------
# 4. A scoreless quarter is a populated 0 bucket, not an absent key.
# --------------------------------------------------------------------------

def test_a_scoreless_quarter_is_a_populated_zero_bucket() -> None:
    """ABSENT AND ZERO MEAN DIFFERENT THINGS. A missing `q2` key reads as "not
    measured"; a `{0: n}` bucket reads as "measured, nobody scored". Only the
    second is true, and a pricer that saw the first would refuse the market."""
    accumulator = FootballSegmentAccumulator()
    # Two games, neither of which scores in q2, one of which is 0-0 all game.
    accumulator.add(_FakeOutput([(7, 0), (0, 0), (0, 3), (7, 7)]))
    accumulator.add(_FakeOutput([(0, 0), (0, 0), (0, 0), (0, 0)], overtime=(0, 0)))
    block = accumulator.payload()

    q2 = block["segments"]["q2"]
    assert "q2" in block["segments"]
    assert q2["total_points_dist"] == {0: 2}
    assert q2["margin_dist"] == {0: 2}
    assert q2["home_points_mean"] == 0.0
    assert q2["away_points_mean"] == 0.0
    # Every segment key is present for every game, including the 0-0 one.
    for segment in SEGMENT_KEYS:
        assert sum(block["segments"][segment]["total_points_dist"].values()) == 2


def test_a_zero_zero_game_still_populates_every_segment() -> None:
    accumulator = FootballSegmentAccumulator()
    accumulator.add(_FakeOutput([(0, 0), (0, 0), (0, 0), (0, 0)]))
    block = accumulator.payload()
    for segment in SEGMENT_KEYS:
        entry = block["segments"][segment]
        assert entry["total_points_dist"] == {0: 1}, segment
        assert entry["margin_dist"] == {0: 1}, segment


def test_the_sidecar_round_trips_and_is_absent_safe(tmp_path) -> None:
    assert read_segment_distributions_artifact(season=2026, week=9, data_root=tmp_path) == {}
    accumulator = FootballSegmentAccumulator()
    accumulator.add(_FakeOutput([(7, 0), (0, 0), (0, 3), (7, 7)], seed=FIXED_SEED))
    path = write_segment_distributions_artifact(
        {"g1": accumulator.payload()}, season=2026, week=9, data_root=tmp_path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["season"] == 2026 and payload["week"] == 9
    assert set(payload["games"]) == {"g1"}
    # Unreadable file -> {} rather than an exception: the artifact is optional
    # by construction and must not be able to break a caller that merely asked.
    path.write_text("{ not json", encoding="utf-8")
    assert read_segment_distributions_artifact(season=2026, week=9, data_root=tmp_path) == {}


def test_the_real_engine_produces_overtime_and_it_is_captured() -> None:
    """Guards against the OT residual quietly becoming unreachable. If the
    engine stops producing overtime, this fails loudly instead of the OT limb
    of `h2` going untested forever."""
    accumulator = FootballSegmentAccumulator()
    for seed in range(1, 61):
        assert accumulator.add(_sim(seed)) is True
    block = accumulator.payload()
    assert block["overtime_sims"] > 0, "engine produced no OT in 60 seeds -- the h2 OT limb is untested"
    # `full` and regulation must differ by exactly the OT points on those sims.
    regulation = sum(
        int(value) * count
        for segment in ("q1", "q2", "q3", "q4")
        for value, count in block["segments"][segment]["total_points_dist"].items()
    )
    full = sum(int(v) * c for v, c in block["segments"]["full"]["total_points_dist"].items())
    assert full > regulation
    h1 = sum(int(v) * c for v, c in block["segments"]["h1"]["total_points_dist"].items())
    h2 = sum(int(v) * c for v, c in block["segments"]["h2"]["total_points_dist"].items())
    assert h1 + h2 == full
