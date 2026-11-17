"""`scripts/fleet_env_snapshot.py`: the one-way move of each role's env snapshot from
`<home>/render_env/` to `<home>/fleet_env/` (lane `render-config-retirement`, 2026-11-17).

The property that matters: for EVERY value, the launcher's expansion of the migrated value
equals the retired `/opt/render` rewrite of the original. Then the snapshot layer of every
role's env is unchanged by the move, byte for byte.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from scripts import fleet_env_snapshot as fes
from scripts import local_production as lp

_DATA, _SRC = "/opt/render/project/data", "/opt/render/project/src"


def _legacy_rewrite(value: str, *, data_root: Path) -> str:
    """`local_production.rewrite_path` as it was at origin/main 3179b1ff1."""
    if value == _DATA or value.startswith(_DATA + "/"):
        tail = value[len(_DATA):].lstrip("/")
        return str(data_root.joinpath(*tail.split("/")) if tail else data_root)
    if value == _SRC or value.startswith(_SRC + "/"):
        tail = value[len(_SRC):].lstrip("/")
        return str(lp.REPO_ROOT.joinpath(*tail.split("/")) if tail else lp.REPO_ROOT)
    return value


VALUES = [
    _DATA, _DATA + "/", _DATA + "/mlb_source", _DATA + "//double/slash", _DATA + "/a/b/c.json",
    _DATA + "_not_the_disk", _DATA + "x", "/opt/render/project", "/opt/render/other",
    _SRC, _SRC + "/scripts", "prefix " + _DATA, "", "true", "https://example.test/x", "{already}",
]


@pytest.mark.parametrize("value", VALUES)
def test_migrated_value_expands_to_the_legacy_rewrite(value: str, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    assert lp.expand_path(fes.to_placeholders(value), data_root=data_root) == _legacy_rewrite(value, data_root=data_root)


def test_only_the_rewritten_values_change() -> None:
    for value in VALUES:
        changed = fes.to_placeholders(value) != value
        assert changed == (value == _DATA or value.startswith(_DATA + "/") or value == _SRC or value.startswith(_SRC + "/"))


def _legacy_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "render_env").mkdir(parents=True)
    for role in fes.ROLES:
        payload = {"fetched_at": "2026-10-01T01:11:30Z", "service_id": "srv-abc", "pages": 2,
                   "values": {"SYNDICATE_DATA_ROOT": _DATA, "SYNDICATE_MLB_SOURCE_ROOT": _DATA + "/mlb_source",
                              "KALSHI_API_KEY_ID": "secret-" + role, "EMPTY": None, "N": "3"}}
        (home / "render_env" / f"{role}.json").write_text(json.dumps(payload), encoding="utf-8")
    return home


def test_migrate_writes_private_files_that_check_clean(tmp_path: Path, capsys) -> None:
    home = _legacy_home(tmp_path)
    assert fes.main(["migrate", "--home", str(home)]) == fes.EXIT_OK
    out = capsys.readouterr().out
    assert "secret-" not in out  # never prints a value
    for role in fes.ROLES:
        path = home / "fleet_env" / f"{role}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["role"] == role and doc["migrated_from"] == f"render_env/{role}.json"
        assert doc["snapshot_taken_at"] == "2026-10-01T01:11:30Z"
        assert "service_id" not in doc and "pages" not in doc
        assert doc["values"] == {"SYNDICATE_DATA_ROOT": "{data_root}", "SYNDICATE_MLB_SOURCE_ROOT": "{data_root}/mlb_source",
                                 "KALSHI_API_KEY_ID": "secret-" + role, "EMPTY": None, "N": "3"}
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        # The legacy file is left exactly as it was: the rollback for older checkouts.
        assert json.loads((home / "render_env" / f"{role}.json").read_text(encoding="utf-8"))["service_id"] == "srv-abc"
    assert fes.main(["check", "--home", str(home)]) == fes.EXIT_OK
    # A second run is a no-op.
    assert fes.main(["migrate", "--home", str(home)]) == fes.EXIT_OK
    assert "ALREADY MIGRATED" in capsys.readouterr().out


def test_launcher_env_from_migrated_snapshot_equals_the_legacy_layer(tmp_path: Path) -> None:
    home = _legacy_home(tmp_path)
    assert fes.main(["migrate", "--home", str(home)]) == fes.EXIT_OK
    settings = lp.Settings(home=home)
    for role in fes.ROLES:
        legacy = json.loads((home / "render_env" / f"{role}.json").read_text(encoding="utf-8"))["values"]
        expected = {k: _legacy_rewrite("" if v is None else str(v), data_root=settings.data_root) for k, v in legacy.items()}
        loaded = lp.load_env_snapshot(settings, role)
        assert {k: lp.expand_path(v, data_root=settings.data_root) for k, v in loaded.items()} == expected


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    home = _legacy_home(tmp_path)
    assert fes.main(["migrate", "--home", str(home), "--dry-run"]) == fes.EXIT_OK
    assert not (home / "fleet_env").exists()


def test_a_differing_target_is_never_overwritten(tmp_path: Path) -> None:
    home = _legacy_home(tmp_path)
    (home / "fleet_env").mkdir()
    (home / "fleet_env" / "web.json").write_text(json.dumps({"values": {"OTHER": "1"}}), encoding="utf-8")
    assert fes.main(["migrate", "--home", str(home)]) == fes.EXIT_REFUSED
    assert json.loads((home / "fleet_env" / "web.json").read_text(encoding="utf-8")) == {"values": {"OTHER": "1"}}
    assert not (home / "fleet_env" / "refresh-worker.json").exists()  # nothing partial
    assert fes.main(["check", "--home", str(home)]) == fes.EXIT_CHECK


def test_a_missing_legacy_file_refuses(tmp_path: Path) -> None:
    home = _legacy_home(tmp_path)
    (home / "render_env" / "web.json").unlink()
    assert fes.main(["migrate", "--home", str(home)]) == fes.EXIT_REFUSED
    assert not (home / "fleet_env").exists()
