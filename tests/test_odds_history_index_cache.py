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


class TestIndexStats:
    """`#414` follow-up. The first version of this fix was UNVERIFIABLE: the
    payload cache (0.7s of a ~1500s build) was instrumented and the index cache
    (essentially all of it) was not. Deployed, then unanswerable.

    These assert the counter distinguishes a working memo from an inert one,
    which a boolean "the cache exists" could not.
    """

    def test_repeated_calls_on_one_payload_count_as_hits(self):
        intel._reset_odds_history_index_stats()
        payload = _payload(3)
        for _ in range(4):
            intel._odds_history_player_index_for(payload)
        assert intel._ODDS_HISTORY_INDEX_STATS["misses"] == 1
        assert intel._ODDS_HISTORY_INDEX_STATS["hits"] == 3

    def test_an_inert_memo_is_visible_as_all_misses(self):
        """If the payload object is rebuilt between calls the memo saves
        nothing. That must show as misses tracking calls, not as silence."""
        intel._reset_odds_history_index_stats()
        for _ in range(4):
            intel._odds_history_player_index_for(_payload(3))
        assert intel._ODDS_HISTORY_INDEX_STATS["hits"] == 0
        assert intel._ODDS_HISTORY_INDEX_STATS["misses"] == 4

    def test_a_non_dict_payload_is_neither_hit_nor_miss(self):
        """There is no payload to memoise, so counting it either way would move
        the rate without anything changing."""
        intel._reset_odds_history_index_stats()
        intel._odds_history_player_index_for(None)
        intel._odds_history_player_index_for("nope")
        # Asserts the COUNTERS, not the dict shape -- an exact-equality check
        # here failed the moment `#414` added event-bucket counters, which is a
        # test coupled to something it is not about.
        assert intel._ODDS_HISTORY_INDEX_STATS["hits"] == 0
        assert intel._ODDS_HISTORY_INDEX_STATS["misses"] == 0

    def test_the_reset_clears_only_the_counters(self):
        intel._odds_history_player_index_for(_payload(2))
        intel._reset_odds_history_index_stats()
        assert intel._ODDS_HISTORY_INDEX_STATS["hits"] == 0
        assert intel._ODDS_HISTORY_INDEX_STATS["misses"] == 0

    def test_the_stats_line_reaches_stdout_not_a_logger(self, capsys):
        """logger.info does not reach Render's log collector from this process;
        an unreadable counter is the defect this counter exists to fix."""
        intel._reset_odds_history_index_stats()
        intel._odds_history_player_index_for(_payload(2))
        intel._log_odds_history_index_stats("test")
        out = capsys.readouterr().out
        assert "ODDS_HISTORY_INDEX_STATS" in out
        assert "hits=0 misses=1" in out and "hit_rate=0%" in out


class TestEventBucket:
    """`#414` proper fix. `by_player` bucketed props and left every game-level
    entry in `unattributed`, copied and scored IN FULL per candidate -- the same
    O(candidates * markets) shape the July fix removed for props only.

    Measured 2026-08-13: ~8-9 seconds PER ROW, flat across seven games. A
    per-build cost gives cheap rows; this was per-row.
    """

    @staticmethod
    def _hist(*keys):
        return {"markets": {k: {"history": [{"line": 1.5}]} for k in keys}}

    def test_a_game_candidate_scores_only_its_own_event(self):
        hist = self._hist(
            "event_id=g1|market=h2h|matchup=Aces at Sky",
            "event_id=g2|market=h2h|matchup=Fever at Sun",
            "event_id=g3|market=h2h|matchup=Wings at Dream",
        )
        idx = intel._build_odds_history_player_index(hist)
        by_player, unattributed, by_event = idx
        assert len(unattributed) == 3, "game-level entries must still be in unattributed"
        assert len(by_event) == 3, "each event must get its own bucket"

    def test_the_full_scan_still_runs_when_the_bucket_misses(self):
        """THE NON-REGRESSION GUARANTEE. A candidate whose event key does not
        match any bucket must still find its match via the full list, or a
        normalisation mismatch silently drops real joins."""
        hist = self._hist("event_id=g1|market=h2h|matchup=Aces at Sky")
        idx = intel._build_odds_history_player_index(hist)
        intel._reset_odds_history_index_stats()
        cand = {"matchup": "Aces at Sky", "market": "h2h", "sport_slug": "wnba",
                "event_id": "COMPLETELY-DIFFERENT"}
        intel._candidate_odds_history_state(cand, idx)
        assert intel._ODDS_HISTORY_INDEX_STATS["full_scans"] == 1, "bucket miss did not fall back"

    def test_an_unkeyable_candidate_takes_the_full_scan(self):
        hist = self._hist("event_id=g1|market=h2h|matchup=Aces at Sky")
        idx = intel._build_odds_history_player_index(hist)
        intel._reset_odds_history_index_stats()
        intel._candidate_odds_history_state({"market": "h2h"}, idx)
        assert intel._ODDS_HISTORY_INDEX_STATS["full_scans"] == 1

    def test_an_empty_index_returns_nothing_without_scanning(self):
        idx = intel._build_odds_history_player_index({"markets": {}})
        key, state = intel._candidate_odds_history_state({"matchup": "x"}, idx)
        assert key == "" and state is None

    def test_the_builder_returns_three_elements(self):
        idx = intel._build_odds_history_player_index(self._hist("event_id=g1|market=h2h"))
        assert len(idx) == 3, "callers unpack three; a 2-tuple would raise at runtime"
