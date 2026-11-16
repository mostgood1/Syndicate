"""`scripts/fleet_secrets_backup.py` -- the Render-free secrets backup (todo #766 D5, E1).

Most tests swap gpg for a reversible stub so they run anywhere; one real round trip runs
when `gpg` is on PATH (the fleet host has it) and is skipped otherwise. Nothing here reads
the real fleet home or a real passphrase.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("fleet_secrets_backup_under_test",
                                               REPO_ROOT / "scripts" / "fleet_secrets_backup.py")
fsb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fsb)

SECRET_VALUE = "sk-live-NEVER-PRINTED-1234567890"


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    home = tmp_path / "syndicate-prod"
    (home / "render_env").mkdir(parents=True)
    (home / "local_production.env").write_text(
        f"# comment\nADMIN_TOKEN={SECRET_VALUE}\nREFRESH_WORKER__FLAG=1\n"
        "SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR=/nowhere/offdisk\n", encoding="utf-8")
    (home / "render_env" / "web.json").write_text(
        json.dumps({"service_id": "srv-x", "values": {"ODDS_API_KEY": SECRET_VALUE, "B": "2"}}), encoding="utf-8")
    (home / "render_env" / "refresh-worker.json").write_text(
        json.dumps({"values": {"A": "1", "B": "2", "C": "3"}}), encoding="utf-8")
    return home


@pytest.fixture()
def passphrase(tmp_path: Path) -> Path:
    path = tmp_path / "pass"
    path.write_text("correct horse battery staple 42\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)
    return path


@pytest.fixture()
def fake_gpg(monkeypatch):
    """A reversible stand-in for gpg: base64 behind a marker, and it checks the args."""
    calls = []

    def fake(args, data):
        calls.append(list(args))
        assert "--passphrase-file" in args
        if "--symmetric" in args:
            assert "AES256" in args
            return b"FAKEGPG:" + base64.b64encode(data)
        assert "--decrypt" in args
        if not data.startswith(b"FAKEGPG:"):
            raise fsb.Refused(fsb.EXIT_GPG, "gpg rc=2: decryption failed")
        return base64.b64decode(data[len(b"FAKEGPG:"):])

    monkeypatch.setattr(fsb, "_gpg", fake)
    return calls


def test_backup_writes_one_encrypted_file_and_reads_it_back(home, passphrase, fake_gpg, tmp_path):
    out = tmp_path / "offdisk" / "secrets"
    report = fsb.do_backup(home, out, passphrase, keep=5)
    files = fsb.backups_in(out)
    assert [Path(report["path"])] == files and not list(out.glob("*.partial"))
    assert [row["path"] for row in report["files"]] == [
        "local_production.env", "render_env/refresh-worker.json", "render_env/web.json"]
    assert {row["path"]: row["keys"] for row in report["files"]} == {
        "local_production.env": 3, "render_env/refresh-worker.json": 3, "render_env/web.json": 2}
    # encrypt then the read-back decrypt: the file on disk was re-read.
    assert [("--symmetric" in c, "--decrypt" in c) for c in fake_gpg] == [(True, False), (False, True)]


def test_nothing_secret_is_printed(home, passphrase, fake_gpg, tmp_path, capsys):
    out = tmp_path / "out"
    assert fsb.main(["--home", str(home), "--passphrase-file", str(passphrase), "backup", "--out", str(out)]) == 0
    assert fsb.main(["--home", str(home), "--passphrase-file", str(passphrase), "verify", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert SECRET_VALUE not in printed and "correct horse" not in printed
    assert "ODDS_API_KEY" not in printed and "ADMIN_TOKEN" not in printed  # not even key names
    assert "same as live" in printed and "integrity ok" in printed


@pytest.mark.parametrize("break_it, code", [
    (lambda h, p: p.unlink(), fsb.EXIT_NO_PASSPHRASE),
    (lambda h, p: p.write_text("short", encoding="utf-8"), fsb.EXIT_NO_PASSPHRASE),
    (lambda h, p: (h / "local_production.env").unlink(), fsb.EXIT_REFUSED),
    (lambda h, p: shutil.rmtree(h / "render_env"), fsb.EXIT_REFUSED),
])
def test_refusals_write_nothing(home, passphrase, fake_gpg, tmp_path, break_it, code):
    break_it(home, passphrase)
    out = tmp_path / "out"
    rc = fsb.main(["--home", str(home), "--passphrase-file", str(passphrase), "backup", "--out", str(out)])
    assert rc == code
    assert not fsb.backups_in(out)
    assert fake_gpg == [], "nothing may be encrypted before the inputs are checked"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_a_group_readable_passphrase_is_refused(home, passphrase, fake_gpg, tmp_path):
    os.chmod(passphrase, 0o640)
    with pytest.raises(fsb.Refused) as caught:
        fsb.do_backup(home, tmp_path / "out", passphrase, keep=5)
    assert caught.value.code == fsb.EXIT_NO_PASSPHRASE and "chmod 600" in str(caught.value)


def test_a_backup_that_does_not_read_back_is_renamed_bad(home, passphrase, monkeypatch, tmp_path):
    monkeypatch.setattr(fsb, "_gpg", lambda args, data: b"garbage" if "--symmetric" in args else b"not a tar")
    out = tmp_path / "out"
    with pytest.raises(fsb.Refused) as caught:
        fsb.do_backup(home, out, passphrase, keep=5)
    assert caught.value.code == fsb.EXIT_VERIFY
    assert not fsb.backups_in(out), "a bad file must never look like the newest backup"
    assert len(list(out.glob("*.bad"))) == 1


def test_verify_reports_a_live_file_that_changed(home, passphrase, fake_gpg, tmp_path):
    report = fsb.do_backup(home, tmp_path / "out", passphrase, keep=5)
    (home / "local_production.env").write_text("ADMIN_TOKEN=rotated-later\n", encoding="utf-8")
    verdicts = {row["path"]: row["live"] for row in fsb.do_verify(home, Path(report["path"]), passphrase)["files"]}
    assert verdicts["local_production.env"] == "DIFFERS from live"
    assert verdicts["render_env/web.json"] == "same as live"


def test_a_tampered_archive_fails_integrity(home, passphrase, fake_gpg, tmp_path):
    files = fsb.secret_files(home)
    tar_bytes, _ = fsb.build_archive(files, home=home, now=fsb.dt.datetime.now(fsb.dt.timezone.utc))
    manifest, members = fsb.read_archive(tar_bytes)
    members["render_env/web.json"] = b"{}"
    assert fsb.integrity_problems(manifest, members) == ["render_env/web.json: content does not match its manifest hash"]


def test_restore_round_trip_and_its_refusals(home, passphrase, fake_gpg, tmp_path):
    backup = Path(fsb.do_backup(home, tmp_path / "out", passphrase, keep=5)["path"])
    target = tmp_path / "restored"
    fsb.do_restore(backup, target, passphrase, live_home=home)
    for name, path in fsb.secret_files(home):
        assert (target / name).read_bytes() == path.read_bytes()
        if os.name != "nt":
            assert stat.S_IMODE((target / name).stat().st_mode) == 0o600
    with pytest.raises(fsb.Refused, match="not empty"):
        fsb.do_restore(backup, target, passphrase, live_home=home)
    with pytest.raises(fsb.Refused, match="live home"):
        fsb.do_restore(backup, home, passphrase, live_home=home)


def test_retention_keeps_the_newest(home, passphrase, fake_gpg, tmp_path):
    out = tmp_path / "out"
    base = fsb.dt.datetime(2026, 11, 16, 9, 15, tzinfo=fsb.dt.timezone.utc)
    for day in range(3):
        fsb.do_backup(home, out, passphrase, keep=2, now=base + fsb.dt.timedelta(days=day))
    assert [p.name for p in fsb.backups_in(out)] == [
        "fleet-secrets-20261117T091500Z.tar.gpg", "fleet-secrets-20261118T091500Z.tar.gpg"]


def test_default_out_dir_follows_the_data_backups_offdisk_dir(home, monkeypatch):
    monkeypatch.delenv("SYNDICATE_SECRETS_BACKUP_DIR", raising=False)
    monkeypatch.delenv("SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR", raising=False)
    assert fsb.default_out_dir(home) == Path("/nowhere/offdisk") / "secrets"
    monkeypatch.setenv("SYNDICATE_SECRETS_BACKUP_DIR", "/explicit")
    assert fsb.default_out_dir(home) == Path("/explicit")


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not on PATH (the fleet host has it)")
def test_real_gpg_round_trip(home, passphrase, tmp_path, monkeypatch):
    """off != on for the real cipher: the file on disk is ciphertext, and it decrypts."""
    gnupg = tmp_path / "gnupg"
    gnupg.mkdir()
    if os.name != "nt":
        os.chmod(gnupg, 0o700)
    monkeypatch.setenv("GNUPGHOME", str(gnupg))
    out = tmp_path / "out"
    report = fsb.do_backup(home, out, passphrase, keep=5)
    blob = Path(report["path"]).read_bytes()
    assert SECRET_VALUE.encode() not in blob and b"ADMIN_TOKEN" not in blob
    rows = fsb.do_verify(home, Path(report["path"]), passphrase)
    assert rows["integrity"] == "ok" and {r["live"] for r in rows["files"]} == {"same as live"}
    wrong = tmp_path / "wrong"
    wrong.write_text("a different passphrase entirely", encoding="utf-8")
    if os.name != "nt":
        os.chmod(wrong, 0o600)
    with pytest.raises(fsb.Refused) as caught:
        fsb.do_verify(home, Path(report["path"]), wrong)
    assert caught.value.code == fsb.EXIT_GPG


# --- the nightly wiring: `local_production.py backup` -------------------------------


def _lp():
    spec = importlib.util.spec_from_file_location("local_production_secrets_under_test",
                                                  REPO_ROOT / "scripts" / "local_production.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("data_rc, secrets_rc, extra, want_rc, ran", [
    (0, 0, [], 0, True),
    (0, 3, [], 7, True),     # no passphrase yet: the job goes non-zero, so the watchdog WARNs
    (4, 0, [], 4, True),     # the data backup's failure wins
    (0, 0, ["--no-secrets"], 0, False),
    (0, 0, ["--no-offdisk"], 0, False),
])
def test_backup_subcommand_runs_the_secrets_step_after_the_data(tmp_path, monkeypatch, data_rc, secrets_rc,
                                                                extra, want_rc, ran):
    lp = _lp()
    home = tmp_path / "home"
    home.mkdir()
    args = lp.parse_args(["--home", str(home), "--state", "file", "backup", "--offdisk", str(tmp_path / "off"), *extra])
    assert args.func is lp.cmd_backup_and_secrets, "the subcommand must run the wrapper (reachability)"
    order, commands = [], []
    monkeypatch.setattr(lp, "cmd_backup", lambda a: order.append("data") or data_rc)

    def fake_run(command, *a, **k):
        order.append("secrets")
        commands.append(command)
        return SimpleNamespace(returncode=secrets_rc)

    monkeypatch.setattr(lp.subprocess, "run", fake_run)
    assert args.func(args) == want_rc
    assert order == (["data", "secrets"] if ran else ["data"])
    if ran:
        assert commands[0][1].endswith("fleet_secrets_backup.py")
        assert commands[0][-2:] == ["--out", str(tmp_path / "off" / "secrets")]
