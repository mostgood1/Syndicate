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

`vendor/` is sibling-repo code pulled in verbatim, and it has 12 duplicates that
are upstream's, not ours. Failing on them would leave a permanently-red gate,
and a permanently-red gate gets muted -- which would cost us the owned-code
coverage that is the whole point. So the vendored set is PINNED in
`VENDOR_BASELINE` instead: exactly that set passes, anything NEW fails. That
matters because a vendor sync is precisely how a new one would arrive, and
because two of those files (`nba_betting_repo/app.py`,
`wnba_betting_repo/app.py`) are imported by owned code, so their dead
definitions sit inside modules we load.

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

# The vendored duplicates as measured 2026-09-06. Upstream's code; we do not
# edit it. Every one of these pairs DIFFERS -- they are not harmless copies --
# so if you are syncing a vendor repo and one of these disappears, that is
# upstream fixing it and the entry should be deleted here.
VENDOR_BASELINE: frozenset[str] = frozenset(
    {
        # EV math. Shadowed version takes `_american_to_b`; the live one parses
        # the american price itself and carries a docstring.
        "vendor/nba_betting_repo/app.py: _ev_from_prob_and_american",
        "vendor/wnba_betting_repo/app.py: _ev_from_prob_and_american",
        # CLI command registered twice; the live one adds an empty-frame guard.
        "vendor/nba_betting_repo/src/nba_betting/cli.py: fetch_rosters_cmd",
        "vendor/wnba_betting_repo/src/wnba_betting/cli.py: fetch_rosters_cmd",
        # Script-local rebinding in a linear script; harmless.
        "vendor/nba_betting_repo/tools/compute_props_reliability.py: out",
        "vendor/wnba_betting_repo/tools/compute_props_reliability.py: out",
        "vendor/nba_betting_repo/tools/compute_props_reliability_summary.py: cols_subset",
        "vendor/wnba_betting_repo/tools/compute_props_reliability_summary.py: cols_subset",
        # Typer commands. `props_project_all`'s shadowed def is a 3-line alias;
        # the live one is a ~514-line implementation.
        "vendor/nhl_betting_repo/nhl_betting/cli.py: props_collect",
        "vendor/nhl_betting_repo/nhl_betting/cli.py: props_project_all",
        # Shadowed `__all__` exports 2 names, live exports 4.
        "vendor/nhl_betting_repo/nhl_betting/data/shifts_api.py: __all__",
        "vendor/nhl_betting_repo/nhl_betting/scripts/backtest_daily_summary.py: main",
    }
)


def module_level_names(tree: ast.Module) -> list[tuple[str, int]]:
    """Every name bound at the module's own top level, with its line number."""
    names: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append((node.name, node.lineno))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append((node.target.id, node.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append((target.id, node.lineno))
                elif isinstance(target, (ast.Tuple, ast.List)):
                    # `A, B = ...` binds both; a repeat of either still shadows.
                    for element in target.elts:
                        if isinstance(element, ast.Name):
                            names.append((element.id, node.lineno))
    return names


def duplicates_in_source(source: str, filename: str) -> dict[str, list[int]]:
    """Names bound more than once at module level, mapped to their line numbers."""
    with warnings.catch_warnings():
        # This function ANALYSES source it never executes. Parsing vendored code
        # raises 13 `DeprecationWarning: invalid escape sequence` from upstream's
        # regex strings, and letting those into every test run's warning summary
        # is how a check earns a `-W ignore` that would also hide our own. They
        # already reach anyone who actually imports those modules.
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=filename)
    lines: dict[str, list[int]] = collections.defaultdict(list)
    for name, lineno in module_level_names(tree):
        lines[name].append(lineno)
    return {name: nums for name, nums in lines.items() if len(nums) > 1}


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
