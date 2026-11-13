"""scripts/_primary_tree.py: scripts reach the MAIN checkout from any worktree, wherever the repo lives.

The repo moved out of OneDrive on 2026-11-09 and every hard-coded copy of its old path broke at once; this helper is
what replaced them, so a worktree must resolve to the main tree and an override must win."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import _primary_tree as pt  # noqa: E402


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, stdin=subprocess.DEVNULL)


def test_worktree_resolves_to_main_tree(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_PRIMARY_TREE", raising=False)
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", "-b", "main", cwd=main)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x", cwd=main)
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", str(wt), "-b", "side", cwd=main)
    assert pt.primary_tree(wt).resolve() == main.resolve()
    assert pt.primary_tree(main).resolve() == main.resolve()


def test_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_PRIMARY_TREE", str(tmp_path / "elsewhere"))
    assert pt.primary_tree(tmp_path) == tmp_path / "elsewhere"


def test_not_a_repo_falls_back_to_start(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_PRIMARY_TREE", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    assert pt.primary_tree(plain) == plain


def test_this_checkout_resolves_off_onedrive():
    # Whatever checkout runs the suite, the main tree it resolves to is not under OneDrive any more.
    assert "OneDrive" not in str(pt.primary_tree())
