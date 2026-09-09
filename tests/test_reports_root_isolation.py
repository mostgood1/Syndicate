"""The `reports/` redirect must be a WALL, not a WINDOW.

`conftest.py`'s `_isolate_reports_root` points `SYNDICATE_REPORTS_ROOT` at a
scratch dir for every test, and that is correct as far as it goes. It is
function-scoped, so `monkeypatch` restores the variable at teardown -- and
anything still running then resolves the REAL `reports/`.

MEASURED 2026-09-09: `reports/intelligence/kalshi_markets.json` came back
modified after a full suite run with every per-test isolation in place. The
writer was a DAEMON THREAD -- `run_live_odds_refresh_worker.main()` starts the
venue poll at line 2343, and a test that drives that entrypoint leaves it
ticking every >=1s for the rest of the session. It was caught only by the
mirror guard's `os.replace` seam, because the write is an atomic rename:

    _venue_poll_background_loop -> _venue_poll_tick -> run_kalshi_odds_refresh
      -> write_json_file -> _atomic_write_text -> os.replace

WHY A SUBPROCESS IS THE RIGHT TEST for a thread's defect. Both read the same
thing -- the process environment -- and a subprocess does it at a moment this
test can control, whereas a thread's write races the fixture teardown that
makes it wrong. A subprocess is also one of the leak vectors in its own right:
`schedule_adapter`'s vendor CLI inherits `os.environ` wholesale.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = (
    "import json, sys;"
    "sys.path.insert(0, r'%s');"
    "from syndicate.features.shared.refresh_state_store import reports_root;"
    "print(json.dumps({'root': str(reports_root())}))"
) % (REPO_ROOT,)


def _resolved_reports_root_in_a_child() -> Path:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    line = [l for l in completed.stdout.splitlines() if l.strip().startswith("{")][-1]
    return Path(json.loads(line)["root"])


def test_the_floor_under_the_per_test_override_is_not_the_repos_reports_tree(
    session_reports_root_floor,
):
    """THE INVARIANT, ASSERTED WHERE IT ACTUALLY BITES.

    `monkeypatch` restores `SYNDICATE_REPORTS_ROOT` to its import-time value at
    teardown, so THAT value -- not the fixture's override -- is what a surviving
    thread reads. Asserting from inside a test can only see the override, which
    is isolated whether or not the wall exists; the first version of this test
    did exactly that and passed with the wall removed, which is why it is
    written against the floor instead.
    """
    assert str(session_reports_root_floor or "").strip(), (
        "SYNDICATE_REPORTS_ROOT must be set at conftest IMPORT, not only by the "
        "per-test fixture -- see the module docstring."
    )
    floor = os.path.normcase(str(Path(session_reports_root_floor).resolve()))
    repo_reports = os.path.normcase(str(REPO_ROOT / "reports"))
    assert floor != repo_reports, session_reports_root_floor
    assert not floor.startswith(repo_reports + os.sep), session_reports_root_floor


def test_a_child_process_resolves_that_same_isolated_floor(session_reports_root_floor):
    """A child inherits `os.environ`, which is the same thing a late thread reads.

    Weaker than the test above on its own -- during a test the fixture's override
    is already isolated -- but it pins the OTHER half: that `reports_root()`
    actually honours the variable rather than resolving the repo regardless.
    """
    resolved = _resolved_reports_root_in_a_child()
    repo_reports = os.path.normcase(str(REPO_ROOT / "reports"))
    assert os.path.normcase(str(resolved)) != repo_reports, resolved
    assert not os.path.normcase(str(resolved)).startswith(repo_reports + os.sep), resolved
