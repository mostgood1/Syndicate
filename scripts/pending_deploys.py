"""What is committed on `origin/main` and NOT yet running, per service.

WHY THIS EXISTS RATHER THAN A HAND-WRITTEN LIST. A list of "commits waiting to
deploy" is stale the moment another lane pushes, and this repo has had four
sessions pushing to `main` in the same hour. Every number here is re-derived on
each run from the LIVE commit each service actually reports.

WHY IT DOES NOT COUNT "COMMITS BEHIND". Every service runs a curated deploy
branch cut from a live SHA, never `main`, so `rev-list --count live..main`
reports 600-700 and means almost nothing. What matters is the far smaller set of
commits that touch code the service actually executes.

WHAT IT DELIBERATELY DOES NOT DO. It does not tell you a deploy is safe. Job
liveness, the deploy claim and the render.yaml blast radius are
`deploy_preflight.py`'s job, and a second tool answering the same question
differently is worse than no second tool.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Which service EXECUTES a given path. `shared` is listed against every service
# on purpose: `syndicate/features/shared/` is imported by the web app and by both
# workers, and treating it as web-only is how a worker-side fix gets deployed to
# the wrong service. That mistake was made tonight -- Phase 1c targets
# `live_refresh_loop.py`, which only live-odds-worker runs for soccer.
PATH_OWNERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("syndicate/blueprints/", ("web",)),
    ("syndicate/templates/", ("web",)),
    ("syndicate/static/", ("web",)),
    ("scripts/run_refresh_worker.py", ("refresh-worker",)),
    ("scripts/run_live_odds_refresh_worker.py", ("live-odds-worker",)),
    ("pipeline/", ("refresh-worker",)),
    ("syndicate/features/shared/", ("web", "refresh-worker", "live-odds-worker")),
    ("syndicate/features/", ("web", "refresh-worker", "live-odds-worker")),
    ("vendor/", ("refresh-worker",)),
    # `scripts/` is resolved by `_owners` via `_executed_scripts` below; this
    # row is the FALLBACK owner set, used when reachability cannot be computed.
    ("scripts/", ("refresh-worker", "live-odds-worker")),
)
#: Where runtime code lives. A script NAMED anywhere in here is executed.
_RUNTIME_ROOTS = ("syndicate", "pipeline", "vendor")
#: Seeds for the reachability closure: what Render actually starts.
_RUNTIME_SEED_FILES = (
    "wsgi.py",
    "app.py",
    "render.yaml",
    "scripts/run_refresh_worker.py",
    "scripts/run_live_odds_refresh_worker.py",
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _strip_comments(src: str) -> str:
    """`src` with `#` comments removed; unchanged if it will not tokenise.

    A script is judged executed by whether runtime code NAMES it, and prose
    names things too. Measured: `deploy_preflight` was classified RUNTIME
    because `syndicate/blueprints/ops.py:1747` mentions it IN A COMMENT, and
    three more tooling scripts matched transitively the same way.

    Only comments are stripped -- never string literals, because a subprocess
    launch IS a string literal (`"scripts/build_soccer_artifacts.py"`) and
    dropping those would cause a false INERT, the dangerous direction. On any
    tokenise failure the raw text is returned, which can only over-report.
    """
    try:
        import io
        import tokenize

        out = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                out.append(tok.string)
        return "\n".join(out)
    except Exception:
        return src


def _executed_scripts():
    """Basenames under `scripts/` that runtime code NAMES, transitively.

    WHY THIS EXISTS. The `("scripts/", both workers)` row above attributes EVERY
    script to both workers. Four consecutive catch-up rounds (2026-09-03/04) then
    reported lane-guard and ledger tooling as pending runtime code, and each had
    to be dismissed by hand-reading the file list. The judgement is mechanical;
    this makes it so.

    **`scripts/` IS NOT UNIFORMLY INERT**, which is why this is a reachability
    closure and not a prefix rule. The workers really do execute
    `refresh_odds_sources.py`, `build_soccer_artifacts.py` and
    `run_mlb_daily_sim_job.py` -- all three observed in `deploy_preflight.py`'s
    live job listing on 2026-09-03/04. A "scripts are inert" shortcut would have
    hidden every one of them.

    **CONSERVATIVE BY CONSTRUCTION.** The failure modes are asymmetric, exactly
    as in `check_lane_invariants` (`learnings.md` 2026-09-03): a false RUNTIME is
    noise, a false INERT HIDES A NEEDED DEPLOY. So a script is demoted only when
    the closure proves no runtime file names it, and `None` -- "cannot tell,
    treat every script as executed" -- is returned if the tree cannot be read.

    TRANSITIVE, because launches chain: `run_refresh_worker.py` starts
    `run_mlb_daily_sim_job.py`, which starts `daily_update.py`, which starts
    vendor tools. A one-hop scan would call the last of those inert.
    """
    scripts_dir = REPO_ROOT / "scripts"
    if not scripts_dir.is_dir():
        return None

    corpus = []
    for root in _RUNTIME_ROOTS:
        base = REPO_ROOT / root
        if base.is_dir():
            corpus.extend(_strip_comments(_read_text(f)) for f in base.rglob("*.py"))
    for rel in _RUNTIME_SEED_FILES:
        corpus.append(_strip_comments(_read_text(REPO_ROOT / rel)))
    if not any(corpus):
        return None

    blob = "\n".join(corpus)
    candidates = {f.stem: f for f in scripts_dir.glob("*.py")}
    executed = set()
    changed = True
    while changed:
        changed = False
        for stem, path in candidates.items():
            if stem in executed:
                continue
            # Named as a module (`import x`, `-m x`) or as a file (`x.py`).
            if stem in blob or (stem + ".py") in blob:
                executed.add(stem)
                blob += "\n" + _strip_comments(_read_text(path))
                changed = True
    return frozenset(executed)


_EXECUTED_SCRIPTS = _executed_scripts()


# Paths that change nothing at runtime. Excluded so the manifest reports work,
# not noise -- ledger churn alone is ~73 files per service.
INERT_PREFIXES = (".syndicate/", "docs/", "reports/", "data/", "tests/")


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def _owners(path: str) -> tuple[str, ...]:
    for prefix, owners in PATH_OWNERS:
        if path.startswith(prefix):
            # `scripts/` is the one prefix whose members are not all executed.
            # Demote ONLY on proof; `None` means the closure could not be
            # computed, so the conservative owners stand.
            if prefix == "scripts/" and _EXECUTED_SCRIPTS is not None:
                if Path(path).stem not in _EXECUTED_SCRIPTS:
                    return ()
            return owners
    return ()


def _live_commits() -> dict[str, str]:
    """Deployed SHA per service, read from deploy_preflight (the one source)."""
    raw = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "deploy_preflight.py"),
         "--service", "web"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout.replace("\r", "")
    out: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in {"web", "refresh-worker", "live-odds-worker"}:
            out[parts[0]] = parts[1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args()

    _git("fetch", "-q", "origin")
    base = _git("rev-parse", args.base)
    live = _live_commits()
    if not live:
        print("could not read live commits from deploy_preflight -- refusing to guess", file=sys.stderr)
        return 2

    report: dict[str, dict] = {}
    for service, sha in sorted(live.items()):
        commits = []
        log = _git("log", "--format=%H\x1f%s", f"{sha}..{base}")
        for line in log.splitlines():
            if "\x1f" not in line:
                continue
            full, subject = line.split("\x1f", 1)
            files = [
                f for f in _git("show", "--pretty=", "--name-only", full).splitlines()
                if f and not f.startswith(INERT_PREFIXES)
            ]
            owned = sorted({f for f in files if service in _owners(f)})
            if owned:
                commits.append({"sha": full[:8], "subject": subject, "files": owned})
        report[service] = {
            "live": sha,
            "pending_code_commits": len(commits),
            "commits": commits,
        }

    if args.json:
        print(json.dumps({"base": base[:8], "services": report}, indent=2))
        return 0

    print(f"# pending deploys against {args.base} ({base[:8]})")
    print("# only commits touching code the service EXECUTES; ledger/docs/data/tests excluded")
    if _EXECUTED_SCRIPTS is not None:
        total = len(list((REPO_ROOT / "scripts").glob("*.py")))
        print(
            f"# scripts/ reachability: {len(_EXECUTED_SCRIPTS)} of {total} are named by "
            "runtime code; the rest are tooling and are excluded"
        )
    for service, data in report.items():
        print(f"\n== {service}   live={data['live']}   {data['pending_code_commits']} pending code commit(s)")
        for c in data["commits"]:
            print(f"   {c['sha']}  {c['subject'][:78]}")
            for f in c["files"][:4]:
                print(f"        {f}")
    # THE VERDICT LINE. This tool existed to LIST drift; the question actually
    # being asked of it, ten catch-up rounds running, was "is a deploy worth a
    # reboot". Answer it here rather than leaving it to be re-derived by reading
    # file lists -- that re-derivation is what made rounds 8 and 11 no-ops and
    # nearly made round 10 a duplicate of a peer's in-flight deploy.
    warranted = [s for s, d in report.items() if d["pending_code_commits"]]
    print()
    if _EXECUTED_SCRIPTS is None:
        print("# NOTE: script reachability could not be computed; every scripts/ path")
        print("#       is being treated as executed (conservative fallback).")
    if warranted:
        print(f"VERDICT: deploy warranted for {', '.join(sorted(warranted))}")
        print("         (each has >=1 pending commit touching code it EXECUTES)")
    else:
        print("VERDICT: NO DEPLOY WARRANTED -- every service is current in the only")
        print("         sense that matters. Any remaining drift is files no service")
        print("         runs, and a reboot to ship it is pure cost (~21 min to first")
        print("         board publish on refresh-worker, `#563`).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
