"""The soccer pre-kickoff freeze: the model's last output before a match starts.

WHY. `recommendations_{date}.json` is rewritten on every build as a match goes
pre -> in -> post. Read 2026-09-17 01:21:48Z over 09-13..09-16: 43 of 43
matches sat in an artifact generated AFTER their kickoff, so production held no
pre-kickoff model values and the forward grades that need them (H24, todo
#665; the #664 watch-list) had a qualifying population of zero.

Three groups:

  1. the rule -- last pre-kickoff build wins; nothing at or after kickoff
     touches an entry; no kickoff, no freeze
  2. it can never cost the board -- corrupt file, atomic write, failure isolated
  3. REACHABILITY -- `build_artifacts` writes it, under a name the publisher
     already ships, one file per service
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def artifacts():
    name = "build_soccer_artifacts_prekickoff_freeze_under_test"
    spec = importlib.util.spec_from_file_location(name, _REPO / "scripts" / "build_soccer_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


KICKOFF = "2026-09-19T14:00Z"


def _payload(generated_at, *, matches=None, props=None):
    return {
        "league": "epl",
        "date": "2026-09-19",
        "generated_at": generated_at,
        "matches": matches if matches is not None else [
            {"match_id": "e1", "kickoff": KICKOFF, "status_state": "pre", "team_projection": {"home_mean": 1.4}},
            {"match_id": "e2", "kickoff": "2026-09-19T16:30Z", "status_state": "pre", "team_projection": {"home_mean": 1.1}},
        ],
        "player_props": props if props is not None else [
            {"match_id": "e1", "player_name": "A", "anytime_scorer_probability_if_playing": 0.31},
            {"match_id": "e2", "player_name": "B", "anytime_scorer_probability_if_playing": 0.12},
        ],
    }


def _read(artifacts, tmp_path, service="svc"):
    return json.loads(artifacts.prekickoff_freeze_path(tmp_path, "2026-09-19", service).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. THE RULE
# ---------------------------------------------------------------------------


def test_a_pre_kickoff_build_freezes_each_match_with_only_its_own_props(artifacts, tmp_path):
    counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"), service="svc")
    body = _read(artifacts, tmp_path)
    assert counts["frozen_this_build"] == 2
    assert body["schema"] == artifacts.PREKICKOFF_FREEZE_SCHEMA
    entry = body["matches"]["e1"]
    assert entry["frozen_at"] < entry["kickoff"]
    assert entry["match"]["team_projection"] == {"home_mean": 1.4}
    assert [p["player_name"] for p in entry["player_props"]] == ["A"]


def test_the_LAST_pre_kickoff_build_wins(artifacts, tmp_path):
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"), service="svc")
    later = _payload("2026-09-19T13:30:00+00:00")
    later["matches"][0]["team_projection"] = {"home_mean": 1.9}
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", later, service="svc")
    entry = _read(artifacts, tmp_path)["matches"]["e1"]
    assert entry["frozen_at"].startswith("2026-09-19T13:30")
    assert entry["match"]["team_projection"] == {"home_mean": 1.9}


def test_a_build_at_or_after_kickoff_never_touches_the_entry(artifacts, tmp_path):
    """The post-match rebuild is exactly what overwrote every pre-kickoff value."""
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T13:30:00+00:00"), service="svc")
    # At 14:00 only e1 has started (e2 is re-frozen); by 20:00 both have.
    for generated_at, state, kept in (("2026-09-19T14:00:00+00:00", "in", 1), ("2026-09-19T20:00:00+00:00", "post", 2)):
        post = _payload(generated_at)
        post["matches"][0].update({"status_state": state, "team_projection": {"home_mean": 9.9}})
        post["player_props"][0]["anytime_scorer_probability_if_playing"] = 1.0
        counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", post, service="svc")
        assert counts["kept_after_kickoff"] == kept
    entry = _read(artifacts, tmp_path)["matches"]["e1"]
    assert entry["match"]["team_projection"] == {"home_mean": 1.4}
    assert entry["player_props"][0]["anytime_scorer_probability_if_playing"] == 0.31


def test_a_match_first_simulated_after_kickoff_is_never_frozen(artifacts, tmp_path):
    counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T15:00:00+00:00"), service="svc")
    body = _read(artifacts, tmp_path)
    assert "e1" not in body["matches"] and counts["started_unfrozen"] == 1
    assert "e2" in body["matches"]


def test_no_kickoff_means_no_freeze(artifacts, tmp_path):
    """Nothing could prove such an entry pre-dates the game."""
    payload = _payload("2026-09-19T09:00:00+00:00", matches=[{"match_id": "e1", "kickoff": None, "status_state": "pre"}])
    counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", payload, service="svc")
    assert counts["no_kickoff"] == 1 and _read(artifacts, tmp_path)["matches"] == {}


def test_a_match_that_is_no_longer_pre_is_not_frozen_even_before_its_kickoff(artifacts, tmp_path):
    """A postponed match reads `void` before its old kickoff (`78932794`)."""
    payload = _payload("2026-09-19T09:00:00+00:00")
    payload["matches"][0]["status_state"] = "void"
    counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", payload, service="svc")
    assert counts["not_pre"] == 1 and "e1" not in _read(artifacts, tmp_path)["matches"]


def test_a_naive_kickoff_is_read_as_utc(artifacts, tmp_path):
    payload = _payload("2026-09-19T13:59:00+00:00", matches=[{"match_id": "e1", "kickoff": "2026-09-19 14:00:00", "status_state": "pre"}])
    assert artifacts.freeze_prekickoff(tmp_path, "2026-09-19", payload, service="svc")["frozen_this_build"] == 1


# ---------------------------------------------------------------------------
# 2. IT CAN NEVER COST THE BOARD
# ---------------------------------------------------------------------------


def test_a_corrupt_freeze_file_restarts_rather_than_raising(artifacts, tmp_path):
    path = artifacts.prekickoff_freeze_path(tmp_path, "2026-09-19", "svc")
    path.write_text("{not json", encoding="utf-8")
    counts = artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"), service="svc")
    assert counts["frozen_this_build"] == 2 and set(_read(artifacts, tmp_path)["matches"]) == {"e1", "e2"}


def test_the_write_is_atomic_and_leaves_no_temp_file(artifacts, tmp_path):
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"), service="svc")
    assert [p.name for p in tmp_path.iterdir()] == ["recommendations_prekickoff_2026-09-19.svc.json"]


def test_a_failure_while_building_the_body_leaves_the_previous_freeze_intact(artifacts, tmp_path, monkeypatch):
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"), service="svc")
    before = artifacts.prekickoff_freeze_path(tmp_path, "2026-09-19", "svc").read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise TypeError("unserialisable")

    monkeypatch.setattr(artifacts.json, "dumps", boom)
    with pytest.raises(TypeError):
        artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T10:00:00+00:00"), service="svc")
    monkeypatch.undo()
    assert artifacts.prekickoff_freeze_path(tmp_path, "2026-09-19", "svc").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 3. REACHABILITY
# ---------------------------------------------------------------------------


def test_one_file_per_service_so_two_writers_never_replace_each_other(artifacts, tmp_path, monkeypatch):
    """live-odds-worker and refresh-worker both build and publish soccer
    recommendations; one shared path would be #630's whole-file replace."""
    monkeypatch.setenv("RENDER_SERVICE_NAME", "live-odds-worker")
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T09:00:00+00:00"))
    monkeypatch.setenv("RENDER_SERVICE_NAME", "refresh-worker")
    artifacts.freeze_prekickoff(tmp_path, "2026-09-19", _payload("2026-09-19T10:00:00+00:00"))
    monkeypatch.delenv("RENDER_SERVICE_NAME")
    assert artifacts.prekickoff_freeze_path(tmp_path, "2026-09-19").name == "recommendations_prekickoff_2026-09-19.local.json"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["recommendations_prekickoff_2026-09-19.live-odds-worker.json",
                     "recommendations_prekickoff_2026-09-19.refresh-worker.json"]


def test_the_name_is_one_the_publisher_already_ships(artifacts):
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    name = artifacts.prekickoff_freeze_path(Path("x"), "2026-09-19", "live-odds-worker").name
    assert is_hot_artifact_relative_path(f"soccer_source/epl/api/recommendations/{name}")
    # The temp file must not be: a half-written name must never be published.
    assert not is_hot_artifact_relative_path(f"soccer_source/epl/api/recommendations/{name}.1234.tmp")


class _FakeOutput:
    def __init__(self, match_outputs, player_outputs):
        self.match_outputs = match_outputs
        self.player_outputs = player_outputs


class _FakeAdapter:
    def simulate_props(self, _input):
        return _FakeOutput(
            [{"match_id": "e1", "matchup": {"home_team": "Arsenal", "away_team": "Leeds"}}],
            [{"player_id": "a0", "player_name": "A", "team": "Arsenal", "side": "home", "match_id": "e1",
              "anytime_scorer_probability_if_playing": 0.31}],
        )


def _wire_build(artifacts, monkeypatch, kickoff):
    monkeypatch.setattr(artifacts, "_fetch_fixtures", lambda league, iso_date: [
        {"event_id": "e1", "home_team": "Arsenal", "away_team": "Leeds", "kickoff": kickoff, "status_state": "pre"}
    ])
    monkeypatch.setattr(artifacts, "_load_team_ratings", lambda league, root, iso_date: {"Arsenal": {}, "Leeds": {}})
    monkeypatch.setattr(artifacts, "_load_player_rows", lambda league, root: [{"player_id": "a0", "team": "Arsenal"}])
    monkeypatch.setattr(artifacts, "_attach_confirmed_starters", lambda league, iso_date, fixtures, rows: fixtures)
    monkeypatch.setattr(artifacts, "_apply_market_anchor", lambda league, root, fixtures, ratings: (ratings, {"state": "disabled"}))
    monkeypatch.setattr(artifacts, "_squad_audit", lambda outputs, rows: {})
    monkeypatch.setattr(artifacts, "build_soccer_simulation_input", lambda **kwargs: object())
    monkeypatch.setattr(artifacts, "build_soccer_simulation_adapter", lambda league: _FakeAdapter())


def test_REACHABILITY_build_artifacts_writes_the_freeze_beside_the_artifact(artifacts, tmp_path, monkeypatch):
    """Read back from DISK. A helper that is tested but never called is the
    inert-feature shape `model_engine_standard.md` exists for."""
    monkeypatch.setenv("RENDER_SERVICE_NAME", "live-odds-worker")
    _wire_build(artifacts, monkeypatch, "2099-09-19T14:00Z")
    out_root = tmp_path / "out"
    artifacts.build_artifacts("epl", "2099-09-19", source_root=tmp_path / "src", out_root=out_root, simulations=10)
    rec = next(out_root.rglob("recommendations_2099-09-19.json"))
    freeze = rec.parent / "recommendations_prekickoff_2099-09-19.live-odds-worker.json"
    body = json.loads(freeze.read_text(encoding="utf-8"))
    assert set(body["matches"]) == {"e1"}
    assert body["matches"]["e1"]["player_props"][0]["anytime_scorer_probability_if_playing"] == 0.31
    assert body["last_build"]["frozen_this_build"] == 1


def test_a_failing_freeze_never_stops_the_artifact_being_written(artifacts, tmp_path, monkeypatch):
    _wire_build(artifacts, monkeypatch, "2099-09-19T14:00Z")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artifacts, "freeze_prekickoff", boom)
    out_root = tmp_path / "out"
    payload = artifacts.build_artifacts("epl", "2099-09-19", source_root=tmp_path / "src", out_root=out_root, simulations=10)
    assert payload["matches"] and next(out_root.rglob("recommendations_2099-09-19.json")).exists()
