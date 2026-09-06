"""Fail if any module-level name is defined more than once.

WHY THIS EXISTS, in three measured instances rather than in principle.

Python keeps the LAST binding of a module-level name. A second `def` of a name
that already exists is not an error, not a warning, and not visible in a diff
that does not happen to show both definitions -- so the FIRST one silently stops
existing while continuing to look like live code.

  1. `syndicate/features/shared/memory_observability.py` -- `_MALLOC_TRIM_STATE`
     and `_resolve_malloc_trim`, each defined twice ~1,900 lines apart. The
     shadowed pair was `#285`'s. Losing it killed the one-time `MALLOC_TRIM_INIT`
     log line, which existed *because* the binding cannot be exercised off Linux
     and a production log line was its only proof, and it reverted `daed5d92`
     ("hold the CDLL, not just the function pointer taken off it") by keeping
     only the pointer. `malloc_trim` still bound and still trimmed; what was lost
     was the EVIDENCE that it had. Fixed in `67af1276`.
  2. `syndicate/features/nba/live_lens.py` -- `build_live_lens_api_payload` twice.
     Benign in the end: the two bodies computed the same payload through
     different aliases of the same functions.
  3. `tests/test_venue_settlement.py` -- three `test_the_repair_*` names collided
     across two DIFFERENT repairs, so three tests of `repair_multi_side_grades`
     had never run once. Money-adjacent settlement invariants, green forever
     because they were never collected.

Note the spread: the first cost a production proof, the second cost nothing, the
third silently disabled tests. The failure mode does not announce which kind it
is, which is the argument for a check rather than for review attention.

ASSIGNMENTS are counted too, not just `def`/`class` -- instance 1 was half
assignment. Only the module's own top level is scanned (`tree.body`), so the
ordinary conditional-definition patterns (`try: import x / except ImportError:`,
`if TYPE_CHECKING:`, `if sys.platform == ...:`) are nested and never flagged.

TWO TIERS, because `vendor/` is not ours to rewrite
---------------------------------------------------
Owned code (`.`, `syndicate/`, `pipeline/`, `scripts/`, `tests/`) must be clean;
any finding fails. `ALLOWLIST` is empty and should stay that way.

`vendor/` is sibling-repo code pulled in verbatim. It had 12 findings; the five
that were genuinely dead have been deleted, five more turned out not to be
duplicates at all (see `duplicates_in_source`), and the two that remain are
upstream's to reconcile rather than ours. Those are PINNED in `VENDOR_BASELINE`:
exactly that set passes, anything NEW fails. Failing on them instead would leave
a permanently-red gate, and a permanently-red gate gets muted -- which would cost
the owned-code coverage that is the whole point. Pinning also means a vendor
sync, which is precisely how a new one would arrive, cannot slip one in.

A baseline entry that no longer matches anything is reported as STALE and also
fails, so the pin cannot quietly rot into a general-purpose allowlist.

Usage:
    python scripts/check_duplicate_module_names.py
    python scripts/check_duplicate_module_names.py --json
    python scripts/check_duplicate_module_names.py --roots syndicate pipeline

Exit codes: 0 clean, 1 duplicates found, 2 a file could not be parsed.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# `.` means the repo-root `*.py` files themselves, NOT a recursive walk of the
# whole tree -- recursing from `.` would drag in `data/`, `.venv/` and every
# other root we do not mean.
ROOT_LEVEL = "."

DEFAULT_ROOTS = (ROOT_LEVEL, "syndicate", "pipeline", "scripts", "tests", "vendor")

# Roots whose findings are pinned rather than failed. See the two-tier note above.
VENDOR_ROOTS = ("vendor",)

# `<posix path>: <name>` entries in OWNED code that are known-good and exempt.
#
# IT IS EMPTY, AND THAT IS THE POINT. Every duplicate found in owned code when
# this check was written was either a real defect or an exact-value copy that
# could simply be deleted, so nothing needed an exemption. An allowlist with
# entries in it is a place for the next real one to hide -- if you are about to
# add a line here, prefer deleting the duplicate, and if you cannot, say why.
ALLOWLIST: frozenset[str] = frozenset()

# What is left of the vendored set after 2026-09-06.
#
# Twelve were found. FIVE were genuinely dead and were DELETED from vendor/ --
# `_ev_from_prob_and_american` x2, `props_collect`, `props_project_all`, and
# `__all__` in `shifts_api.py` -- verified by comparing each file's OBSERVABLE
# surface before and after (EV results over 13 inputs, all 89 Typer commands with
# their callbacks and params, the `__all__` value): identical.
#
# FIVE more were never duplicates at all and are no longer reported, because
# `duplicates_in_source` now requires the earlier binding to be DEAD: `out` x2 and
# `cols_subset` x2 are sequential rebindings whose successor consumes them, and
# `backtest_daily_summary.py`'s `main` is read at module level by an
# `if __name__ == '__main__':` block sitting between the two definitions.
#
# These TWO remain, and they are the interesting shape: the module-level NAME is
# dead, but the OBJECT is not. Click registers each function when it is decorated,
# and here the two decorators give DIFFERENT command names, so both survive --
# verified against click 8.1.7, the group ends up with `fetch-rosters-cmd` AND
# `fetch-rosters`. Deleting the shadowed def would delete a working CLI command.
# Pinned rather than fixed: they are upstream's to reconcile.
VENDOR_BASELINE: frozenset[str] = frozenset(
    {
        "vendor/nba_betting_repo/src/nba_betting/cli.py: fetch_rosters_cmd",
        "vendor/wnba_betting_repo/src/wnba_betting/cli.py: fetch_rosters_cmd",
    }
)


def module_level_names(tree: ast.Module) -> list[tuple[str, int, int]]:
    """Every name bound at the module's own top level, as (name, start, end).

    `end` is the last line of the binding STATEMENT, which is what the liveness
    window needs: a decorated `def` starts at its first decorator and ends at the
    last line of its body.
    """
    names: list[tuple[str, int, int]] = []
    for node in tree.body:
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", None) or start
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators = [d.lineno for d in node.decorator_list]
            names.append((node.name, min([start] + decorators), end))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append((node.target.id, start, end))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append((target.id, start, end))
                elif isinstance(target, (ast.Tuple, ast.List)):
                    # `A, B = ...` binds both; a repeat of either still shadows.
                    for element in target.elts:
                        if isinstance(element, ast.Name):
                            names.append((element.id, start, end))
    return names


def _module_level_reads(tree: ast.Module, name: str, lo: int, hi: int) -> bool:
    """Is `name` READ by module-level code with lo < lineno <= hi?

    `<= hi` is deliberate: `hi` is the END of the next binding, so that binding's
    own right-hand side counts. `cols_subset = [c for c in cols_subset if ...]`
    consumes the previous value, and a strict `<` window calls that dead.

    Function and class bodies are skipped -- they run when called, by which point
    the LAST binding has already won, so a read there says nothing about whether
    the earlier binding was used.
    """
    found = False

    def scan(stmt: ast.stmt) -> None:
        nonlocal found
        for node in ast.walk(stmt):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                if lo < getattr(node, "lineno", 0) <= hi:
                    found = True
                    return

    def descend(body: list[ast.stmt]) -> None:
        for stmt in body:
            if found:
                return
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            scan(stmt)
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, field, None)
                if isinstance(inner, list):
                    descend(inner)
            for handler in getattr(stmt, "handlers", []) or []:
                descend(handler.body)

    descend(tree.body)
    return found


def duplicates_in_source(source: str, filename: str) -> dict[str, list[int]]:
    """Names whose EARLIER module-level binding is dead, mapped to all their lines.

    "Bound twice" is not the same as "the first one is dead". A linear script that
    does `out = df.agg(...)` / uses `out` / `out = out[cols]` binds the name twice
    on purpose, and deleting the first gives a `NameError` -- measured on
    `vendor/*/tools/compute_props_reliability.py`, where an earlier version of
    this function reported exactly that as a duplicate. So a rebinding is only
    reported when nothing READS the earlier value before it is replaced, which is
    the actual definition of a dead store.

    Verified not to weaken the cases this check exists for: run against
    `memory_observability.py` at `67af1276^`, it still reports both
    `_MALLOC_TRIM_STATE` and `_resolve_malloc_trim`.

    NOT covered, deliberately: a shadowed binding that is dead by this rule but
    whose OBJECT was captured elsewhere -- `@cli.command()` registers the function
    in a Click group, so it stays reachable under its own command name even though
    the module name is rebound. Those are still reported (the name IS dead), and
    the report is right, but "dead name" does not imply "safe to delete". Diff the
    two definitions before removing either.
    """
    with warnings.catch_warnings():
        # This function ANALYSES source it never executes. Parsing vendored code
        # raises 13 `DeprecationWarning: invalid escape sequence` from upstream's
        # regex strings, and letting those into every test run's warning summary
        # is how a check earns a `-W ignore` that would also hide our own. They
        # already reach anyone who actually imports those modules.
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=filename)

    bound: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for name, lineno, end_lineno in module_level_names(tree):
        bound[name].append((lineno, end_lineno))

    reported: dict[str, list[int]] = {}
    for name, spans in bound.items():
        if len(spans) < 2:
            continue
        spans.sort()
        # Report only if some EARLIER binding is never read before the next one
        # replaces it. That is the dead-store test; a rebinding whose value is
        # consumed in between is ordinary linear code, not a shadowed definition.
        dead = any(
            not _module_level_reads(tree, name, spans[i][1], spans[i + 1][1])
            for i in range(len(spans) - 1)
        )
        if dead:
            reported[name] = [lineno for lineno, _ in spans]
    return reported


def is_vendor(rel_path: str) -> bool:
    return any(rel_path == root or rel_path.startswith(root + "/") for root in VENDOR_ROOTS)


def iter_python_files(base: Path, root: str):
    """`.` yields the repo-root files only; anything else is a recursive walk."""
    if root == ROOT_LEVEL:
        return sorted(base.glob("*.py"))
    return sorted((base / root).rglob("*.py"))


def scan(roots: list[str], repo_root: Path | None = None) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return (findings, parse_errors) over every `*.py` under `roots`."""
    base = repo_root or REPO_ROOT
    findings: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for root in roots:
        if root != ROOT_LEVEL and not (base / root).is_dir():
            errors.append({"path": root, "error": "not a directory"})
            continue
        for path in iter_python_files(base, root):
            rel = path.relative_to(base).as_posix()
            try:
                # `utf-8-sig`, NOT `utf-8`: Python's own import machinery strips a
                # BOM, and reading as plain utf-8 makes every BOM'd file raise
                # `SyntaxError: invalid non-printable character U+FEFF` and be
                # SKIPPED. Measured over `vendor/`: `utf-8` skips 46 files and
                # reports 10 duplicates; `utf-8-sig` skips 0 and reports 12. A
                # parse error that drops a file is the unknown-defaults-permissive
                # shape -- a findings-only summary cannot tell an unread file from
                # a clean one -- so it must not recur.
                source = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append({"path": rel, "error": "%s: %s" % (type(exc).__name__, exc)})
                continue
            try:
                dupes = duplicates_in_source(source, rel)
            except SyntaxError as exc:
                errors.append({"path": rel, "error": "SyntaxError: %s" % exc})
                continue
            for name, linenos in sorted(dupes.items()):
                findings.append({"path": rel, "name": name, "lines": linenos, "key": "%s: %s" % (rel, name)})
    return findings, errors


def classify(findings: list[dict[str, object]], roots: list[str]) -> dict[str, list]:
    """Split findings into the tiers that decide the exit code."""
    owned: list[dict[str, object]] = []
    vendor_new: list[dict[str, object]] = []
    vendor_pinned: list[dict[str, object]] = []
    for finding in findings:
        key = str(finding["key"])
        if is_vendor(str(finding["path"])):
            (vendor_pinned if key in VENDOR_BASELINE else vendor_new).append(finding)
        elif key not in ALLOWLIST:
            owned.append(finding)

    # Only judge the pin for completeness when vendor was actually scanned --
    # `--roots syndicate` must not report all 12 as stale.
    vendor_scanned = any(root in VENDOR_ROOTS for root in roots)
    seen = {str(f["key"]) for f in vendor_pinned}
    stale = sorted(VENDOR_BASELINE - seen) if vendor_scanned else []
    return {"owned": owned, "vendor_new": vendor_new, "vendor_pinned": vendor_pinned, "stale": stale}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS), help="directories to scan; '.' means the repo-root *.py files only (default: %s)" % " ".join(DEFAULT_ROOTS))
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable output")
    return parser.parse_args(argv)


def _render(finding: dict[str, object], label: str) -> str:
    lines = ", ".join(str(num) for num in finding["lines"])  # type: ignore[index]
    return "%s  %s: `%s` defined %d times (lines %s)" % (label, finding["path"], finding["name"], len(finding["lines"]), lines)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    findings, errors = scan(args.roots)
    tiers = classify(findings, args.roots)

    if args.as_json:
        ok = not errors and not tiers["owned"] and not tiers["vendor_new"] and not tiers["stale"]
        print(json.dumps({"ok": ok, "roots": args.roots, **tiers, "errors": errors}, indent=2))
        if errors:
            return 2
        return 0 if ok else 1

    for error in errors:
        print("ERROR  %s -- %s" % (error["path"], error["error"]))
    for finding in tiers["owned"]:
        print(_render(finding, "DUPLICATE"))
    for finding in tiers["vendor_new"]:
        print(_render(finding, "NEW-IN-VENDOR"))
    for key in tiers["stale"]:
        print("STALE-PIN  %s -- in VENDOR_BASELINE but no longer present; delete the entry" % key)

    if tiers["owned"]:
        print()
        print("%d duplicate module-level name(s) in owned code. Python keeps the LAST" % len(tiers["owned"]))
        print("binding, so every definition but the last is dead code. Diff them before")
        print("deleting: they may be identical, or the shadowed one may hold a fix that")
        print("has silently not been running.")
    if tiers["vendor_new"]:
        print()
        print("%d NEW duplicate(s) under vendor/, not in VENDOR_BASELINE. If a vendor" % len(tiers["vendor_new"]))
        print("sync brought this in, diff the two definitions and add it to the pin with")
        print("a note saying which is live and how they differ.")

    if tiers["owned"] or tiers["vendor_new"] or tiers["stale"]:
        return 1
    if errors:
        return 2
    print("ok  no module-level name is defined twice in %s" % ", ".join(args.roots))
    if tiers["vendor_pinned"]:
        print("    (%d known vendored duplicate(s) pinned in VENDOR_BASELINE, unchanged)" % len(tiers["vendor_pinned"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
