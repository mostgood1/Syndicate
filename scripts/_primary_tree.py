"""The primary (main-worktree) checkout, for scripts that read its untracked state.

Session worktrees have no `data/` (`session_worktree.py open` excludes it) and no `.env`, so a script that reads the
git-tracked mirror, the ledger or the secrets file must reach the MAIN tree, not the checkout it runs from.

Resolution order:
  1. `SYNDICATE_PRIMARY_TREE`, when set;
  2. the parent of `git rev-parse --git-common-dir`, which every worktree of a repo shares (the same rule as
     `deploy_claim._main_worktree_root`);
  3. the repo this file lives in.

Never a literal path: the repo moved from `C:\\Users\\tempadmin\\OneDrive\\Coding\\Syndicate` to
`C:\\Users\\tempadmin\\Coding\\Syndicate` on 2026-11-09 (docs/ai_context/repo_out_of_onedrive_plan.md), and every
hard-coded copy of the old path broke at once.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def primary_tree(start: Path | None = None) -> Path:
    override = os.environ.get("SYNDICATE_PRIMARY_TREE", "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(start) if start is not None else REPO_ROOT
    for args in (
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # git >= 2.31
        ["git", "rev-parse", "--git-common-dir"],
    ):
        try:
            done = subprocess.run(args, cwd=str(base), capture_output=True, text=True, timeout=15,
                                  stdin=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            continue
        raw = (done.stdout or "").strip()
        if done.returncode != 0 or not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (base / common).resolve()
        if common.name == ".git" and common.parent.is_dir():
            return common.parent
    return base
