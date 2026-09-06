"""No module-level name in this repo is defined twice.

The per-file version of this invariant lives in `tests/test_malloc_info_arenas.py`,
pinned there after a duplicate definition silently killed `#285`'s
`MALLOC_TRIM_INIT` proof line and reverted `daed5d92`. Two more instances turned
up in an AST sweep afterwards -- `syndicate/features/nba/live_lens.py` and
`tests/test_venue_settlement.py`, the latter of which had three settlement tests
that had never run -- so the invariant is repo-wide from here.

`scripts/check_duplicate_module_names.py` carries the reasoning and is the CLI
form; this file is what makes CI enforce it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_duplicate_module_names as checker  # noqa: E402
from scripts.check_duplicate_module_names import DEFAULT_ROOTS  # noqa: E402
from scripts.check_duplicate_module_names import duplicates_in_source  # noqa: E402
from scripts.check_duplicate_module_names import classify  # noqa: E402
from scripts.check_duplicate_module_names import scan  # noqa: E402

SHADOWED = "\n".join(["def f():", "    return 1", "", "", "def f():", "    return 2", ""])


# --- the detector itself -----------------------------------------------------


def test_the_check_actually_detects_a_duplicate():
    """OFF != ON. A check whose only evidence is that it returns clean has not
    been shown able to return anything else -- and this repo has shipped inert
    guards before. Establish the positive reading first."""
    assert duplicates_in_source(SHADOWED, "<synthetic>") == {"f": [1, 5]}


def test_it_counts_assignments_and_classes_not_only_defs():
    """The `memory_observability` instance was half assignment (`_MALLOC_TRIM_STATE`),
    so a `def`-only scan would have missed the half that mattered."""
    source = "\n".join(
        [
            "STATE = {}",
            "class C:",
            "    pass",
            "STATE = {'replaced': True}",
            "class C:",
            "    pass",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {"STATE": [1, 4], "C": [2, 5]}


def test_a_conditional_definition_is_not_a_duplicate():
    """`try/except ImportError` and `if TYPE_CHECKING:` bind the same name on
    purpose and only one branch runs. They are nested, not module-level, so the
    check must leave them alone -- otherwise it gets muted for noise."""
    source = "\n".join(
        [
            "import sys",
            "try:",
            "    import ujson as json_impl",
            "except ImportError:",
            "    import json as json_impl",
            "if sys.platform == 'win32':",
            "    SEP = '\\\\'",
            "else:",
            "    SEP = '/'",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {}


def test_a_file_with_a_BOM_is_read_not_skipped(tmp_path):
    """REGRESSION. The scanner read sources as `utf-8`, so a BOM became
    `SyntaxError: invalid non-printable character U+FEFF` and the file was
    SKIPPED. Measured over `vendor/`: `utf-8` skips 46 files and finds 10
    duplicates; `utf-8-sig` skips 0 and finds 12. Python's own import machinery
    decodes with `utf-8-sig`, so those files import fine -- only the checker
    could not read them. A parse error that silently drops a file is the
    unknown-defaults-permissive shape, so this is pinned rather than left to the
    next reader."""
    (tmp_path / "bommed.py").write_text(SHADOWED, encoding="utf-8-sig")
    findings, errors = scan(["."], repo_root=tmp_path)
    assert errors == [], "a BOM must not read as a parse error: %r" % (errors,)
    assert [f["key"] for f in findings] == ["bommed.py: f"]


# --- "bound twice" is not the same as "the first one is dead" ----------------


def test_a_live_sequential_rebinding_is_not_a_duplicate():
    """A linear script that builds a frame, uses it, then narrows it binds the
    name twice ON PURPOSE. Reporting that is a false positive, and acting on it
    is a `NameError`: measured on `vendor/*/tools/compute_props_reliability.py`,
    where `out = grp.agg(...)` / `out['bin_low'] = ...` / `out = out[keep]` was
    reported as a duplicate by an earlier version of this check."""
    source = "\n".join(
        [
            "out = compute()",
            "out['extra'] = 1",
            "out = out[['extra']]",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {}


def test_the_second_bindings_own_right_hand_side_counts_as_a_read():
    """`cols_subset = [c for c in cols_subset if ...]` consumes the first value on
    the very next line. A liveness window that stops BEFORE the second binding
    calls this dead -- which is exactly the off-by-one that nearly shipped a
    NameError into two vendored scripts."""
    source = "\n".join(
        [
            "cols = ['a', 'b']",
            "cols = [c for c in cols if c]",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {}


def test_a_dead_store_IS_still_reported():
    """The other half of the same rule -- without this, the liveness refinement
    would have quietly turned the check off."""
    source = "\n".join(["x = expensive()", "x = 2", ""])
    assert duplicates_in_source(source, "<synthetic>") == {"x": [1, 2]}


def test_a_read_inside_a_function_body_does_not_keep_the_first_binding_alive():
    """A function body runs when it is CALLED, by which point the last binding has
    won. So a reference there is not evidence the first binding was used -- it is
    evidence of the opposite, which is the whole `memory_observability` failure."""
    source = "\n".join(
        [
            "HANDLER = first",
            "def use():",
            "    return HANDLER",
            "HANDLER = second",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {"HANDLER": [1, 4]}


def test_a_dead_NAME_can_still_have_a_live_OBJECT():
    """REPORTED IS NOT THE SAME AS SAFE TO DELETE, and this is the case that
    proves it. A decorator captures the function when it is defined; rebinding the
    module name afterwards does not unregister it. In
    `vendor/*/src/*/cli.py` the two `fetch_rosters_cmd` decorators name their
    commands DIFFERENTLY, so click 8.1.7 ends up with both `fetch-rosters-cmd` and
    `fetch-rosters` -- deleting the "shadowed" def deletes a working command.
    The check still reports it, which is right; the judgement is a human's."""
    source = "\n".join(
        [
            "@cli.command()",
            "def cmd():",
            "    pass",
            "@cli.command('other-name')",
            "def cmd():",
            "    pass",
            "",
        ]
    )
    assert duplicates_in_source(source, "<synthetic>") == {"cmd": [1, 4]}


# --- the two roots this file was extended for --------------------------------


def test_repo_root_and_vendor_are_both_scanned_by_default():
    assert "." in DEFAULT_ROOTS, "repo-root *.py files (app.py, wsgi.py, ...) must be covered"
    assert "vendor" in DEFAULT_ROOTS, "vendored sibling-repo code must be covered"


def test_the_repo_root_entry_does_not_recurse(tmp_path):
    """`.` means the repo-root files THEMSELVES. Recursing from `.` would drag in
    `data/` (34k+ files) and `.venv/`, which is why it is a special case rather
    than just another root."""
    (tmp_path / "top.py").write_text(SHADOWED, encoding="utf-8")
    nested = tmp_path / "data" / "deep"
    nested.mkdir(parents=True)
    (nested / "buried.py").write_text(SHADOWED, encoding="utf-8")
    findings, errors = scan(["."], repo_root=tmp_path)
    assert errors == []
    assert [f["key"] for f in findings] == ["top.py: f"]


def test_a_duplicate_in_a_repo_root_file_is_owned_and_fails(tmp_path):
    """off != on for the repo-root tier."""
    (tmp_path / "app.py").write_text(SHADOWED, encoding="utf-8")
    findings, _ = scan(["."], repo_root=tmp_path)
    tiers = classify(findings, ["."])
    assert [f["key"] for f in tiers["owned"]] == ["app.py: f"]
    assert tiers["vendor_new"] == []


def test_a_NEW_duplicate_under_vendor_fails_even_though_vendor_is_pinned(tmp_path):
    """The pin freezes the KNOWN vendored set; it is not a blanket exemption. A
    vendor sync is exactly how a new one would arrive, so this is the case the
    tier exists for."""
    vendored = tmp_path / "vendor" / "some_repo"
    vendored.mkdir(parents=True)
    (vendored / "mod.py").write_text(SHADOWED, encoding="utf-8")
    findings, _ = scan(["vendor"], repo_root=tmp_path)
    tiers = classify(findings, ["vendor"])
    assert [f["key"] for f in tiers["vendor_new"]] == ["vendor/some_repo/mod.py: f"]
    assert tiers["owned"] == [], "a vendored finding must not be reported as owned"


def test_a_pinned_entry_that_no_longer_exists_is_reported_stale(monkeypatch, tmp_path):
    """Otherwise the pin rots into the general-purpose allowlist this check
    deliberately does not have. If upstream fixes one, we must delete the entry."""
    monkeypatch.setattr(checker, "VENDOR_BASELINE", frozenset({"vendor/gone/mod.py: f"}))
    (tmp_path / "vendor").mkdir()
    findings, _ = scan(["vendor"], repo_root=tmp_path)
    assert classify(findings, ["vendor"])["stale"] == ["vendor/gone/mod.py: f"]


def test_a_narrowed_run_does_not_report_the_whole_pin_as_stale(monkeypatch, tmp_path):
    """`--roots syndicate` must not fail with 12 stale entries just because it
    never looked at vendor/. A check that cries wolf on a narrowed run gets run
    with `|| true`."""
    monkeypatch.setattr(checker, "VENDOR_BASELINE", frozenset({"vendor/gone/mod.py: f"}))
    (tmp_path / "syndicate").mkdir()
    findings, _ = scan(["syndicate"], repo_root=tmp_path)
    assert classify(findings, ["syndicate"])["stale"] == []


# --- the invariant itself ----------------------------------------------------


def test_no_module_level_name_is_defined_twice_anywhere():
    """Over the repo root, `syndicate/`, `pipeline/`, `scripts/`, `tests/` and
    `vendor/` -- vendored findings only count if they are not in the pin."""
    findings, errors = scan(list(DEFAULT_ROOTS), repo_root=REPO_ROOT)
    assert not errors, "files the duplicate check could not parse: %r" % (errors,)
    tiers = classify(findings, list(DEFAULT_ROOTS))

    def render(items):
        return "; ".join("%s at lines %s" % (item["key"], item["lines"]) for item in items)

    assert not tiers["owned"], (
        "module-level names defined more than once (Python keeps the LAST "
        "binding, so every earlier definition is dead code): " + render(tiers["owned"])
    )
    assert not tiers["vendor_new"], (
        "NEW duplicate(s) under vendor/ that are not in VENDOR_BASELINE -- diff "
        "the two definitions, then pin with a note: " + render(tiers["vendor_new"])
    )
    assert not tiers["stale"], (
        "VENDOR_BASELINE names duplicate(s) that no longer exist; delete these "
        "entries: " + "; ".join(tiers["stale"])
    )
