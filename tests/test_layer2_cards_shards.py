"""`cards` gets its own per-sport keys, so the combined key stops scaling with rows.

WHY THIS EXISTS. Sharding the ROWS moved only part of the payload. `cards` is
built one-per-row, so the combined key still grew ~2,020 bytes/row even with
`rows: []` -- 3,754,595 B at 1,634 rows, 9,648,192 B at 4,552 -- which is what
refused the write on 2026-08-31 and capped the board at ~3,600 rows regardless of
how much room the row shards had. `_shed_rows_to_fit_keyvalue` had been reporting
this all along as SHORTLIST_SHED_IMPOSSIBLE and naming this exact fix.
"""
from __future__ import annotations

import pipeline.intelligence_state as istate


def _card(sport: str, n: int) -> dict:
    return {"sport": sport, "event_id": f"{sport}-{n}"}


def _install(monkeypatch, cards_by_sport: dict[str, dict]):
    def fake_path(selected_date: str, sport: str):
        return f"/cards/{selected_date}/{sport}"

    def fake_read(path):
        return cards_by_sport.get(str(path).rsplit("/", 1)[-1])

    monkeypatch.setattr(istate, "_layer2_shortlist_cards_shard_path", fake_path)
    monkeypatch.setattr(istate, "read_json_file", fake_read)


def _shard(sport, cards, positions, written_at="T1"):
    return {"sport": sport, "cards": cards, "positions": positions, "written_at": written_at}


# --- the flag ------------------------------------------------------------

def test_flag_defaults_to_keeping_cards_inline(monkeypatch):
    """Default must be a NO-OP. A writer that drops cards before every reader can
    hydrate them serves a board with no cards and no error."""
    monkeypatch.delenv("SYNDICATE_LAYER2_CARDS_INLINE", raising=False)
    assert istate._layer2_combined_keeps_cards() is True


def test_flag_off_is_reachable_and_differs_from_on(monkeypatch):
    """off != on. A flag whose two states behave identically is an inert feature
    that looks shipped -- four of those were caught in one session by this check
    and nothing else."""
    monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", "1")
    on = istate._layer2_combined_keeps_cards()
    monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", "0")
    off = istate._layer2_combined_keeps_cards()
    assert on is True and off is False, "the flag must actually switch behaviour"


def test_only_explicit_falsey_values_disable_inline(monkeypatch):
    for raw in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", raw)
        assert istate._layer2_combined_keeps_cards() is False, raw
    for raw in ("1", "yes", "", "banana"):
        monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", raw)
        assert istate._layer2_combined_keeps_cards() is True, raw


# --- bucketing -----------------------------------------------------------

def test_cards_bucket_by_sport_slug_when_sport_is_absent():
    """A card carries its sport under either name. Without the fallback every
    card buckets to 'unknown' -- ONE key holding the whole board's cards, which
    is the shared budget this split exists to remove, silently."""
    buckets = istate._shard_rows_by_sport([
        {"sport_slug": "mlb", "id": 1},
        {"sport": "soccer", "id": 2},
    ])
    assert set(buckets) == {"mlb", "soccer"}, "sport_slug must not fall through to 'unknown'"


# --- hydration -----------------------------------------------------------

def test_cards_are_restored_from_shards_in_board_order(monkeypatch):
    _install(monkeypatch, {
        "mlb": _shard("mlb", [_card("mlb", 0), _card("mlb", 2)], [0, 2]),
        "soccer": _shard("soccer", [_card("soccer", 1)], [1]),
    })
    payload = {"cards": [], "card_shards": ["mlb", "soccer"], "card_total": 3}

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert [c["event_id"] for c in out["cards"]] == ["mlb-0", "soccer-1", "mlb-2"], "global order"
    assert out["cards_from_shards"] is True


def test_inline_cards_win_over_shards(monkeypatch):
    """Precedence matches the rows: a new reader against an old writer must be
    unaffected."""
    _install(monkeypatch, {"mlb": _shard("mlb", [_card("mlb", 9)], [0])})
    payload = {"cards": [_card("inline", 0)], "card_shards": ["mlb"], "card_total": 1}

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert out["cards"] == [_card("inline", 0)], "inline cards must win"
    assert "cards_from_shards" not in out


def test_a_payload_with_no_card_shards_is_untouched(monkeypatch):
    _install(monkeypatch, {})
    payload = {"cards": [], "rows": [1, 2]}
    assert istate._hydrate_layer2_cards("2026-08-31", payload) is payload


def test_a_stale_card_total_does_not_discard_cards(monkeypatch):
    """The rows merge learned this on 2026-08-31: never size the collection from
    a total on the combined key, which a refused write can freeze."""
    _install(monkeypatch, {
        "mlb": _shard("mlb", [_card("mlb", 0), _card("mlb", 1)], [0, 1]),
        "ncaaf": _shard("ncaaf", [_card("ncaaf", 2), _card("ncaaf", 3)], [2, 3]),
    })
    payload = {"cards": [], "card_shards": ["mlb", "ncaaf"], "card_total": 2}  # frozen

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert len(out["cards"]) == 4, "cards above the stale total must NOT be discarded"
    assert {c["sport"] for c in out["cards"]} == {"mlb", "ncaaf"}, "no sport may vanish"


def test_a_missing_card_shard_still_leaves_its_hole(monkeypatch):
    _install(monkeypatch, {"mlb": _shard("mlb", [_card("mlb", 0)], [0])})
    payload = {"cards": [], "card_shards": ["mlb", "soccer"], "card_total": 5}

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert out["card_shards_missing"] == ["soccer"]
    assert len(out["cards"]) == 1


def test_a_bool_position_cannot_place_a_card(monkeypatch):
    _install(monkeypatch, {"mlb": _shard("mlb", [_card("mlb", 0), _card("mlb", 1)], [0, True])})
    payload = {"cards": [], "card_shards": ["mlb"], "card_total": 2}

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert [c["event_id"] for c in out["cards"]] == ["mlb-0"], "True must not place a card at 1"


def test_a_shard_whose_positions_do_not_match_is_refused_not_guessed(monkeypatch):
    _install(monkeypatch, {"mlb": {"sport": "mlb", "cards": [_card("mlb", 0)], "positions": [0, 1]}})
    payload = {"cards": [], "card_shards": ["mlb"], "card_total": 1}

    out = istate._hydrate_layer2_cards("2026-08-31", payload)

    assert out["card_shards_missing"] == ["mlb"]
    assert out["cards"] == []


# --- the measurement that actually matters -------------------------------

def _measure(monkeypatch, rows_n: int, cards_inline: bool) -> dict[str, int]:
    """Run the real writer and record the BYTES of every key it writes."""
    import json as _json

    written: dict[str, int] = {}

    def fake_write(path, payload):
        written[str(path).replace("\\", "/").rsplit("/", 1)[-1]] = len(_json.dumps(payload, default=str))

    monkeypatch.setattr(istate, "write_json_file", fake_write)
    monkeypatch.setattr(istate, "_warn_if_layer2_keys_near_ceiling", lambda *a, **k: None)
    monkeypatch.setattr(istate, "_shadow_verify_layer2_shards", lambda *a, **k: None)
    monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", "0")
    monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", "1" if cards_inline else "0")

    sports = ("mlb", "ncaaf", "soccer")
    # One card per row, which is how the builder makes them, and the reason the
    # combined key scaled with the per-sport cap in the first place.
    rows = [{"sport": sports[i % 3], "event_id": f"e{i}", "market": "h2h",
             "side": "home", "line": str(i), "pad": "x" * 400} for i in range(rows_n)]
    cards = [{"sport": sports[i % 3], "event_id": f"e{i}", "pad": "y" * 400} for i in range(rows_n)]
    istate.write_layer2_shortlist("2026-08-31", {"rows": rows, "cards": cards})
    return written


def test_splitting_cards_actually_shrinks_the_combined_key(monkeypatch):
    """GATE ON THE OUTPUT, not on the code path. The whole point of this change
    is bytes on the combined key; a version that wrote the shards and still
    inlined the cards would pass every other test in this file.
    """
    before = _measure(monkeypatch, 300, cards_inline=True)
    after = _measure(monkeypatch, 300, cards_inline=False)

    combined = "layer2_shortlist_2026_08_31.json"
    assert combined in before and combined in after
    assert after[combined] < before[combined] / 2, (
        f"combined must shed the cards: {before[combined]} -> {after[combined]}"
    )
    # And the cards must have gone somewhere, not been dropped.
    card_keys = [k for k in after if "__cards__" in k]
    assert sorted(card_keys) == [
        "layer2_shortlist_2026_08_31__cards__mlb.json",
        "layer2_shortlist_2026_08_31__cards__ncaaf.json",
        "layer2_shortlist_2026_08_31__cards__soccer.json",
    ], card_keys


def test_the_combined_key_stops_scaling_with_rows(monkeypatch):
    """THE ACTUAL DEFECT. Measured on production, the combined key grew ~2,020
    bytes/row even with `rows: []`, which capped the board at ~3,600 rows no
    matter how much room the row shards had. With cards split it must be
    roughly FLAT in the row count."""
    combined = "layer2_shortlist_2026_08_31.json"
    small = _measure(monkeypatch, 200, cards_inline=False)[combined]
    large = _measure(monkeypatch, 800, cards_inline=False)[combined]
    growth_per_row = (large - small) / 600.0
    assert growth_per_row < 100, (
        f"combined still scales with rows at {growth_per_row:.0f} B/row "
        f"({small} -> {large}); the split did not do its job"
    )
