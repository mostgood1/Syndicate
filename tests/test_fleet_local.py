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
# PRODUCTION IS ON THIS MACHINE: the fleet's ports and data root
# (lane fleet-local-env-source, 2026-11-17). Measured before the fix: a guarded
# replay child CONNECTED to 127.0.0.1:10000 and :6379 and resolved its web base
# URL to the fleet.
# --------------------------------------------------------------------------


def test_fleet_ports_are_the_fleets_own_defaults() -> None:
    """The guard spells the ports out (it runs in every child's startup); this
    pins them to the fleet's own settings, so a moved port fails here."""
    from scripts import local_production as lp
    from scripts._fleet_guard import FLEET_PORTS, url_port

    defaults = lp.Settings(home=Path("."))
    assert set(FLEET_PORTS) == {defaults.port, url_port(defaults.redis_url)}


def _guarded_env(tmp_path: Path, fetch: str) -> dict[str, str]:
    guard_dir = fleet_local.write_guard_dir(tmp_path / "guard")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(ROOT)])
    env["SYNDICATE_EXECUTION_MODE"] = "paper"
    env["SYNDICATE_EXECUTION_LIVE_ARMED"] = "0"
    env["SYNDICATE_FLEET_FETCH_MODE"] = fetch
    env["SYNDICATE_FLEET_GUARD_RECEIPT"] = str(tmp_path / "receipt.json")
    for name in VENUE_CREDENTIAL_ENV + ("SYNDICATE_DATA_ROOT", "SYNDICATE_REPORTS_ROOT", "SYNDICATE_REFRESH_STATE_URL",
                                        "REDIS_URL", "SYNDICATE_KEYVALUE_URL"):
        env.pop(name, None)
    return env


@pytest.mark.parametrize("fetch", ["replay", "live"])
def test_the_fleets_ports_are_denied_in_every_fetch_mode(tmp_path: Path, fetch: str) -> None:
    """`--fetch live` opts into upstream data, never into production. The guard
    raises BEFORE the connect, so this sends nothing to the fleet even when it
    is up -- and if the guard regressed, the child would only open and close a
    TCP connection."""
    env = _guarded_env(tmp_path, fetch)
    probe = subprocess.run(
        [sys.executable, "-c", fleet_local._FLEET_PORT_PROBE, "10000", "6379"],
        env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert probe.returncode == 0, probe.stderr[-500:]
    assert "10000 GUARD" in probe.stdout and "6379 GUARD" in probe.stdout, probe.stdout


@pytest.mark.parametrize(
    "key,value",
    [
        ("SYNDICATE_DATA_ROOT", "/home/someone/syndicate-prod/data"),
        ("SYNDICATE_REPORTS_ROOT", "C:\\Users\\x\\AppData\\Local\\SyndicateProd\\data\\reports"),
        ("SYNDICATE_REFRESH_STATE_URL", "redis://127.0.0.1:6379/0"),
        ("REDIS_URL", "redis://172.20.0.5:6379/1"),
    ],
)
def test_guard_refuses_a_production_root_or_state_store(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    from scripts._fleet_guard import assert_not_production

    for name in ("SYNDICATE_DATA_ROOT", "SYNDICATE_REPORTS_ROOT", "SYNDICATE_REFRESH_STATE_URL", "REDIS_URL",
                 "SYNDICATE_KEYVALUE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert len(assert_not_production()) == 2
    monkeypatch.setenv(key, value)
    with pytest.raises(FleetGuardRefused):
        assert_not_production()


def test_the_real_guard_hard_exits_on_a_fleet_data_root(tmp_path: Path) -> None:
    env = _guarded_env(tmp_path, "replay")
    env["SYNDICATE_DATA_ROOT"] = str(Path.home() / "syndicate-prod" / "data")
    probe = subprocess.run(
        [sys.executable, "-c", "print('SHOULD NOT REACH HERE')"], env=env, cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    assert probe.returncode == 71, probe.stderr[-500:]
    assert "SHOULD NOT REACH HERE" not in probe.stdout
    assert "could write to production" in probe.stderr.lower()


@pytest.mark.parametrize("raw", ["/home/someone/syndicate-prod/data", "/home/someone/syndicate-prod/data/mlb"])
def test_a_mirror_inside_a_fleet_home_is_refused(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setattr("scripts.mirror_manifest.mirror_root", lambda explicit=None: Path(raw))
    with pytest.raises(SystemExit) as excinfo:
        fleet_local.rehearsal_mirror(raw)
    assert "fleet" in str(excinfo.value).lower()


@pytest.mark.parametrize("port,redis_url", [(10000, None), (6379, None), (5000, "redis://127.0.0.1:6379/3")])
def test_the_fleets_ports_are_refused_as_arguments(port: int, redis_url: str | None) -> None:
    with pytest.raises(SystemExit):
        fleet_local.check_ports(port, redis_url)


# --------------------------------------------------------------------------
# THE CREDENTIAL-FREE SNAPSHOT. Its producer until 2026-11-15 read Render
# (`snapshot_render_env.py`, retired); every `doctor`/`up` then exited at
# "no env snapshot". Now `snapshot` copies the fleet's own fleet_env/.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value,allowed",
    [
        ("SYNDICATE_ENABLE_X_AUTORUN", "true", True),
        ("SYNDICATE_PORTFOLIO_AUTH_REQUIRED", "false", True),  # no credential is spelled false
        ("SYNDICATE_REFRESH_LANE", "refresh-worker", True),  # a run-mode string: the reason to snapshot
        ("SYNDICATE_ACTIVE_SPORTS", "mlb,nba,nhl,ncaab", True),
        ("SYNDICATE_DATA_ROOT", "{data_root}", True),
        ("MLB_LIVE_LENS_DIR", "{data_root}/mlb_source/live_lens", True),
        ("SYNDICATE_MLB_SIM_MAX_GAMES", "15", True),
        ("ADMIN_TOKEN", "1234567890", False),  # the 2026-09 leak: a NUMBER under a secret name
        ("SYNDICATE_PORTFOLIO_USERNAME", "someone", False),
        ("SYNDICATE_PORTFOLIO_PASSWORD_HASH", "pbkdf2:sha256:600000$abc$def", False),
        ("SYNDICATE_REFRESH_STATE_URL", "redis://127.0.0.1:6379/0", False),
        ("SOME_PLAIN_SETTING", "9f2c4e1b7a3d5f60e8c2b4a6d8f0e1c3", False),  # key-shaped value, plain name
        ("SOME_PLAIN_SETTING", "x" * 600, False),
        ("ODDS_API_KEY", "true", False),  # a dropped key is never recorded, whatever its value
        ("KALSHI_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...", False),
    ],
)
def test_rehearsal_value_allowed_is_shape_and_name(key: str, value: str, allowed: bool) -> None:
    assert fleet_local.rehearsal_value_allowed(key, value) is allowed


SECRET_VALUES = {
    "KALSHI_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7s3cr3tK3yM4t3r1al\n-----END",
    "ADMIN_TOKEN": "8675309421",
    "SYNDICATE_PORTFOLIO_PASSWORD": "hunter2-correct-horse",
    "ODDS_API_KEY": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
}


def _fleet_home(tmp_path: Path) -> Path:
    home = tmp_path / "syndicate-home"
    for role in ("web", "refresh-worker", "live-odds-worker"):
        values = {
            "SYNDICATE_REFRESH_LANE": role,
            "SYNDICATE_ENABLE_SOMETHING_AUTORUN": "true",
            "SYNDICATE_EXECUTION_MODE": "live",
            "MLB_LIVE_LENS_DIR": "{data_root}/mlb_source/live_lens",
            **SECRET_VALUES,
        }
        path = home / "fleet_env" / f"{role}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"role": role, "snapshot_taken_at": "2026-10-01T01:11:31Z", "values": values}),
                        encoding="utf-8")
    return home


def test_snapshot_writes_no_secret_and_records_withheld_names_only(tmp_path: Path) -> None:
    home = _fleet_home(tmp_path)
    out = tmp_path / "rehearsal_env"
    summary = fleet_local.write_rehearsal_snapshot(home, out)
    for role in ("web", "refresh-worker", "live-odds-worker"):
        text = (out / "fleet_env" / f"{role}.json").read_text(encoding="utf-8")
        for secret in SECRET_VALUES.values():
            assert secret not in text and json.dumps(secret)[1:-1] not in text
        payload = json.loads(text)
        assert payload["redacted_by"] == fleet_local.REHEARSAL_MARK
        assert payload["snapshot_taken_at"] == "2026-10-01T01:11:31Z"
        assert set(payload["withheld"]) == set(SECRET_VALUES)
        assert "sha256" not in text, "no hash either: a ten-digit token's hash reverses in seconds"
        assert payload["values"]["SYNDICATE_REFRESH_LANE"] == role
        assert summary[role]["kept"] == 4


def test_snapshot_refuses_a_rehearsal_copy_as_its_source(tmp_path: Path) -> None:
    out = tmp_path / "rehearsal_env"
    fleet_local.write_rehearsal_snapshot(_fleet_home(tmp_path), out)
    with pytest.raises(SystemExit):
        fleet_local.write_rehearsal_snapshot(out, tmp_path / "again")


def test_doctor_and_up_refuse_the_fleets_own_fleet_env(tmp_path: Path) -> None:
    """The live fleet_env/ holds every credential in plaintext. Pointing the
    rehearsal at it must refuse, not filter."""
    home = _fleet_home(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        fleet_local.load_rehearsal_env(home)
    assert "live credentials" in str(excinfo.value)


def test_a_render_era_snapshot_file_is_refused_with_its_history(tmp_path: Path) -> None:
    old = tmp_path / "env_20261001T234655Z.json"
    old.write_text(json.dumps({"services": {"web": {"keys": {}}}}), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        fleet_local.load_rehearsal_env(old)
    assert "snapshot_render_env.py" in str(excinfo.value)


def test_load_reapplies_the_rule_to_a_tampered_file(tmp_path: Path) -> None:
    out = tmp_path / "rehearsal_env"
    fleet_local.write_rehearsal_snapshot(_fleet_home(tmp_path), out)
    path = out / "fleet_env" / "live-odds-worker.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["values"]["KALSHI_PRIVATE_KEY"] = SECRET_VALUES["KALSHI_PRIVATE_KEY"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = fleet_local.load_rehearsal_env(out)
    assert "KALSHI_PRIVATE_KEY" not in loaded["live-odds-worker"].values
    assert loaded["live-odds-worker"].rewithheld == ["KALSHI_PRIVATE_KEY"]


# --------------------------------------------------------------------------
# ENV DERIVATION: the fleet's own `local_production.derive_role_env`, then the
# rehearsal overrides.
# --------------------------------------------------------------------------


def _derive(tmp_path: Path, role: str, snapshot: dict[str, str], **kwargs):
    params = dict(
        mirror=tmp_path / "mirror",
        fetch="replay",
        state_backend="file",
        receipt_path=tmp_path / "r.json",
        guard_dir=tmp_path / "guard",
        port=5000,
    )
    params.update(kwargs)
    return fleet_local.derive_env(fleet_local.ROLES[role], snapshot, **params)


def test_derive_env_forces_paper_and_drops_inherited_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A developer's own shell holds real keys -- `ODDS_API_KEY` is in this
    machine's -- so the scrub must cover the INHERITED environment too."""
    monkeypatch.setenv("ODDS_API_KEY", "real-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "real-key")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    env, diff = _derive(tmp_path, "refresh-worker",
                        {"SYNDICATE_REFRESH_LANE": "refresh-worker", "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true"})
    assert env["SYNDICATE_EXECUTION_MODE"] == "paper"
    assert env["SYNDICATE_EXECUTION_LIVE_ARMED"] == "0"
    assert env["SYNDICATE_EXECUTION_ENABLED"] == "0"
    assert "ODDS_API_KEY" not in env and "KALSHI_PRIVATE_KEY" not in env
    assert "ODDS_API_KEY" in diff["dropped"] and "KALSHI_PRIVATE_KEY" in diff["dropped"]
    # The fleet's RUN-MODE is passed through -- that is the point of the tool.
    assert env["SYNDICATE_REFRESH_LANE"] == "refresh-worker"
    # ...and the hosted-storage assertion is cleared for a file backend, or both
    # workers refuse to start (`assert_refresh_state_backend_ready`).
    assert "SYNDICATE_REQUIRE_HOSTED_STORAGE" not in env
    assert "SYNDICATE_HOSTED" not in env


def test_derive_env_is_the_fleets_construction(tmp_path: Path) -> None:
    """Spec -> snapshot -> forced, through local_production itself: a declared
    key arrives with no snapshot, a snapshot value beats the declaration, a
    `{data_root}` path lands in the mirror, and the fleet's markers are set so
    web serves instead of starting its own board builder."""
    from scripts import local_production as lp

    spec = lp.load_role_spec()
    declared = {item.key: item.value for item in spec["refresh-worker"] if item.source == "value"}
    env, diff = _derive(tmp_path, "refresh-worker",
                        {"MLB_LIVE_LENS_DIR": "{data_root}/mlb_source/live_lens", "SYNDICATE_REFRESH_LANE": "x-override"})
    skip = {"SYNDICATE_REFRESH_LANE", "SYNDICATE_REQUIRE_HOSTED_STORAGE", "SYNDICATE_REFRESH_STATE_BACKEND"}
    for key, value in declared.items():
        if "{" in str(value) or key in fleet_local.DROPPED_ENV or key in fleet_local.FORCED_ENV_BASE or key in skip:
            continue
        if key in fleet_local.MIRROR_BOUND_ENV:
            continue
        assert env.get(key) == value, key
    assert env["SYNDICATE_REFRESH_LANE"] == "x-override"
    assert env["MLB_LIVE_LENS_DIR"] == str((tmp_path / "mirror").joinpath("mlb_source", "live_lens"))
    assert env["SYNDICATE_DATA_ROOT"] == str(tmp_path / "mirror")
    assert env["SYNDICATE_SERVICE_ID"] == "local-refresh-worker"
    assert env["SYNDICATE_INSTANCE_ID"].startswith("rehearsal-refresh-worker-")
    assert env["SYNDICATE_LOCAL_PRODUCTION"] == "1"
    assert env["SYNDICATE_LOCAL_MEMORY_LIMIT_MB"] == "4096"
    assert env["SYNDICATE_REFRESH_STATE_BACKEND"] == "filesystem"
    assert diff["declared"] == len(spec["refresh-worker"])


def test_the_workers_web_url_is_this_runs_web_never_the_fleet(tmp_path: Path) -> None:
    """Before: unset, so `_base_url` fell back to the fleet's 127.0.0.1:10000."""
    env, _ = _derive(tmp_path, "live-odds-worker", {}, port=5123)
    for key in ("SYNDICATE_INTERNAL_WEB_BASE_URL", "SYNDICATE_WNBA_LIVE_BOX_BASE_URL", "SYNDICATE_BASE_URL"):
        assert env[key] == "http://127.0.0.1:5123", key


def test_derive_env_never_reads_local_production_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """local_production.env holds the live keys and the live arm."""
    from scripts import local_production as lp

    def _refuse(*_a, **_k):
        raise AssertionError("fleet_local read local_production.env")

    monkeypatch.setattr(lp, "parse_env_file", _refuse)
    _derive(tmp_path, "web", {})


def test_inherited_syndicate_keys_do_not_set_a_run_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fleet's supervisor has none; a developer's shell value would change
    a run-mode that no fleet layer set."""
    monkeypatch.setenv("SYNDICATE_ENABLE_SHELL_ONLY_AUTORUN", "1")
    env, diff = _derive(tmp_path, "refresh-worker", {})
    assert "SYNDICATE_ENABLE_SHELL_ONLY_AUTORUN" not in env
    assert "SYNDICATE_ENABLE_SHELL_ONLY_AUTORUN" in diff["stripped_inherited"]


def test_a_per_sport_root_outside_the_mirror_is_dropped(tmp_path: Path) -> None:
    """These silently win over SYNDICATE_DATA_ROOT. Inside the mirror (the
    fleet's own `{data_root}` layout) they are kept; anywhere else, dropped."""
    env, diff = _derive(tmp_path, "web", {
        "NHL_LIVE_LENS_DIR": "./data/nhl_source/live_lens",  # checkout-relative, as the fleet's are
        "MLB_LIVE_LENS_DIR": "{data_root}/mlb_source/live_lens",
    })
    assert "NHL_LIVE_LENS_DIR" not in env and "NHL_LIVE_LENS_DIR" in diff["dropped_outside_mirror"]
    assert env["MLB_LIVE_LENS_DIR"].startswith(str(tmp_path / "mirror"))


def test_redis_backend_needs_a_rehearsal_redis(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _derive(tmp_path, "refresh-worker", {}, state_backend="redis")
    with pytest.raises(SystemExit):
        _derive(tmp_path, "refresh-worker", {}, state_backend="redis", redis_url="redis://127.0.0.1:6379/0")
    env, _ = _derive(tmp_path, "refresh-worker", {"SYNDICATE_REQUIRE_HOSTED_STORAGE": "true"},
                     state_backend="redis", redis_url="redis://127.0.0.1:6390/0")
    assert env["SYNDICATE_REQUIRE_HOSTED_STORAGE"] == "true"
    assert env["SYNDICATE_REFRESH_STATE_BACKEND"] == "keyvalue"
    assert env["SYNDICATE_REFRESH_STATE_URL"] == "redis://127.0.0.1:6390/0"
    assert "SYNDICATE_HOSTED" not in env


def test_file_backend_names_no_state_url(tmp_path: Path) -> None:
    env, _ = _derive(tmp_path, "web", {})
    assert "SYNDICATE_REFRESH_STATE_URL" not in env and "REDIS_URL" not in env


def test_guard_dir_goes_first_on_pythonpath(tmp_path: Path) -> None:
    """Another `sitecustomize` earlier on the path silently wins -- the fleet's
    own log-stamp one is on this PYTHONPATH too."""
    env, _ = _derive(tmp_path, "web", {})
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "guard")


def test_role_commands_are_the_fleets(tmp_path: Path) -> None:
    from scripts import local_production as lp

    env, _ = _derive(tmp_path, "refresh-worker", {})
    command, _ = fleet_local.role_command(fleet_local.ROLES["refresh-worker"], env, port=5000, bounded=True)
    fleet_command, _ = lp.role_command("refresh-worker", env, lp.Settings(home=Path(".")))
    assert command == fleet_command + ["--run-once"]
    web, _ = fleet_local.role_command(fleet_local.ROLES["web"], env, port=5000, bounded=True)
    assert "--run-once" not in web and any("5000" in part for part in web)


def test_role_caps_are_the_fleets_defaults() -> None:
    """`#625` asks for 2/2/4 GB: the fleet's own per-role defaults. A cap that
    drifts from them makes every local memory reading a claim about a machine
    nobody runs."""
    from scripts import local_production as lp

    for name, role in fleet_local.ROLES.items():
        assert role.memory_cap_mb == lp.PLAN_MEMORY_MB[name]
    assert fleet_local.ROLES["refresh-worker"].memory_cap_mb == 4096
    assert not hasattr(fleet_local.ROLES["web"], "render_plan")


def test_no_render_era_input_is_left() -> None:
    text = (ROOT / "scripts" / "fleet_local.py").read_text(encoding="utf-8")
    assert "render_plan" not in text
    assert "render.yaml" not in text


def test_a_dead_role_is_not_a_healthy_fleet() -> None:
    """The first version reported ok=True while all three roles had exited 1: a
    guard receipt is written before the role does any work, so it cannot stand
    in for the role succeeding."""
    roles = [{"role": "web", "guard": {"role": "web"}, "exit_code": 1}]
    assert not all(r["guard"] and r["exit_code"] in (None, 0) for r in roles)
    roles = [{"role": "web", "guard": {"role": "web"}, "exit_code": None}]
    assert all(r["guard"] and r["exit_code"] in (None, 0) for r in roles)
