"""The in-play nightly + recorder must survive the repo moving out of OneDrive (F6,
docs/ai_context/repo_out_of_onedrive_plan.md): path defaults pick whichever checkout exists, the
recorder is handed the repo's .env explicitly, and a missing repo is logged as SYNC_FAILED rather
than as ten misleading "SYNC_KEEP (not on origin/main)" lines."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_nightly as nightly  # noqa: E402
import inplay_recorder as recorder  # noqa: E402


def _repo(path: Path) -> str:
    (path / ".git").mkdir(parents=True)
    return str(path)


def test_default_repo_prefers_new_location_then_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_PRIMARY_TREE", raising=False)
    new, old = tmp_path / "Coding" / "Syndicate", tmp_path / "OneDrive" / "Coding" / "Syndicate"
    monkeypatch.setattr(nightly, "REPO_CANDIDATES", (str(new), str(old)))
    _repo(old)
    assert nightly.default_repo() == str(old)  # before the move
    _repo(new)
    assert nightly.default_repo() == str(new)  # after the move (old would be gone; new wins regardless)


def test_default_repo_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_PRIMARY_TREE", str(tmp_path / "elsewhere"))
    assert nightly.default_repo() == str(tmp_path / "elsewhere")


def test_default_env_file_follows_the_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ENV_FILE", raising=False)
    new, old = tmp_path / "new.env", tmp_path / "old.env"
    monkeypatch.setattr(recorder, "ENV_CANDIDATES", (str(new), str(old)))
    old.write_text("ODDS_API_KEY=x\n")
    assert recorder.default_env_file() == str(old)
    new.write_text("ODDS_API_KEY=y\n")
    assert recorder.default_env_file() == str(new)
    monkeypatch.setenv("SYNDICATE_ENV_FILE", str(tmp_path / "override.env"))
    assert recorder.default_env_file() == str(tmp_path / "override.env")


def test_sync_logs_failed_when_repo_is_missing(tmp_path, monkeypatch):
    runner = tmp_path / "runner"
    runner.mkdir()
    monkeypatch.setattr(nightly, "RUNNER", runner)
    calls = []
    monkeypatch.setattr(nightly.subprocess, "run", lambda *a, **k: calls.append(a))
    nightly.sync(tmp_path, str(tmp_path / "gone"))
    log = (tmp_path / "inplay_nightly.log").read_text(encoding="utf-8")
    assert "SYNC_FAILED repo not found" in log
    assert "SYNC_KEEP" not in log
    assert calls == []  # never shells out to git against a missing repo


def test_recorder_is_handed_the_repo_env(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(nightly, "run", lambda root, cmd, out: seen.append(cmd) or 0)
    monkeypatch.setattr(nightly, "idle", lambda: None)
    monkeypatch.setattr(nightly, "slate", lambda sports, ymd: {"nba": [(nightly.datetime.now(nightly.timezone.utc), "in")]})
    repo = tmp_path / "Coding" / "Syndicate"
    monkeypatch.setattr(sys, "argv", ["inplay_nightly.py", "--date", "2026-11-04", "--sports", "nba", "--root", str(tmp_path),
                                      "--repo", str(repo), "--no-sync", "--no-wait"])
    try:
        nightly.main()
    except Exception:
        pass  # the stages after the recorder need real artifacts; only the recorder call is under test
    rec = [c for c in seen if any(str(x).endswith("inplay_recorder.py") for x in c)]
    assert rec, seen
    cmd = [str(x) for x in rec[0]]
    assert cmd[cmd.index("--env") + 1] == str(repo / ".env")
