"""`canonical_team`'s memo can never outlive the map it read (lane `web-restart-healthz`).

py-spy on the fleet refresh-worker 2026-10-06: ~43% of the process was the board's
row x chip `teams_match` loop, and every `canonical_team` call rebuilt
`set(mapping.values())`. The memo added for that is keyed on the map OBJECT: tests
(and anything else) that `cache_clear()` a per-sport map get a new object and a
recomputed answer, never a stale one.
"""

from __future__ import annotations

from syndicate.features.shared import team_aliases as ta


def test_the_memo_follows_the_map_object(monkeypatch):
    first = {"aaa": "alpha club"}
    second = {"aaa": "beta club"}
    current = {"map": first}
    monkeypatch.setattr(ta, "_alias_map", lambda sport: current["map"])
    monkeypatch.setattr(ta, "_nickname_alias_map", lambda sport: {})
    monkeypatch.setattr(ta, "_CANONICAL_MEMO", {})
    monkeypatch.setattr(ta, "_ALIAS_VALUES_MEMO", {})

    assert ta.canonical_team("soccer", "AAA") == "alpha club"
    assert ta.canonical_team("soccer", "alpha club") == "alpha club"   # value side, via _alias_values
    current["map"] = second                                            # a cache_clear() yields a new object
    assert ta.canonical_team("soccer", "AAA") == "beta club"
    assert ta.canonical_team("soccer", "alpha club") is None
    assert ta.canonical_team("soccer", "beta club") == "beta club"


def test_a_repeat_call_is_served_from_the_memo(monkeypatch):
    calls = {"n": 0}

    def uncached(sport, value, **kwargs):
        calls["n"] += 1
        return "x"

    monkeypatch.setattr(ta, "_CANONICAL_MEMO", {})
    monkeypatch.setattr(ta, "_canonical_team_uncached", uncached)
    for _ in range(5):
        assert ta.canonical_team("mlb", "NYY") == "x"
    assert calls["n"] == 1


def test_non_string_inputs_keep_the_old_semantics():
    assert ta.canonical_team("mlb", None) is None
    assert ta.normalize(None) == "" and ta.normalize(0) == "" and ta.normalize(12) == "12"
    assert ta.normalize("  New_York-Yankees ") == "new york yankees"
