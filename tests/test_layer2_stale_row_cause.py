"""`STALE_ROW_CAUSE` must classify EVERY stale row, and the index must not change a verdict.

WHY THIS FILE EXISTS
--------------------

`_report_stale_row_causes` used to classify the 3 worst rows per sport
(`per_sport=3`). The emitted line therefore read

    soccer[stale=288 worst=38599s sidecar=1384s market_gone=3]

which a reader takes as "3 of 288 explained" and which actually means "3 of 3
SAMPLED". The counts could not sum to `stale=`, so the line could never answer
the one question a staleness tail poses: ONE cause, or several?

Lifted by hand 2026-08-30 against the live 22,544-entry soccer state file and
the served board: **288 of 288 `market_gone`, 100%.** A single cause, and
structurally invisible at n=3.

The two properties pinned here are exactly the two that made lifting the cap
safe, and each corresponds to an objection that had to be answered first:

  1. THE INDEX MUST NOT CHANGE A VERDICT. It is an optimisation, and an
     optimisation that alters a diagnostic's answer is worse than the cost it
     saves. Verified on production data at 288/288 identical, 0 disagreements;
     pinned here on synthetic rows covering every branch.
  2. THE COUNTS MUST SUM TO `stale=`. That is what makes the emitted line
     self-checking -- if they ever disagree, a row fell through the classifier
     instead of being labelled `unknown_*`, and the line says so on its face.

Measured cost, same production data, 288 rows against 22,544 state entries:

    old per-row scan, all 288      16,499 ms
    index build (once)                 95 ms
    indexed classify                    3 ms
    NEW TOTAL                          98 ms      167.7x
    old cost for just 3 rows          172 ms   <- classifying ALL is now cheaper
                                                  than the old 3-row sample
"""
from __future__ import annotations

import re

from pipeline.layer2_shortlist import (
    _QUOTE_KEY_ORDER,
    _classify_stale_row,
    _index_last_seen,
)

NOW = "2026-08-30T02:00:00Z"


def _key(*, event_id="evt1", bookmaker="fanduel", market="totals", selection="over", line="8.5"):
    """A `last_seen` key in the real 9-field order."""
    parts = {
        "sport": "mlb",
        "kind": "game",
        "event_id": event_id,
        "bookmaker": bookmaker,
        "segment": "full",
        "market": market,
        "selection": selection,
        "player_name": "",
        "line": line,
    }
    return "|".join(parts[f] for f in _QUOTE_KEY_ORDER)


def _row(*, event_id="evt1", market="totals", line="8.5", seen=7200.0):
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": event_id,
        "segment": "full",
        "market": market,
        "player_name": "",
        "line": line,
        "quote": {"quote_seen_age_seconds": seen},
    }


def test_index_never_changes_a_verdict_across_every_branch():
    """The index is an optimisation. An optimisation that changes an answer is a bug."""
    fresh, old = NOW, "2026-08-29T16:00:00Z"
    cases = [
        # (last_seen, row, what it exercises)
        ({_key(line="9.5"): fresh}, _row(line="8.5"), "sibling line fresher -> orphaned_line"),
        ({_key(line="9.5"): old}, _row(line="8.5"), "sibling line stale -> market_gone"),
        ({_key(line="8.5"): fresh}, _row(line="8.5"), "only SAME line -> not the orphan test"),
        ({}, _row(line="8.5"), "empty state file"),
        ({_key(event_id="other", line="9.5"): fresh}, _row(line="8.5"), "different game"),
        ({_key(market="h2h", line="9.5"): fresh}, _row(line="8.5"), "different market"),
        ({"malformed|key": fresh, _key(line="9.5"): fresh}, _row(line="8.5"), "malformed key skipped"),
        ({_key(bookmaker="draftkings", line="9.5"): fresh, _key(line="9.5"): old},
         _row(line="8.5"), "two books on one line -> freshest wins"),
    ]
    for last_seen, row, label in cases:
        scan = _classify_stale_row(row, last_seen, NOW, 30.0)
        indexed = _classify_stale_row(row, last_seen, NOW, 30.0, _index_last_seen(last_seen))
        assert scan == indexed, f"index disagreed with scan on: {label} ({scan!r} vs {indexed!r})"


def test_index_and_scan_agree_on_the_two_named_verdicts():
    """Pin the actual labels too, not just that the two paths match each other."""
    fresh, old = NOW, "2026-08-29T16:00:00Z"
    gi = _index_last_seen({_key(line="9.5"): fresh})
    assert _classify_stale_row(_row(line="8.5"), {_key(line="9.5"): fresh}, NOW, 30.0, gi) == "orphaned_line"
    ls = {_key(line="9.5"): old}
    assert _classify_stale_row(_row(line="8.5"), ls, NOW, 30.0, _index_last_seen(ls)) == "market_gone"


def test_every_stale_row_is_classified_not_a_sample(capsys):
    """The counts on the emitted line must SUM to `stale=`.

    This is the regression that matters: with the old `per_sport=3` cap, ten
    stale rows emitted `market_gone=3` and the line looked like an explanation
    of three unrelated rows rather than a sample of ten.
    """
    from pipeline import layer2_shortlist as mod

    rows = [_row(event_id=f"evt{i}", line="8.5", seen=7200.0 + i) for i in range(10)]
    # Every row's group has a fresher sibling on a different line -> orphaned_line.
    last_seen = {_key(event_id=f"evt{i}", line="9.5"): NOW for i in range(10)}

    mod._report_stale_row_causes.__globals__["read_quote_last_seen"] = lambda *_a, **_k: last_seen
    import syndicate.features.shared.odds_book_quotes as obq

    original = obq.read_quote_last_seen
    obq.read_quote_last_seen = lambda *_a, **_k: last_seen
    try:
        mod._report_stale_row_causes(rows, "2026-08-30")
    finally:
        obq.read_quote_last_seen = original

    line = capsys.readouterr().out
    assert "STALE_ROW_CAUSE" in line, line
    stale_n = int(re.search(r"stale=(\d+)", line).group(1))
    counted = sum(int(n) for n in re.findall(r"=(\d+)(?:,|\])", line.split("sidecar=")[1]))
    assert stale_n == 10, line
    assert counted == stale_n, (
        f"counts sum to {counted} but stale={stale_n} -- rows fell through the "
        f"classifier, or the per_sport cap is back. Line: {line}"
    )


def test_per_sport_cap_is_gone_from_the_signature():
    """A guard against the cap being reintroduced as a 'performance fix'.

    It was never a saving: indexed, classifying ALL 288 production rows cost
    98ms against 172ms for the old 3-row sample.
    """
    import inspect

    from pipeline.layer2_shortlist import _report_stale_row_causes

    assert "per_sport" not in inspect.signature(_report_stale_row_causes).parameters, (
        "per_sport is back. Classifying a SAMPLE makes the emitted counts "
        "un-summable against stale=, which is the blind spot that hid a "
        "288/288 single-cause result."
    )
