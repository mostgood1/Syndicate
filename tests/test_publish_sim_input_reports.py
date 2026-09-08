"""The read-back verifier in `scripts/publish_sim_input_reports.py`.

WHY IT EXISTS. The `sim-input-reports` Render cron (`crn-dafj4ie7bikc738q9ol0`,
`0 7 * * *`) failed its first three runs. Two of them died here:

    n = len((doc or {}).get("failures") or (doc or {}).get("alarms") or [])
    TypeError: object of type 'int' has no len()

The verifier assumed every checklist reports a LIST. Two of them report a
COUNT -- `nhl_sim_input_checklist.py:402` and `sim_input_checklist.py:714`
both write `"failures": len(failures)`. Read back from production 2026-09-08,
`nhl_source.failures` was `int 21` while nfl/ncaaf/wnba/nba carried `alarms`
as lists, so the crash was guaranteed on the third root every single day.

What makes it worth a test rather than a one-line patch: the crash was the
LEAST damaging part. It landed in the verify loop, after the pull, all five
checklists and all five publishes had already succeeded -- so the cron reported
failure on work that had reached production. And the `or` chain underneath it
collapsed two pairs of states that must stay distinct: `failures = 0` fell
THROUGH to `alarms`, and a report carrying neither field read as a confident 0,
which is indistinguishable from a clean engine.

The two shapes are both deliberate and neither is going away, so the reader has
to tolerate both rather than one producer being "fixed" to match the other.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(
        "publish_sim_input_reports", REPO / "scripts" / "publish_sim_input_reports.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return _load()


# The exact payload that crashed the cron, and one of each of the others.
# Values are the ones production actually served on 2026-09-08.
PRODUCTION_SHAPES = [
    ("nhl_source", {"failures": 21, "warnings": 0}, 21),
    ("wnba_source", {"alarms": ["UNFED: wnba team_advanced_stats.games ..."]}, 1),
    ("nba_source", {"alarms": ["UNFED: wnba team_advanced_stats.games ..."]}, 1),
    ("nfl_source", {"alarms": ["a", "b", "c", "d", "e", "f"]}, 6),
    ("ncaaf_source", {"alarms": ["a", "b", "c", "d", "e", "f"]}, 6),
]


@pytest.mark.parametrize("root,doc,expected", PRODUCTION_SHAPES)
def test_reads_every_shape_production_actually_publishes(module, root, doc, expected):
    assert module._alarm_count(doc) == expected, root


def test_the_int_shape_does_not_raise(module):
    """The regression itself, stated as the exception it used to throw."""
    assert module._alarm_count({"failures": 21}) == 21


def test_zero_failures_does_not_fall_through_to_alarms(module):
    """`failures = 0` is an answer, not a missing value.

    Under the old `or` chain this returned 1 -- the falsy 0 fell through and
    the report was described by a field its own producer had not written.
    """
    assert module._alarm_count({"failures": 0, "alarms": ["something else"]}) == 0


def test_absent_is_not_zero(module):
    """A report with no countable alarm field must not read as a clean engine.

    This is the direction that matters: an unreadable report defaulting to 0
    is the permissive branch, and it looks exactly like the PASS this whole
    script exists to make trustworthy.
    """
    assert module._alarm_count({"resolved_root": "/opt/render/project/src/data"}) is None
    assert module._alarm_count({}) is None
    assert module._alarm_count(None) is None


def test_a_bool_is_not_a_count(module):
    """`bool` subclasses `int`, so an `isinstance(v, int)` test accepts it.

    A producer writing `failures: true` means "there are some", not "there is
    one". Refusing is the only reading that cannot be wrong.
    """
    assert module._alarm_count({"failures": True}) is None
    assert module._alarm_count({"failures": False}) is None


def test_empty_list_is_zero_not_absent(module):
    """The other side of the absent/zero split: an empty list IS a reading."""
    assert module._alarm_count({"alarms": []}) == 0


def test_unreadable_report_sets_a_distinct_exit_code(module):
    """`main()` must not treat an unreadable report as a successful verify.

    Pinning the constant rather than the branch, because the branch needs a
    live token and this is the part that has to stay true regardless.
    """
    source = (REPO / "scripts" / "publish_sim_input_reports.py").read_text(encoding="utf-8")
    assert "rc_overall = 7" in source
    assert "UNREADABLE" in source
