"""The mirror-data check reads the DISK, and it can actually fail.

WHY IT EXISTS. `PROTECTED_MIRROR_ASSETS`' breadth check reads
`mirror_refresh_latest.json` -- the manifest of the last refresh -- and the MLB
entry is waived, because that manifest is CI-written and no local action updates
it. Measured 2026-08-17: 255 artifacts (186 MiB) pulled from production took the
mirror 161 -> 416 files, matching production inventory exactly, and the violation
did not move.

Waiving it left nothing checking that the mirror HAS data.
`PROTECTED_LOCAL_RESOLVER_CHECKS` looks like the backstop and is not -- it runs
against a `TemporaryDirectory` with patched roots and verifies path RESOLUTION,
so it passes on a completely empty mirror. These tests are the falsification the
waived check no longer provides.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_GATE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migration_gate.py"
_spec = importlib.util.spec_from_file_location("_migration_gate_for_test", _GATE)
mg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mg
_spec.loader.exec_module(mg)

FAMILY = "data/mlb_source/data/daily"
BUNDLE = "data/mlb_source/source_artifacts/data/daily"


def _mirror(tmp_path: pathlib.Path, rel: str, *names: str) -> pathlib.Path:
    target = tmp_path / rel
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        (target / name).write_text("{}", encoding="utf-8")
    return tmp_path


def test_an_empty_mirror_FAILS(tmp_path):
    """The catastrophic case no other check in the gate sees."""
    result = mg.evaluate_protected_mirror_data(tmp_path)
    assert result["ok"] is False
    assert [v["issue"] for v in result["violations"]] == ["mirror_family_empty"]
    assert result["families"][0]["count"] == 0


def test_one_artifact_is_enough(tmp_path):
    """The floor is 1 BY DESIGN. `data/**` is a lossy, per-family-scheduled
    mirror, so a floor tuned to today's count would fail every fresh clone and
    get waived like its predecessor. See the docstring in the gate."""
    root = _mirror(tmp_path, FAMILY, "daily_summary_2026_08_17.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert result["ok"] is True
    assert result["families"][0]["count"] == 1
    assert result["families"][0]["newest_date"] == "2026-08-17"


def test_either_mirror_root_satisfies_it(tmp_path):
    """Tracked copies live under `data/`, bundle copies under `source_artifacts/`.
    Either satisfies a reader, so requiring one specific root would fail on a
    legitimate layout."""
    root = _mirror(tmp_path, BUNDLE, "daily_summary_2026_07_01.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert result["ok"] is True
    assert result["families"][0]["count"] == 1


def test_a_file_from_another_family_does_not_count(tmp_path):
    """`lineups_last_known_by_team.json` is a real artifact in that directory and
    must not be mistaken for daily-summary coverage -- otherwise the check passes
    on a mirror that has everything EXCEPT the family it names."""
    root = _mirror(tmp_path, FAMILY, "lineups_last_known_by_team.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert result["ok"] is False
    assert result["families"][0]["count"] == 0


def test_staleness_is_REPORTED_and_never_gated(tmp_path):
    """A mirror four months stale still PASSES, and says so in the report.

    Gating on recency is what the waived check effectively did, and it fired on
    normal operation. `newest_date` exists so a human can see a lagging mirror
    without the gate blocking on it. **If staleness should gate, it needs its own
    decision and its own allowance list -- not a quietly raised `min_count`.**
    """
    root = _mirror(tmp_path, FAMILY, "daily_summary_2026_04_01.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert result["ok"] is True
    assert result["families"][0]["newest_date"] == "2026-04-01"


def test_dates_and_bytes_are_reported_for_a_human(tmp_path):
    root = _mirror(
        tmp_path, FAMILY,
        "daily_summary_2026_08_15.json",
        "daily_summary_2026_08_16.json",
        "daily_summary_2026_08_16_hr_targets.json",
    )
    family = mg.evaluate_protected_mirror_data(root)["families"][0]
    assert family["count"] == 3
    assert family["distinct_dates"] == 2, "two dates across three files"
    assert family["oldest_date"] == "2026-08-15"
    assert family["newest_date"] == "2026-08-16"
    assert family["bytes"] > 0


def test_the_check_is_wired_into_the_verdict():
    """A check that runs but does not gate is decoration. Pins the wiring."""
    source = _GATE.read_text(encoding="utf-8")
    assert "protected_mirror_data = evaluate_protected_mirror_data()" in source
    assert 'and bool(protected_mirror_data.get("ok"))' in source
    assert '"protected_mirror_data": protected_mirror_data,' in source


def test_the_real_repo_mirror_is_not_empty():
    """The live assertion the waiver removed. If this fails on a real checkout,
    the MLB daily mirror is genuinely gone -- which is the whole point."""
    result = mg.evaluate_protected_mirror_data()
    assert result["ok"] is True, result["violations"]
    assert result["families"][0]["count"] > 0
