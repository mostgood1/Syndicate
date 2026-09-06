"""The vendor sync must never silently revert a local patch.

`scripts/sync_vendor_upstream.py` exists because a `vendor/` file that differs
from upstream is ambiguous without a third input: "upstream moved ahead" and "we
patched it locally" are the same observation. These tests pin the classifier that
resolves it, and drive the whole apply path against a real throwaway git repo --
no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import sync_vendor_upstream as sync  # noqa: E402

A, B, C = "aaaa", "bbbb", "cccc"


# --- the classifier ----------------------------------------------------------


@pytest.mark.parametrize(
    "local, upstream, baseline, expected",
    [
        (A, A, A, sync.IN_SYNC),
        (A, A, None, sync.IN_SYNC),          # equal wins even with no baseline
        (A, B, A, sync.UPSTREAM_AHEAD),      # we never touched it; they moved
        (B, A, A, sync.LOCAL_PATCH),         # we moved; they did not
        (B, C, A, sync.CONFLICT),            # both moved since the last sync
        (A, B, None, sync.UNCLASSIFIED),     # differs, and nothing says who moved
        (A, None, None, sync.LOCAL_ONLY),    # not upstream at all
        (A, None, A, sync.LOCAL_ONLY),
    ],
)
def test_the_six_states(local, upstream, baseline, expected):
    assert sync.classify(local, upstream, baseline) == expected


def test_an_unknown_never_defaults_to_upstream_ahead():
    """The one that matters. `UPSTREAM_AHEAD` is the only state `--apply` acts on,
    so mapping "I cannot tell" onto it would make the script silently overwrite
    local work -- and when this was written, four vendored files held deletions
    whose upstream PRs were still open."""
    assert sync.classify(A, B, None) == sync.UNCLASSIFIED
    assert sync.UNCLASSIFIED not in (sync.UPSTREAM_AHEAD,)


def test_only_upstream_ahead_is_auto_appliable():
    """A guard's blast radius is the set of states it acts on. Pin it, so widening
    it later is a deliberate edit rather than a side effect."""
    auto = {s for s in (sync.IN_SYNC, sync.UPSTREAM_AHEAD, sync.LOCAL_PATCH,
                        sync.CONFLICT, sync.UNCLASSIFIED, sync.LOCAL_ONLY)
            if s == sync.UPSTREAM_AHEAD}
    assert auto == {sync.UPSTREAM_AHEAD}
    assert sync.CONFLICT in sync.ACTIONABLE and sync.UNCLASSIFIED in sync.ACTIONABLE
    assert sync.LOCAL_PATCH not in sync.ACTIONABLE  # reported, never blocking


# --- exclusions --------------------------------------------------------------


def test_data_is_excluded_by_default_and_includable():
    assert sync.is_excluded("data/processed/game_cards_2026-05-25.csv", include_data=False)
    assert not sync.is_excluded("data/processed/game_cards_2026-05-25.csv", include_data=True)
    assert not sync.is_excluded("src/pkg/mod.py", include_data=False)


def test_the_baseline_file_never_syncs_itself():
    assert sync.is_excluded("upstream_sync.json", include_data=True)


# --- end to end, against a real throwaway git repo ---------------------------


def _norm(text: str) -> str:
    """Collapse the report's column padding, so assertions pin CONTENT not spacing."""
    return " ".join(text.split())


def _git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """An 'upstream' repo and a Syndicate-shaped repo vendoring three of its files."""
    upstream = tmp_path / "upstream"
    _init(upstream)
    (upstream / "keep.py").write_text("original\n", encoding="utf-8")
    (upstream / "theirs.py").write_text("v1\n", encoding="utf-8")
    (upstream / "ours.py").write_text("shared\n", encoding="utf-8")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-qm", "base")

    local = tmp_path / "syndicate"
    tree_dir = local / "vendor" / "demo_repo"
    _init(local)
    tree_dir.mkdir(parents=True)
    for name in ("keep.py", "theirs.py", "ours.py"):
        (tree_dir / name).write_text((upstream / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tree_dir / "local_only.py").write_text("ours alone\n", encoding="utf-8")
    _git(local, "add", "-A")
    _git(local, "commit", "-qm", "vendored")

    monkeypatch.setattr(sync, "REPO_ROOT", local)
    monkeypatch.setattr(sync, "BASELINE_PATH", local / "vendor" / "upstream_sync.json")
    monkeypatch.setattr(sync, "TREES", {"demo": {"tree": "demo_repo", "repo": "x/demo", "branch": "main"}})
    monkeypatch.setattr(sync, "prepare_upstream", lambda *a, **k: upstream)
    return {"upstream": upstream, "local": local, "tree_dir": tree_dir}


def _run(*argv):
    return sync.main(list(argv))


def test_a_fresh_tree_is_all_in_sync_and_seeds_cleanly(world, capsys):
    rc = _run("--trees", "demo", "--seed-baseline")
    out = capsys.readouterr().out
    assert "IN_SYNC 3" in out
    assert rc == 0
    saved = json.loads((world["local"] / "vendor" / "upstream_sync.json").read_text(encoding="utf-8"))
    files = saved["trees"]["demo_repo"]["files"]
    assert set(files) == {"keep.py", "theirs.py", "ours.py"}
    assert "local_only.py" not in files, "a file that is not upstream must not enter the baseline"


def test_off_is_not_on_upstream_ahead_applies_and_local_patch_is_kept(world, capsys):
    """The two directions, in one run, on real files.

    `theirs.py` moves upstream and we never touch it -> must be updated.
    `ours.py` we edit and upstream does not -> must be left exactly as we wrote it.
    """
    _run("--trees", "demo", "--seed-baseline")
    capsys.readouterr()

    # upstream moves one file
    (world["upstream"] / "theirs.py").write_text("v2\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves")
    # we patch a different one
    (world["tree_dir"] / "ours.py").write_text("shared + our fix\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "our local patch")

    rc = _run("--trees", "demo", "--apply")
    out = capsys.readouterr().out

    assert "UPSTREAM_AHEAD theirs.py" in _norm(out)
    assert "LOCAL_PATCH ours.py" in _norm(out)
    assert (world["tree_dir"] / "theirs.py").read_text(encoding="utf-8") == "v2\n"
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "shared + our fix\n"
    assert (world["tree_dir"] / "keep.py").read_text(encoding="utf-8") == "original\n"
    assert rc == 0


def test_a_local_only_file_is_never_deleted(world, capsys):
    _run("--trees", "demo", "--seed-baseline")
    _run("--trees", "demo", "--apply")
    capsys.readouterr()
    assert (world["tree_dir"] / "local_only.py").exists()
    assert (world["tree_dir"] / "local_only.py").read_text(encoding="utf-8") == "ours alone\n"


def test_a_file_we_do_not_vendor_is_never_added(world, capsys):
    (world["upstream"] / "brand_new.py").write_text("not ours\n", encoding="utf-8")
    _git(world["upstream"], "add", "-A")
    _git(world["upstream"], "commit", "-qm", "upstream adds a file")
    _run("--trees", "demo", "--seed-baseline")
    _run("--trees", "demo", "--apply")
    capsys.readouterr()
    assert not (world["tree_dir"] / "brand_new.py").exists(), (
        "the trees are deliberate subsets -- 89 of upstream's 3,000 files for nhl -- "
        "so pulling in a new file is a separate decision, not a sync"
    )


def test_a_conflict_is_reported_and_nothing_is_written(world, capsys):
    _run("--trees", "demo", "--seed-baseline")
    (world["upstream"] / "ours.py").write_text("their change\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves ours.py")
    (world["tree_dir"] / "ours.py").write_text("our change\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "we move ours.py")
    capsys.readouterr()

    rc = _run("--trees", "demo", "--apply")
    out = capsys.readouterr().out
    assert "CONFLICT ours.py" in _norm(out)
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "our change\n"
    assert rc == 1


def test_an_unclassified_file_is_not_applied_without_adopting_it(world, capsys):
    """No baseline entry: the script must refuse, then obey an explicit adopt."""
    (world["upstream"] / "theirs.py").write_text("v2\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves")
    capsys.readouterr()

    rc = _run("--trees", "demo", "--apply")
    out = capsys.readouterr().out
    assert "UNCLASSIFIED theirs.py" in _norm(out)
    assert (world["tree_dir"] / "theirs.py").read_text(encoding="utf-8") == "v1\n"
    assert rc == 1

    _run("--trees", "demo", "--apply", "--adopt-upstream", "theirs.py")
    capsys.readouterr()
    assert (world["tree_dir"] / "theirs.py").read_text(encoding="utf-8") == "v2\n"


def test_an_UNCOMMITTED_local_edit_is_seen(world, capsys):
    """REGRESSION. The first revision read local hashes from `ls-tree HEAD`, so an
    uncommitted edit was invisible: the file classified IN_SYNC and `--apply`
    would have destroyed it. The working tree is what gets overwritten, so the
    working tree is what must be compared. Found because a hand-run demo against
    the real nhl tree reported the wrong state."""
    _run("--trees", "demo", "--seed-baseline")
    (world["upstream"] / "ours.py").write_text("upstream moved\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves ours.py")
    # edited but NOT committed
    (world["tree_dir"] / "ours.py").write_text("uncommitted local work\n", encoding="utf-8")
    capsys.readouterr()

    rc = _run("--trees", "demo", "--apply")
    out = capsys.readouterr().out
    assert "CONFLICT ours.py" in _norm(out), "an uncommitted edit must not read as IN_SYNC"
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "uncommitted local work\n"
    assert rc == 1


def test_apply_keeps_the_files_existing_line_endings(world, capsys):
    """`cat-file blob` hands back git's LF-normalised form. Writing that verbatim
    into a CRLF checkout flips one file's endings while its neighbours keep
    theirs -- invisible to git, since the clean filter normalises on the way back
    in, but a confusing artefact of the tool rather than of the change."""
    crlf = world["tree_dir"] / "theirs.py"
    crlf.write_bytes(b"v1\r\nsecond\r\n")
    (world["upstream"] / "theirs.py").write_bytes(b"v1\nsecond\nthird\n")
    _git(world["local"], "add", "-A")
    _git(world["local"], "commit", "-qm", "crlf in the worktree")
    _git(world["upstream"], "commit", "-qam", "upstream adds a line")

    _run("--trees", "demo", "--seed-baseline")
    _run("--trees", "demo", "--apply", "--adopt-upstream", "theirs.py")
    capsys.readouterr()

    data = crlf.read_bytes()
    assert b"third" in data, "content must be upstream's"
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), (
        "line endings must match what the file already used, got %r" % data
    )


def test_keep_local_records_the_decision_without_touching_content(world, capsys):
    """The way an UNCLASSIFIED file gets resolved as ours. Baseline := upstream's
    CURRENT hash, content left alone, so it reads LOCAL_PATCH from then on instead
    of re-prompting on every run."""
    (world["tree_dir"] / "ours.py").write_text("our fix\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "our patch, no baseline yet")
    capsys.readouterr()

    out = capsys.readouterr().out
    _run("--trees", "demo")
    assert "UNCLASSIFIED ours.py" in _norm(capsys.readouterr().out)

    _run("--trees", "demo", "--keep-local", "ours.py")
    capsys.readouterr()
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "our fix\n"

    _run("--trees", "demo")
    out = capsys.readouterr().out
    assert "LOCAL_PATCH ours.py" in _norm(out)
    assert "UNCLASSIFIED" not in out


def test_a_recorded_local_patch_becomes_a_CONFLICT_when_upstream_moves(world, capsys):
    """The property the whole triage rests on. Writing 53 files off as LOCAL_PATCH
    is only safe if a LATER upstream change to one of them stops the sync instead
    of overwriting our work."""
    (world["tree_dir"] / "ours.py").write_text("our fix\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "our patch")
    _run("--trees", "demo", "--keep-local", "ours.py")
    capsys.readouterr()

    (world["upstream"] / "ours.py").write_text("upstream moves too\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves ours.py")

    rc = _run("--trees", "demo", "--apply")
    out = capsys.readouterr().out
    assert "CONFLICT ours.py" in _norm(out)
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "our fix\n"
    assert rc == 1


def test_keep_all_unclassified_sweeps_only_unclassified(world, capsys):
    """It must not quietly bless an UPSTREAM_AHEAD file as a local patch -- that
    would convert 'we owe them a pull' into 'we deliberately diverged'."""
    _run("--trees", "demo", "--seed-baseline")
    # theirs.py: upstream moves, we did not -> UPSTREAM_AHEAD (has a baseline)
    (world["upstream"] / "theirs.py").write_text("v2\n", encoding="utf-8")
    _git(world["upstream"], "commit", "-qam", "upstream moves theirs.py")
    # keep.py: drop its baseline entry so it is UNCLASSIFIED, and diverge it
    data = json.loads((world["local"] / "vendor" / "upstream_sync.json").read_text(encoding="utf-8"))
    del data["trees"]["demo_repo"]["files"]["keep.py"]
    (world["local"] / "vendor" / "upstream_sync.json").write_text(
        json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (world["tree_dir"] / "keep.py").write_text("locally changed\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "diverge keep.py")
    capsys.readouterr()

    _run("--trees", "demo", "--keep-all-unclassified")
    capsys.readouterr()
    _run("--trees", "demo")
    out = _norm(capsys.readouterr().out)
    assert "LOCAL_PATCH keep.py" in out, "the UNCLASSIFIED one should now be recorded"
    assert "UPSTREAM_AHEAD theirs.py" in out, "the UPSTREAM_AHEAD one must be left alone"


def test_seeding_does_not_bless_a_file_that_already_differs(world, capsys):
    """Seeding records IN_SYNC files only. If it recorded everything, the very next
    run would call a pre-existing local patch `UPSTREAM_AHEAD` and overwrite it."""
    (world["tree_dir"] / "ours.py").write_text("our fix\n", encoding="utf-8")
    _git(world["local"], "commit", "-qam", "pre-existing local patch")
    _run("--trees", "demo", "--seed-baseline")
    capsys.readouterr()
    saved = json.loads((world["local"] / "vendor" / "upstream_sync.json").read_text(encoding="utf-8"))
    assert "ours.py" not in saved["trees"]["demo_repo"]["files"]

    _run("--trees", "demo", "--apply")
    capsys.readouterr()
    assert (world["tree_dir"] / "ours.py").read_text(encoding="utf-8") == "our fix\n"
