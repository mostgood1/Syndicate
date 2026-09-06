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

from scripts.check_duplicate_module_names import DEFAULT_ROOTS  # noqa: E402
from scripts.check_duplicate_module_names import duplicates_in_source  # noqa: E402
from scripts.check_duplicate_module_names import scan  # noqa: E402


def test_the_check_actually_detects_a_duplicate():
    """OFF != ON. A check whose only evidence is that it returns clean has not
    been shown to be able to return anything else -- and this repo has shipped
    inert guards before. Establish the positive reading first."""
    shadowed = "\n".join(
        [
            "def f():",
            "    return 1",
            "",
            "",
            "def f():",
            "    return 2",
            "",
        ]
    )
    assert duplicates_in_source(shadowed, "<synthetic>") == {"f": [1, 5]}


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


def test_no_module_level_name_is_defined_twice_anywhere():
    """The invariant itself, over `syndicate/`, `pipeline/`, `scripts/`, `tests/`."""
    findings, errors = scan(list(DEFAULT_ROOTS), repo_root=REPO_ROOT)
    assert not errors, "files the duplicate check could not parse: %r" % (errors,)
    rendered = [
        "%s: `%s` at lines %s" % (item["path"], item["name"], item["lines"])
        for item in findings
    ]
    assert not rendered, (
        "module-level names defined more than once (Python keeps the LAST "
        "binding, so every earlier definition is dead code): " + "; ".join(rendered)
    )
