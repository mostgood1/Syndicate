"""The one default base URL for operator scripts under `scripts/`.

WHY THIS EXISTS. Render has been billing-suspended since 2026-09-30 06:37Z and
production runs on the local WSL fleet at http://127.0.0.1:10000
(`docs/ai_context/local_production_runbook.md`). About sixty scripts each
hard-coded `https://syndicate-an21.onrender.com` as their default, in half a
dozen shapes, so every one of them failed unless the operator remembered a
flag. They now resolve the default here, so one exported variable repoints
all of them:

    export SYNDICATE_BASE_URL=http://127.0.0.1:10000

Precedence, first non-empty wins (a trailing `/` is stripped):

    1. any script-specific variables the caller passes in `prefer`
       (e.g. `default_base_url("SYNDICATE_WEB_PUBLISH_URL")`), in order
    2. SYNDICATE_BASE_URL
    3. SYNDICATE_OPS_BASE_URL
    4. SYNDICATE_DIAG_BASE_URL
    5. RENDER_BASE_URL -- so with nothing set, behaviour is exactly as before.

A script's own `--base-url` flag still beats all of this: the flag's argparse
default is what this function returns.

ADMIN TOKEN. Scripts that read `ADMIN_TOKEN` from the repo `.env` still do --
this module does not touch tokens. But the repo `.env` holds the RENDER
token. The local fleet's admin token is the `ADMIN_TOKEN` line of
`~/syndicate-prod/local_production.env` inside WSL, NOT `.env`'s; pointing a
script at the fleet with `.env`'s token gets a 401/403.

DELIBERATELY NOT USED BY `scripts/deploy_preflight.py`. Preflight gates a
RENDER deploy and compares Render API state with the web service's own
memory endpoint; letting the generic `SYNDICATE_BASE_URL` repoint half of
that comparison at another host would make its reading wrong without
making it fail. It keeps its own `SYNDICATE_DIAG_BASE_URL` override.

`tests/test_base_url.py` fails if a new hard-coded default appears anywhere
in `scripts/` outside this file.
"""

from __future__ import annotations

import os

RENDER_BASE_URL = "https://syndicate-an21.onrender.com"

BASE_URL_ENV_VARS = (
    "SYNDICATE_BASE_URL",
    "SYNDICATE_OPS_BASE_URL",
    "SYNDICATE_DIAG_BASE_URL",
)


def default_base_url(*prefer: str) -> str:
    """The first set variable among `prefer` then BASE_URL_ENV_VARS, else Render."""
    for key in (*prefer, *BASE_URL_ENV_VARS):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    return RENDER_BASE_URL
