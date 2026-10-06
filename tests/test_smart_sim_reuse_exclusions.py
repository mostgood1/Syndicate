"""A SmartSim built with a different exclusion set than the current run is rebuilt, not reused
(lane smart-sim-reuse-stale-exclusions). Drives the REAL reuse branch of _smart_sim_run_date_local with the
worker stubbed, switch on vs off, so the check is shown reachable (off != on)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local
from syndicate.features.shared.smart_sim_reuse import exclusion_drift, stamped_exclusions

DATE = "2026-10-07"


def _fake_worker_run(job: dict) -> dict:
    return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}


def _seed(root: Path, *, stamp: dict | None, feed_status: str = "OUT") -> tuple[Path, Path, Path]:
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text("home_team,visitor_team,totals,spread_margin\nLVA,NYL,160,4\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nKelsey Plum,LVA\nA'ja Wilson,LVA\nBreanna Stewart,NYL\n", encoding="utf-8"
    )
    (raw / "injuries.csv").write_text(f"team,player,status,injury,date\nLVA,Kelsey Plum,{feed_status},Out,2026-10-06\n", encoding="utf-8")
    payload: dict = {"home": "LVA", "away": "NYL", "players": {"home": [{"player": "A"}], "away": [{"player": "B"}]}}
    if stamp is not None:
        payload["context"] = {"excluded_players": stamp}
    sim = processed / f"smart_sim_{DATE}_LVA_NYL.json"
    sim.write_text(json.dumps(payload), encoding="utf-8")
    return processed, raw, sim


def _run(processed: Path, raw: Path) -> dict:
    with patch(
        "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local", side_effect=_fake_worker_run
    ), patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local", return_value=None):
        return _smart_sim_run_date_local(
            processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None, max_games=None,
            overwrite=False, workers=1, league_code="wnba",
        )


def test_sim_built_before_a_player_went_out_is_rebuilt(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    processed, raw, _ = _seed(tmp_path, stamp=None)  # built when nobody was out
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (1, 0)
    out = capsys.readouterr().out
    assert "SMART_SIM_REUSE_STALE_EXCLUSIONS" in out and "LVA:+KELSEY PLUM" in out


def test_switch_off_reuses_the_stale_sim(tmp_path, monkeypatch):
    # reachability: the same stale file is reused with the check off -> the check is what rebuilds it
    monkeypatch.setenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", "0")
    processed, raw, _ = _seed(tmp_path, stamp=None)
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1)


def test_sim_built_with_todays_exclusions_is_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    processed, raw, sim = _seed(tmp_path, stamp={"LVA": ["KELSEY PLUM"]})
    before = sim.read_bytes()
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1)
    assert sim.read_bytes() == before


def test_returned_player_still_excluded_in_the_file_triggers_a_rebuild(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    processed, raw, _ = _seed(tmp_path, stamp={"LVA": ["KELSEY PLUM"]}, feed_status="DAY-TO-DAY")
    result = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "LVA:+-/-KELSEY PLUM" in capsys.readouterr().out


def test_stamp_reader_and_drift():
    assert exclusion_drift({"LVA": {"A"}}, {"LVA": {"A"}, "NYL": set()}, ["LVA", "NYL"]) == {}
    assert exclusion_drift({}, {"LVA": {"a "}}, ["LVA"]) == {"LVA": {"added": ["A"], "removed": []}}


def test_unreadable_file_is_not_a_match(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json", encoding="utf-8")
    assert stamped_exclusions(bad) is None
