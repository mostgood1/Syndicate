"""The size guard must measure the unit the STORE refuses: one KEY.

HISTORY, because this guard has now been wrong twice in opposite directions and
the second failure was caused by fixing the first.

1. `select_shortlist`'s guard measured `selected` -- the ROWS -- while the
   artifact also carried `cards`, `openings_records`, `clv_openings` and every
   coverage payload. Measured 2026-08-22 20:56:30Z, right after the per-sport
   cap went 100 -> 400: the guard was SILENT while the written artifact was
   4,434,665 B, 53% of the ceiling and past the 4.37 MB recorded as the largest
   known-good state. An all-clear from a subset-measuring guard is worse than no
   guard.

2. So it moved to `write_layer2_shortlist` and measured the WHOLE payload. That
   was correct until the board was sharded, and then it measured an object that
   is no longer written as one key. Measured 2026-08-31:

       healthy board 18:54Z   pct=93.3   rows=1600   ALARM, nothing wrong
       broken build  18:25Z   pct=237.9  rows=4552   right, but for the wrong key

   and its advice -- "lower SYNDICATE_LAYER2_ROWS_PER_SPORT" -- was BACKWARDS on
   the healthy board, where the combined key was a few hundred KB and the cap was
   not the constraint.

Both failures are the same error at different scopes: measuring the object the
code happens to hold rather than the unit the store refuses. The store raises
PER KEY. There is no ceiling on "the payload".
"""

from __future__ import annotations

import pipeline.intelligence_state as state
from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes

CEIL = int(_keyvalue_max_bytes())
BIG = "x" * (CEIL // 2 + 1000)


def test_small_keys_are_silent(capsys) -> None:
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [], "per_sport_limit": 1000}, {"rows:mlb": 10, "cards:mlb": 10}, rows=5, cards=5
    )
    assert "LAYER2_KEY_LARGE" not in capsys.readouterr().out


def test_a_big_SHARD_is_reported_even_when_the_combined_key_is_tiny(capsys) -> None:
    """The post-sharding case the old guard could not see at all: the combined
    key is small and one sport's shard is the thing near the ceiling."""
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [], "cards": [], "per_sport_limit": 1000},
        {"rows:ncaaf": CEIL // 2 + 5000, "rows:mlb": 100},
        rows=3000, cards=3000,
    )
    out = capsys.readouterr().out
    assert "LAYER2_KEY_LARGE" in out
    assert "worst=rows:ncaaf" in out, out
    assert "SYNDICATE_LAYER2_ROWS_PER_SPORT" in out, "a per-sport cap bounds a per-sport shard"


def test_a_big_COMBINED_key_holding_cards_names_the_CARDS_flag_not_the_cap(capsys) -> None:
    """THE BACKWARDS ADVICE, pinned. A combined key that is large because it
    still carries cards is not fixed by lowering a row cap -- that was the
    instruction the old version printed at pct=93.3 on a healthy board."""
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [], "cards": [{"pad": BIG}], "per_sport_limit": 1000},
        {"rows:mlb": 100}, rows=1600, cards=1600,
    )
    out = capsys.readouterr().out
    assert "worst=combined" in out, out
    assert "SYNDICATE_LAYER2_CARDS_INLINE=0" in out, out
    assert "ROWS_PER_SPORT" not in out, "must NOT send the reader to the cap; that is the old bug"


def test_a_big_COMBINED_key_holding_ROWS_names_the_rows_flag(capsys) -> None:
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [{"pad": BIG}], "per_sport_limit": 1000}, {}, rows=1600, cards=0
    )
    out = capsys.readouterr().out
    assert "worst=combined" in out
    assert "SYNDICATE_LAYER2_COMBINED_ROWS=0" in out, out


def test_a_big_COMBINED_key_with_NEITHER_refuses_to_name_a_cap(capsys) -> None:
    """The genuinely unknown case. Naming a lever that cannot help is how the
    previous version wasted a reader's time -- say 'find it' instead."""
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [], "cards": [], "mystery": BIG, "per_sport_limit": 1000},
        {}, rows=0, cards=0,
    )
    out = capsys.readouterr().out
    assert "worst=combined" in out
    assert "some other field scales" in out, out
    assert "a row cap will not shrink this" in out, out


def test_every_key_is_listed_so_the_reader_can_see_the_split(capsys) -> None:
    state._warn_if_layer2_keys_near_ceiling(
        {"rows": [], "cards": [{"pad": BIG}]},
        {"rows:mlb": 111, "cards:mlb": 222}, rows=1, cards=1,
    )
    out = capsys.readouterr().out
    assert "cards:mlb=222" in out and "rows:mlb=111" in out and "combined=" in out, out


def test_it_never_raises_on_an_unserialisable_payload(capsys) -> None:
    """An instrument that can break the write it measures is worse than none."""
    class Bad:
        def __repr__(self):
            raise RuntimeError("boom")

    state._warn_if_layer2_keys_near_ceiling({"rows": [], "x": Bad()}, {}, rows=0, cards=0)
    assert "LAYER2_KEY_LARGE" not in capsys.readouterr().out


def test_the_stale_instrument_is_GONE() -> None:
    """It measured a payload the code no longer writes as one key. Leaving it
    beside the replacement would give two answers to one question."""
    assert not hasattr(state, "_warn_if_shortlist_near_keyvalue_ceiling")
