#!/usr/bin/env python3
"""What is waiting on the coordinator, right now. Read-only.

WHY THIS EXISTS. The coordinator was told twice on 2026-08-17 that lanes were
reaching out and getting no answer. Both times the information was sitting in
the ledger the whole time -- unattended sessions cannot send a message
(`coordinator.md` s4a), so the ONLY way they reach the coordinator is by writing
a file. Nothing surfaced that, so "did anyone ask me something" depended on the
coordinator remembering to grep. That is exactly the shape of rule the
coordination protocol says always fails.

Run this at the START of every coordinator turn, before doing any deploy work.

It answers four questions and deliberately does not try to be clever:
  1. What is in the deploy queue, and is the local view stale against origin?
  2. Which ledger lines added since <ref> address the coordinator?
  3. Which requests in done/ were closed WITHOUT an outcome recorded?
  4. Which deploy rows are still owed a measurement?

Usage:  py -3 scripts/coordinator_inbox.py [--since <git-ref>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYN = ROOT / ".syndicate"
LEDGER = ["state.md", "lanes.md", "deploys.md", "learnings.md"]


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=120)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else ""


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def queue() -> None:
    section("DEPLOY QUEUE")
    local_req = sorted(p.name for p in (SYN / "deploy" / "requests").glob("*.md"))
    remote = [l.rsplit("/", 1)[-1] for l in
              git("ls-tree", "-r", "--name-only", "origin/main",
                  "--", ".syndicate/deploy/requests").splitlines() if l.strip()]
    for name in sorted(set(local_req) | set(remote)):
        where = []
        if name in local_req:
            where.append("local")
        if name in remote:
            where.append("origin")
        flag = "" if len(where) == 2 else "   <-- ONLY IN " + where[0].upper()
        print(f"  PENDING  {name}{flag}")
    if not (local_req or remote):
        print("  (empty)")

    # A request in done/ with no outcome is a silent close.
    section("CLOSED WITHOUT AN OUTCOME (should be none)")
    bad = []
    for p in sorted((SYN / "deploy" / "done").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"(CLOSED|EXECUTED|OUTCOME|WITHDRAWN)", text):
            bad.append(p.name)
    print("  " + ("\n  ".join(bad) if bad else "(none)"))


def asks(since: str) -> None:
    section(f"LEDGER LINES ADDRESSING THE COORDINATOR, added since {since}")
    diff = git("diff", f"{since}..origin/main", "--", ".syndicate/")
    hits = [l[1:].strip() for l in diff.splitlines()
            if l.startswith("+") and not l.startswith("+++")
            and re.search(r"(?i)coordinator|owed to|handed (to|off)|queued for|"
                          r"asked the|blocked by:.*coordinator", l)]
    if not hits:
        print("  (nothing new)")
    for h in hits[:40]:
        print(f"  - {h[:150]}")
    if len(hits) > 40:
        print(f"  ... and {len(hits) - 40} more")


def obligations() -> None:
    section("DEPLOY ROWS STILL OWED A MEASUREMENT")
    text = (SYN / "deploys.md").read_text(encoding="utf-8", errors="replace")
    pending = text.count("<pending>")
    reconciled = len(re.findall(r"^- RECONCILED:", text, re.M))
    owed = max(0, pending - reconciled)
    print(f"  markers {pending}, reconciled {reconciled}  ->  OWED {owed}")
    if owed:
        print("  (find them: grep -n '<pending>' .syndicate/deploys.md, then")
        print("   check each has a matching '- RECONCILED:' line)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="HEAD~1",
                    help="git ref to diff the ledger against (default HEAD~1)")
    a = ap.parse_args()
    git("fetch", "-q", "origin")
    queue()
    asks(a.since)
    obligations()
    print("\nRun this BEFORE deploy work, not after. Unattended sessions cannot "
          "message you; the ledger is their only channel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
