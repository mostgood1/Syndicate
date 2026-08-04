"""Code-version attribution for evaluation-ledger records.

Context: docs/reports/syndicate_learning_loop_plan_2026_08_03.md, Stage 5.

Without this, an accuracy change over time can never be attributed to a
specific code change -- every measurement in the repo (compute_metrics,
build_reliability_profile, the new model_scoring.py) is retrospective-only,
answering "how are we doing" but never "did commit X make it better or
worse". Stamping the code SHA on every prediction/recommendation at the
moment it's recorded is what makes that question answerable later, by
joining ledger records to git history on this one field.

Mirrors syndicate.blueprints.ops._build_version_payload's own env-var-first
resolution (RENDER_GIT_COMMIT -> git rev-parse -> "unknown"), duplicated
rather than imported because that helper depends on Flask's current_app
and only runs inside a request; this needs to be callable from worker code
(where recording actually happens -- pipeline/intelligence_state.py) with
no app context at all.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

from syndicate.features.shared.source_roots import repo_root_from

_UNKNOWN_VERSION = "unknown"


def _git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


@lru_cache(maxsize=1)
def code_version() -> str:
    """The running process's code identity -- short git SHA, preferring
    Render's own env var (available on every service without shelling out)
    over a live `git rev-parse` (works locally, and as a fallback if the
    env var is ever unset). Cached for the process lifetime: this is
    called on every recorded prediction/recommendation, and neither the
    env var nor the repo's HEAD can change without a redeploy/restart."""
    env_commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    if env_commit:
        return env_commit[:12]
    git_commit = _git_commit(repo_root_from(__file__))
    return git_commit or _UNKNOWN_VERSION


__all__ = ["code_version"]
