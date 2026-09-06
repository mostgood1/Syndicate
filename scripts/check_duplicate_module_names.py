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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Scanned by default. `vendor/` is deliberately absent -- it is other people's
# code, vendored verbatim, and reformatting it would defeat the point of
# vendoring it.
DEFAULT_ROOTS = ("syndicate", "pipeline", "scripts", "tests")

# `<posix path>: <name>` entries that are known-good and deliberately exempt.
#
# IT IS EMPTY, AND THAT IS THE POINT. Every duplicate found when this check was
# written was either a real defect or an exact-value copy that could simply be
# deleted, so nothing needed an exemption. An allowlist with entries in it is a
# place for the next real one to hide -- if you are about to add a line here,
# prefer deleting the duplicate, and if you cannot, say why in the entry.
ALLOWLIST: frozenset[str] = frozenset()


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
    tree = ast.parse(source, filename=filename)
    lines: dict[str, list[int]] = collections.defaultdict(list)
    for name, lineno in module_level_names(tree):
        lines[name].append(lineno)
    return {name: nums for name, nums in lines.items() if len(nums) > 1}


def scan(roots: list[str], repo_root: Path | None = None) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return (findings, parse_errors) over every `*.py` under `roots`."""
    base = repo_root or REPO_ROOT
    findings: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for root in roots:
        root_path = base / root
        if not root_path.is_dir():
            errors.append({"path": root, "error": "not a directory"})
            continue
        for path in sorted(root_path.rglob("*.py")):
            rel = path.relative_to(base).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append({"path": rel, "error": "%s: %s" % (type(exc).__name__, exc)})
                continue
            try:
                dupes = duplicates_in_source(source, rel)
            except SyntaxError as exc:
                errors.append({"path": rel, "error": "SyntaxError: %s" % exc})
                continue
            for name, linenos in sorted(dupes.items()):
                if "%s: %s" % (rel, name) in ALLOWLIST:
                    continue
                findings.append({"path": rel, "name": name, "lines": linenos})
    return findings, errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS), help="directories to scan (default: %s)" % " ".join(DEFAULT_ROOTS))
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    findings, errors = scan(args.roots)

    if args.as_json:
        print(json.dumps({"ok": not findings and not errors, "roots": args.roots, "findings": findings, "errors": errors}, indent=2))
        if errors:
            return 2
        return 1 if findings else 0

    for error in errors:
        print("ERROR  %s -- %s" % (error["path"], error["error"]))
    for finding in findings:
        lines = ", ".join(str(num) for num in finding["lines"])
        print("DUPLICATE  %s: `%s` defined %d times (lines %s)" % (finding["path"], finding["name"], len(finding["lines"]), lines))

    if findings:
        print()
        print("%d duplicate module-level name(s). Python keeps the LAST binding, so" % len(findings))
        print("every definition but the last is dead code. Diff them before deleting:")
        print("they may be identical, or the shadowed one may hold a fix that has")
        print("silently not been running.")
        return 1
    if errors:
        return 2
    print("ok  no module-level name is defined twice in %s" % ", ".join(args.roots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
