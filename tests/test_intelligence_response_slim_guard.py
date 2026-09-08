"""`#632`: an oversized `/api/intelligence/query` response must not be able to
kill the container, whether or not the caller asked for slimming.

MEASURED 2026-09-08 on the live endpoint, ONE request, no `slim_aliases`:
**3,927 candidates -> a 64.98 MB payload carrying the SAME 3,927 rows five
times**, built in **28.2 s**. Web's limit is 2 GiB across 8 gunicorn slots. It
was `oomKilled memoryLimit=2Gi` minutes later.

`response_compression.py` already documented this endpoint at 53-67 MB per call,
so the SIZE was known. That the default shape can kill the service was not.

THE UI IS SAFE ONLY BECAUSE IT OPTS IN (`slim_aliases: true`). Every other caller
gets the 65 MB shape, including `scripts/watch_clamp_trigger.py:340`, which POSTs
`{"question": "show me the board"}` on a 600 s poll. That script is not currently
running -- its last observation is 2026-08-16 -- so it is a loaded gun rather
than a smoking one, and the default is the defect either way.

THE GUARD IS NOT A CONTRACT CHANGE BELOW ITS THRESHOLD. That is the property
these tests pin hardest: a normal-sized response must come back byte-identical
for a caller that did not ask to slim.
"""

from __future__ import annotations

from syndicate.blueprints.intelligence import (
    _RESPONSE_SLIM_ROW_GUARD,
    _oversized_response_rows,
    _slim_oversized_response,
)


def _rows(n, sport="mlb"):
    return [{"sport": sport, "id": i, "edge": 0.1} for i in range(n)]


def _payload(n):
    """The real duplication shape: the same rows under several keys."""
    rows = _rows(n)
    return {
        "ok": True,
        "top_opportunities": rows,
        "recommendations": list(rows),
        "ranked_all": list(rows),
        "board_contract": {"cards": list(rows)},
        "boardContract": {"cards": list(rows)},
        "by_sport": {"mlb": list(rows)},
    }


def test_a_NORMAL_response_is_untouched_for_a_caller_that_did_not_ask():
    """THE CONTRACT. Below the guard, an unasking caller gets exactly what it got
    before -- same object, same keys, no marker."""
    payload = _payload(10)
    out = _slim_oversized_response(payload, requested=False)
    assert out is payload, "a normal-sized response must not even be copied"
    assert "_response_aliases" not in out
    assert "_response_slimmed_reason" not in out


def test_an_OVERSIZED_response_is_slimmed_even_though_nobody_asked():
    payload = _payload(_RESPONSE_SLIM_ROW_GUARD + 1)
    out = _slim_oversized_response(payload, requested=False)
    assert out is not payload
    assert out.get("_response_slimmed_reason") == "row_guard"
    assert out.get("_response_slimmed_rows") == _RESPONSE_SLIM_ROW_GUARD + 1
    # It dropped duplicates, and it SAID which -- so every dropped key is
    # rebuildable by the caller.
    aliases = out.get("_response_aliases") or {}
    assert aliases, "slimming without declaring the aliases is a silent contract break"
    for dropped in aliases:
        assert dropped not in out, f"{dropped} was declared dropped but is still present"


def test_the_canonical_list_SURVIVES_slimming():
    """Slimming must remove DUPLICATES, never the data. A guard that drops the
    rows themselves would turn an OOM into an empty board."""
    payload = _payload(_RESPONSE_SLIM_ROW_GUARD + 50)
    out = _slim_oversized_response(payload, requested=False)
    assert len(out.get("top_opportunities") or []) == _RESPONSE_SLIM_ROW_GUARD + 50
    assert out.get("ok") is True


def test_a_caller_that_ALREADY_asked_is_not_double_slimmed():
    payload = _payload(_RESPONSE_SLIM_ROW_GUARD + 1)
    out = _slim_oversized_response(payload, requested=True)
    assert out is payload, "the caller's own slimming already ran; this must be a no-op"
    assert "_response_slimmed_reason" not in out


def test_row_count_is_the_MAX_across_the_duplicate_lists():
    # Whichever list is longest is the one that sizes the payload; taking a sum
    # would trip the guard ~3x early, taking one key would miss a payload whose
    # duplication sits on a different key.
    assert _oversized_response_rows({"top_opportunities": _rows(9), "ranked_all": _rows(4)}) == 9
    assert _oversized_response_rows({"ranked_all": _rows(7)}) == 7
    assert _oversized_response_rows({"recommendations": _rows(3)}) == 3


def test_row_count_is_defensive_about_shapes_it_did_not_expect():
    # This runs on the response path of a live endpoint. Raising here would turn
    # a large board into a 500.
    assert _oversized_response_rows(None) == 0
    assert _oversized_response_rows("not a dict") == 0
    assert _oversized_response_rows({}) == 0
    assert _oversized_response_rows({"top_opportunities": "not a list"}) == 0


def test_a_response_with_NO_duplicates_is_returned_unchanged_even_when_huge():
    """`_slim_response_aliases` only drops keys it PROVES are duplicates. If a
    huge payload has none, there is nothing to drop and the guard must not
    invent something -- it must not, for instance, truncate."""
    rows = _rows(_RESPONSE_SLIM_ROW_GUARD + 100)
    payload = {"ok": True, "top_opportunities": rows}
    out = _slim_oversized_response(payload, requested=False)
    assert len(out.get("top_opportunities") or []) == len(rows)
    assert "_response_aliases" not in out


def test_the_guard_sits_between_the_measured_safe_and_measured_fatal_sizes():
    # The UI is measured serving ~2,004-row payloads; 3,927 rows produced 64.98 MB
    # and preceded an oomKilled. A guard outside that band is either useless or
    # a contract change for normal traffic.
    assert 2004 < _RESPONSE_SLIM_ROW_GUARD < 3927
