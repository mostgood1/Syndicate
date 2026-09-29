"""commit_live_gameline_history.py: append-only commit of the nightly rows.

The load-bearing property is that origin's rows are never removed or rewritten
-- the primary tree's copy is stale and other sessions push rows too."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "commit_live_gameline_history", _ROOT / "scripts/commit_live_gameline_history.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_only_rows_origin_lacks_are_appended_in_source_order():
    origin = '{"a":1}\n{"b":2}\n'
    source = '{"a":1}\r\n{"c":3}\n{"b":2}\n{"d":4}\n{"c":3}\n'
    assert mod.rows_to_append(origin, source) == ['{"c":3}', '{"d":4}']


def test_origin_rows_the_source_lacks_are_not_a_reason_to_do_anything():
    assert mod.rows_to_append('{"a":1}\n{"z":9}\n', '{"a":1}\n') == []


def _git(*a, cwd):
    subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True)


def _setup(tmp_path):
    bare = tmp_path / "origin.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    _git("clone", "-q", str(bare), str(seed), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git("config", k, v, cwd=seed)
    f = seed / mod.REL
    f.parent.mkdir(parents=True)
    f.write_text('{"r":1}\n{"peer":1}\n', encoding="utf-8")   # a peer already pushed "peer"
    _git("add", ".", cwd=seed)
    _git("commit", "-q", "-m", "seed", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)
    repo = tmp_path / "repo"
    _git("clone", "-q", str(bare), str(repo), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git("config", k, v, cwd=repo)
    return bare, repo


def test_it_commits_the_new_rows_and_keeps_the_peers_row(tmp_path):
    bare, repo = _setup(tmp_path)
    source = tmp_path / "stale_primary_history.jsonl"
    source.write_text('{"r":1}\n{"mine":1}\n', encoding="utf-8")   # stale: lacks "peer"
    assert mod.run(repo, source) == 0
    out = subprocess.run(["git", "--git-dir", str(bare), "show", "main:" + mod.REL],
                         capture_output=True, text=True, check=True).stdout
    assert out.splitlines() == ['{"r":1}', '{"peer":1}', '{"mine":1}']
    # the worktree is gone and a second run has nothing to do
    assert "gameline-history-commit" not in subprocess.run(
        ["git", "worktree", "list"], cwd=str(repo), capture_output=True, text=True).stdout
    assert mod.run(repo, source) == 0
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "--oneline", "main"],
                         capture_output=True, text=True, check=True).stdout
    assert len(log.splitlines()) == 2


def test_dry_run_pushes_nothing(tmp_path):
    bare, repo = _setup(tmp_path)
    source = tmp_path / "h.jsonl"
    source.write_text('{"mine":1}\n', encoding="utf-8")
    assert mod.run(repo, source, dry_run=True) == 0
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "--oneline", "main"],
                         capture_output=True, text=True, check=True).stdout
    assert len(log.splitlines()) == 1
