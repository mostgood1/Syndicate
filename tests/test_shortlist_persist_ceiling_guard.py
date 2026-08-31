"""The size guard measured a SUBSET of what it guarded, and reported comfort.

Measured 2026-08-22 20:56:30Z, immediately after the per-sport cap went
100 -> 400:

    the guard (rows only)   under its half-ceiling trigger -> SILENT
    the written artifact    4,434,665 B = 53% of the 8 MB keyvalue ceiling

The ceiling's own comment records 4.37 MB as the largest state known to work and
8.9 MB as reproducibly fatal ("Connection closed by server"), so the real
payload had crossed the known-good mark while the instrument said nothing.

`select_shortlist` can only ever see `selected` — the rows. The persisted
artifact also carries `per_sport`, `cards`, `openings_records`, `clv_openings`
and every coverage payload. **An all-clear from a subset-measuring guard is
worse than no guard**: nobody has reason to doubt it.

So the warning moved to the only place the whole payload exists —
`write_layer2_shortlist`, BEFORE the write. The store's own
`KEYVALUE_WRITE_LARGE` does see the true size, but it warns at 1 MB (which every
board payload exceeds, so it is noise) and it fires after the write.
"""

from __future__ import annotations

import pipeline.intelligence_state as state


def _payload(rows: int, filler_bytes: int = 0) -> dict:
    out = {
        "rows": [{"i": i, "sport": "soccer"} for i in range(rows)],
        "per_sport_limit": 400,
    }
    if filler_bytes:
        # Stands in for `cards`/`openings_records`/coverage -- everything that
        # is in the artifact and NOT in `rows`. This is the mass the old guard
        # could not see.
        out["cards"] = "x" * filler_bytes
    return out


def test_a_small_payload_is_silent(capsys) -> None:
    state._warn_if_shortlist_near_keyvalue_ceiling(_payload(10))
    assert "SHORTLIST_PERSIST_LARGE" not in capsys.readouterr().out


def test_it_warns_on_the_WHOLE_payload_not_just_the_rows(capsys) -> None:
    """The exact shape of the miss: few rows, huge non-row mass."""
    ceiling = state.__dict__.get("_keyvalue_max_bytes")
    from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes

    over_half = _keyvalue_max_bytes() // 2 + 1024
    # Deliberately only 5 rows -- a rows-only guard sees ~200 bytes here and
    # stays silent. The artifact is over half the ceiling.
    state._warn_if_shortlist_near_keyvalue_ceiling(_payload(5, filler_bytes=over_half))
    out = capsys.readouterr().out
    assert "SHORTLIST_PERSIST_LARGE" in out
    assert "rows=5" in out


def test_the_warning_names_the_knob_to_turn(capsys) -> None:
    """A warning that does not say what to change gets read and not acted on.

    The failure at the ceiling is an opaque "Connection closed by server", so
    the line has to carry its own remedy.
    """
    from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes

    state._warn_if_shortlist_near_keyvalue_ceiling(
        _payload(5, filler_bytes=_keyvalue_max_bytes() // 2 + 1024)
    )
    out = capsys.readouterr().out
    assert "SYNDICATE_LAYER2_ROWS_PER_SPORT" in out
    assert "pct=" in out


def test_it_never_raises_on_an_unserialisable_payload(capsys) -> None:
    """An instrument that can break the write it measures is worse than none."""

    class Bad:
        def __repr__(self):  # pragma: no cover - defensive
            raise RuntimeError("boom")

    # `default=str` calls repr() on unknown objects; this one raises.
    state._warn_if_shortlist_near_keyvalue_ceiling({"rows": [], "x": Bad()})
    # No exception is the assertion. The write must still be reachable.


def test_the_guard_runs_BEFORE_the_write(monkeypatch, capsys) -> None:
    """Warning after the write is warning after the failure it predicts."""
    order: list[str] = []
    from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes

    monkeypatch.setattr(
        state, "_warn_if_shortlist_near_keyvalue_ceiling",
        lambda payload: order.append("warn"),
    )
    monkeypatch.setattr(state, "write_json_file", lambda path, payload: order.append("write"))
    monkeypatch.setattr(state, "_utc_now", lambda: "2026-08-22T00:00:00Z")
    state.write_layer2_shortlist("2026-08-22", _payload(3))
    # THE PROPERTY, NOT THE CALL COUNT. This asserted `== ["warn", "write"]`,
    # which pins two things: the guard precedes the write, and there is EXACTLY
    # ONE write. The first is what the test exists for; the second stopped being
    # true when the board gained a per-sport shard key beside the combined one
    # (`SYNDICATE_LAYER2_COMBINED_ROWS`). A warning after the write is a warning
    # after the failure it predicts, so what must hold is that NO write of any
    # kind precedes the guard. Widened, not deleted: `order[0]` still fails if a
    # shard write ever moves ahead of it.
    assert order, "neither the guard nor the write ran"
    assert order[0] == "warn", f"a write preceded the ceiling guard: {order}"
    assert "write" in order, "the guard ran but the write did not"
