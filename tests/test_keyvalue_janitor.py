"""scripts/keyvalue_janitor.py -- classification, dry-run safety, backup/restore, tripwires."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "keyvalue_janitor", Path(__file__).resolve().parents[1] / "scripts" / "keyvalue_janitor.py"
)
janitor = importlib.util.module_from_spec(_SPEC)
sys.modules["keyvalue_janitor"] = janitor
_SPEC.loader.exec_module(janitor)

NS = "syndicate"
PROD = "/home/amyn/syndicate-prod/data/odds_control_plane/oddsapi_quota.json"
WIN = "C:/Users/tempadmin/AppData/Local/Temp/tmpab12cd/odds_control_plane/oddsapi_quota.json"
POSIX = "/tmp/pytest-of-amyn/pytest-3/test_x0/odds_control_plane/oddsapi_quota.json"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def key(path: str) -> bytes:
    return f"{NS}:refresh-state:{path}".encode()


class FakeRedis:
    """Just the commands the janitor uses. idle is seconds; pttl is ms (-1 = no expiry)."""

    def __init__(self):
        self.store: dict[bytes, bytes] = {}
        self.idle: dict[bytes, int] = {}
        self.pttl_ms: dict[bytes, int] = {}
        self.fail_dump = False

    def add(self, path: str, *, idle: int = 86400, pttl: int = -1, value: bytes = b"{}") -> bytes:
        k = key(path)
        self.store[k] = value
        self.idle[k] = idle
        self.pttl_ms[k] = pttl
        return k

    def ping(self):
        return True

    def scan_iter(self, match=None, count=None):
        prefix = match.rstrip("*").encode()
        return iter([k for k in list(self.store) if k.startswith(prefix)])

    def object(self, what, k):
        assert what == "idletime"
        return self.idle[k]

    def pttl(self, k):
        return self.pttl_ms.get(k, -2) if k in self.store else -2

    def dump(self, k):
        if self.fail_dump:
            raise OSError("boom")
        return b"DUMP:" + self.store[k] if k in self.store else None

    def restore(self, name, ttl, blob, replace=False):
        k = name.encode() if isinstance(name, str) else name
        self.store[k] = blob[len(b"DUMP:"):]
        self.idle[k] = 0
        self.pttl_ms[k] = ttl if ttl else -1

    def expire(self, k, seconds):
        self.pttl_ms[k] = int(seconds) * 1000

    def unlink(self, k):
        self.store.pop(k, None)


def run(r, *argv, tmp=None):
    args = list(argv)
    if tmp is not None and "--apply" in args and "--backup-dir" not in args and "--no-backup" not in args:
        args += ["--backup-dir", str(tmp)]
    return janitor.main(args, client_factory=lambda url: r, now=NOW)


@pytest.mark.parametrize("path,cls", [
    ("C:/Users/x/AppData/Local/Temp/tmp1/a.json", "windows_temp"),
    ("C:\\Users\\x\\AppData\\Local\\Temp\\tmp1\\a.json", "windows_temp"),
    ("/tmp/abc/a.json", "posix_tmp"),
    ("/var/tmp/abc/a.json", "posix_tmp"),
    ("/mnt/c/pytest-of-amyn/pytest-1/t/a.json", "pytest_tmp"),
    ("/home/amyn/syndicate-prod/data/a.json", None),
    ("/home/amyn/syndicate-prod/tmp/pytest-of-amyn/x/a.json", None),   # protected root beats a signature
    ("/opt/render/project/src/data/a.json", None),
    ("/home/amyn/syndicate-prod-copy/tmp/a.json", None),                # lookalike root is not "protected" but is not a signature either
    ("/home/amyn/data/tmpfile.json", None),
    ("/data/tmp/a.json", None),                                         # "/tmp/" must anchor at the root
])
def test_classify_path(path, cls):
    assert janitor.classify_path(path) == cls


def test_lookalike_of_protected_root_with_tmp_signature_is_a_candidate_only_if_it_is_really_tmp():
    # /home/amyn/syndicate-prod-copy is NOT the protected root; a tmp signature there needs the path to START at /tmp.
    assert janitor.is_protected_path("/home/amyn/syndicate-prod-copy/x") is False
    assert janitor.is_protected_path("/home/amyn/syndicate-prod/x") is True
    assert janitor.is_protected_path("/home/amyn/syndicate-prod") is True


def test_dry_run_changes_nothing_and_reports(capsys):
    r = FakeRedis()
    r.add(PROD)
    w = r.add(WIN)
    before = (dict(r.store), dict(r.pttl_ms))
    assert run(r) == 0
    assert (dict(r.store), dict(r.pttl_ms)) == before
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "mode=dry-run" in out and "candidates=1" in out
    assert r.pttl_ms[w] == -1


def test_dry_run_fail_on_found():
    r = FakeRedis()
    r.add(WIN)
    assert run(r, "--fail-on-found") == 1
    r2 = FakeRedis()
    r2.add(PROD)
    assert run(r2, "--fail-on-found") == 0


def test_apply_expires_only_test_keys_and_leaves_prod_untouched(tmp_path, capsys):
    r = FakeRedis()
    prod = r.add(PROD, value=b"real")
    other = r.add("/home/amyn/syndicate-prod/data/sim_runs/x.json", value=b"keep")
    w = r.add(WIN)
    p = r.add(POSIX)
    assert run(r, "--apply", tmp=tmp_path) == 0
    assert r.pttl_ms[w] == 60_000 and r.pttl_ms[p] == 60_000
    assert r.pttl_ms[prod] == -1 and r.pttl_ms[other] == -1
    assert r.store[prod] == b"real"
    out = capsys.readouterr().out
    assert "expired=2" in out and "remaining=0" in out and "quota_docs_after=1" in out


def test_apply_delete_now_unlinks(tmp_path):
    r = FakeRedis()
    prod = r.add(PROD)
    w = r.add(WIN)
    assert run(r, "--apply", "--delete-now", tmp=tmp_path) == 0
    assert w not in r.store and prod in r.store


def test_recently_touched_key_is_left_alone(tmp_path, capsys):
    r = FakeRedis()
    r.add(PROD)
    hot = r.add(WIN, idle=10)
    cold = r.add(POSIX, idle=7200)
    assert run(r, "--apply", tmp=tmp_path) == 0
    assert r.pttl_ms[hot] == -1       # in flight, not touched
    assert r.pttl_ms[cold] == 60_000
    assert "skipped_recent=1" in capsys.readouterr().out


def test_idle_unknown_is_treated_as_recent(tmp_path):
    r = FakeRedis()
    r.add(PROD)
    w = r.add(WIN)
    r.object = lambda what, k: (_ for _ in ()).throw(RuntimeError("LFU"))
    assert run(r, "--apply", tmp=tmp_path) == 0
    assert r.pttl_ms[w] == -1


def test_backup_roundtrip_restores_value_and_ttl(tmp_path):
    r = FakeRedis()
    r.add(PROD)
    w = r.add(WIN, value=b"fixture-body", pttl=90_000)
    assert run(r, "--apply", "--delete-now", tmp=tmp_path) == 0
    assert w not in r.store
    files = sorted(tmp_path.glob("keyvalue_janitor_*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert rows[0]["key"] == w.decode() and rows[0]["pttl_ms"] == 90_000
    assert run(r, "--restore", str(files[0]), "--apply") == 0
    assert r.store[w] == b"fixture-body" and r.pttl_ms[w] == 90_000


def test_restore_without_apply_writes_nothing(tmp_path):
    r = FakeRedis()
    f = tmp_path / "x.jsonl"
    f.write_text("")
    assert run(r, "--restore", str(f)) == 0
    assert not r.store


def test_apply_without_backup_dir_is_refused(capsys):
    r = FakeRedis()
    w = r.add(WIN)
    r.add(PROD)
    assert run(r, "--apply") == 3
    assert r.pttl_ms[w] == -1
    assert "needs --backup-dir" in capsys.readouterr().out


def test_no_backup_flag_allows_apply():
    r = FakeRedis()
    r.add(PROD)
    w = r.add(WIN)
    assert run(r, "--apply", "--no-backup") == 0
    assert r.pttl_ms[w] == 60_000


def test_backup_failure_changes_nothing(tmp_path):
    r = FakeRedis()
    r.add(PROD)
    w = r.add(WIN)
    r.fail_dump = True
    assert run(r, "--apply", tmp=tmp_path) == 3
    assert r.pttl_ms[w] == -1 and w in r.store
    assert not list(tmp_path.glob("keyvalue_janitor_*.jsonl"))   # only a .partial may remain, never a final


def test_max_keys_tripwire_changes_nothing(tmp_path, capsys):
    r = FakeRedis()
    r.add(PROD)
    for i in range(5):
        r.add(f"/tmp/pytest-of-a/p{i}/x.json")
    assert run(r, "--apply", "--max-keys", "3", tmp=tmp_path) == 5
    assert all(v == -1 for v in r.pttl_ms.values())
    assert "REFUSING" in capsys.readouterr().out


def test_two_real_quota_docs_is_exit_4(tmp_path, capsys):
    r = FakeRedis()
    r.add(PROD)
    r.add("/home/amyn/syndicate-prod-b/odds_control_plane/oddsapi_quota.json")
    r.add(WIN)
    assert run(r, "--apply", tmp=tmp_path) == 4
    assert "quota_docs_after=2" in capsys.readouterr().out


def test_nothing_to_do_is_exit_0(tmp_path, capsys):
    r = FakeRedis()
    r.add(PROD)
    assert run(r, "--apply", tmp=tmp_path) == 0
    assert "candidates=0" in capsys.readouterr().out


def test_keys_outside_the_namespace_are_ignored(tmp_path):
    r = FakeRedis()
    r.add(PROD)
    foreign = b"other:refresh-state:" + WIN.encode()
    r.store[foreign] = b"x"; r.idle[foreign] = 99999; r.pttl_ms[foreign] = -1
    assert run(r, "--apply", tmp=tmp_path) == 0
    assert r.pttl_ms[foreign] == -1


def test_namespace_flag(tmp_path):
    r = FakeRedis()
    k = b"alt:refresh-state:" + WIN.encode()
    r.store[k] = b"x"; r.idle[k] = 99999; r.pttl_ms[k] = -1
    assert janitor.main(["--apply", "--namespace", "alt", "--backup-dir", str(tmp_path)], client_factory=lambda u: r, now=NOW) == 0
    assert r.pttl_ms[k] == 60_000


def test_backup_retention(tmp_path):
    r = FakeRedis()
    r.add(PROD)
    for n in range(4):
        r.add(f"/tmp/pytest-of-a/r{n}/x.json")
        stamp_now = datetime(2026, 10, 22, 12, n, tzinfo=timezone.utc)
        janitor.main(["--apply", "--keep-backups", "2", "--backup-dir", str(tmp_path)], client_factory=lambda u: r, now=stamp_now)
    assert len(list(tmp_path.glob("keyvalue_janitor_*.jsonl"))) == 2


def test_unreachable_redis_is_exit_2_and_never_prints_the_url(capsys):
    def boom(url):
        raise ConnectionError("nope")
    rc = janitor.main(["--url", "redis://user:s3cretpw@10.9.9.9:6380/2", "--apply", "--no-backup"], client_factory=boom, now=NOW)
    out = capsys.readouterr().out
    assert rc == 2
    assert "s3cretpw" not in out and "user:" not in out
    assert "10.9.9.9:6380" in out


def test_default_factory_refuses_loopback_under_pytest():
    # pytest sets PYTEST_CURRENT_TEST, so main() with no injected client must not open the fleet's Redis.
    rc = janitor.main(["--url", "redis://127.0.0.1:6379/0"], now=NOW)
    assert rc == 2   # RuntimeError from the guard is reported as unreachable; nothing was opened
