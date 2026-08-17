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


MLB_FAMILY = "daily summary artifacts on disk"


def _family(result, description: str) -> dict:
    """The one family under test.

    These tests were written when there was a single family, and asserted on the
    whole-result `ok`. Adding the nba/wnba families broke four of them -- correctly:
    a partial fixture leaves the OTHER families empty, so global `ok` is False for
    reasons that have nothing to do with what the test is about. Scope to the
    family, assert on it.
    """
    matches = [f for f in result["families"] if f["description"] == description]
    assert len(matches) == 1, f"{description!r} not found in {[f['description'] for f in result['families']]}"
    return matches[0]


def _violations_for(result, description: str) -> list:
    return [v for v in result["violations"] if v["description"] == description]


def test_an_empty_mirror_FAILS(tmp_path):
    """The catastrophic case no other check in the gate sees."""
    result = mg.evaluate_protected_mirror_data(tmp_path)
    assert result["ok"] is False
    assert [v["issue"] for v in _violations_for(result, MLB_FAMILY)] == ["mirror_family_empty"]
    assert _family(result, MLB_FAMILY)["count"] == 0


def test_one_artifact_is_enough(tmp_path):
    """The floor is 1 BY DESIGN. `data/**` is a lossy, per-family-scheduled
    mirror, so a floor tuned to today's count would fail every fresh clone and
    get waived like its predecessor. See the docstring in the gate."""
    root = _mirror(tmp_path, FAMILY, "daily_summary_2026_08_17.json")
    family = _family(mg.evaluate_protected_mirror_data(root), MLB_FAMILY)
    assert family["count"] == 1
    assert family["newest_date"] == "2026-08-17"
    assert not _violations_for(mg.evaluate_protected_mirror_data(root), MLB_FAMILY)


def test_either_mirror_root_satisfies_it(tmp_path):
    """Tracked copies live under `data/`, bundle copies under `source_artifacts/`.
    Either satisfies a reader, so requiring one specific root would fail on a
    legitimate layout."""
    root = _mirror(tmp_path, BUNDLE, "daily_summary_2026_07_01.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert _family(result, MLB_FAMILY)["count"] == 1
    assert not _violations_for(result, MLB_FAMILY)


def test_a_file_from_another_family_does_not_count(tmp_path):
    """`lineups_last_known_by_team.json` is a real artifact in that directory and
    must not be mistaken for daily-summary coverage -- otherwise the check passes
    on a mirror that has everything EXCEPT the family it names."""
    root = _mirror(tmp_path, FAMILY, "lineups_last_known_by_team.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert _violations_for(result, MLB_FAMILY)
    assert _family(result, MLB_FAMILY)["count"] == 0


def test_staleness_is_REPORTED_and_never_gated(tmp_path):
    """A mirror four months stale still PASSES, and says so in the report.

    Gating on recency is what the waived check effectively did, and it fired on
    normal operation. `newest_date` exists so a human can see a lagging mirror
    without the gate blocking on it. **If staleness should gate, it needs its own
    decision and its own allowance list -- not a quietly raised `min_count`.**
    """
    root = _mirror(tmp_path, FAMILY, "daily_summary_2026_04_01.json")
    result = mg.evaluate_protected_mirror_data(root)
    assert not _violations_for(result, MLB_FAMILY), "stale must not gate"
    assert _family(result, MLB_FAMILY)["newest_date"] == "2026-04-01"


def test_dates_and_bytes_are_reported_for_a_human(tmp_path):
    root = _mirror(
        tmp_path, FAMILY,
        "daily_summary_2026_08_15.json",
        "daily_summary_2026_08_16.json",
        "daily_summary_2026_08_16_hr_targets.json",
    )
    family = _family(mg.evaluate_protected_mirror_data(root), MLB_FAMILY)
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
    """The live assertion the waivers removed. If this fails on a real checkout,
    one of these mirror families is genuinely gone -- which is the whole point."""
    result = mg.evaluate_protected_mirror_data()
    assert result["ok"] is True, result["violations"]
    assert all(family["count"] > 0 for family in result["families"])


def test_every_waived_manifest_family_is_covered():
    """One entry per WAIVED PREFIX, not one per sport.

    Three manifest-breadth violations are waived -- mlb, nba, wnba -- and each
    lists several prefixes. A per-sport data check would pass on a sport that had
    lost five of six families. This pins the mapping so a future waiver does not
    quietly widen the hole."""
    covered = {(f["slug"], f["description"]) for f in mg.PROTECTED_MIRROR_DATA_FAMILIES}
    slugs = {slug for slug, _ in covered}
    assert slugs == {"mlb", "nba", "wnba"}, "every waived sport needs a data family"
    assert len(covered) == 7, "one family per covered prefix"


def test_each_family_fails_independently(tmp_path):
    """Populate every family except one; only that one may fail.

    Guards the failure mode a per-sport check would have: WNBA keeping
    `game_cards_` while losing `recommendations_slate_` must still fail."""
    seed = {
        "data/mlb_source/data/daily": "daily_summary_2026_08_17.json",
        "data/nba_source/data/processed": "season_betting_card_manifest_x.json",
        "data/wnba_source/data/processed": "game_cards_2026-05-29.csv",
        "data/wnba_source/data/live_lens": "live_lens_projections_2026-05-29.jsonl",
        "data/wnba_source/data/processed/live_snapshots": "live_lines_2026-05-29.jsonl",
    }
    for rel, name in seed.items():
        target = tmp_path / rel
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text("{}", encoding="utf-8")
    # `season_betting_card_day_` and `recommendations_slate_` are absent.
    result = mg.evaluate_protected_mirror_data(tmp_path)
    assert result["ok"] is False
    failing = sorted(v["description"] for v in result["violations"])
    assert failing == [
        "season betting-card day files on disk",
        "slate recommendations on disk",
    ], failing


def test_an_empty_root_fails_every_family(tmp_path):
    """A count of violations, so adding a family cannot silently go unchecked."""
    result = mg.evaluate_protected_mirror_data(tmp_path)
    assert result["ok"] is False
    assert len(result["violations"]) == len(mg.PROTECTED_MIRROR_DATA_FAMILIES)
