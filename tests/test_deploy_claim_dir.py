"""deploy_claim.py resolves its claim dir the way the local_production guard does (lane deploy-claim-dir-parity)."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_claim  # noqa: E402


def test_env_var_wins(tmp_path, monkeypatch):
    target = tmp_path / "claims"
    target.mkdir()
    monkeypatch.setenv("SYNDICATE_DEPLOY_CLAIM_DIR", str(target))
    assert deploy_claim._local_production_env_claim_dir() == target


def test_local_production_env_file_is_read(tmp_path, monkeypatch):
    target = tmp_path / "claims"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / "local_production.env").write_text(f'FOO=1\nSYNDICATE_DEPLOY_CLAIM_DIR="{target}"\n', encoding="utf-8")
    monkeypatch.delenv("SYNDICATE_DEPLOY_CLAIM_DIR", raising=False)
    monkeypatch.setenv("SYNDICATE_LOCAL_HOME", str(home))
    assert deploy_claim._local_production_env_claim_dir() == target


def test_missing_dir_is_ignored_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    monkeypatch.setenv("SYNDICATE_DEPLOY_CLAIM_DIR", str(missing))
    assert deploy_claim._local_production_env_claim_dir() is None
    assert not missing.exists()


def test_no_setting_falls_back_to_main_worktree(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_DEPLOY_CLAIM_DIR", raising=False)
    monkeypatch.setenv("SYNDICATE_LOCAL_HOME", str(tmp_path / "nohome"))
    assert deploy_claim._local_production_env_claim_dir() is None
    mod = importlib.reload(deploy_claim)
    try:
        assert mod.CLAIM_DIR == mod._main_worktree_root() / ".syndicate" / "deploy_claims"
    finally:
        monkeypatch.undo()
        importlib.reload(deploy_claim)
