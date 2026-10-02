"""`scripts/_base_url.py`: precedence, and no NEW hard-coded Render default.

Render was billing-suspended 2026-09-30 and production moved to the local WSL
fleet; ~60 scripts hard-coded the Render URL as their default and all failed
until each was pointed at the resolver. The scan below keeps that from
regrowing one script at a time.
"""

from __future__ import annotations

import ast
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _base_url  # noqa: E402
from _base_url import RENDER_BASE_URL, default_base_url  # noqa: E402

ENV_VARS = (
    "SYNDICATE_BASE_URL",
    "SYNDICATE_OPS_BASE_URL",
    "SYNDICATE_DIAG_BASE_URL",
    "SCRIPT_SPECIFIC_URL",
)

# Files allowed to carry the literal as live code, each with its reason.
ALLOWED = {
    # The resolver itself.
    "scripts/_base_url.py": "defines RENDER_BASE_URL",
    # Gates a RENDER deploy; must not follow the generic SYNDICATE_BASE_URL.
    "scripts/deploy_preflight.py": "Render-deploy gate, deliberately Render-pinned",
    # PENDING: claimed by another OPEN lane on 2026-10-01 when the resolver
    # landed (lane `scripts-base-url-resolver`). Convert each when its lane
    # closes, and delete its line here -- the test then guards it too.
    "scripts/board_delivery_probe.py": "pending: lane nhl-board-rows-missing",
    "scripts/bucket_search.py": "pending: lane accuracy-assessment-0914",
    "scripts/build_wnba_boxscores.py": "pending: lane restore-measurement",
    "scripts/check_e2e_coverage.py": "pending: lane e2e-coverage-contract",
    "scripts/controlled_transfer_probe.py": "pending: lane bandwidth-controlled-transfer",
    "scripts/grade_wnba_live_prop_projection.py": "pending: lane live-props-model-probability",
    "scripts/regrade_mlb_game_markets.py": "pending: lane dh-grading-ledger-joins",
}


@pytest.fixture
def clean_env(monkeypatch):
    for key in ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_unset_falls_back_to_render(clean_env):
    assert default_base_url() == RENDER_BASE_URL
    assert default_base_url("SCRIPT_SPECIFIC_URL") == RENDER_BASE_URL


def test_precedence(clean_env):
    clean_env.setenv("SYNDICATE_DIAG_BASE_URL", "http://diag")
    assert default_base_url() == "http://diag"
    clean_env.setenv("SYNDICATE_OPS_BASE_URL", "http://ops")
    assert default_base_url() == "http://ops"
    clean_env.setenv("SYNDICATE_BASE_URL", "http://127.0.0.1:10000/")
    assert default_base_url() == "http://127.0.0.1:10000"  # trailing / stripped
    clean_env.setenv("SCRIPT_SPECIFIC_URL", "http://mine")
    assert default_base_url("SCRIPT_SPECIFIC_URL") == "http://mine"


def test_blank_values_are_unset(clean_env):
    clean_env.setenv("SYNDICATE_BASE_URL", "   ")
    clean_env.setenv("SYNDICATE_OPS_BASE_URL", "http://ops")
    assert default_base_url() == "http://ops"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    ids.add(id(stmt.value))
    return ids


def _hardcoded_sites(path: Path) -> list[int]:
    """Line numbers of string constants carrying the Render URL, docstrings excluded.

    Comments never reach the AST, and prose that names the bare host without
    the scheme is not matched, so only a usable URL counts.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # other scripts' escapes
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    skip = _docstring_nodes(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and RENDER_BASE_URL in node.value
        and id(node) not in skip
    )


def test_no_new_hardcoded_render_default():
    offenders = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED:
            continue
        lines = _hardcoded_sites(path)
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, (
        "Hard-coded Render base URL outside scripts/_base_url.py -- use "
        "default_base_url() so SYNDICATE_BASE_URL repoints it:\n  " + "\n  ".join(offenders)
    )


def test_allowlist_has_no_stale_entries():
    """A converted file must leave ALLOWED, or the scan stops guarding it."""
    stale = [rel for rel in ALLOWED if not _hardcoded_sites(REPO_ROOT / rel)]
    assert not stale, f"no longer hard-code the URL; delete from ALLOWED: {stale}"


def test_scan_detects_a_planted_default(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text(
        '"""Docstring naming https://syndicate-an21.onrender.com is fine."""\n'
        "# so is a comment: https://syndicate-an21.onrender.com\n"
        f'BASE = "{_base_url.RENDER_BASE_URL}/api/ops"\n',
        encoding="utf-8",
    )
    assert _hardcoded_sites(planted) == [3]
