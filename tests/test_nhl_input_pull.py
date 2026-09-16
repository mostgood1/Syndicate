"""The NHL runner pulls missing season inputs onto its own disk before generating.

Lane nhl-season-readiness, 2026-09-16. Generation reads `<artifact_root>/data/processed`
on the worker's OWN disk and nothing else copies non-dated inputs there, so without this
pull every hockeysim feature silently falls back to its neutral default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import refresh_nhl_oddsapi as runner  # noqa: E402
from syndicate.features.shared import artifact_publisher as publisher  # noqa: E402

NAMES = runner._NHL_SEASON_INPUT_FILES


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """A data root whose `nhl_source` is the artifact root, as on Render."""
    data_root = tmp_path / "data"
    artifact_root = data_root / "nhl_source"
    (artifact_root / "data" / "processed").mkdir(parents=True)
    calls: list[str] = []

    def fake_pull(url, token, *, timeout_seconds):
        # Mirror the real writer: the exact path lands under the data root.
        rel = url.split("exact_path=", 1)[1]
        target = data_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("team,value\nX,1\n", encoding="utf-8")
        calls.append(rel)
        return True, 1

    monkeypatch.setattr(publisher, "_data_root", lambda: data_root)
    monkeypatch.setattr(publisher, "_admin_token", lambda: "token")
    monkeypatch.setattr(publisher, "_export_url", lambda pattern=None, *, since_epoch=None, exact_path=None: f"https://web/export?exact_path={exact_path}")
    monkeypatch.setattr(publisher, "_pull_hot_artifacts_request", fake_pull)
    return artifact_root, calls


def test_missing_inputs_are_pulled_to_the_generation_root(hosted, capsys):
    artifact_root, calls = hosted
    result = runner._ensure_season_inputs(artifact_root)
    assert calls == [f"nhl_source/data/processed/{n}" for n in NAMES]
    assert result["missing"] == []
    assert sorted(result["present"]) == sorted(NAMES)
    for name in NAMES:
        assert (artifact_root / "data" / "processed" / name).is_file()
    assert "NHL_SEASON_INPUTS" in capsys.readouterr().out


def test_present_inputs_are_not_pulled_again(hosted):
    artifact_root, calls = hosted
    for name in NAMES:
        (artifact_root / "data" / "processed" / name).write_text("team,value\nX,1\n", encoding="utf-8")
    result = runner._ensure_season_inputs(artifact_root)
    assert calls == []
    assert result["missing"] == []


def test_only_the_missing_ones_are_pulled(hosted):
    artifact_root, calls = hosted
    (artifact_root / "data" / "processed" / "team_elo_latest.csv").write_text("team,elo\nX,1500\n", encoding="utf-8")
    runner._ensure_season_inputs(artifact_root)
    assert "nhl_source/data/processed/team_elo_latest.csv" not in calls
    assert len(calls) == len(NAMES) - 1


def test_an_empty_file_counts_as_missing(hosted):
    artifact_root, calls = hosted
    (artifact_root / "data" / "processed" / "team_xg_latest.csv").write_text("", encoding="utf-8")
    runner._ensure_season_inputs(artifact_root)
    assert "nhl_source/data/processed/team_xg_latest.csv" in calls


def test_a_root_the_pull_cannot_write_into_is_reported_not_attempted(hosted, tmp_path, capsys):
    _, calls = hosted
    elsewhere = tmp_path / "repo" / "data" / "nhl_source" / "source_artifacts"
    (elsewhere / "data" / "processed").mkdir(parents=True)
    result = runner._ensure_season_inputs(elsewhere)
    assert calls == []
    assert sorted(result["missing"]) == sorted(NAMES)
    assert "root_mismatch" in capsys.readouterr().out


def test_a_failing_pull_never_raises(hosted, monkeypatch, capsys):
    artifact_root, _ = hosted

    def boom(url, token, *, timeout_seconds):
        raise RuntimeError("web down")

    monkeypatch.setattr(publisher, "_pull_hot_artifacts_request", boom)
    result = runner._ensure_season_inputs(artifact_root)
    assert sorted(result["missing"]) == sorted(NAMES)
    assert "error=RuntimeError" in capsys.readouterr().out


def test_generation_records_a_warning_when_inputs_stay_missing(hosted, monkeypatch):
    artifact_root, _ = hosted
    monkeypatch.setattr(publisher, "_admin_token", lambda: "")
    warnings: list[str] = []

    import types

    fake_ingestion = types.SimpleNamespace(collect_slate_inputs=lambda *a, **k: None)
    fake_anchor = types.SimpleNamespace(ENV_ANCHOR_WEIGHT="X", resolve_anchor_weight=lambda: (0.35, "default"))
    fake_producer = types.SimpleNamespace(
        build_predictions_for_date=lambda *a, **k: None,
        build_recommendations_for_date=lambda *a, **k: None,
        build_props_for_date=lambda *a, **k: None,
    )
    monkeypatch.setitem(sys.modules, "syndicate.features.nhl.sim_engine.hockeysim.ingestion", fake_ingestion)
    monkeypatch.setitem(sys.modules, "syndicate.features.nhl.sim_engine.hockeysim.market_anchoring", fake_anchor)
    monkeypatch.setitem(sys.modules, "build_nhl_artifacts", fake_producer)
    runner._run_owned_generation(artifact_root=artifact_root, target_dates=["2026-09-19"], props_n_sims=10, warnings=warnings)
    assert any("nhl season inputs missing after pull" in w for w in warnings)
