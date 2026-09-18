"""NCAAF player-prop projections: the producer, its chain, and the board join.

Lane `ncaaf-player-data` (2026-09-18). The lane's registered falsification
tests are the first three: a player with no season game gets NO projection
(never a league default); week N's own game never feeds week N's projection;
and the board reads the artifact rather than computing it.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from syndicate.features.ncaaf import prop_projections as pp

COLUMNS = (
    "season", "week", "game_id", "player_id", "player_name", "team", "passing_completions", "passing_attempts",
    "passing_yards", "passing_tds", "interceptions", "rushing_attempts", "rushing_yards", "rushing_tds", "receptions",
    "receiving_yards", "receiving_tds", "anytime_td", "source_system", "source_snapshot_date",
)


def _row(**kw) -> dict:
    row = {c: "0" for c in COLUMNS}
    row.update({"source_system": "cfbd", "source_snapshot_date": "2026-09-14", "season": "2026"})
    row.update({k: str(v) for k, v in kw.items()})
    return row


def _receiver(pid, name, team, season, week, rec, yds, game=None):
    return _row(season=season, week=week, game_id=game or f"G{season}{week}{team}", player_id=pid, player_name=name,
                team=team, receptions=rec, receiving_yards=yds)


def _qb(pid, name, team, season, week, att, yds, tds, rush_att=3, rush_yds=10):
    return _row(season=season, week=week, game_id=f"G{season}{week}{team}", player_id=pid, player_name=name, team=team,
                passing_attempts=att, passing_yards=yds, passing_tds=tds, rushing_attempts=rush_att,
                rushing_yards=rush_yds)


def _reference_rows(season: str, weeks=range(1, 6)) -> list[dict]:
    """A reference population large enough for every role bucket to fit."""
    rows = []
    for i in range(12):
        for w in weeks:
            rows.append(_receiver(f"RL{i}", f"Lead Receiver{i}", f"Team{i}", season, w, 5 + (i + w) % 3, 60 + 5 * ((i + w) % 5)))
            rows.append(_receiver(f"RR{i}", f"Rot Receiver{i}", f"Team{i}", season, w, 2 + (i + w) % 2, 25 + 3 * ((i * w) % 4)))
            rows.append(_receiver(f"RS{i}", f"Spot Receiver{i}", f"Team{i}", season, w, 1, 8 + (i % 3)))
            rows.append(_qb(f"QB{i}", f"Lead Passer{i}", f"Team{i}", season, w, 28 + (i % 4), 210 + 10 * ((i + w) % 5), 1 + (i + w) % 3))
    return rows


def _write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An isolated NCAAF source root: snapshot, week_state and artifacts all under tmp."""
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path))
    pp._index_cached.cache_clear()
    yield tmp_path
    pp._index_cached.cache_clear()


def _snapshot(root: Path) -> Path:
    return root / "source_artifacts" / "data" / "processed" / "player_game_stats" / "ncaaf_player_game_stats_snapshot.csv"


def _player(payload: dict, name: str) -> dict | None:
    return next((p for p in payload["players"] if p["name"] == name), None)


# ---------------------------------------------------------------------------
# The registered falsification tests
# ---------------------------------------------------------------------------


def test_a_player_with_no_season_game_gets_no_projection_not_a_league_default(root):
    rows = _reference_rows("2025") + _reference_rows("2026", weeks=(1, 2))
    # A 2025 star with no 2026 line yet: prior-season data exists, current does not.
    rows += [_receiver("STAR", "Last Year Star", "Texas", "2025", w, 8, 110) for w in range(1, 10)]
    # ...and one whose ONLY 2026 game is week 3 itself (a Thursday game already
    # in the snapshot when the week-3 build runs).
    rows += [_receiver("THU", "Thursday Debut", "Texas", "2026", 3, 9, 150)]
    payload = pp.build_payload(season=2026, week=3, snapshot_path=_write(_snapshot(root), rows))
    assert _player(payload, "Last Year Star") is None
    assert _player(payload, "Thursday Debut") is None
    assert payload["refusals"]["no_game_before_week"] == 1


def test_week_n_own_game_never_feeds_week_n(root):
    base = _reference_rows("2026", weeks=(1, 2))
    target = [_receiver("W1", "Target Guy", "Colorado", "2026", 1, 5, 50), _receiver("W1", "Target Guy", "Colorado", "2026", 2, 5, 70)]
    week3_blowup = [_receiver("W1", "Target Guy", "Colorado", "2026", 3, 15, 400)]
    path = _snapshot(root)
    without = pp.build_payload(season=2026, week=3, snapshot_path=_write(path, base + target), generated_at="x")
    with_game = pp.build_payload(season=2026, week=3, snapshot_path=_write(path, base + target + week3_blowup), generated_at="x")
    assert _player(without, "Target Guy") == _player(with_game, "Target Guy")
    # ...and the NEXT week's build does use it (the filter is < N, not a stale file).
    week4 = pp.build_payload(season=2026, week=4, snapshot_path=path, generated_at="x")
    assert _player(week4, "Target Guy")["markets"]["receiving_yards"]["season_mean"] == pytest.approx((50 + 70 + 400) / 3, abs=1e-3)


def test_the_board_reads_the_artifact_and_never_builds_it(root, monkeypatch):
    """Reachability: off != on, and the join path never calls the builder."""
    _setup_board_week(root, monkeypatch)
    grid = [_prop_row()]

    def forbidden(*args, **kwargs):
        raise AssertionError("the board must not build projections")

    before = pp.attach_ncaaf_prop_projections([dict(r) for r in grid], selected_date="2026-09-19")
    assert before["rows_with_projection"] == 0 and before["no_artifact_rows"] == 1

    _write_artifact(root, week=3)  # the WORKER's step
    monkeypatch.setattr(pp, "build_payload", forbidden)
    monkeypatch.setattr(pp, "payload_from_players", forbidden)
    monkeypatch.setattr(pp, "build_prop_projections", forbidden)
    attached_grid = [dict(r) for r in grid]
    after = pp.attach_ncaaf_prop_projections(attached_grid, selected_date="2026-09-19")
    assert after["rows_with_projection"] == 1
    assert attached_grid[0]["projection"]["source"] == "ncaaf_prop_model"


# ---------------------------------------------------------------------------
# The method
# ---------------------------------------------------------------------------


def test_one_game_with_no_prior_season_is_shrunk_toward_the_role_prior(root):
    rows = _reference_rows("2025") + [_receiver("NEW", "True Freshman", "Colorado", "2026", 1, 6, 120)]
    payload = pp.build_payload(season=2026, week=2, snapshot_path=_write(_snapshot(root), rows))
    entry = _player(payload, "True Freshman")["markets"]["receiving_yards"]
    role = payload["reference"]["priors"]["receiving_yards"]["lead"]["mean"]
    assert entry["role"] == "lead" and entry["prior_source"] == "role:lead"
    assert entry["prior_weight_games"] == pp.K_ROLE
    assert entry["mean"] == pytest.approx((1 * 120 + pp.K_ROLE * role) / (1 + pp.K_ROLE), abs=1e-3)


def test_prior_season_is_the_prior_only_when_the_role_is_unchanged(root):
    rows = _reference_rows("2025")
    rows += [_receiver("VET", "Same Job", "Colorado", "2025", w, 6, 90) for w in range(1, 11)]
    rows += [_receiver("BUP", "Promoted Guy", "Colorado", "2025", w, 1, 9) for w in range(1, 11)]
    rows += [_receiver("VET", "Same Job", "Colorado", "2026", 1, 6, 60), _receiver("BUP", "Promoted Guy", "Colorado", "2026", 1, 7, 100)]
    payload = pp.build_payload(season=2026, week=2, snapshot_path=_write(_snapshot(root), rows))
    same = _player(payload, "Same Job")["markets"]["receiving_yards"]
    role = payload["reference"]["priors"]["receiving_yards"]["lead"]["mean"]
    mu0 = (10 * 90 + pp.K_PRIOR_ROLE * role) / (10 + pp.K_PRIOR_ROLE)
    assert same["prior_source"].startswith("prior_season") and same["prior_season_games"] == 10
    assert same["mean"] == pytest.approx((60 + pp.K_SEASON * mu0) / (1 + pp.K_SEASON), abs=1e-3)
    promoted = _player(payload, "Promoted Guy")["markets"]["receiving_yards"]
    # A 1-catch backup last year is not a prior for this year's 7-catch starter.
    assert promoted["prior_source"].startswith("role:lead") and promoted["prior_season_games"] == 0


def test_a_transfer_keeps_his_prior_season_through_the_player_id(root):
    rows = _reference_rows("2025")
    rows += [_receiver("XFER", "Portal Guy", "Old School", "2025", w, 6, 95) for w in range(1, 11)]
    rows += [_receiver("XFER", "Portal Guy", "New School", "2026", 1, 6, 70)]
    payload = pp.build_payload(season=2026, week=2, snapshot_path=_write(_snapshot(root), rows))
    player = _player(payload, "Portal Guy")
    assert player["team"] == "New School"
    assert player["markets"]["receiving_yards"]["prior_season_games"] == 10


def test_spot_role_only_players_and_zero_opportunity_markets_are_refused(root):
    rows = _reference_rows("2025")
    rows += [_row(season="2026", week=1, game_id="Gx", player_id="KR", player_name="Two Carries", team="Colorado",
                  rushing_attempts=2, rushing_yards=9)]
    rows += [_receiver("WR", "Pure Wideout", "Colorado", "2026", 1, 6, 80)]
    payload = pp.build_payload(season=2026, week=2, snapshot_path=_write(_snapshot(root), rows))
    assert _player(payload, "Two Carries") is None
    assert payload["refusals"]["spot_role_only_player"] >= 1
    wideout = _player(payload, "Pure Wideout")
    assert "passing_yards" not in wideout["markets"] and "rushing_yards" not in wideout["markets"]
    assert payload["refusals"]["no_opportunity_market"] >= 2


def test_a_running_backs_catches_are_priced_off_running_backs(root):
    """Measured on the 2025 checkout: the receivers the plain bucket priced
    worst ran 3.5 yards a catch -- backs catching screens, priced off wideouts."""
    rows = _reference_rows("2025")
    rows += [_row(season="2025", week=w, game_id=f"B{i}{w}", player_id=f"RB{i}", player_name=f"Back{i}", team=f"Team{i}",
                  rushing_attempts=15, rushing_yards=70, receptions=2, receiving_yards=12)
             for i in range(10) for w in range(1, 6)]
    rows += [_row(season="2026", week=1, game_id="B", player_id="RBX", player_name="New Back", team="Colorado",
                  rushing_attempts=16, rushing_yards=80, receptions=2, receiving_yards=10)]
    payload = pp.build_payload(season=2026, week=2, snapshot_path=_write(_snapshot(root), rows))
    entry = _player(payload, "New Back")["markets"]["receiving_yards"]
    assert entry["role"] == "rotation+rusher"
    assert entry["prior_mean"] == pytest.approx(12.0, abs=1e-6)


def test_an_empty_build_is_never_written_or_published(root, monkeypatch):
    calls = []
    import syndicate.features.shared.artifact_publisher as publisher

    monkeypatch.setattr(publisher, "publish_hot_artifact", lambda *a, **k: calls.append(a) or True)
    _write(_snapshot(root), _reference_rows("2025"))  # no 2026 rows at all
    result = pp.build_prop_projections(season=2026, week=1)
    assert not result.written and result.reason == "no_player_has_a_game_before_week"
    assert not pp.artifact_path(2026, 1).exists()
    assert calls == []


def test_a_written_build_is_published_from_the_ncaaf_data_root(root, monkeypatch):
    calls = []
    import syndicate.features.shared.artifact_publisher as publisher

    monkeypatch.setattr(publisher, "publish_hot_artifact", lambda path, **k: calls.append(Path(path)) or True)
    _write(_snapshot(root), _reference_rows("2025") + _reference_rows("2026", weeks=(1, 2)))
    result = pp.build_prop_projections(season=2026, week=3)
    assert result.written and result.published is True
    assert calls == [root / "data" / "ncaaf_prop_projections_2026_wk3.json"]
    payload = json.loads(calls[0].read_text(encoding="utf-8"))
    assert payload["schema"] == pp.SCHEMA and payload["input"]["weeks_used"] == [1, 2]
    assert "bytes=" in result.summary_line() and "WRITTEN" in result.summary_line()


def test_the_allowlist_would_carry_the_artifact_path():
    """The ONE `HOT_ARTIFACT_PATTERNS` entry this artifact needs (applied by the
    publisher module's owner). Until it lands, publish_hot_artifact refuses."""
    import fnmatch

    pattern = "ncaaf_source/data/ncaaf_prop_projections_*_wk*.json"
    assert fnmatch.fnmatch("ncaaf_source/data/ncaaf_prop_projections_2026_wk4.json", pattern)
    assert not fnmatch.fnmatch("ncaaf_source/data/smartsim2_projections_2026_wk4.csv", pattern)


# ---------------------------------------------------------------------------
# Distribution arithmetic
# ---------------------------------------------------------------------------


def test_prob_over_matches_scipy_for_every_family():
    scipy_stats = pytest.importorskip("scipy.stats")
    gamma = {"mean": 64.0, "sd": 38.0, "dist": "gamma"}
    shape, scale = (64.0 / 38.0) ** 2, 38.0 ** 2 / 64.0
    for line in (0.5, 20.5, 64.5, 150.5):
        assert pp.prob_over(gamma, line) == pytest.approx(scipy_stats.gamma.sf(line, shape, scale=scale), abs=1e-9)
    small_shape = {"mean": 9.0, "sd": 14.0, "dist": "gamma"}
    s2, sc2 = (9.0 / 14.0) ** 2, 14.0 ** 2 / 9.0
    assert pp.prob_over(small_shape, 5.5) == pytest.approx(scipy_stats.gamma.sf(5.5, s2, scale=sc2), abs=1e-9)
    normal = {"mean": -2.0, "sd": 12.0, "dist": "normal"}
    assert pp.prob_over(normal, 0.5) == pytest.approx(scipy_stats.norm.sf(0.5, -2.0, 12.0), abs=1e-12)
    poisson = {"mean": 1.7, "dispersion": 1.0, "dist": "poisson"}
    assert pp.prob_over(poisson, 1.5) == pytest.approx(scipy_stats.poisson.sf(1, 1.7), abs=1e-12)
    negbin = {"mean": 4.2, "dispersion": 1.6, "dist": "negbin"}
    r = 4.2 / 0.6
    assert pp.prob_over(negbin, 4.5) == pytest.approx(scipy_stats.nbinom.sf(4, r, r / (r + 4.2)), abs=1e-12)
    assert pp.prob_over(gamma, None) is None
    assert pp.prob_over({"mean": 5.0, "dist": "gamma"}, 4.5) is None  # no spread, no price


# ---------------------------------------------------------------------------
# The chain at the end of the player-stats refresh
# ---------------------------------------------------------------------------


class _Client:
    def __init__(self, payload):
        self.payload = payload

    def fetch_player_game_stats(self, **kwargs):
        return self.payload


def test_refresh_chains_the_build_for_the_production_snapshot(root, monkeypatch):
    from syndicate.features.ncaaf import player_stats_refresh as refresh

    calls = []
    monkeypatch.setattr(pp, "build_prop_projections",
                        lambda **kw: calls.append(kw) or pp.BuildResult(season=kw["season"], week=kw["week"], path=None, written=True))
    report = refresh.refresh_player_game_stats(client=_Client([]), season=2026, weeks=(1,), projection_week=3)
    assert report.prop_projections["status"] == "written"
    assert calls and calls[0]["week"] == 3 and Path(calls[0]["snapshot_path"]) == _snapshot(root)
    assert report.as_dict()["prop_projections"]["week"] == 3


def test_a_scratch_refresh_never_writes_a_projection(root, tmp_path, monkeypatch):
    from syndicate.features.ncaaf import player_stats_refresh as refresh

    monkeypatch.setattr(pp, "build_prop_projections", lambda **kw: (_ for _ in ()).throw(AssertionError("built")))
    report = refresh.refresh_player_game_stats(client=_Client([]), season=2026, weeks=(1,),
                                               output_path=tmp_path / "scratch.csv")
    assert report.prop_projections is None


def test_a_failing_build_never_fails_the_refresh(root, monkeypatch, capsys):
    from syndicate.features.ncaaf import player_stats_refresh as refresh

    def boom(**kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pp, "build_prop_projections", boom)
    report = refresh.refresh_player_game_stats(client=_Client([]), season=2026, weeks=(1,), projection_week=3)
    assert report.ok
    assert report.prop_projections["status"] == "error" and "disk full" in report.prop_projections["error"]
    assert "[ncaaf_prop_projections] ERROR" in capsys.readouterr().out


def test_no_target_week_skips_the_build_by_name(root, monkeypatch):
    from syndicate.features.ncaaf import player_stats_refresh as refresh
    from syndicate.features.ncaaf import sources

    monkeypatch.setattr(pp, "current_week_from_state", lambda season, **kw: None)
    monkeypatch.setattr(sources, "ncaaf_target_week", lambda season: None)
    summary = refresh.build_prop_projections_after_refresh(season=2026, snapshot_path=_snapshot(root))
    assert summary["status"] == "skipped" and summary["reason"] == "no_target_week"


# ---------------------------------------------------------------------------
# The board join
# ---------------------------------------------------------------------------


_TEAMS = {"Colorado Buffaloes": "Colorado", "Northwestern Wildcats": "Northwestern", "Holy Cross Crusaders": "Holy Cross"}


def _setup_board_week(root: Path, monkeypatch) -> None:
    from syndicate.features.ncaaf import oddsapi_lines

    monkeypatch.setattr(oddsapi_lines, "resolve_team", lambda name: _TEAMS.get(str(name)))
    state = {"season": 2026, "weeks": {"3": {"games": 1, "completed": 0, "unplayed": 1}},
             "unplayed_kickoffs": {"3": {"undated": 0, "last": "2026-09-20T03:00:00+00:00"},
                                   "4": {"undated": 0, "last": "2026-09-27T03:00:00+00:00"}}}
    path = root / "data" / "week_state" / "ncaaf_week_state_2026.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _write_artifact(root: Path, *, week: int, rows: list[dict] | None = None) -> Path:
    base = rows if rows is not None else (
        _reference_rows("2025")
        + [_receiver("JW", "Joseph Williams", "Colorado", "2026", 1, 2, 23), _receiver("JW", "Joseph Williams", "Colorado", "2026", 2, 4, 123)]
        + [_receiver("HC", "Joseph Williams", "Holy Cross", "2026", 1, 7, 90), _receiver("HC", "Joseph Williams", "Holy Cross", "2026", 2, 6, 80)]
    )
    path = _write(_snapshot(root), base)
    result = pp.build_prop_projections(season=2026, week=week, snapshot_path=path, publish=False)
    assert result.written
    pp._index_cached.cache_clear()
    return result.path


def _prop_row(**overrides) -> dict:
    row = {
        "sport": "ncaaf", "kind": "prop", "event_id": "03297aa8", "market": "Receptions", "segment": "full",
        "player_name": "Joseph Williams", "line": 4.5, "home_team": "Northwestern Wildcats",
        "away_team": "Colorado Buffaloes", "commence_time": "2026-09-19T23:30:00Z", "sides": ["over", "under"],
        "best": {"over": {"price": 110}, "under": {"price": -140}},
        "consensus": {"over": 105, "under": -135},
    }
    row.update(overrides)
    return row


def test_board_row_gets_the_projection_contract(root, monkeypatch):
    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=3)
    grid = [_prop_row()]
    coverage = pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-19")
    projection = grid[0]["projection"]
    index = pp.load_index(2026, 3)
    colorado = next(p for p in index.by_id.values() if p["team"] == "Colorado")
    entry = colorado["markets"]["receptions"]
    assert projection["projected"] == pytest.approx(entry["mean"])
    assert projection["model_prob_over"] == pytest.approx(round(pp.prob_over(entry, 4.5), 4))
    assert projection["side"] == "over" and projection["player_team"] == "Colorado"
    assert projection["market_fair_prob_over"] is not None
    assert projection["edge_vs_market_pct"] == pytest.approx(
        round((projection["model_prob_over"] - projection["market_fair_prob_over"]) * 100.0, 2), abs=0.02)
    assert projection["artifact_week"] == 3 and projection["game_week"] == 3 and projection["stale_week"] is False
    assert coverage["rows_with_projection"] == 1 and coverage["pct_projected"] == 100.0


def test_a_namesake_at_another_school_is_never_joined(root, monkeypatch):
    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=3, rows=_reference_rows("2025") + [
        _receiver("HC", "Joseph Williams", "Holy Cross", "2026", 1, 7, 90)])
    grid = [_prop_row()]
    coverage = pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-19")
    assert "projection" not in grid[0]
    assert coverage["player_not_on_either_team_rows"] == 1


def test_a_live_row_carries_the_probability_but_no_edge(root, monkeypatch):
    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=3)
    grid = [_prop_row(game={"state": "live"})]
    pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-19")
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] is not None
    assert projection["edge_vs_market_pct"] is None and projection["edge_unavailable_reason"]


def test_rows_of_another_date_are_not_counted_on_this_pass(root, monkeypatch):
    """The layer2 window calls the join once per date over one grid and SUMS."""
    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=3)
    grid = [_prop_row(), _prop_row(commence_time="2026-09-21T00:00:00Z", event_id="other")]
    first = pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-19")
    second = pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-20")
    assert first["rows_considered"] == 1 and second["rows_considered"] == 1


def test_only_an_earlier_week_is_ever_used_and_it_is_labelled_stale(root, monkeypatch):
    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=2)
    later = pp.build_prop_projections(season=2026, week=4, snapshot_path=_snapshot(root), publish=False)
    assert later.written
    pp._index_cached.cache_clear()
    grid = [_prop_row()]
    coverage = pp.attach_ncaaf_prop_projections(grid, selected_date="2026-09-19")
    projection = grid[0]["projection"]
    assert projection["artifact_week"] == 2 and projection["stale_week"] is True  # never wk4
    assert coverage["stale_week_rows"] == 1


def test_the_board_join_never_falls_back_to_the_games_cache(root, monkeypatch):
    """`sources.ncaaf_target_week` falls back to the raw CFBD games cache when
    week_state is absent (17.9 s, 41 MB retained, measured). A row whose week
    cannot be placed from week_state is counted, never resolved that way."""
    from syndicate.features.ncaaf import oddsapi_lines, sources

    monkeypatch.setattr(oddsapi_lines, "resolve_team", lambda name: _TEAMS.get(str(name)))
    monkeypatch.setattr(sources, "ncaaf_target_week", lambda season: (_ for _ in ()).throw(AssertionError("games cache")))
    _write_artifact(root, week=3)  # artifact present, week_state absent
    coverage = pp.attach_ncaaf_prop_projections([_prop_row()], selected_date="2026-09-19")
    assert coverage["no_week_rows"] == 1 and coverage["rows_with_projection"] == 0


def test_the_board_wrapper_attaches_props_with_no_game_projections_and_declares_skill(root, monkeypatch):
    """The old NCAAF branch returned early when `not index.games`, which would
    have blanked every prop row on a date with no game projection."""
    from syndicate.features.ncaaf import game_projections
    from syndicate.features.shared import board_enrichment

    _setup_board_week(root, monkeypatch)
    _write_artifact(root, week=3)
    monkeypatch.setattr(game_projections, "load_ncaaf_game_projections", lambda date: game_projections.NcaafGameProjectionIndex())
    grid = [_prop_row()]
    coverage = board_enrichment.attach_projections(grid, sport="ncaaf", selected_date="2026-09-19")
    assert coverage["prop_rows_with_projection"] == 1 and coverage["game_rows_with_projection"] == 0
    assert coverage["game_coverage"]["reason"] == "no NCAAF SmartSim2 projections for this date"
    skill = grid[0]["projection"]["model_skill"]
    assert skill["status"] == "unmeasured"
    assert coverage.get("rows_with_unmeasured_skill") == 1
