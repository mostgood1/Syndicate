"""Dated env-var snapshots per Render service, with a diff. `#625`(3).

WHY THIS EXISTS, and it is a specific failure rather than tidiness.

2026-09-02: `#626`(h) — the evaluation autorun the whole edge plan rests on —
had NEVER RUN. Not because it was broken: because
`ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN` was absent and the job is
default-OFF. The code had shipped, the tests passed, the item read as done. The
only thing standing between "shipped" and "running" was one key nobody could see,
because **nothing records which service has which key.**

That is the `deployed-inert` class `#625`'s own verification names. A dated
snapshot makes it visible, and a DIFF makes "what changed on this service since
yesterday" answerable — which is the question `enumerate env changes when
bisecting` says to ask and which has been unanswerable.

--------------------------------------------------------------------------
IT NEVER WRITES A SECRET, AND THAT CONSTRAINT SHAPES THE FORMAT
--------------------------------------------------------------------------

These services hold `ADMIN_TOKEN`, `RENDER_API_KEY`, database URLs. A snapshot
that records values is a credential file waiting to be committed. So values are
recorded as `sha256(value)[:12]` plus a length — enough to prove a value CHANGED
without ever storing what it is.

Plaintext is allowed only where it cannot be a credential, and getting that
rule right took a REAL LEAK to find:

**The first version was shape-only** — `true|false|on|off|[0-9]{1,10}` — on the
argument that a name denylist fails silently the moment someone adds
`NEW_SERVICE_TOKEN`. That argument is correct and the rule was still WRONG,
because this platform's `ADMIN_TOKEN` is a ten-digit number. It matched the
numeric shape, and the very first snapshot wrote a live credential to disk in
plaintext. The file was deleted; the rule is now:

  * a BOOLEAN literal (`true`/`false`/`yes`/`no`/`on`/`off`) is always plaintext
    — no credential is spelled `false`;
  * a NUMBER is plaintext only if the key name is not secret-shaped;
  * everything else is hashed.

So it is shape AND name, and a leak now needs BOTH to fail at once. The original
reasoning survives as half of the rule rather than all of it: names alone miss a
new key, shapes alone miss a numeric token.

--------------------------------------------------------------------------
IT PAGINATES, BECAUSE NOT PAGINATING IS HOW THE FIRST READ WENT WRONG
--------------------------------------------------------------------------

`?limit=100` is a PAGE SIZE. refresh-worker has **153** keys, so a single-page
read shows 100 and looks complete. I reported "absent from refresh-worker's 100
env keys" on exactly that mistake — the conclusion happened to be right, the
evidence could not support it. CLAUDE.md says to paginate this endpoint (and that
`limit` > 100 returns HTTP 400). This does, and it REFUSES to write a snapshot
whose page count suggests truncation.

Usage:
    py -3 scripts/snapshot_render_env.py                       # snapshot all services
    py -3 scripts/snapshot_render_env.py --out DIR
    py -3 scripts/snapshot_render_env.py --diff A.json B.json  # what changed
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Same ids `deploy_preflight.py` uses. `web` and `syndicate` are the SAME
# service (see `#635`), so it is listed once to avoid a duplicate snapshot
# claiming to be two.
SERVICES = {
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}

# No credential is spelled "false". A boolean literal is always safe to show.
_BOOLEAN_LITERAL = re.compile(r"^(?:true|false|yes|no|on|off)$", re.IGNORECASE)
# A bare number is USUALLY config (timeouts, intervals) and worth reading -- but
# this platform's ADMIN_TOKEN is a ten-digit number, and the first version of
# this file wrote it to disk in plaintext because it matched. So a number is
# shown only when the KEY NAME is not secret-shaped.
_NUMERIC_LITERAL = re.compile(r"^[0-9]{1,10}$")
_SECRET_NAME = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH|SIGNATURE|SALT|"
    r"DSN|URL|URI|CONN|COOKIE|SESSION", re.IGNORECASE)

# The mirror lives OUTSIDE the git tree and outside OneDrive (`#625` practicals).
_DEFAULT_OUT = Path(os.environ.get("SYNDICATE_ENV_SNAPSHOT_DIR")
                    or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "syndicate_mirror" / "env"))


def _api_key(env_file: str = "") -> str:
    """The Render key, from the environment or a named `.env`.

    `.env` is GITIGNORED, so it exists in the primary tree and NOT in a session
    worktree — a script that only looks in its own `REPO_ROOT` works when run
    from the primary tree and dies in a worktree, which is where lane work
    happens. Order: explicit --env-file, then the process environment, then
    REPO_ROOT/.env, then the primary tree if one is configured.
    """
    candidates = []
    if env_file:
        candidates.append(Path(env_file))
    if os.environ.get("RENDER_API_KEY"):
        return os.environ["RENDER_API_KEY"].strip()
    candidates.append(REPO_ROOT / ".env")
    primary = os.environ.get("SYNDICATE_PRIMARY_TREE")
    if primary:
        candidates.append(Path(primary) / ".env")
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("RENDER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    raise SystemExit(
        "no RENDER_API_KEY. Set it in the environment, pass --env-file, or run "
        "from a tree that has .env (it is gitignored, so a worktree will not)."
    )


def redact(key: str, value: str) -> dict:
    """A value's IDENTITY without its content.

    `sha256[:12]` proves a change; `len` gives a sanity signal. Plaintext needs
    SHAPE and NAME to agree — see the module docstring; a shape-only rule wrote
    a live ten-digit `ADMIN_TOKEN` to disk.
    """
    text = "" if value is None else str(value)
    row = {"sha256_12": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "len": len(text)}
    if _BOOLEAN_LITERAL.match(text):
        row["value"] = text
    elif _NUMERIC_LITERAL.match(text) and not _SECRET_NAME.search(str(key or "")):
        row["value"] = text
    return row


def fetch_env(service_id: str, api_key: str) -> tuple[dict, int]:
    """Every env var for one service. Returns (rows, pages).

    PAGINATED. A single 100-row page reads as a complete list and is how a
    153-key service got reported as 100.
    """
    out: dict[str, str] = {}
    cursor = None
    pages = 0
    while True:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars?limit=100"
        if cursor:
            # Cursors are opaque and base64-ish -- '=' and '+' are ordinary in
            # them and must not be read as query syntax.
            url += "&cursor=" + urllib.parse.quote(str(cursor), safe="")
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=90) as response:
            rows = json.loads(response.read().decode("utf-8"))
        pages += 1
        if not rows:
            break
        for entry in rows:
            env_var = entry.get("envVar") or entry
            key = env_var.get("key")
            if key is not None:
                out[key] = env_var.get("value")
        cursor = rows[-1].get("cursor")
        if not cursor or len(rows) < 100 or pages > 25:
            break
    return out, pages


def snapshot(api_key: str) -> dict:
    taken_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    services: dict[str, dict] = {}
    for name, service_id in sorted(SERVICES.items()):
        raw, pages = fetch_env(service_id, api_key)
        # A snapshot that silently stops at a page boundary is worse than none:
        # it makes an ABSENT key indistinguishable from an UNREAD one, which is
        # precisely the inference this tool exists to support.
        truncated = pages == 1 and len(raw) >= 100
        services[name] = {
            "service_id": service_id,
            "key_count": len(raw),
            "pages_fetched": pages,
            "suspect_truncated": truncated,
            "keys": {key: redact(key, value) for key, value in sorted(raw.items())},
        }
    return {"taken_at": taken_at, "services": services}


def diff(before: dict, after: dict) -> list[str]:
    """What changed between two snapshots, per service."""
    lines: list[str] = []
    for name in sorted(set(before.get("services", {})) | set(after.get("services", {}))):
        a = (before.get("services") or {}).get(name) or {}
        b = (after.get("services") or {}).get(name) or {}
        ak, bk = a.get("keys") or {}, b.get("keys") or {}
        added = sorted(set(bk) - set(ak))
        removed = sorted(set(ak) - set(bk))
        changed = sorted(k for k in set(ak) & set(bk)
                         if ak[k].get("sha256_12") != bk[k].get("sha256_12"))
        if not (added or removed or changed):
            lines.append(f"{name}: no change ({len(bk)} keys)")
            continue
        lines.append(f"{name}: +{len(added)} -{len(removed)} ~{len(changed)}")
        for key in added:
            shown = bk[key].get("value")
            lines.append(f"    ADDED    {key}" + (f" = {shown}" if shown is not None else ""))
        for key in removed:
            lines.append(f"    REMOVED  {key}")
        for key in changed:
            before_v, after_v = ak[key].get("value"), bk[key].get("value")
            if before_v is not None or after_v is not None:
                lines.append(f"    CHANGED  {key}: {before_v} -> {after_v}")
            else:
                lines.append(f"    CHANGED  {key} (opaque: "
                             f"{ak[key]['sha256_12']} -> {bk[key]['sha256_12']})")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    ap.add_argument("--env-file", default="", help="path to a .env holding RENDER_API_KEY")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--against-latest", action="store_true",
                    help="after snapshotting, diff against the previous snapshot in --out")
    args = ap.parse_args()

    if args.diff:
        before = json.loads(Path(args.diff[0]).read_text(encoding="utf-8"))
        after = json.loads(Path(args.diff[1]).read_text(encoding="utf-8"))
        for line in diff(before, after):
            print(line)
        return 0

    out_dir = Path(args.out)
    # An EXISTING but EMPTY directory is the normal first-run state (and what a
    # cleanup leaves behind); indexing [-1] on it crashes before anything is written.
    prior = sorted(out_dir.glob("env_*.json")) if out_dir.is_dir() else []
    previous = prior[-1] if prior else None

    current = snapshot(_api_key(args.env_file))
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"env_{current['taken_at'].replace(':', '').replace('-', '')}.json"
    dest.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")

    print(f"{'service':<20}{'keys':>7}{'pages':>7}  note")
    print("-" * 56)
    failed = False
    for name, row in sorted(current["services"].items()):
        note = "SUSPECT TRUNCATED -- did not paginate?" if row["suspect_truncated"] else ""
        if row["suspect_truncated"]:
            failed = True
        print(f"{name:<20}{row['key_count']:>7}{row['pages_fetched']:>7}  {note}")
    print(f"\nwrote {dest}")

    if args.against_latest and previous:
        print(f"\ndiff vs {previous.name}:")
        for line in diff(json.loads(previous.read_text(encoding="utf-8")), current):
            print(f"  {line}")
    elif args.against_latest:
        print("\nno previous snapshot to diff against -- this is the baseline")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
