"""A segment series is detected by SHAPE, in whichever spelling Kalshi ships.

`_SEGMENT_MARKERS` is the "does this LOOK like a segment market" guard: a series
carrying a marker but absent from `_SERIES_SEGMENT` REFUSES, and everything else
defaults to `full`. It enumerated `Q1..Q4` while Kalshi writes quarters
digit-first, and `F5` while Kalshi also ships `F3` and `F7` -- the module's own
segment-winner note names "KXMLBF3/F5/F7".

MEASURED 2026-09-04, before the fix -- every one read `full`, i.e. a SEGMENT
contract classified as a WHOLE-GAME one:

    KXNCAAF1QSPREAD  KXNFL2QTOTAL  KXNBA3QSPREAD  KXNFL4QTOTAL
    KXMLBF3TOTAL     KXMLBF7TOTAL  KXMLBF3        KXMLBF7

That is `#563` -- five orders, $7.08 -- and the MLB board carries 31 `first3`
rows for such a contract to land on. It is latent only because the market NAME
is double-encoded Kalshi-side, which is exactly what anyone fixing the F5 join
would remove.

**THE ENUMERATION IS WHAT FAILED**, not the eight names it missed. Listing
spellings was a guess, and the venue used the other order for one family and
more numbers for another. Matching the shape covers `F1`, `5Q`, `H3` and
whatever ships next.

`test_a_head_to_head_series_is_not_a_half` is the guard in the other direction:
a FALSE positive refuses a whole-game series and takes the Kalshi order path to
zero, which is the failure the module's own comment warns about at length.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.kalshi_catalogue as kc  # noqa: E402

SEGMENT_SPELLINGS = [
    "KXNCAAF1QSPREAD", "KXNFL2QTOTAL", "KXNBA3QSPREAD", "KXNFL4QTOTAL",
    "KXNBAQ1TOTAL", "KXNCAAF1HSPREAD", "KXNFL2HTOTAL", "KXWNBA1HWINNER",
    "KXMLBF3", "KXMLBF7", "KXMLBF3TOTAL", "KXMLBF7TOTAL", "KXMLBINNINGTOTAL",
]


def test_every_segment_spelling_refuses():
    """`None` means refuse. `full` here is the defect: it lets a period contract
    key-match a whole-game board row."""
    for series in SEGMENT_SPELLINGS:
        assert kc.segment_for_series(series) is None, (
            "%s resolved to %r -- a segment contract read as whole-game"
            % (series, kc.segment_for_series(series)))


def test_the_digit_first_quarters_are_the_ones_that_were_missed():
    """The specific regression: the table had `Q1..Q4`, the venue writes `1Q`."""
    for series in ("KXNCAAF1QSPREAD", "KXNFL2QTOTAL", "KXNBA3QSPREAD", "KXNFL4QTOTAL"):
        assert kc.segment_for_series(series) is None, series


def test_first_three_and_seven_innings_were_also_missed():
    """`F5` was listed and `F3`/`F7` were not, though the module's own note names
    all three. MLB is where a board actually has `first3` rows to land on."""
    for series in ("KXMLBF3", "KXMLBF7", "KXMLBF3TOTAL", "KXMLBF7TOTAL"):
        assert kc.segment_for_series(series) is None, series


def test_mapped_segment_series_still_resolve_to_their_segment():
    """Off != on. Refusing everything would also pass the tests above."""
    for series in ("KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL"):
        assert kc.segment_for_series(series) == "first5", series


# --- the other direction: a false positive is the expensive failure ---------


def test_a_head_to_head_series_is_not_a_half():
    """`KXNFLH2HWINS` matched `\\dH` on the `2H` inside "head-to-head" -- found
    while writing this. Inert (that series is out-of-scope and refused earlier)
    but real: a false positive REFUSES a whole-game series."""
    assert kc.segment_for_series("KXNFLH2HWINS") == "full"


def test_no_registered_or_out_of_scope_series_is_mistaken_for_a_segment():
    """The population check. A wrong refusal here zeroes the Kalshi order path,
    which the module warns is worse than the $7.08 defect it guards against."""
    mapped = {"KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL"}
    everything = set(kc.SERIES_SPORT) | set(kc.SERIES_OUT_OF_SCOPE)
    assert len(everything) > 50, "the registries shrank -- this check is not guarding much"
    wrong = {s: kc.segment_for_series(s) for s in everything
             if s not in mapped and kc.segment_for_series(s) != "full"}
    assert not wrong, wrong


def test_the_whole_game_and_prop_book_still_defaults_to_full():
    """Prop series are inherently whole-game and absent from `_SERIES_SEGMENT`;
    refusing them would take Kalshi orders to zero rather than fix anything."""
    for series in ("KXMLBKS", "KXMLBHIT", "KXMLBHR", "KXMLBRBI", "KXMLBGAME",
                   "KXNCAAFTOTAL", "KXNFLTOTAL"):
        assert kc.segment_for_series(series) == "full", series


def test_the_shape_rule_covers_spellings_no_table_listed():
    """The point of matching shape: a spelling nobody enumerated still refuses."""
    for series in ("KXABCF1TOTAL", "KXABC5QSPREAD", "KXABCH3TOTAL"):
        assert kc.segment_for_series(series) is None, series
