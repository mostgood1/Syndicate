"""The live game-line record caps, sized against a REAL slate rather than MLB's.

THE DEFECT, measured on production refresh-worker 2026-09-26 15:00-18:55Z while
an NCAAF Saturday was still running:

    ncaaf   121 builds   max 937 candidates   61 builds truncated (50%)
            max 437 dropped in ONE build      13,383 records dropped in total
    mlb      69 builds   max 137 candidates    0 truncated
    nhl / nfl / soccer                         0 truncated

`_MAX_RECORDS_PER_BUILD` was 500, and its own comment said why: "a live slate
tops out around 15 games x a handful of priceable markets". That is true of MLB
and false of college football -- an NCAAF Saturday is ~65 games and every game
carries SEVEN segments (full, h1, h2, q1-q4), so candidates scale with
games x segments x markets.

TWO THINGS THESE TESTS PROTECT.

1. THE SECOND CAP MUST NOT BECOME THE FIRST. `_MAX_RECORDS_PER_FILE` does not
   truncate a build -- it STOPS WRITING FOR THE REST OF THE DAY. Lifting the
   build cap raises writes per build (~75 -> ~140 for ncaaf), so raising one
   into the other would have turned a partial loss into a total one. It was
   raised in step, BEFORE it bound: `truncated_file` was 0 for every sport on
   the day this was measured.

2. TRUNCATION, IF IT EVER HAPPENS AGAIN, MUST BE ATTRIBUTABLE. `records[:N]`
   keeps the FIRST N, so the loss is systematic rather than random -- it falls
   on whatever sorts last, every time. A scalar count cannot say which bet was
   lost, which is the same shape as the MLB first5-vs-full skew that let a
   capped scorer read healthy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import live_gameline_ledger as led  # noqa: E402


# --------------------------------------------------------------------------
# the caps themselves
# --------------------------------------------------------------------------

def test_the_build_cap_clears_a_real_ncaaf_saturday():
    """937 was the measured peak, mid-slate, with more games still to start."""
    assert led._MAX_RECORDS_PER_BUILD > 937


def test_the_build_cap_still_bounds_a_pathological_build():
    """The original intent, kept: far above a real slate, not unbounded."""
    assert led._MAX_RECORDS_PER_BUILD <= 20_000


def test_the_file_cap_was_raised_IN_STEP_with_the_build_cap():
    """Raising one into the other turns a partial loss into a total one."""
    # ~140 written/build for ncaaf once the build cap stops binding, x ~360
    # builds/day, is ~50k. The file cap must clear that with headroom.
    assert led._MAX_RECORDS_PER_FILE >= 100_000


def test_both_caps_are_env_overridable(monkeypatch):
    """So a bad default can be corrected WITHOUT a deploy. This one went
    unnoticed as long as it did partly because changing it meant shipping."""
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MAX_RECORDS_PER_BUILD", "77")
    assert led._int_env("SYNDICATE_LIVE_GAMELINE_MAX_RECORDS_PER_BUILD", 5_000) == 77


@pytest.mark.parametrize("raw", ["", "banana", "0", "-5", "   "])
def test_a_junk_or_nonpositive_override_falls_back(monkeypatch, raw):
    """A cap of 0 would silently drop EVERY record -- worse than the defect."""
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MAX_RECORDS_PER_BUILD", raw)
    assert led._int_env("SYNDICATE_LIVE_GAMELINE_MAX_RECORDS_PER_BUILD", 5_000) == 5_000


# --------------------------------------------------------------------------
# truncation, when it happens, is attributable
# --------------------------------------------------------------------------

def _rec(segment: str, n: int) -> dict:
    return {"segment": segment, "key": f"{segment}-{n}"}


def test_truncation_reports_WHICH_segments_were_lost(monkeypatch, tmp_path):
    monkeypatch.setattr(led, "_MAX_RECORDS_PER_BUILD", 3)
    monkeypatch.setattr(led, "_enabled", lambda: True)
    monkeypatch.setattr(led, "read_last_by_key", lambda _p: {})
    monkeypatch.setattr(led, "record_key", lambda rec: rec["key"])
    monkeypatch.setattr(led, "_moved", lambda _prev, _rec: True)

    records = [_rec("full", 1), _rec("full", 2), _rec("q1", 3), _rec("q4", 4), _rec("q4", 5)]
    coverage = led.append_records(tmp_path / "led.jsonl", records)

    assert coverage["truncated_build_cap"] == 2
    # The SHAPE of the loss, not just its size.
    assert coverage["truncated_build_cap_by_segment"] == {"q4": 2}
    assert "full" not in coverage["truncated_build_cap_by_segment"]


def test_no_truncation_leaves_the_split_empty(monkeypatch, tmp_path):
    """NEGATIVE CONTROL. A dict that is always populated says nothing."""
    monkeypatch.setattr(led, "_MAX_RECORDS_PER_BUILD", 50)
    monkeypatch.setattr(led, "_enabled", lambda: True)
    monkeypatch.setattr(led, "read_last_by_key", lambda _p: {})
    monkeypatch.setattr(led, "record_key", lambda rec: rec["key"])
    monkeypatch.setattr(led, "_moved", lambda _prev, _rec: True)

    coverage = led.append_records(tmp_path / "led.jsonl", [_rec("full", 1), _rec("q1", 2)])
    assert coverage["truncated_build_cap"] == 0
    assert coverage["truncated_build_cap_by_segment"] == {}


def test_the_dropped_records_are_the_TAIL_which_is_why_it_is_systematic(monkeypatch, tmp_path):
    """Pins the bias rather than hiding it: `records[:N]` keeps the FIRST N, so
    the same segment loses every time. Until the ordering is made fair, the
    honest thing is to MEASURE the skew, which the split above does."""
    monkeypatch.setattr(led, "_MAX_RECORDS_PER_BUILD", 2)
    monkeypatch.setattr(led, "_enabled", lambda: True)
    monkeypatch.setattr(led, "read_last_by_key", lambda _p: {})
    monkeypatch.setattr(led, "record_key", lambda rec: rec["key"])
    monkeypatch.setattr(led, "_moved", lambda _prev, _rec: True)

    records = [_rec("full", 1), _rec("full", 2), _rec("h1", 3)]
    coverage = led.append_records(tmp_path / "led.jsonl", records)
    assert coverage["truncated_build_cap_by_segment"] == {"h1": 1}, (
        "the tail is what gets dropped -- if this ever becomes random, say so here"
    )
