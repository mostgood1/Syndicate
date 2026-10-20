"""Pin `attach_projections`' call-site enumeration and the `#425` scope caveat.

The docstring's job is to let a reader see that the `#425` degeneracy check
covers every producer that reaches it. It said FOUR call sites and named
`attach_live_projections_for_sport` as one. That function is not a caller -- it
calls `attach_live_projections` -- so the list read as though the live producer
were covered. It is not: the check reads `projected_raw`/`projected` and the
live path writes `live_projected`.

Three ways the old list misled, each pinned below:
  - the COUNT was four and is three;
  - a NON-CALLER was named;
  - `intelligence.py` was written bare, and two files share that basename, so
    grepping the wrong one finds no caller and looks like rot.
"""

import inspect
import re

from syndicate.features.shared import board_enrichment

#: Full paths, because basenames are ambiguous in this tree.
CALL_SITES = (
    "pipeline/layer2_shortlist.py",
    "syndicate/blueprints/intelligence.py",
    "syndicate/features/shared/book_grid_artifact.py",
)
#: Named in the old list and NOT a caller.
NOT_A_CALLER = "attach_live_projections_for_sport"


def _doc():
    return inspect.getdoc(board_enrichment.attach_projections) or ""


def test_the_docstring_says_THREE_not_four():
    doc = _doc()
    assert "THREE CALL SITES" in doc
    assert "there are four" not in doc.lower()


def test_every_call_site_is_named_with_its_FULL_PATH():
    doc = _doc()
    for path in CALL_SITES:
        assert path in doc, "%s is a caller and the docstring omits it" % path


def test_the_non_caller_is_not_listed_as_one():
    """`attach_live_projections_for_sport` may be MENTIONED, but not as a caller."""
    doc = _doc()
    assert NOT_A_CALLER in doc, "it should still be mentioned, as the correction"
    assert "is not a caller" in doc


def test_the_live_scope_caveat_is_present():
    """Without this, the list reads as "every producer is covered"."""
    doc = _doc()
    assert "DOES NOT COVER LIVE PROJECTIONS" in doc
    assert "live_projected" in doc
    assert "projected_raw" in doc


def test_the_wrapper_really_has_exactly_these_callers():
    """The claim, measured against the tree rather than trusted.

    Anchored so it cannot match `_attach_projections_by_sport`,
    `attach_live_projections` or `prop_projections.attach_projections` --
    three functions in this tree answer to some form of the name.
    """
    import subprocess

    call = re.compile(r"(?<![A-Za-z0-9_])attach_projections\s*\(")
    out = subprocess.run(["git", "grep", "-n", "attach_projections"],
                         capture_output=True, text=True)
    found = set()
    for line in out.stdout.splitlines():
        path, _, rest = line.partition(":")
        if not path.endswith(".py") or path.startswith("tests/"):
            continue
        body = rest.partition(":")[2]
        if re.search(r"\bdef\s+attach_projections\s*\(", body):
            continue
        stripped = body.strip()
        if stripped.startswith("#"):
            continue
        if not call.search(body):
            continue
        # the MLB branch calls the same-named prop_projections helper
        if path.endswith("board_enrichment.py"):
            continue
        found.add(path.replace("\\", "/"))
    assert found == set(CALL_SITES), (
        "callers changed: found %s, docstring claims %s -- update both together"
        % (sorted(found), sorted(CALL_SITES)))


def test_the_check_reads_pregame_keys_so_the_caveat_stays_true():
    """If `_projected_value` ever reads `live_projected`, the caveat is stale."""
    src = inspect.getsource(board_enrichment._projected_value)
    assert "projected_raw" in src and "projected" in src
    assert "live_projected" not in src, (
        "the degeneracy check now reads the live field; the docstring's scope "
        "caveat must be updated")
