"""`#671`: the NFL usage artifact must be WRITTEN where it survives and PUBLISHED when kept.

Three defects are pinned here, all measured on production 2026-09-17:

1. `usage_artifact_path` resolved through `default_nfl_source_root()`, a READ
   selector that picks a root by probing for `upcoming_recs_*.csv`. On
   refresh-worker that is the ephemeral checkout, so the artifact was written
   where every deploy erases it AND where `publish_hot_artifact` -- which
   addresses files relative to `SYNDICATE_DATA_ROOT` -- cannot name it.
2. Nothing published the document, although `nfl_fantasy_usage_*.json` has been
   in `HOT_ARTIFACT_PATTERNS` all along and web holds zero of them.
3. Only PRIOR seasons were built, so the current season -- the one a prop Ask
   needs for recent form -- never had a document at all.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl import fantasy_usage
from syndicate.features.shared import source_roots


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A mounted disk and a repo checkout, with the checkout holding the probe file.

    This is the production shape: `upcoming_recs_*.csv` is git-tracked so it
    exists in the checkout and not on the disk.
    """
    disk = tmp_path / "disk"
    checkout = tmp_path / "checkout" / "nfl_source"
    (disk / "nfl_source").mkdir(parents=True)
    checkout.mkdir(parents=True)
    (checkout / "upcoming_recs_2026.csv").write_text("x", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(disk))
    monkeypatch.delenv("SYNDICATE_NFL_SOURCE_ROOT", raising=False)
    source_roots.clear_source_root_caches()
    fantasy_usage._load_usage_payload.cache_clear()
    yield {"disk_nfl": disk / "nfl_source", "checkout_nfl": checkout, "data_root": disk}
    source_roots.clear_source_root_caches()
    fantasy_usage._load_usage_payload.cache_clear()


def test_the_write_path_is_the_mounted_disk_not_wherever_a_probe_file_lives(roots):
    path = fantasy_usage.usage_artifact_path(2026)
    assert path == roots["disk_nfl"] / "fantasy" / "nfl_fantasy_usage_2026.json"
    # The old selector would have answered the checkout, because that is where
    # `upcoming_recs_*.csv` is. Prove the trap is real and that we dodge it.
    from syndicate.features.nfl.sources import default_nfl_source_root

    assert (roots["checkout_nfl"] / "upcoming_recs_2026.csv").is_file()
    assert path.parent.parent != default_nfl_source_root() or default_nfl_source_root() == roots["disk_nfl"]


def test_the_write_path_is_addressable_by_the_publisher(roots):
    from syndicate.features.shared import artifact_publisher as ap

    path = fantasy_usage.usage_artifact_path(2026)
    relative = ap.relative_to_data_root(path)
    assert relative == "nfl_source/fantasy/nfl_fantasy_usage_2026.json"
    # And the allowlist already accepts it -- the entry was never the problem.
    assert ap.is_hot_artifact_relative_path(relative)


def test_a_document_in_the_other_candidate_root_is_still_found_by_readers(roots):
    """A copy under `source_artifacts/` -- the other root the resolver returns -- still loads.

    The resolver searches the roots `preferred_artifact_roots` actually yields,
    per file, rather than probing for an unrelated artifact. On Render the repo
    checkout is deliberately NOT among them (`SYNDICATE_REQUIRE_HOSTED_STORAGE`
    is on there), which is the point of the move: the ephemeral copy stops
    being reachable instead of being silently preferred.
    """
    legacy = roots["disk_nfl"] / "source_artifacts" / "fantasy" / "nfl_fantasy_usage_2025.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"players": {}, "teams": {}, "player_game_lines": []}), encoding="utf-8")
    assert fantasy_usage.existing_usage_artifact_path(2025) == legacy
    assert fantasy_usage._load_usage_payload(2025) is not None
    # Nothing exists for 2026 anywhere.
    assert fantasy_usage.existing_usage_artifact_path(2026) is None

    # And when BOTH roots hold one, the write root wins, so a publish and a read
    # cannot disagree about which document is current.
    written = fantasy_usage.usage_artifact_path(2025)
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(json.dumps({"players": {"x": {}}, "teams": {}, "player_game_lines": []}), encoding="utf-8")
    assert fantasy_usage.existing_usage_artifact_path(2025) == written


def _builder(monkeypatch, roots, published: list, *, exists: bool = True):
    module = importlib.import_module("scripts.build_nfl_fantasy_usage")
    monkeypatch.setattr(module, "usage_substrate",
                        lambda season: {"season": season, "path": "pbp.csv", "exists": exists, "bytes": 1})
    monkeypatch.setattr(module, "publish", lambda path, **kw: published.append(Path(path)) or True)
    return module


def test_a_kept_artifact_is_published(monkeypatch, roots):
    """The steady state on the worker is 'already built' -- that is the case that must push."""
    target = fantasy_usage.usage_artifact_path(2025)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    published: list[Path] = []
    module = _builder(monkeypatch, roots, published)
    monkeypatch.setattr(sys, "argv", ["build_nfl_fantasy_usage.py", "--seasons", "2025"])
    assert module.main() == 0
    assert published == [target]


def test_no_publish_suppresses_the_push(monkeypatch, roots):
    target = fantasy_usage.usage_artifact_path(2025)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    published: list[Path] = []
    module = _builder(monkeypatch, roots, published)
    monkeypatch.setattr(sys, "argv", ["build_nfl_fantasy_usage.py", "--seasons", "2025", "--no-publish"])
    assert module.main() == 0
    assert published == []


def test_a_missing_substrate_is_a_named_skip_not_a_publish(monkeypatch, roots):
    published: list[Path] = []
    module = _builder(monkeypatch, roots, published, exists=False)
    monkeypatch.setattr(sys, "argv", ["build_nfl_fantasy_usage.py", "--seasons", "2026"])
    assert module.main() == 1          # a refusal, not a silent success
    assert published == []


def test_publish_refuses_a_path_outside_the_data_root(tmp_path, monkeypatch, roots):
    module = importlib.import_module("scripts.build_nfl_fantasy_usage")
    stray = tmp_path / "elsewhere" / "nfl_fantasy_usage_2025.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}", encoding="utf-8")
    assert module.publish(stray) is False   # the `#389` shape, named rather than attempted


def test_prepare_builds_the_current_season_and_rebuilds_it_when_pbp_is_newer(monkeypatch, roots, tmp_path):
    module = importlib.import_module("scripts.build_nfl_fantasy_projection_artifact")
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "_run", lambda label, args: calls.append([label, *args]) or True)

    pbp = tmp_path / "pbp_2026.csv"
    pbp.write_text("x", encoding="utf-8")
    monkeypatch.setattr(module, "usage_substrate",
                        lambda season: {"season": season, "path": str(pbp), "exists": True, "bytes": 1})

    # History present, current season absent -> the current season is built.
    history_doc = fantasy_usage.usage_artifact_path(2025)
    history_doc.parent.mkdir(parents=True, exist_ok=True)
    history_doc.write_text("{}", encoding="utf-8")
    module._prepare_inputs(2026, (2025,))
    usage_calls = [c for c in calls if c[0] == "usage"]
    assert usage_calls and "2026" in usage_calls[-1][-2]

    # Now the current season exists but the pbp is NEWER -> rebuilt.
    calls.clear()
    current = fantasy_usage.usage_artifact_path(2026)
    current.write_text("{}", encoding="utf-8")
    import os, time

    old = time.time() - 3600
    os.utime(current, (old, old))
    module._prepare_inputs(2026, (2025,))
    assert [c for c in calls if c[0] == "usage"], "a newer pbp must rebuild the current season"

    # And when the artifact is newer than the pbp, nothing is rebuilt but the
    # documents are still PUBLISHED -- absence from web is the defect, not staleness.
    calls.clear()
    fresh = time.time() + 60
    os.utime(current, (fresh, fresh))
    module._prepare_inputs(2026, (2025,))
    assert [c for c in calls if c[0] == "usage"] == []
    assert [c for c in calls if c[0] == "usage_publish"], "a run that builds nothing must still publish"
