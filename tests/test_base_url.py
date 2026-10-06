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
from _base_url import FLEET_BASE_URL, RENDER_BASE_URL, admin_token, default_base_url, is_local_fleet  # noqa: E402

ENV_VARS = (
    "SYNDICATE_BASE_URL",
    "SYNDICATE_OPS_BASE_URL",
    "SYNDICATE_DIAG_BASE_URL",
    "SCRIPT_SPECIFIC_URL",
    "RENDER",
    "SYNDICATE_LOCAL_PRODUCTION",
    "ADMIN_TOKEN",
    "SYNDICATE_ADMIN_TOKEN",
    "SYNDICATE_FLEET_ADMIN_TOKEN",
    "SYNDICATE_FLEET_ENV_FILE",
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
}


@pytest.fixture
def clean_env(monkeypatch):
    for key in ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    _base_url._read_fleet_token.cache_clear()
    yield monkeypatch
    _base_url._read_fleet_token.cache_clear()


def test_unset_falls_back_to_the_local_fleet(clean_env):
    """Render is billing-suspended (2026-09-30); an unflagged script must reach production."""
    assert default_base_url() == FLEET_BASE_URL == "http://127.0.0.1:10000"
    assert default_base_url("SCRIPT_SPECIFIC_URL") == FLEET_BASE_URL


def test_a_render_host_still_falls_back_to_render(clean_env):
    """A Render cron/worker must not post to its own loopback."""
    clean_env.setenv("RENDER", "true")
    assert default_base_url() == RENDER_BASE_URL
    # ...but the fleet's roles carry RENDER=true as a marker, with SYNDICATE_LOCAL_PRODUCTION=1.
    clean_env.setenv("SYNDICATE_LOCAL_PRODUCTION", "1")
    assert default_base_url() == FLEET_BASE_URL
    clean_env.setenv("SYNDICATE_BASE_URL", "http://explicit")
    assert default_base_url() == "http://explicit"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://127.0.0.1:10000", True),
        ("http://localhost:10000/", True),
        ("http://[::1]:10000/api", True),
        ("http://127.0.0.1:5000", False),  # `py -3 app.py` dev server reads the repo .env
        (RENDER_BASE_URL, False),
        ("", False),
        ("http://127.0.0.1:notaport", False),
    ],
)
def test_is_local_fleet(url, expected):
    assert is_local_fleet(url) is expected


def _no_wsl(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("must not shell out for this target")

    monkeypatch.setattr(_base_url.subprocess, "run", forbidden)


def test_fleet_target_prefers_the_fleet_token_over_an_inherited_one(clean_env, tmp_path):
    env_file = tmp_path / "local_production.env"
    env_file.write_text("OTHER=1\nADMIN_TOKEN='fleet-tok'\n", encoding="utf-8")
    clean_env.setenv("SYNDICATE_FLEET_ENV_FILE", str(env_file))
    clean_env.setattr(_base_url.sys, "platform", "linux")
    clean_env.setenv("ADMIN_TOKEN", "render-tok")  # an exported token may be Render's
    assert admin_token(FLEET_BASE_URL) == "fleet-tok"
    assert admin_token() == "fleet-tok"  # unset base -> the default, which is the fleet


def test_fleet_target_reads_through_wsl_on_windows(clean_env):
    calls = []

    class Done:
        stdout = '"fleet-tok"\n'

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Done()

    clean_env.setattr(_base_url.sys, "platform", "win32")
    clean_env.setattr(_base_url.subprocess, "run", fake_run)
    clean_env.setenv("SYNDICATE_FLEET_ENV_FILE", "~/syndicate-prod/local_production.env")
    assert admin_token("http://localhost:10000") == "fleet-tok"
    assert admin_token("http://localhost:10000") == "fleet-tok"
    assert len(calls) == 1, "read once per process"
    argv = calls[0]
    assert argv[:4] == ["wsl.exe", "-d", "Ubuntu-24.04", "-e"]
    assert argv[-1] == "syndicate-prod/local_production.env"
    assert "ADMIN_TOKEN" in argv[-3]


def test_fleet_target_never_falls_back_to_the_repo_env(clean_env, tmp_path):
    clean_env.setenv("SYNDICATE_FLEET_ENV_FILE", str(tmp_path / "missing.env"))
    clean_env.setattr(_base_url.sys, "platform", "linux")
    dotenv = tmp_path / ".env"
    dotenv.write_text("ADMIN_TOKEN=render-tok\n", encoding="utf-8")
    assert admin_token(FLEET_BASE_URL, env_file=dotenv) == ""
    clean_env.setenv("ADMIN_TOKEN", "inherited")  # e.g. run inside a fleet role
    assert admin_token(FLEET_BASE_URL) == "inherited"


def test_under_pytest_the_real_fleet_file_is_never_read(clean_env):
    """Nothing named -> "" without shelling out, so no test can print the live token."""
    _no_wsl(clean_env)
    clean_env.setattr(_base_url.sys, "platform", "win32")
    assert admin_token(FLEET_BASE_URL) == ""
    clean_env.setattr(_base_url.sys, "platform", "linux")
    assert admin_token(FLEET_BASE_URL) == ""


def test_a_worktree_falls_back_to_the_primary_checkouts_dotenv(clean_env, tmp_path):
    primary, worktree = tmp_path / "primary", tmp_path / "wt"
    (primary / ".git" / "worktrees" / "wt").mkdir(parents=True)
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {primary / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    (primary / ".env").write_text("ADMIN_TOKEN=from-primary\n", encoding="utf-8")
    clean_env.setattr(_base_url, "_REPO_ROOT", worktree)
    assert _base_url.dotenv_candidates() == [worktree / ".env", primary / ".env"]
    assert admin_token(RENDER_BASE_URL) == "from-primary"
    assert _base_url.dotenv_candidates([tmp_path / "a", tmp_path / "b"]) == [tmp_path / "a", tmp_path / "b"]


def test_explicit_fleet_token_short_circuits(clean_env):
    _no_wsl(clean_env)
    clean_env.setattr(_base_url.sys, "platform", "win32")
    clean_env.setenv("SYNDICATE_FLEET_ADMIN_TOKEN", "given")
    assert admin_token(FLEET_BASE_URL) == "given"


def test_non_fleet_target_keeps_env_then_dotenv(clean_env, tmp_path):
    _no_wsl(clean_env)
    dotenv = tmp_path / ".env"
    dotenv.write_text('# c\nADMIN_TOKEN_OLD=x\nADMIN_TOKEN = "dot-tok"\n', encoding="utf-8")
    assert admin_token(RENDER_BASE_URL, env_file=dotenv) == "dot-tok"
    clean_env.setenv("SYNDICATE_ADMIN_TOKEN", "alias")
    assert admin_token(RENDER_BASE_URL, env_file=dotenv) == "alias"
    clean_env.setenv("ADMIN_TOKEN", "env-tok")
    assert admin_token("http://127.0.0.1:5000", env_file=dotenv) == "env-tok"
    assert admin_token(RENDER_BASE_URL, env_file=tmp_path / "absent") == "env-tok"


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
