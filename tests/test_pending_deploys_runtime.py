"""`pending_deploys.py` must say whether a pending commit contains code a service
actually EXECUTES -- and must never say "inert" about something that runs.

WHY. The `("scripts/", both workers)` row attributed EVERY script to both
workers, so four consecutive catch-up rounds on 2026-09-03/04 reported lane-guard
and ledger tooling as pending runtime code. Each had to be dismissed by
hand-reading the file list, which is a judgement call made ten times where a
computation would do.

**THE ASYMMETRY IS THE WHOLE DESIGN**, and it is the same one `check_lane_invariants`
taught (`learnings.md` 2026-09-03):

    false RUNTIME -> noise; a deploy happens that need not have
    false INERT   -> A NEEDED DEPLOY IS HIDDEN

So `scripts/` is demoted only on PROOF that no runtime file names the script, and
the closure returns `None` -- "treat everything as executed" -- when it cannot
read the tree. These tests pin that direction, not the tidiness.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("pending_deploys_under_test",
                                                  ROOT / "scripts" / "pending_deploys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pd():
    return _load()


#: Observed in `deploy_preflight.py`'s LIVE job listing on 2026-09-03/04. These
#: are not guesses about what might run -- they were seen running in production.
OBSERVED_RUNNING = (
    "refresh_odds_sources",
    "build_soccer_artifacts",
    "run_mlb_daily_sim_job",
    "run_refresh_worker",
    "run_live_odds_refresh_worker",
    "run_refresh_odds_job",
)


def test_every_script_seen_running_in_production_is_RUNTIME(pd) -> None:
    """THE FALSIFICATION TEST. If any of these is classified inert, the
    classifier hides a real deploy and must not ship."""
    executed = pd._EXECUTED_SCRIPTS
    if executed is None:
        pytest.skip("closure unavailable; fallback already treats all as executed")
    present = [s for s in OBSERVED_RUNNING if (ROOT / "scripts" / f"{s}.py").exists()]
    assert present, "fixture drift: none of the observed scripts exist any more"
    missing = [s for s in present if s not in executed]
    assert not missing, f"classified INERT but seen running in production: {missing}"


def test_a_worker_still_owns_an_executed_script(pd) -> None:
    """End to end through `_owners`, which is what the report actually calls."""
    if pd._EXECUTED_SCRIPTS is None:
        pytest.skip("closure unavailable")
    owners = pd._owners("scripts/refresh_odds_sources.py")
    assert "live-odds-worker" in owners or "refresh-worker" in owners


def test_pure_tooling_is_demoted(pd) -> None:
    """The point of the change: at least some scripts/ paths are recognised as
    tooling. Asserted as a PROPERTY, not a fixed list, so it does not fail every
    time a script is renamed."""
    if pd._EXECUTED_SCRIPTS is None:
        pytest.skip("closure unavailable")
    total = len(list((ROOT / "scripts").glob("*.py")))
    assert len(pd._EXECUTED_SCRIPTS) < total, "nothing was demoted -- the closure is inert itself"
    assert pd._owners("scripts/trim_lane_blocks.py") == (), "ledger tooling should own no service"


def test_an_unreadable_tree_falls_back_to_TREAT_ALL_AS_EXECUTED(pd, monkeypatch) -> None:
    """The conservative default. If the closure cannot be computed it must return
    None, and `_owners` must then keep the fallback owners rather than demoting."""
    monkeypatch.setattr(pd, "_read_text", lambda path: "")
    assert pd._executed_scripts() is None

    monkeypatch.setattr(pd, "_EXECUTED_SCRIPTS", None)
    owners = pd._owners("scripts/anything_at_all.py")
    assert owners == ("refresh-worker", "live-odds-worker"), (
        "with reachability unknown, every script must stay owned -- demoting would hide a deploy"
    )


def test_non_script_paths_are_untouched_by_the_classifier(pd) -> None:
    """The closure must only affect `scripts/`. A regression here would silently
    change which service owns the app itself."""
    assert pd._owners("syndicate/blueprints/mlb.py") == ("web",)
    assert "refresh-worker" in pd._owners("pipeline/intelligence_state.py")
    shared = pd._owners("syndicate/features/shared/execution_ledger.py")
    assert set(shared) == {"web", "refresh-worker", "live-odds-worker"}


def test_comments_do_not_make_a_script_look_executed(pd) -> None:
    """`deploy_preflight` was classified RUNTIME because `ops.py` mentions it in a
    COMMENT. Prose names things; only code launches them."""
    src = "# see scripts/deploy_preflight.py for details\nx = 1\n"
    assert "deploy_preflight" not in pd._strip_comments(src)


def test_string_literals_SURVIVE_stripping(pd) -> None:
    """The other half, and the dangerous one: a subprocess launch IS a string
    literal, so stripping strings would cause a false INERT."""
    src = 'subprocess.run(["python", "scripts/build_soccer_artifacts.py"])\n'
    assert "build_soccer_artifacts" in pd._strip_comments(src)


def test_unparseable_source_returns_raw_text(pd) -> None:
    """Over-reporting is safe; losing a launch is not."""
    broken = "def f(:\n  # scripts/run_refresh_worker.py\n"
    assert "run_refresh_worker" in pd._strip_comments(broken)
