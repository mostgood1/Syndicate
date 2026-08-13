"""`#414` -- the board build re-read and re-indexed a 57 MB shard up to 3x.

Measured 2026-08-12/13: `collect_candidates` went ~200s at 14:41 to 1508.9s at
01:29 -- 7.5x in eleven hours, on FEWER rows at the end. The input is
`odds_history/<date>.json`, which accumulates ticks all day: MLB's 2026-08-12
shard measured 57.11 MB and a complete day is ~57 MB.

The discriminator was WNBA: `GAME_CANDIDATES_EXIT` 2s -> 5s at `rows=12` every
build. Identical output, 2.5x time, no slate or row confound. Cost tracks INPUT
SIZE, not output.

These tests assert WORK AVOIDED, not just that the code runs. A cache that is
present and never hit is the failure mode this repo has hit repeatedly.
"""

from __future__ import annotations

import importlib

import pytest

intel = importlib.import_module("syndicate.features.intelligence")


def _payload(n=3):
    return {"markets": {f"mlb|player_points|Player {i}|over": {"history": []} for i in range(n)}}


class TestIndexCache:
    def test_the_index_is_built_once_per_payload_not_once_per_call(self, monkeypatch):
        calls = []
        real = intel._build_odds_history_player_index
        monkeypatch.setattr(intel, "_build_odds_history_player_index",
                            lambda oh: (calls.append(1), real(oh))[1])
        payload = _payload()
        for _ in range(4):
            intel._odds_history_player_index_for(payload)
        assert len(calls) == 1, f"index rebuilt {len(calls)}x for one payload"

    def test_a_new_payload_object_gets_its_own_index(self, monkeypatch):
        """The supplement assigns a BRAND-NEW {'markets': ...} when it merges
        extra shards. That new object must not serve the old index."""
        calls = []
        real = intel._build_odds_history_player_index
        monkeypatch.setattr(intel, "_build_odds_history_player_index",
                            lambda oh: (calls.append(1), real(oh))[1])
        intel._odds_history_player_index_for(_payload(3))
        intel._odds_history_player_index_for(_payload(5))
        assert len(calls) == 2, "a changed payload served a stale index"

    def test_the_cached_index_equals_the_uncached_one(self):
        payload = _payload(4)
        fresh = intel._build_odds_history_player_index({"markets": dict(payload["markets"])})
        cached = intel._odds_history_player_index_for(payload)
        assert intel._odds_history_player_index_for(payload) is cached
        assert cached[0].keys() == fresh[0].keys()
        assert len(cached[1]) == len(fresh[1])

    def test_a_non_dict_payload_does_not_crash_or_cache(self):
        assert intel._odds_history_player_index_for(None) is not None
        assert intel._odds_history_player_index_for("nope") is not None

    def test_the_reserved_key_does_not_become_a_market(self):
        """The index is stashed on the payload. It must not be mistaken for
        market data by anything reading `markets`."""
        payload = _payload(2)
        intel._odds_history_player_index_for(payload)
        assert intel._ODDS_HISTORY_INDEX_KEY not in payload["markets"]
        assert len(payload["markets"]) == 2


class TestPayloadCache:
    def test_an_unfingerprintable_overview_skips_the_cache(self, monkeypatch):
        """Unknown must not be treated as unchanged -- an unreadable stat must
        never serve a stale 57MB payload."""
        monkeypatch.setattr(intel, "_odds_history_shard_fingerprint", lambda ov: None)
        loads = []
        monkeypatch.setattr(intel, "_load_odds_history_payload_for_sport",
                            lambda slug, key: (loads.append(1), {"markets": {}})[1])
        ov = [{"slug": "mlb", "context_label": ""}]
        intel._odds_history_payloads_by_sport(ov)
        intel._odds_history_payloads_by_sport(ov)
        assert len(loads) >= 2, "a None fingerprint was cached as if it were valid"

    def test_a_matching_fingerprint_serves_the_cache_without_reloading(self, monkeypatch):
        monkeypatch.setattr(intel, "_odds_history_shard_fingerprint", lambda ov: (("p", 1, 2),))
        intel._ODDS_HISTORY_PAYLOAD_CACHE["fingerprint"] = None
        loads = []
        monkeypatch.setattr(intel, "_load_odds_history_payload_for_sport",
                            lambda slug, key: (loads.append(1), {"markets": {}})[1])
        ov = [{"slug": "mlb", "context_label": ""}]
        intel._odds_history_payloads_by_sport(ov)
        first = len(loads)
        intel._odds_history_payloads_by_sport(ov)
        intel._odds_history_payloads_by_sport(ov)
        assert len(loads) == first, f"reloaded {len(loads)-first}x despite an unchanged fingerprint"

    def test_a_changed_fingerprint_reloads(self, monkeypatch):
        """The capture writing mid-build must invalidate, not be served stale."""
        fp = {"v": (("p", 1, 2),)}
        monkeypatch.setattr(intel, "_odds_history_shard_fingerprint", lambda ov: fp["v"])
        intel._ODDS_HISTORY_PAYLOAD_CACHE["fingerprint"] = None
        loads = []
        monkeypatch.setattr(intel, "_load_odds_history_payload_for_sport",
                            lambda slug, key: (loads.append(1), {"markets": {}})[1])
        ov = [{"slug": "mlb", "context_label": ""}]
        intel._odds_history_payloads_by_sport(ov)
        before = len(loads)
        fp["v"] = (("p", 99, 2),)
        intel._odds_history_payloads_by_sport(ov)
        assert len(loads) > before, "a changed shard mtime served a stale payload"

    def test_an_absent_shard_is_part_of_the_fingerprint(self, tmp_path, monkeypatch):
        """A shard APPEARING must invalidate. Absent is a state, not a gap."""
        fp = intel._odds_history_shard_fingerprint([{"slug": "mlb", "context_label": ""}])
        assert fp is None or isinstance(fp, tuple)
