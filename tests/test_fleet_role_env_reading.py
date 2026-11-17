"""`scripts/fleet_role_env_reading.py`: the before/after reading across a drained down/up."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import fleet_role_env_reading as fre
from syndicate.features.shared import service_identity as si


def _fleet(root: Path, supervisor: int, roles: dict[str, tuple[int, dict[str, str]]]) -> Path:
    home = root / "home"
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "supervisor.json").write_text(json.dumps(
        {"supervisor_pid": supervisor, "roles": {r: pid for r, (pid, _) in roles.items()}}), encoding="utf-8")
    for _role, (pid, env) in roles.items():
        d = root / "proc" / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0")
    return home


OLD = {"RENDER": "true", "RENDER_SERVICE_NAME": "local-{r}", "RENDER_SERVICE_ID": "local-{r}",
       "RENDER_INSTANCE_ID": "local-{r}-1", "RENDER_GIT_COMMIT": "aaa", "KALSHI_API_KEY_ID": "secret", "X": "1"}
NEW = {"SYNDICATE_HOSTED": "true", "SYNDICATE_SERVICE_NAME": "local-{r}", "SYNDICATE_SERVICE_ID": "local-{r}",
       "SYNDICATE_INSTANCE_ID": "local-{r}-2", "SYNDICATE_GIT_COMMIT": "bbb", "KALSHI_API_KEY_ID": "secret", "X": "1"}


def _env(template: dict[str, str], role: str, **override) -> dict[str, str]:
    env = {k: v.replace("{r}", role) for k, v in template.items()}
    env.update(override)
    return env


def _run(tmp_path, after_template, capsys, *flags, before=None, **override):
    before_home = _fleet(tmp_path / "b", 10, {r: (100 + i, _env(before or OLD, r)) for i, r in enumerate(fre.ROLES)})
    snap = tmp_path / "before.json"
    assert fre.main(["--home", str(before_home), "--proc-root", str(tmp_path / "b" / "proc"), "snapshot", "--out", str(snap)]) == 0
    after_home = _fleet(tmp_path / "a", 11, {r: (200 + i, _env(after_template, r, **override)) for i, r in enumerate(fre.ROLES)})
    rc = fre.main(["--home", str(after_home), "--proc-root", str(tmp_path / "a" / "proc"), "compare", "--before", str(snap), *flags])
    return rc, capsys.readouterr().out, json.loads(snap.read_text(encoding="utf-8"))


def test_the_step3_load_reads_as_expected_only(tmp_path, capsys) -> None:
    rc, out, snap = _run(tmp_path, NEW, capsys, "--render-markers-step3")
    assert rc == fre.EXIT_OK, out
    assert "secret" not in out and "secret" not in json.dumps(snap)  # hashes and names only
    assert "COMPARE: OK" in out


def test_a_step2_only_load_also_reads_as_expected(tmp_path, capsys) -> None:
    both = dict(OLD)
    both.update(NEW)
    rc, out, _ = _run(tmp_path, both, capsys, "--render-markers-step3")
    assert rc == fre.EXIT_OK, out


def test_an_unrelated_change_is_flagged(tmp_path, capsys) -> None:
    rc, out, _ = _run(tmp_path, NEW, capsys, "--render-markers-step3", X="2")
    assert rc == fre.EXIT_UNEXPECTED and "~X" in out


def test_a_moved_stable_twin_is_flagged(tmp_path, capsys) -> None:
    rc, out, _ = _run(tmp_path, NEW, capsys, "--render-markers-step3", SYNDICATE_SERVICE_NAME="local-other")
    assert rc == fre.EXIT_UNEXPECTED and "SYNDICATE_SERVICE_NAME" in out


def test_a_lost_marker_is_flagged(tmp_path, capsys) -> None:
    lost = {k: v for k, v in NEW.items() if k != "SYNDICATE_HOSTED"}
    rc, out, _ = _run(tmp_path, lost, capsys, "--render-markers-step3")
    assert rc == fre.EXIT_UNEXPECTED and "SYNDICATE_HOSTED" in out


def test_no_up_in_between_reads_as_no_change(tmp_path, capsys) -> None:
    # Measured on the fleet 2026-11-17: a snapshot then a compare with no `up` between them
    # must not cry wolf about markers the old launcher never set.
    rc, out, _ = _run(tmp_path, OLD, capsys)
    assert rc == fre.EXIT_OK, out


def test_strict_by_default_after_step3b(tmp_path, capsys) -> None:
    """Since step 3b the one-time RENDER* -> SYNDICATE_* transition is NOT expected unless
    asked for: a later `up` that dropped or renamed markers must read as a change."""
    rc, out, _ = _run(tmp_path, NEW, capsys)
    assert rc == fre.EXIT_UNEXPECTED and "-RENDER" in out and "+SYNDICATE_HOSTED" in out


def test_wsl_interop_changes_on_every_up(tmp_path, capsys) -> None:
    # Measured 2026-11-17 21:53Z: WSL's per-launch interop socket path changed across a
    # scheduled-task `up` and nothing else did.
    before = dict(OLD, WSL_INTEROP="/run/WSL/1_interop")
    rc, out, _ = _run(tmp_path, before, capsys, before=before, WSL_INTEROP="/run/WSL/999_interop")
    assert rc == fre.EXIT_OK, out
    assert "changed=['WSL_INTEROP']" in out


def test_marker_table_is_the_transition_that_was_loaded() -> None:
    assert set(fre.MARKERS) == set(si.SERVICE_MARKERS) - {"SYNDICATE_GIT_BRANCH"}
    assert fre.MARKERS == {
        "SYNDICATE_HOSTED": "RENDER", "SYNDICATE_SERVICE_NAME": "RENDER_SERVICE_NAME",
        "SYNDICATE_SERVICE_ID": "RENDER_SERVICE_ID", "SYNDICATE_INSTANCE_ID": "RENDER_INSTANCE_ID",
        "SYNDICATE_GIT_COMMIT": "RENDER_GIT_COMMIT", "SYNDICATE_EXTERNAL_URL": "RENDER_EXTERNAL_URL",
    }
