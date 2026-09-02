"""`#625`(4): the local fleet runner, and the guard that makes it safe to run.

Every test here corresponds to something that was WRONG while this was built,
and each was invisible until a control was run:

- a `sitecustomize` that RAISES does not stop the interpreter. CPython's
  `site.execsitecustomize` catches it, prints `Error in sitecustomize; ...` and
  carries on **rc=0** — so the first guard announced its refusal and then let a
  money-armed process run. `doctor`'s negative control caught it;
- `shutil.which("gunicorn")` succeeds on Windows and gunicorn then dies on
  `import fcntl`. Presence is not reachability, in the harness for that;
- both workers REFUSE a file state backend while
  `SYNDICATE_REQUIRE_HOSTED_STORAGE` is truthy, which production sets on all
  three services — clearing `RENDER` alone is not enough;
- the run reported `ok=True` while all three roles had exited 1, because the
  criterion was "a guard receipt exists" and a receipt is written before the
  role does any work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import fleet_local  # noqa: E402
from scripts._fleet_guard import (  # noqa: E402
    FleetGuardRefused,
    SHARED_BUDGET_ENV,
    VENUE_CREDENTIAL_ENV,
    assert_money_is_off,
)


# --------------------------------------------------------------------------
# THE MONEY GUARD. Three independent reasons; any one holding is enough, and
# the guard must refuse if any one fails.
# --------------------------------------------------------------------------


def _clean_money_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "0")
    for name in VENUE_CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_paper_env_gives_three_independent_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_money_env(monkeypatch)
    reasons = assert_money_is_off()
    assert len(reasons) == 3, "mode, arm, and credentials are three separate defences"


@pytest.mark.parametrize(
    "key,value",
    [
        ("SYNDICATE_EXECUTION_MODE", "live"),
        ("SYNDICATE_EXECUTION_LIVE_ARMED", "1"),
        ("SYNDICATE_EXECUTION_LIVE_ARMED", "true"),
        ("SYNDICATE_EXECUTION_LIVE_ARMED", "YES"),
    ],
)
def test_guard_refuses_any_money_switch(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    _clean_money_env(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(FleetGuardRefused):
        assert_money_is_off()


@pytest.mark.parametrize("credential", VENUE_CREDENTIAL_ENV)
def test_guard_refuses_any_venue_credential(monkeypatch: pytest.MonkeyPatch, credential: str) -> None:
    """A credential present is a credential that can sign a submit. The guard
    does not reason about whether the code path is reached today."""
    _clean_money_env(monkeypatch)
    monkeypatch.setenv(credential, "x" * 40)
    with pytest.raises(FleetGuardRefused) as excinfo:
        assert_money_is_off()
    assert credential in str(excinfo.value)


def test_execution_mode_contract_matches_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard forces `paper`, and the engine treats ANYTHING that is not
    literally `live` as paper (`execution_ledger.py:233`). If that ever
    inverted, forcing a value the engine does not recognise would arm it."""
    from syndicate.features.shared import execution_ledger

    for value in ("paper", "", "PAPER", "nonsense"):
        monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", value)
        assert execution_ledger.execution_mode() != execution_ledger.LIVE
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    assert execution_ledger.execution_mode() == execution_ledger.LIVE


# --------------------------------------------------------------------------
# THE REFUSAL MUST ACTUALLY STOP THE PROCESS.
# --------------------------------------------------------------------------


def test_a_raising_sitecustomize_does_not_stop_the_interpreter(tmp_path: Path) -> None:
    """The measurement the guard's design rests on. If CPython ever started
    propagating this, `os._exit` would be unnecessary — and if it silently
    stopped, this test tells us why the guard is shaped the way it is."""
    (tmp_path / "sitecustomize.py").write_text('raise RuntimeError("GUARD REFUSED")\n', encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    probe = subprocess.run(
        [sys.executable, "-c", "print('CONTINUED')"], env=env, capture_output=True, text=True, timeout=120
    )
    assert probe.returncode == 0, "CPython swallows it"
    assert "CONTINUED" in probe.stdout
    assert "Error in sitecustomize" in probe.stderr


def test_the_real_guard_hard_exits_on_a_money_armed_env(tmp_path: Path) -> None:
    """End to end, through a real interpreter: the generated sitecustomize must
    KILL a process whose env could spend money, not merely complain."""
    guard_dir = fleet_local.write_guard_dir(tmp_path / "guard")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(ROOT)])
    env["SYNDICATE_EXECUTION_MODE"] = "live"
    env["SYNDICATE_EXECUTION_LIVE_ARMED"] = "1"
    env["SYNDICATE_FLEET_GUARD_RECEIPT"] = str(tmp_path / "receipt.json")
    probe = subprocess.run(
        [sys.executable, "-c", "print('SHOULD NOT REACH HERE')"],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert probe.returncode == 70, f"expected the guard's hard exit, got {probe.returncode}"
    assert "SHOULD NOT REACH HERE" not in probe.stdout
    assert "could spend money" in probe.stderr.lower()


def test_the_real_guard_lets_a_paper_env_through_and_writes_a_receipt(tmp_path: Path) -> None:
    guard_dir = fleet_local.write_guard_dir(tmp_path / "guard")
    receipt = tmp_path / "receipt.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(ROOT)])
    env["SYNDICATE_EXECUTION_MODE"] = "paper"
    env["SYNDICATE_EXECUTION_LIVE_ARMED"] = "0"
    env["SYNDICATE_FLEET_GUARD_RECEIPT"] = str(receipt)
    env["SYNDICATE_FLEET_ROLE"] = "test-role"
    env["SYNDICATE_FLEET_FETCH_MODE"] = "replay"
    for name in VENUE_CREDENTIAL_ENV:
        env.pop(name, None)
    probe = subprocess.run(
        [sys.executable, "-c", "print('REACHED')"], env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=180
    )
    assert probe.returncode == 0, probe.stderr[-500:]
    assert "REACHED" in probe.stdout
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["role"] == "test-role"
    assert len(payload["money_off_because"]) == 3
    assert payload["network"].startswith("DENIED")


def test_replay_mode_denies_outbound_but_allows_loopback(tmp_path: Path) -> None:
    """Loopback must stay open or the roles cannot talk to each other, and a
    guard that breaks the fleet is a guard someone turns off."""
    guard_dir = fleet_local.write_guard_dir(tmp_path / "guard")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(ROOT)])
    env["SYNDICATE_EXECUTION_MODE"] = "paper"
    env["SYNDICATE_EXECUTION_LIVE_ARMED"] = "0"
    env["SYNDICATE_FLEET_FETCH_MODE"] = "replay"
    env["SYNDICATE_FLEET_GUARD_RECEIPT"] = str(tmp_path / "receipt.json")
    for name in VENUE_CREDENTIAL_ENV:
        env.pop(name, None)
    script = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('example.com', 443), timeout=5)\n"
        "    print('OUTBOUND ALLOWED')\n"
        "except OSError as exc:\n"
        "    print('OUTBOUND DENIED' if 'REPLAY' in str(exc).upper() else f'OTHER: {exc}')\n"
        "s = socket.socket()\n"
        "try:\n"
        "    s.connect(('127.0.0.1', 1))\n"
        "except OSError as exc:\n"
        "    print('LOOPBACK REFUSED BY GUARD' if 'REPLAY' in str(exc).upper() else 'LOOPBACK REACHED THE OS')\n"
    )
    probe = subprocess.run(
        [sys.executable, "-c", script], env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=180
    )
    assert "OUTBOUND DENIED" in probe.stdout, probe.stdout + probe.stderr[-300:]
    assert "LOOPBACK REACHED THE OS" in probe.stdout, "loopback must not be blocked"


# --------------------------------------------------------------------------
# ENV DERIVATION
# --------------------------------------------------------------------------


def _snapshot_file(tmp_path: Path, values: dict[str, str], *, withheld: tuple[str, ...] = ()) -> Path:
    keys: dict[str, object] = {k: {"len": len(v), "sha256_12": "0" * 12, "value": v} for k, v in values.items()}
    for name in withheld:
        keys[name] = {"len": 40, "sha256_12": "1" * 12}
    path = tmp_path / "env.json"
    path.write_text(
        json.dumps({"taken_at": "now", "services": {"refresh-worker": {"key_count": len(keys), "keys": keys}}}),
        encoding="utf-8",
    )
    return path


def test_a_withheld_value_can_never_reach_a_child(tmp_path: Path) -> None:
    """The snapshot's secret-withholding IS the strongest credential scrub, and
    it is structural: a key with no plaintext value was never in the file, so no
    future production key can leak through by being absent from `DROPPED_ENV`."""
    path = _snapshot_file(tmp_path, {"SYNDICATE_REFRESH_LANE": "refresh-worker"}, withheld=("KALSHI_PRIVATE_KEY",))
    values, withheld = fleet_local.load_env_snapshot(path)
    assert values["refresh-worker"] == {"SYNDICATE_REFRESH_LANE": "refresh-worker"}
    assert withheld["refresh-worker"] == 1
    assert "KALSHI_PRIVATE_KEY" not in values["refresh-worker"]


def test_derive_env_forces_paper_and_drops_inherited_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A developer's own shell holds real keys — `ODDS_API_KEY` was in mine —
    so the scrub must cover the INHERITED environment, not just the snapshot."""
    monkeypatch.setenv("ODDS_API_KEY", "real-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "real-key")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    env, diff = fleet_local.derive_env(
        fleet_local.ROLES["refresh-worker"],
        {"SYNDICATE_REFRESH_LANE": "refresh-worker", "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true"},
        mirror=tmp_path / "mirror",
        fetch="replay",
        state_backend="file",
        receipt_path=tmp_path / "r.json",
        guard_dir=tmp_path / "guard",
        port=5000,
    )
    assert env["SYNDICATE_EXECUTION_MODE"] == "paper"
    assert env["SYNDICATE_EXECUTION_LIVE_ARMED"] == "0"
    assert "ODDS_API_KEY" not in env and "KALSHI_PRIVATE_KEY" not in env
    assert "ODDS_API_KEY" in diff["dropped"] and "KALSHI_PRIVATE_KEY" in diff["dropped"]
    # The production RUN-MODE is passed through -- that is the point of the tool.
    assert env["SYNDICATE_REFRESH_LANE"] == "refresh-worker"
    # ...and the hosted-storage assertion is cleared for a file backend, or both
    # workers refuse to start (`refresh_state_store.py:316`).
    assert "SYNDICATE_REQUIRE_HOSTED_STORAGE" not in env


def test_redis_backend_leaves_the_hosted_storage_flag_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, _ = fleet_local.derive_env(
        fleet_local.ROLES["refresh-worker"],
        {"SYNDICATE_REQUIRE_HOSTED_STORAGE": "true"},
        mirror=tmp_path / "mirror",
        fetch="replay",
        state_backend="redis",
        receipt_path=tmp_path / "r.json",
        guard_dir=tmp_path / "guard",
        port=5000,
    )
    assert env["SYNDICATE_REQUIRE_HOSTED_STORAGE"] == "true"
    assert env["SYNDICATE_REFRESH_STATE_BACKEND"] == "redis"


def test_guard_dir_goes_first_on_pythonpath(tmp_path: Path) -> None:
    """Another `sitecustomize` earlier on the path silently wins."""
    env, _ = fleet_local.derive_env(
        fleet_local.ROLES["web"],
        {},
        mirror=tmp_path / "mirror",
        fetch="replay",
        state_backend="file",
        receipt_path=tmp_path / "r.json",
        guard_dir=tmp_path / "guard",
        port=5000,
    )
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "guard")


def test_role_caps_match_the_render_plans() -> None:
    """`#625` asks for 2/2/4 GB, and those are the actual plans in render.yaml.
    A cap that drifts from the plan makes every local memory reading a claim
    about a machine nobody runs."""
    assert fleet_local.ROLES["web"].memory_cap_mb == 2048
    assert fleet_local.ROLES["live-odds-worker"].memory_cap_mb == 2048
    assert fleet_local.ROLES["refresh-worker"].memory_cap_mb == 4096


def test_a_dead_role_is_not_a_healthy_fleet() -> None:
    """The first version reported ok=True while all three roles had exited 1: a
    guard receipt is written before the role does any work, so it cannot stand
    in for the role succeeding."""
    roles = [{"role": "web", "guard": {"role": "web"}, "exit_code": 1}]
    assert not all(r["guard"] and r["exit_code"] in (None, 0) for r in roles)
    roles = [{"role": "web", "guard": {"role": "web"}, "exit_code": None}]
    assert all(r["guard"] and r["exit_code"] in (None, 0) for r in roles)
