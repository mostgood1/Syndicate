"""The nightly off-disk archive: staged outside OneDrive, retried once.

2026-10-30: the 09:21Z archive into OneDrive/SyndicateBackup failed mid-write
(`gzip: stdout: Cannot allocate memory`), the first write after the OneDrive
client resumed syncing; a re-run of the same snapshot at 15:19Z succeeded.
These tests drive `archive_offdisk` with a fake `tar`, so they run without tar
or rsync, and check the wiring from `cmd_backup` first (reachability).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import local_production as lp


def _fake_tar(calls: list[Path], outcomes: list[int]):
    """A subprocess.run stand-in: records where each tar write went and writes a
    small file there, or fails with the 2026-10-30 error."""

    def run(command, capture_output=True, text=True, **kwargs):
        if command and command[0] == "git":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        out = Path(command[command.index("-cf") + 1])
        calls.append(out)
        rc = outcomes.pop(0) if outcomes else 0
        if rc == 0:
            out.write_bytes(b"archive")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        out.write_bytes(b"half")  # a failed write leaves a partial behind
        return subprocess.CompletedProcess(command, rc, stdout="", stderr="gzip: stdout: Cannot allocate memory\n")

    return run


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "backup" / "20261030T091501Z"
    (snap / "data").mkdir(parents=True)
    (snap / "manifest.json").write_text("{}", encoding="utf-8")
    return snap


@pytest.fixture(autouse=True)
def _no_staging_env(monkeypatch):
    monkeypatch.delenv("SYNDICATE_LOCAL_BACKUP_OFFDISK_STAGING_DIR", raising=False)


# --- reachability: cmd_backup hands the staging dir and the retry policy over ----


def test_cmd_backup_passes_staging_and_retries_to_the_archive(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    offdisk = tmp_path / "Users" / "u" / "OneDrive" / "SyndicateBackup"
    seen: dict = {}

    def fake_archive(snapshot, off, keep, **kwargs):
        seen.update(kwargs, offdisk=off, keep=keep)
        return {"ok": True, "path": str(off / "x.tar.gz"), "bytes": 1, "attempts": 1, "failures": [], "staging": None}

    monkeypatch.setattr(lp.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(lp.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, stdout="", stderr=""))
    monkeypatch.setattr(lp, "archive_offdisk", fake_archive)
    args = lp.parse_args(["--home", str(home), "--state", "file", "backup", "--dest", str(tmp_path / "backup"),
                          "--offdisk", str(offdisk)])
    assert lp.cmd_backup(args) == 0
    assert seen["offdisk"] == offdisk
    assert seen["staging"] == tmp_path / "Users" / "u" / "SyndicateBackup-staging"
    assert seen["retries"] == 1 and seen["retry_delay"] == 300.0


def test_backup_cli_retry_flags():
    args = lp.parse_args(["backup", "--offdisk-retries", "0", "--offdisk-retry-delay", "5"])
    assert (args.offdisk_retries, args.offdisk_retry_delay) == (0, 5.0)


# --- the staging default ---------------------------------------------------------


def test_staging_sits_beside_the_onedrive_folder():
    assert lp.default_offdisk_staging_dir({}, Path("/mnt/c/Users/u/OneDrive/SyndicateBackup")) == Path("/mnt/c/Users/u/SyndicateBackup-staging")
    assert lp.default_offdisk_staging_dir({}, Path("/mnt/c/Users/u/OneDrive - Contoso/Backups")) == Path("/mnt/c/Users/u/SyndicateBackup-staging")


def test_no_staging_outside_onedrive_and_override_wins():
    assert lp.default_offdisk_staging_dir({}, Path("/mnt/c/SyndicateBackup")) is None
    local = {"SYNDICATE_LOCAL_BACKUP_OFFDISK_STAGING_DIR": "/mnt/c/stage"}
    assert lp.default_offdisk_staging_dir(local, Path("/mnt/c/Users/u/OneDrive/SyndicateBackup")) == Path("/mnt/c/stage")


# --- archive_offdisk -------------------------------------------------------------


def test_staged_write_never_touches_offdisk_until_complete(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [0]))
    offdisk, staging = tmp_path / "OneDrive" / "SyndicateBackup", tmp_path / "SyndicateBackup-staging"
    result = lp.archive_offdisk(snapshot, offdisk, 2, staging=staging)
    assert result["ok"] and result["attempts"] == 1
    assert calls == [staging / "20261030T091501Z.tar.gz.partial"]
    assert [p.name for p in offdisk.iterdir()] == ["20261030T091501Z.tar.gz"]
    assert not list(staging.iterdir())


def test_without_staging_the_partial_is_written_in_offdisk(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [0]))
    offdisk = tmp_path / "offdisk"
    assert lp.archive_offdisk(snapshot, offdisk, 2)["ok"]
    assert calls == [offdisk / "20261030T091501Z.tar.gz.partial"]


def test_a_failed_write_is_retried_once_after_the_delay(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    slept: list[float] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [2, 0]))
    monkeypatch.setattr(lp.time, "sleep", slept.append)
    offdisk, staging = tmp_path / "OneDrive" / "SyndicateBackup", tmp_path / "stage"
    result = lp.archive_offdisk(snapshot, offdisk, 2, staging=staging, retries=1, retry_delay=300.0)
    assert result["ok"] and result["attempts"] == 2
    assert slept == [300.0]
    assert "Cannot allocate memory" in result["failures"][0]
    assert [p.name for p in offdisk.iterdir()] == ["20261030T091501Z.tar.gz"]


def test_gives_up_after_the_retries_and_leaves_no_partial(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [2, 2]))
    monkeypatch.setattr(lp.time, "sleep", lambda s: None)
    offdisk, staging = tmp_path / "OneDrive" / "SyndicateBackup", tmp_path / "stage"
    result = lp.archive_offdisk(snapshot, offdisk, 2, staging=staging, retries=1, retry_delay=0)
    assert not result["ok"] and result["attempts"] == 2 and result["rc"] == 2
    assert len(calls) == 2
    assert not list(offdisk.iterdir()) and not list(staging.iterdir())


def test_zero_retries_is_one_attempt(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [2]))
    monkeypatch.setattr(lp.time, "sleep", lambda s: pytest.fail("must not wait with retries=0"))
    assert not lp.archive_offdisk(snapshot, tmp_path / "offdisk", 2, retries=0)["ok"]
    assert len(calls) == 1


def test_cross_volume_staging_copies_in_under_the_partial_name(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [0]))
    offdisk, staging = tmp_path / "OneDrive" / "SyndicateBackup", tmp_path / "stage"
    real_rename = Path.rename

    def rename(self, target):
        if self.parent == staging:
            raise OSError(18, "Invalid cross-device link")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    result = lp.archive_offdisk(snapshot, offdisk, 2, staging=staging)
    assert result["ok"]
    assert [p.name for p in offdisk.iterdir()] == ["20261030T091501Z.tar.gz"]
    assert (offdisk / "20261030T091501Z.tar.gz").read_bytes() == b"archive"
    assert not list(staging.iterdir())


def test_rotation_and_stale_partials_with_staging(tmp_path, snapshot, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_tar(calls, [0]))
    offdisk, staging = tmp_path / "OneDrive" / "SyndicateBackup", tmp_path / "stage"
    offdisk.mkdir(parents=True)
    staging.mkdir()
    for name in ("20261028T091501Z.tar.gz", "20261029T091500Z.tar.gz"):
        (offdisk / name).write_bytes(b"old")
    (offdisk / "20261029T091500Z.tar.gz.partial").write_bytes(b"stale")
    (staging / "20261029T091500Z.tar.gz.partial").write_bytes(b"stale")
    assert lp.archive_offdisk(snapshot, offdisk, 2, staging=staging)["ok"]
    assert sorted(p.name for p in offdisk.iterdir()) == ["20261029T091500Z.tar.gz", "20261030T091501Z.tar.gz"]
    assert not list(staging.iterdir())
