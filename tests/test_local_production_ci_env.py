"""`local_production.ci_env` -- the env the nightly ci-suite runs with (lane `ci-env-home-sandbox`, 2026-10-14).

ci_env() scrubbed every fleet env var but passed HOME through, and code that falls back to
`~/syndicate-prod/local_production.env` read the production deploy-claim dir from there:
the ci-suite wrote live 45-min `web` claims (lane-a/session-aaa) into it on 10-13 and 10-14.
These tests gate on what a child process actually RESOLVES, not on the dict's keys alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts import local_production as lp

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVE = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from scripts import deploy_claim as d; print(d._local_production_env_claim_dir())"
)


def _fake_fleet_home(tmp_path: Path) -> tuple[Path, Path]:
    """A real-looking HOME whose local_production.env names an existing claim dir."""
    real_home = tmp_path / "real-home"
    prod_claims = tmp_path / "prod-claims"
    prod_claims.mkdir()
    (real_home / "syndicate-prod").mkdir(parents=True)
    (real_home / "syndicate-prod" / "local_production.env").write_text(
        f"SYNDICATE_DEPLOY_CLAIM_DIR={prod_claims}\n", encoding="utf-8"
    )
    return real_home, prod_claims


def _resolve(env: dict[str, str]) -> str:
    if "SYSTEMROOT" in os.environ:  # CPython on Windows needs it to start
        env = {**env, "SYSTEMROOT": os.environ["SYSTEMROOT"]}
    done = subprocess.run([sys.executable, "-c", RESOLVE, str(REPO_ROOT)], env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_ci_env_replaces_home_with_the_sandbox(tmp_path: Path):
    base = {"PATH": "/usr/bin", "HOME": "/home/x", "USERPROFILE": "C:\\Users\\x",
            "SYNDICATE_LOCAL_HOME": "/home/x/syndicate-prod", "LOCALAPPDATA": "C:\\x"}
    env = lp.ci_env(tmp_path / "ci-home", base)
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path / "ci-home")
    assert Path(env["SYNDICATE_LOCAL_HOME"]).parent == tmp_path / "ci-home"
    assert not Path(env["SYNDICATE_LOCAL_HOME"]).exists()
    assert "LOCALAPPDATA" not in env
    assert env["SYNDICATE_ODDSAPI_QUOTA_FORWARD"] == "0"
    assert "HOME" not in lp.CI_ENV_PASSTHROUGH


def test_ci_child_cannot_reach_the_fleet_claim_dir_through_home(tmp_path: Path):
    real_home, prod_claims = _fake_fleet_home(tmp_path)
    base = {"PATH": os.environ.get("PATH", ""), "HOME": str(real_home), "USERPROFILE": str(real_home)}

    # Control (off != on): the pre-fix env -- HOME passed through, no SYNDICATE_LOCAL_HOME --
    # does reach the production claim dir, so the check below can fail.
    leaky = {**lp.ci_env(tmp_path / "unused", base), "HOME": str(real_home), "USERPROFILE": str(real_home)}
    leaky.pop("SYNDICATE_LOCAL_HOME")
    assert _resolve(leaky) == str(prod_claims)

    sandboxed = lp.ci_env(lp.reset_ci_home(tmp_path / "ci-home"), base)
    assert _resolve(sandboxed) == "None"


def test_reset_ci_home_empties_the_previous_run(tmp_path: Path):
    home = tmp_path / "ci-home"
    (home / ".cache").mkdir(parents=True)
    (home / ".cache" / "stale").write_text("x", encoding="utf-8")
    assert lp.reset_ci_home(home) == home
    assert home.is_dir() and not any(home.iterdir())
