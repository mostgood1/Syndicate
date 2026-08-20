"""The season-artifact probe. `#440`.

WHY IT EXISTS. On 2026-08-20 `pitch_type_whiff_mult` read 0.0% in production
while: the arsenal artifact was published and schema-valid on web (466/466
pitchers carrying the multipliers), the consumer was provably REACHED (the
appliers on both sides of it populated at 76.87%), the round trip through the
roster artifact was lossless, and the REAL `apply_arsenal_to_pitcher` populated
5/5 pitchers against the real file locally.

Four hypotheses died against that evidence. The unread link was the simplest one
-- whether the file exists on the WORKER at build time -- and it was unreadable
remotely because `pull_season_artifacts()`'s diagnostics go to a disk file that
Render's log API cannot serve. This probe makes that link a published reading.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(monkeypatch, root: Path):
    """Import the real script with _data_root pointed at a temp tree."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(root))
    spec = importlib.util.spec_from_file_location(
        "_probe_mod", REPO / "scripts" / "sim_input_checklist.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, payload) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_absent_artifact_is_reported_absent_not_crashed(monkeypatch, tmp_path):
    """The production case being diagnosed: nothing on disk.

    It must come back `exists: False` -- NOT an exception, and NOT silence.
    Silence here is what let this go unread for a day.
    """
    mod = _load(monkeypatch, tmp_path)
    out = mod._season_artifact_probe(2026)
    by = {f["name"]: f for f in out["files"]}
    assert by["arsenal"]["exists"] is False
    assert out["data_root"] == str(tmp_path)


def test_present_artifact_reports_counts(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    _write(tmp_path, "mlb_source/source_artifacts/data/arsenal/arsenal_2026.json",
           {"pitchers": {"1": {"FF": {"whiff_mult": 0.9}}, "2": {}}, "batters": {"3": {}}})
    out = mod._season_artifact_probe(2026)
    a = {f["name"]: f for f in out["files"]}["arsenal"]
    assert a["exists"] is True and a["loadable"] is True
    assert a["n_pitchers"] == 2 and a["n_batters"] == 1
    assert a["bytes"] > 0


def test_corrupt_artifact_is_loadable_false_with_a_reason(monkeypatch, tmp_path):
    """A file that EXISTS but cannot parse is a different failure from absence,
    and conflating them would send the next reader down the wrong path."""
    mod = _load(monkeypatch, tmp_path)
    p = tmp_path / "mlb_source/source_artifacts/data/arsenal/arsenal_2026.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    a = {f["name"]: f for f in mod._season_artifact_probe(2026)["files"]}["arsenal"]
    assert a["exists"] is True
    assert a["loadable"] is False
    assert "error" in a and a["error"]


def test_every_season_input_is_probed(monkeypatch, tmp_path):
    """If a new season-scoped input is added to the pull list and not here, it
    becomes exactly the kind of unreadable link this probe was written for."""
    mod = _load(monkeypatch, tmp_path)
    names = {f["name"] for f in mod._season_artifact_probe(2026)["files"]}
    assert {"arsenal", "conditional_mix", "batted_ball", "quality", "pitch_splits"} <= names
