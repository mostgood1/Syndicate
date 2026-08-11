"""`#355` -- one league that launches cleanly and writes nothing must not starve the queue.

MEASURED, NOT HYPOTHETICAL. On 2026-08-11 `la_liga|2026-08-15` launched cleanly
44 times in an hour, wrote its recommendations file zero times, and took the
soccer slot every ten minutes. The unit histogram over the refresh-worker log:

    before #353 (17:30-19:07)  belgian 35 · eredivisie 32 · mls 25 · champ 7 · primeira 1
    after  #353 (19:07-20:10)  la_liga 44 · belgian 27

`#353` is what changed. It stopped stamping `unitEpochs` on launch -- correctly,
because stamping on launch is what let failed units sleep four hours while
reporting themselves done -- but the picker sorts on `unitEpochs`. So a unit that
can launch and cannot write keeps its ancient success epoch forever, is
permanently the stalest unit, and wins `due[0]` every single retry window.

The fix sorts on max(last success, last attempt): a unit that just burned a slot
goes to the back, while units that have not attempted recently still order by
genuine staleness. These tests assert BOTH halves, because a fix that only
de-prioritises the failing unit would break stalest-first for everyone else.

The comment the old sort carried -- "stalest first, so a unit can never be
starved by ordering" -- was true when written and false after `#353` touched a
different function. That is the reason this is a test and not a comment.
"""

from __future__ import annotations

from scripts.run_refresh_worker import _soccer_unit_key, _soccer_unit_last_touched

NOW = 1_000_000.0
HOUR = 3600.0


def _order(units, unit_epochs, last_attempts):
    """The picker's real ordering -- same key function, same direction."""
    return [
        u["league"]
        for u in sorted(
            units,
            key=lambda u: _soccer_unit_last_touched(_soccer_unit_key(u), unit_epochs, last_attempts),
        )
    ]


def _units(*leagues, date="2026-08-15"):
    return [{"league": lg, "date": date} for lg in leagues]


def test_the_measured_starvation_does_not_recur():
    units = _units("la_liga", "mls", "eredivisie", "belgian_pro_league")
    # la_liga: verified 22 days ago (2026-07-20), attempted 3 minutes ago.
    # Everyone else: verified ~2h ago, not attempted since.
    unit_epochs = {
        "la_liga|2026-08-15": NOW - 22 * 24 * HOUR,
        "mls|2026-08-15": NOW - 2 * HOUR,
        "eredivisie|2026-08-15": NOW - 2.5 * HOUR,
        "belgian_pro_league|2026-08-15": NOW - 3 * HOUR,
    }
    last_attempts = {"la_liga|2026-08-15": NOW - 180.0}

    order = _order(units, unit_epochs, last_attempts)
    assert order[-1] == "la_liga", f"la_liga still monopolises the slot: {order}"
    # And the slot goes to the league that has waited longest without trying.
    assert order[0] == "belgian_pro_league", order

    # The old rule, asserted directly so the regression is unmistakable: sorting
    # on the success epoch alone puts the broken unit first, every time.
    old = [u["league"] for u in sorted(units, key=lambda u: unit_epochs[_soccer_unit_key(u)])]
    assert old[0] == "la_liga", "the pre-#355 ordering no longer reproduces -- this test proves nothing"


def test_stalest_first_still_holds_for_healthy_units():
    # The half a de-prioritisation fix could easily break. With no recent
    # attempts, ordering must be exactly staleness order.
    units = _units("a", "b", "c")
    unit_epochs = {"a|2026-08-15": NOW - HOUR, "b|2026-08-15": NOW - 5 * HOUR, "c|2026-08-15": NOW - 3 * HOUR}
    # Attempts older than the successes -- max() must collapse to the success.
    last_attempts = {k: v - HOUR for k, v in unit_epochs.items()}
    assert _order(units, unit_epochs, last_attempts) == ["b", "c", "a"]


def test_a_never_seen_unit_goes_first():
    units = _units("new", "old")
    order = _order(units, {"old|2026-08-15": NOW - HOUR}, {"old|2026-08-15": NOW - HOUR})
    assert order[0] == "new", "a cold-start unit must not queue behind a unit that already ran"


def test_a_broken_unit_still_gets_its_turn_eventually():
    # De-prioritised is not banned. Once the broken unit's attempt ages past the
    # others' last touch, it comes back to the front -- otherwise a league that
    # breaks once never runs again and the fix trades one starvation for another.
    units = _units("la_liga", "mls")
    unit_epochs = {"la_liga|2026-08-15": NOW - 22 * 24 * HOUR, "mls|2026-08-15": NOW - 30.0}
    last_attempts = {"la_liga|2026-08-15": NOW - 2 * HOUR, "mls|2026-08-15": NOW - 30.0}
    assert _order(units, unit_epochs, last_attempts)[0] == "la_liga"


def test_unreadable_stamps_are_treated_as_never_not_as_a_crash():
    # State round-trips through the keyvalue store as JSON, so a stamp can come
    # back as a string or null. A raw float() would raise and take the whole
    # autorun down -- a worse outcome than the starvation being fixed here.
    units = _units("s", "n", "junk")
    unit_epochs = {"s|2026-08-15": str(NOW - HOUR), "n|2026-08-15": None, "junk|2026-08-15": "not-a-number"}
    order = _order(units, unit_epochs, {})
    assert order[-1] == "s", "a string stamp must still be read as a real epoch"
    assert set(order[:2]) == {"n", "junk"}, "null/garbage must sort as never-run, not crash"
