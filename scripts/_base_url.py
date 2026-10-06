"""The one default base URL -- and the one admin token -- for operator scripts under `scripts/`.

WHY THIS EXISTS. Render has been billing-suspended since 2026-09-30 06:37Z and
production runs on the local WSL fleet at http://127.0.0.1:10000
(`docs/ai_context/local_production_runbook.md`). About sixty scripts each
hard-coded `https://syndicate-an21.onrender.com` as their default, in half a
dozen shapes; they now resolve the default here.

Precedence, first non-empty wins (a trailing `/` is stripped):

    1. any script-specific variables the caller passes in `prefer`
       (e.g. `default_base_url("SYNDICATE_WEB_PUBLISH_URL")`), in order
    2. SYNDICATE_BASE_URL
    3. SYNDICATE_OPS_BASE_URL
    4. SYNDICATE_DIAG_BASE_URL
    5. the LOCAL FLEET, FLEET_BASE_URL -- except on a Render host (below).

The fallback was Render until 2026-10-06. Measured that day: the Windows task
`SyndicateSoccerLiveProjectionHarvest` had failed 569 times in a row (HTTP 503,
09-30..10-06) and the scheduled soccer H24 grader hung polling a 503, both for
want of one exported variable. They were patched from OUTSIDE the repo with a
wrapper (`~/.claude/scheduled-tasks/_shared/local_fleet_env.py`); this is the
in-repo fix, so an unflagged script needs no wrapper.

ON A RENDER HOST the fallback stays Render (`RENDER` set, `SYNDICATE_LOCAL_PRODUCTION`
not): a cron or worker there would otherwise post to its own loopback. The fleet's
roles set `RENDER=true` as a marker AND `SYNDICATE_LOCAL_PRODUCTION=1`
(`scripts/local_production.py`), so they get the fleet.

A script's own `--base-url` flag still beats all of this: the flag's argparse
default is what this function returns.

ADMIN TOKEN -- `admin_token(base_url)`. The repo `.env` holds the RENDER token;
the fleet's is the `ADMIN_TOKEN` line of `~/syndicate-prod/local_production.env`
inside WSL. Sending `.env`'s token to the fleet gets a 401/403. So for a target
that IS the fleet (loopback, port 10000) the token is read from that file --
through `wsl.exe` on Windows, directly on Linux -- BEFORE an inherited
`ADMIN_TOKEN`, because an exported one may be Render's (the same trap as the
shell-exported dead `ODDS_API_KEY`). Any other target keeps the old order:
`ADMIN_TOKEN` / `SYNDICATE_ADMIN_TOKEN`, then `.env` (this checkout's, then the
primary checkout's -- a session worktree has none). THE TOKEN IS NEVER PRINTED;
callers that report it may report its length only.

DELIBERATELY NOT USED BY `scripts/deploy_preflight.py`. Preflight gates a
RENDER deploy and compares Render API state with the web service's own
memory endpoint; letting the generic `SYNDICATE_BASE_URL` repoint half of
that comparison at another host would make its reading wrong without
making it fail. It keeps its own `SYNDICATE_DIAG_BASE_URL` override and its
own `.env` token (`sample_request_path_guard.py` borrows both).

`tests/test_base_url.py` fails if a new hard-coded Render default appears
anywhere in `scripts/` outside this file.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import urllib.parse
from collections.abc import Iterable
from pathlib import Path

RENDER_BASE_URL = "https://syndicate-an21.onrender.com"
FLEET_BASE_URL = "http://127.0.0.1:10000"
FLEET_WSL_DISTRO = "Ubuntu-24.04"
FLEET_ENV_FILE = "~/syndicate-prod/local_production.env"

BASE_URL_ENV_VARS = (
    "SYNDICATE_BASE_URL",
    "SYNDICATE_OPS_BASE_URL",
    "SYNDICATE_DIAG_BASE_URL",
)

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_render_host() -> bool:
    if str(os.environ.get("SYNDICATE_LOCAL_PRODUCTION") or "").strip() not in ("", "0"):
        return False
    return bool(str(os.environ.get("RENDER") or "").strip())


def default_base_url(*prefer: str) -> str:
    """The first set variable among `prefer` then BASE_URL_ENV_VARS, else the fleet (Render on a Render host)."""
    for key in (*prefer, *BASE_URL_ENV_VARS):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    return RENDER_BASE_URL if _on_render_host() else FLEET_BASE_URL


def is_local_fleet(base_url: str | None) -> bool:
    """True when `base_url` is the fleet's web: a loopback host on the fleet's port.

    Narrower than "any loopback" on purpose: `py -3 app.py` on :5000 is a dev
    server that reads the repo `.env`, so it must keep `.env`'s token.
    """
    parts = urllib.parse.urlsplit(str(base_url or "").strip())
    try:
        port = parts.port
    except ValueError:
        return False
    fleet_port = urllib.parse.urlsplit(FLEET_BASE_URL).port
    return (parts.hostname or "").lower() in _LOOPBACK_HOSTS and port == fleet_port


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _env_file_value(path: Path, key: str) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == key:
            value = _unquote(value)
            if value:
                return value
    return ""


def _primary_checkout() -> Path | None:
    """The main checkout when this file runs from a `git worktree` (whose `.git` is a file)."""
    marker = _REPO_ROOT / ".git"
    if not marker.is_file():
        return None
    try:
        gitdir = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not gitdir.startswith("gitdir:"):
        return None
    # <primary>/.git/worktrees/<name>
    path = Path(gitdir.split(":", 1)[1].strip())
    return path.parents[2] if len(path.parents) > 2 else None


def dotenv_candidates(env_file: Path | str | Iterable[Path | str] | None = None) -> list[Path]:
    """`env_file` (one path or several) if given, else this checkout's `.env`, then the primary checkout's."""
    if isinstance(env_file, (str, Path)):
        return [Path(env_file)] if str(env_file) else []
    if env_file is not None:
        return [Path(path) for path in env_file]
    paths = [_REPO_ROOT / ".env"]
    primary = _primary_checkout()
    if primary is not None:
        paths.append(primary / ".env")
    return paths


def fleet_admin_token() -> str:
    """The fleet's ADMIN_TOKEN, or "" if it cannot be read. Never printed.

    `SYNDICATE_FLEET_ADMIN_TOKEN` short-circuits the read. `SYNDICATE_FLEET_ENV_FILE`
    (a POSIX path, `~` allowed) moves the file; `SYNDICATE_FLEET_WSL_DISTRO` the distro.

    UNDER PYTEST THE REAL FILE IS NEVER READ -- only one a test names in
    `SYNDICATE_FLEET_ENV_FILE`. Measured the day the fleet became the default:
    two older tests called a script's token helper with no base URL, it read the
    LIVE token through WSL, and pytest's assertion diff printed it.
    """
    explicit = _unquote(str(os.environ.get("SYNDICATE_FLEET_ADMIN_TOKEN") or ""))
    if explicit:
        return explicit
    named = str(os.environ.get("SYNDICATE_FLEET_ENV_FILE") or "").strip()
    if not named and ("pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST")):
        return ""
    env_file = named or FLEET_ENV_FILE
    distro = str(os.environ.get("SYNDICATE_FLEET_WSL_DISTRO") or FLEET_WSL_DISTRO).strip()
    return _read_fleet_token(env_file, distro, sys.platform == "win32")


@functools.lru_cache(maxsize=4)
def _read_fleet_token(env_file: str, distro: str, through_wsl: bool) -> str:
    """One read per (file, distro) per process: `wsl.exe` costs ~1 s to start."""
    if not through_wsl:
        return _env_file_value(Path(os.path.expanduser(env_file)), "ADMIN_TOKEN")
    # Only the one line crosses the boundary. `~` is expanded by the shell, so it
    # stays outside the quotes; the rest of the path is passed as an argument.
    rest = env_file[2:] if env_file.startswith("~/") else env_file
    prefix = '"$HOME"/' if env_file.startswith("~/") else ""
    command = f"grep -m1 '^ADMIN_TOKEN=' {prefix}\"$1\" | cut -d= -f2-"
    try:
        out = subprocess.run(
            ["wsl.exe", "-d", distro, "-e", "sh", "-c", command, "sh", rest],
            capture_output=True, text=True, timeout=90,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return _unquote(out or "")


def admin_token(
    base_url: str | None = None, *, env_file: Path | str | Iterable[Path | str] | None = None
) -> str:
    """The admin token for `base_url` (default: `default_base_url()`), or "". Never printed.

    Fleet target: the fleet's own token, else an inherited `ADMIN_TOKEN` (e.g.
    a script run inside a fleet role, where the two are the same). Never the
    repo `.env` -- that is Render's, and a 401 is a worse failure than "no
    token" because it reads as an auth bug on the fleet.

    Any other target: `ADMIN_TOKEN`, `SYNDICATE_ADMIN_TOKEN`, then `.env`.
    """
    target = base_url if base_url else default_base_url()
    inherited = _unquote(str(os.environ.get("ADMIN_TOKEN") or ""))
    if is_local_fleet(target):
        return fleet_admin_token() or inherited
    if inherited:
        return inherited
    alias = _unquote(str(os.environ.get("SYNDICATE_ADMIN_TOKEN") or ""))
    if alias:
        return alias
    for path in dotenv_candidates(env_file):
        for key in ("ADMIN_TOKEN", "SYNDICATE_ADMIN_TOKEN"):
            value = _env_file_value(path, key)
            if value:
                return value
    return ""
