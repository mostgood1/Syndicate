"""The NCAAF live re-sim's CALL SITE, which is the half that was missing.

`syndicate/features/ncaaf/live_resim.py` shipped with 50 tests and nothing
called it, so the board kept publishing pregame win probabilities on live games.
`tests/test_ncaaf_live_resim.py` covers the producer; this file covers the wiring
that makes it run -- which is a different thing and is exactly the thing that was
absent.

REACHABILITY BEFORE CORRECTNESS. The first assertion in this file is that the
loop CALLS the tick at all, sourced from the loop's own text rather than from a
belief about it, because a correct producer nothing invokes is the defect being
fixed here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.run_refresh_worker as rw


# ---------------------------------------------------------------------------
# REACHABILITY
# ---------------------------------------------------------------------------

def test_refresh_worker_loop_calls_the_ncaaf_live_resim_tick():
    """The loop must CALL it. `#341`'s lesson, asserted rather than assumed.

    An autorun that is enabled, configured and never reached emits nothing and
    looks identical to one that is broken -- measured on `reconciliation`, which
    sat 6th in an exclusive `elif` chain and produced nothing for weeks. This
    reads the source of `main()` so the assertion is about the code that runs,
    not about a function that merely exists.
    """
    source = Path(rw.__file__).read_text(encoding="utf-8")
    body = source[source.index("def main() -> int:"):]
    assert "_run_ncaaf_live_resim_tick()" in body, "the loop never calls the producer"
    # UNCONDITIONAL, not a branch of the claimed_count/elif chain. The chain is
    # exclusive and a live MLB slate keeps winning it.
    call_at = body.index("_run_ncaaf_live_resim_tick()")
    chain_at = body.index("refresh_cycle = {\"claimed_count\": 0")
    assert call_at < chain_at, "the tick sits inside/behind the exclusive elif chain"


def test_the_tick_publishes_a_heartbeat_before_it_blocks():
    """A <=90 s synchronous block must not push the loop past the drain bound.

    `deploy_drain._HEARTBEAT_STALE_SECONDS` is 180 and the poll sleep is 30, so
    an iteration that gains 90 s can make the deployer read this worker as
    UNKNOWN and HOLD. The publish in front of the block is what buys that back,
    and it is load-bearing rather than decorative.
    """
    from syndicate.features.shared.deploy_drain import _HEARTBEAT_STALE_SECONDS

    source = Path(rw.__file__).read_text(encoding="utf-8")
    body = source[source.index("def main() -> int:"):]
    call_at = body.index("_run_ncaaf_live_resim_tick()")
    window = body[:call_at]
    assert "stage=pre_ncaaf_live_resim" in window, "no heartbeat publish in front of the block"
    # The bound this depends on. If someone lowers it, this test says so.
    assert _HEARTBEAT_STALE_SECONDS >= 120


# ---------------------------------------------------------------------------
# THE RATINGS INPUT -- the trap that made this lane more than a one-line call
# ---------------------------------------------------------------------------

def _write_mirror(path: Path, *, teams: dict[str, tuple[float, float]], fetched_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "season": 2026,
            "fetched_at": fetched_at,
            "source": "cfbd /ratings/sp",
            "teams": {k: [v[0], v[1]] for k, v in teams.items()},
        }),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _clear_ratings_memo():
    rw._NCAAF_SP_RATINGS_MEMO.clear()
    yield
    rw._NCAAF_SP_RATINGS_MEMO.clear()


def test_a_fresh_durable_mirror_is_used_and_the_loader_is_never_called(tmp_path, monkeypatch):
    """THE POST-DEPLOY CASE. A deploy erases the generator's ephemeral cache.

    `sp_ratings_cache_path` and `ncaaf_historical_loader.DEFAULT_CACHE_DIR` both
    resolve off `__file__`, so on Render they live in the ephemeral checkout --
    measured on refresh-worker 2026-09-04T01:03:29Z and 2026-09-05T01:15:49Z,
    both `source=api`, i.e. empty after the previous deploy. Without the mirror
    this producer's FIRST reading after its own deploy is `no_pregame_ratings`
    on every game, which is indistinguishable from an inert feature.

    The loader is replaced by a function that FAILS THE TEST if called, so this
    cannot pass for the wrong reason.
    """
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    mirror = tmp_path / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json"
    _write_mirror(
        mirror,
        teams={"texas": (35.0, 12.0), "texas st": (10.0, 30.0)},
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

    def _explode(_season):
        raise AssertionError("load_sp_ratings was called with a fresh mirror on disk")

    monkeypatch.setattr(
        "scripts.generate_smartsim2_ncaaf_projections.load_sp_ratings", _explode
    )

    index, source = rw._ncaaf_sp_ratings_index(2026)
    assert source == "durable_mirror"
    assert index == {"texas": (35.0, 12.0), "texas st": (10.0, 30.0)}


def test_the_mirror_age_comparison_does_not_raise_on_a_tz_aware_now(tmp_path, monkeypatch):
    """The bug this test exists for, pinned so it cannot come back.

    `_parse_utc_timestamp` ends with `.replace(tzinfo=None)`. The first cut of
    `_ncaaf_sp_ratings_index` subtracted it from an AWARE
    `datetime.now(timezone.utc)`, which raises TypeError -- swallowed by a bare
    `except`, so `durable_age` was always None and the mirror was NEVER trusted.
    It failed in the SAFE direction (the ratings were still fetched, just
    needlessly), which is why nothing looked wrong; only a run with no
    `CFBD_API_KEY` at all could tell the two apart.

    MUTATION CHECK, by construction: revert that line to the aware subtraction
    and this test goes red, because the loader below would be reached.
    """
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    _write_mirror(
        tmp_path / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json",
        teams={"iowa": (20.0, 15.0)},
        # Timezone-AWARE with an offset, which is exactly what `_write_sp_cache`
        # produces (`datetime.now(timezone.utc).isoformat()`).
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr(
        "scripts.generate_smartsim2_ncaaf_projections.load_sp_ratings",
        lambda _season: (_ for _ in ()).throw(AssertionError("fell through to the loader")),
    )
    index, source = rw._ncaaf_sp_ratings_index(2026)
    assert source == "durable_mirror" and index == {"iowa": (20.0, 15.0)}


def test_a_stale_mirror_falls_through_to_the_loader_and_is_rewritten(tmp_path, monkeypatch):
    """IN-SEASON SP+ MOVES WEEK TO WEEK, so a frozen mirror is its own defect.

    The quieter of the two failures: a mirror that is never refreshed keeps
    pricing live games off week-1 ratings all season, and nothing reports it.
    """
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    mirror = tmp_path / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json"
    _write_mirror(
        mirror,
        teams={"iowa": (1.0, 1.0)},
        fetched_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    )
    monkeypatch.setattr(
        "scripts.generate_smartsim2_ncaaf_projections.load_sp_ratings",
        lambda _season: {"iowa": (9.0, 9.0), "ohio st": (30.0, 10.0)},
    )

    index, source = rw._ncaaf_sp_ratings_index(2026)
    assert source == "loader"
    assert index == {"iowa": (9.0, 9.0), "ohio st": (30.0, 10.0)}
    # REWRITTEN, or the next boot reads the stale copy again.
    rewritten = json.loads(mirror.read_text(encoding="utf-8"))
    assert rewritten["teams"] == {"iowa": [9.0, 9.0], "ohio st": [30.0, 10.0]}


def test_an_empty_loader_falls_back_to_the_stale_mirror_and_says_so(tmp_path, monkeypatch):
    """CFBD rate-limited is the expected failure here, not a hypothetical.

    `[cfbd-monthly-quota-exhausted]` in `state_football.md` is the incident. A
    stale rating is a far better answer than none -- but it must be REPORTED as
    stale, and the mirror must not be overwritten with the empty result.
    """
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    mirror = tmp_path / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json"
    _write_mirror(
        mirror,
        teams={"iowa": (1.0, 1.0)},
        fetched_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    )
    monkeypatch.setattr(
        "scripts.generate_smartsim2_ncaaf_projections.load_sp_ratings", lambda _season: {}
    )

    index, source = rw._ncaaf_sp_ratings_index(2026)
    assert source == "durable_mirror_stale"
    assert index == {"iowa": (1.0, 1.0)}
    assert json.loads(mirror.read_text(encoding="utf-8"))["teams"] == {"iowa": [1.0, 1.0]}


def test_the_durable_mirror_is_on_the_mounted_disk_and_is_allowlisted(tmp_path, monkeypatch):
    """WRITE PATH -> READ PATH -> ALLOWLIST, in one assertion chain.

    An allowlist entry that names a path nothing writes is inert and looks
    exactly like the bug it was added to fix (the `smartsim2_projections` entry
    was that, for 13 days). This pins the mirror under `data_root()` AND pins
    that `HOT_ARTIFACT_PATTERNS` admits the relative path that produces.
    """
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    path = rw._ncaaf_sp_ratings_durable_path(2026)
    relative = path.relative_to(tmp_path).as_posix()
    assert relative == "ncaaf_source/historical_truth/sp_ratings_2026.json"
    assert is_hot_artifact_relative_path(relative) is True
    # NARROW. The gzip caches beside it are NOT admitted -- a `.gz` fails the
    # publisher's UTF-8 read anyway (`SKIP_READ_FAILED`), so admitting it would
    # be a promise the transport cannot keep.
    assert is_hot_artifact_relative_path("ncaaf_source/historical_truth/games_2026.json.gz") is False


# ---------------------------------------------------------------------------
# THE ESPN INDEX -- the join key, and the parser it must NOT become
# ---------------------------------------------------------------------------

def _espn_event(*, away_loc, home_loc, away_id="1", home_id="2", state="in", period=2,
                clock="12:34", away_score="7", home_score="10", situation=None):
    event = {
        "id": "401",
        "status": {"period": period, "displayClock": clock,
                   "type": {"state": state, "completed": state == "post",
                            "shortDetail": "2nd Quarter"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "score": home_score,
                 "team": {"id": home_id, "location": home_loc,
                          "displayName": f"{home_loc} Mascots", "abbreviation": "HOM"}},
                {"homeAway": "away", "score": away_score,
                 "team": {"id": away_id, "location": away_loc,
                          "displayName": f"{away_loc} Mascots", "abbreviation": "AWY"}},
            ],
        }],
    }
    if situation is not None:
        event["competitions"][0]["situation"] = situation
    return event


def test_the_live_index_is_keyed_on_location_not_display_name(monkeypatch):
    """MEASURED 2026-09-05 on the live slate: `location` 35/51, `displayName` 0/51.

    The projections artifact carries only `home_team`/`away_team`, so the key has
    to be a name -- and ESPN has two name fields that differ on every row.
    Keying on the wrong one matches NOTHING and reads exactly like ESPN not
    covering the slate.
    """
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard",
        lambda _date: {"events": [_espn_event(away_loc="Boise State", home_loc="Oregon")]},
    )
    index, stats = rw._ncaaf_live_resim_live_index(["2026-09-05"])
    assert list(index) == ["boise state@oregon"]
    assert "boise state mascots@oregon mascots" not in index
    assert stats["events"] == 1 and stats["keyed"] == 1 and stats["in_progress"] == 1


def test_the_live_index_carries_period_clock_and_the_possession_block(monkeypatch):
    """The four fields `live_state_from_espn_event` refuses without.

    `_game_from_event` carries none of them -- it is the SETTLEMENT parser and
    has no use for a clock -- so this is the seam where a third parser would be
    born. It is not one: the state semantics come from that function unmodified
    and the possession block from `live_resim.possession_side_from_espn`.
    """
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard",
        lambda _date: {"events": [_espn_event(
            away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2",
            situation={"possession": "2", "down": 3, "distance": 7, "yardLine": 41},
        )]},
    )
    index, _ = rw._ncaaf_live_resim_live_index(["2026-09-05"])
    row = index["baylor@auburn"]
    assert row["period"] == 2
    assert row["clock"] == "12:34"
    assert row["possession_owner"] == "home"
    assert row["situation"]["yardLine"] == 41
    assert row["as_of"]

    # AND IT RESUMES. The producer must accept what this index produces --
    # asserting the shape without asserting that is how a wiring ships inert.
    from syndicate.features.ncaaf.live_resim import NcaafLiveGameState, live_state_from_espn_event

    state = live_state_from_espn_event(row, away_team="Baylor", home_team="Auburn")
    assert isinstance(state, NcaafLiveGameState), getattr(state, "reason", state)
    assert (state.period, state.clock_seconds, state.home_score, state.away_score) == (2, 754, 10, 7)
    assert state.down == 3 and state.distance == 7
    # ESPN's `yardLine` is in the HOME frame; the home team possesses, so it is
    # already its own 41. An inversion here would place a team 18 yards from the
    # wrong goal line and the sim would treat it as authoritative.
    assert state.field_position == 41


def test_a_scoreboard_fetch_failure_is_counted_not_swallowed(monkeypatch):
    """An ESPN outage and a quiet slate both yield an empty index.

    They have opposite owners, so they must not read the same way.
    """
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard", lambda _date: None
    )
    index, stats = rw._ncaaf_live_resim_live_index(["2026-09-05", "2026-09-04"])
    assert index == {}
    assert stats["fetch_failures"] == 2
    assert stats["events"] == 0


def test_yesterday_utc_is_fetched_only_while_an_evening_kickoff_could_still_be_live():
    """One 1.4 MB scoreboard pull, not two, once yesterday's slate is final.

    Measured by lane `render-egress-transport` 2026-09-05: the CFB scoreboard is
    1,441,192 bytes uncompressed and `urllib` sends no `Accept-Encoding` at any
    of this repo's 122 call sites.
    """
    early = datetime(2026, 9, 6, 3, 0, tzinfo=timezone.utc)
    late = datetime(2026, 9, 5, 21, 30, tzinfo=timezone.utc)
    assert rw._ncaaf_live_resim_espn_dates(early) == ["2026-09-05", "2026-09-06"]
    assert rw._ncaaf_live_resim_espn_dates(late) == ["2026-09-05"]


# ---------------------------------------------------------------------------
# THE TICK, END TO END, AGAINST THE JOIN THE BOARD ACTUALLY CALLS
# ---------------------------------------------------------------------------

class _FakeProjection:
    def __init__(self, away_team, home_team):
        self.away_team = away_team
        self.home_team = home_team


def _wire_tick(monkeypatch, tmp_path, *, events, projections, ratings_teams):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("NCAAF_LIVE_RESIM_SIMS", "12")  # the wiring, not the estimator
    monkeypatch.setattr(rw, "_season_projection_target_week", lambda sport, season: 1)
    monkeypatch.setattr(
        "syndicate.features.ncaaf.smartsim2_projection.read_projection_artifact",
        lambda **_kwargs: tuple(projections),
    )
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard", lambda _date: {"events": events}
    )
    _write_mirror(
        tmp_path / "ncaaf_source" / "historical_truth" / f"sp_ratings_{datetime.now().year}.json",
        teams=ratings_teams,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def test_the_tick_publishes_a_snapshot_the_board_join_accepts(tmp_path, monkeypatch):
    """END TO END: tick -> published artifact -> `build_live_gameline_index`.

    Through the SAME functions `board_enrichment.attach_live_gamelines_for_sport`
    calls, and reading the SAME path it reads. A test that stopped at the
    snapshot would prove the producer and say nothing about the join, which is
    the hop this lane exists to close.
    """
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(
            away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2",
            period=4, clock="0:15", away_score="7", home_score="35",
            situation={"possession": "2", "down": 1, "distance": 10, "yardLine": 50},
        )],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )

    meta = rw._run_ncaaf_live_resim_tick()
    assert meta["written"] is True
    assert meta["sp_ratings_source"] == "durable_mirror"
    assert meta["coverage"]["live_resimmed"] == 1
    assert meta["coverage"]["refusals_by_reason"] == {}

    from syndicate.features.ncaaf.live_resim import live_lens_snapshot_path
    from syndicate.features.shared.live_gameline_join import (
        build_live_gameline_index, lens_sources_for_sport,
    )
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(live_lens_snapshot_path(data_root()))
    assert isinstance(snapshot, dict)

    diagnostics: dict = {}
    index = build_live_gameline_index(
        snapshot, sources=lens_sources_for_sport("ncaaf"),
        diagnostics=diagnostics, sport="ncaaf",
    )
    # THE CLOSING READING'S SHAPE, asserted here so a production zero can be
    # compared against something.
    assert diagnostics["sources_seen"] == {"live_resim": 1}
    assert diagnostics["accepted_sources"] == ["live_resim"]
    # THE GRID'S SPELLING, not the artifact's. This assertion originally read
    # `("baylor", "auburn")` and PASSED, because this fixture builds both sides
    # from the same names -- so it could not express the disagreement that
    # production has between the odds source and CFBD. See
    # `test_the_snapshot_is_keyed_on_the_GRID_spelling_not_the_artifacts`.
    key = ("baylor mascots", "auburn mascots")
    assert list(index) == [key]
    # Auburn up 28 with 15 seconds left in the 4th. If this is not ~1.0 the
    # resumed state never reached the engine.
    assert index[key]["home_win_prob"] == pytest.approx(1.0)


def test_a_game_with_no_rating_refuses_by_name_and_the_join_withholds(tmp_path, monkeypatch):
    """`no_pregame_ratings`, NOT a neutral 0.0 that rates an unknown as average.

    And the refusal must reach the JOIN as a withheld row, not as a live-looking
    lane -- `LIVE_LENS_SOURCES_BY_SPORT["ncaaf"]` accepts only `live_resim`, so
    the `pregame` stamp is the interlock. This asserts the OPPOSITE outcome for
    the same machinery as the test above, which is what makes either one mean
    anything.
    """
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Furman", home_loc="Tennessee", period=3, clock="11:38")],
        projections=[_FakeProjection("Furman", "Tennessee")],
        ratings_teams={"tennessee": (28.0, 18.0)},  # Furman (FCS) has no SP+ row
    )

    meta = rw._run_ncaaf_live_resim_tick()
    assert meta["coverage"]["live_resimmed"] == 0
    assert meta["coverage"]["refusals_by_reason"] == {"no_pregame_ratings": 1}

    from syndicate.features.ncaaf.live_resim import live_lens_snapshot_path
    from syndicate.features.shared.live_gameline_join import (
        build_live_gameline_index, lens_sources_for_sport,
    )
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(live_lens_snapshot_path(data_root()))
    lane = snapshot["games"][0]["gameLens"][0]
    assert lane["source"] == "pregame"
    assert lane["liveResimRefusal"] == "no_pregame_ratings"
    # NOT the pregame value, not zero, not a null an `or` could rescue (`#414`).
    assert "modelHomeWinProb" not in lane

    diagnostics: dict = {}
    index = build_live_gameline_index(
        snapshot, sources=lens_sources_for_sport("ncaaf"),
        diagnostics=diagnostics, sport="ncaaf",
    )
    assert index == {}
    assert diagnostics["sources_seen"] == {"pregame": 1}
    assert diagnostics["skipped_no_accepted_lane"] == 1


def test_no_projection_artifact_means_no_espn_fetch(tmp_path, monkeypatch):
    """Out of season this branch runs forever; it must cost one stat, not 1.4 MB."""
    calls: list[str] = []
    _wire_tick(
        monkeypatch, tmp_path, events=[], projections=[],
        ratings_teams={"iowa": (1.0, 1.0)},
    )
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard",
        lambda date: calls.append(date) or {"events": []},
    )
    meta = rw._run_ncaaf_live_resim_tick()
    assert meta["skipped"] == "no_projection_artifact"
    assert calls == []


def test_the_interval_gate_holds_the_second_call_in_the_same_window(tmp_path, monkeypatch):
    """One re-sim per interval. A 90 s budget on a 30 s poll would otherwise run
    this worker's CPU flat for the whole slate."""
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", period=4, clock="0:05")],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    assert rw._run_ncaaf_live_resim_tick() is not None
    assert rw._run_ncaaf_live_resim_tick() is None


def test_the_tick_is_on_by_default_and_off_only_when_told(tmp_path, monkeypatch):
    """ABSENT != OFF. CLAUDE.md's standing rule, and the code's default decides."""
    monkeypatch.delenv("SYNDICATE_NCAAF_LIVE_RESIM", raising=False)
    assert rw._ncaaf_live_resim_enabled() is True
    for value in ("off", "0", "false", "no", "OFF"):
        monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_RESIM", value)
        assert rw._ncaaf_live_resim_enabled() is False
    monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_RESIM", "on")
    assert rw._ncaaf_live_resim_enabled() is True


def test_the_interval_floor_cannot_be_configured_below_one_minute(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_RESIM_INTERVAL_SECONDS", "1")
    assert rw._ncaaf_live_resim_interval_seconds() == 60.0
    monkeypatch.setenv("SYNDICATE_NCAAF_LIVE_RESIM_INTERVAL_SECONDS", "nonsense")
    assert rw._ncaaf_live_resim_interval_seconds() == rw._NCAAF_LIVE_RESIM_INTERVAL_DEFAULT_SECONDS
    monkeypatch.delenv("SYNDICATE_NCAAF_LIVE_RESIM_INTERVAL_SECONDS")
    assert rw._ncaaf_live_resim_interval_seconds() == 180.0


def test_the_snapshot_carries_its_own_ratings_provenance(tmp_path, monkeypatch):
    """"Which ratings produced this probability" must be answerable FROM THE
    ARTIFACT. `smartsim2_projection.profile_source` is the precedent: a
    boot-time print is weakly reachable and a log line is not evidence a reader
    holding the payload can use."""
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", period=4, clock="0:05")],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    rw._run_ncaaf_live_resim_tick()

    from syndicate.features.ncaaf.live_resim import live_lens_snapshot_path
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(live_lens_snapshot_path(data_root()))
    assert snapshot["spRatingsSource"] == "durable_mirror"
    assert snapshot["spRatingsTeams"] == 2
    assert snapshot["week"] == 1
    assert snapshot["espnFetch"]["fetch_failures"] == 0


def test_the_snapshot_is_keyed_on_the_GRID_spelling_not_the_artifacts(tmp_path, monkeypatch):
    """THE DEFECT PRODUCTION FOUND, pinned. 0 of 8 became 7 of 8.

    Measured 2026-09-05T23:17:39Z on the first board rebuild after the first
    snapshot: the index built perfectly -- `index_size 8`, `sources_seen
    {live_resim: 8, pregame: 43}` -- and every one of 257 considered rows was
    withheld as `no_live_gameline_projection`. The two key sets did not
    intersect at all:

        lens, from the projections artifact   grid, from the odds source
        ('baylor', 'auburn')                  ('baylor bears', 'auburn tigers')
        ('tulane', 'duke')                    ('tulane green wave', 'duke blue devils')

    `_norm_team` has no alias table on purpose, so the producer has to publish
    the spelling the grid uses. ESPN's `displayName` matched 7 of 8 live grid
    keys; `location`, `shortDisplayName` and `name` each matched 0.

    THIS TEST WOULD HAVE CAUGHT IT AND THE ORIGINAL SUITE COULD NOT, which is
    the part worth keeping: every earlier test built the grid row from the same
    names as the projection, so the two sides agreed by construction. A fixture
    that cannot express the disagreement cannot test the join.
    """
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(
            away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2",
            period=4, clock="0:15", away_score="7", home_score="35",
        )],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    rw._run_ncaaf_live_resim_tick()

    from syndicate.features.ncaaf.live_resim import live_lens_snapshot_path
    from syndicate.features.shared.live_gameline_join import (
        build_live_gameline_index, lens_sources_for_sport,
    )
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(live_lens_snapshot_path(data_root()))
    game = snapshot["games"][0]
    # The artifact's own spelling is PRESERVED for a human reading the payload.
    assert (game["away_name"], game["home_name"]) == ("Baylor", "Auburn")
    # The GRID's spelling is what the join keys on. `_espn_event` builds
    # `displayName` as "<location> Mascots", standing in for "Baylor Bears".
    assert game["matchup"] == {"away": {"name": "Baylor Mascots"},
                               "home": {"name": "Auburn Mascots"}}

    index = build_live_gameline_index(snapshot, sources=lens_sources_for_sport("ncaaf"))
    assert list(index) == [("baylor mascots", "auburn mascots")]
    # And NOT the artifact spelling -- asserting the negative too, because a key
    # that happened to carry both would pass the positive and still be ambiguous.
    assert ("baylor", "auburn") not in index


def test_a_game_with_no_espn_row_gets_no_matchup_key(tmp_path, monkeypatch):
    """Absence stays absent. Inventing a key for an unmatched game would turn a
    named `no_live_state` refusal into an unattributable join miss."""
    _wire_tick(
        monkeypatch, tmp_path,
        events=[],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    rw._run_ncaaf_live_resim_tick()

    from syndicate.features.ncaaf.live_resim import live_lens_snapshot_path
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(live_lens_snapshot_path(data_root()))
    game = snapshot["games"][0]
    assert "matchup" not in game
    assert game["gameLens"][0]["liveResimRefusal"] == "no_live_state"
