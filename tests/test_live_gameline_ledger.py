"""The live game-line ledger records the OPEN half of CLV, and only movement.

Lane `live-game-line-projection`, for `clv-without-settlement`. Evidence:
`.syndicate/lanes.md` handoff, 2026-08-16.

The load-bearing tests are DEDUPLICATION and NON-FATALITY. The board rebuilds
every few minutes; a recorder that writes unconditionally multiplies the file by
the build rate for no information, and one that raises takes down the product to
protect instrumentation for a measurement nobody has computed yet.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared.live_gameline_ledger import (
    LEDGER_VERSION,
    append_records,
    build_records,
    read_last_by_key,
    record_key,
)


def _row(*, priceable=True, model=0.6, market=0.4069, edge=19.31, segment="full",
         books=("pinnacle", "fanduel"), game_pk=824966):
    return {
        "kind": "game", "market": "h2h", "segment": segment,
        "event_id": "1145a9db", "home_team": "Athletics", "away_team": "Texas Rangers",
        "books": list(books), "age_seconds": 42.5, "updated_at": "2026-08-16T02:00:00Z",
        "game": {"state": "live", "home_score": 3, "away_score": 1},
        "live_gameline": {
            "game_pk": game_pk, "priceable": priceable, "model_prob": model,
            "market_prob": market, "edge_pp": edge, "prob_std_err": 0.04405,
            "sims_run": 120, "as_of": None, "carried_forward": False,
        },
    }


class TestBuildRecords:
    def test_records_a_priceable_row_with_the_join_key_and_the_open_half(self):
        rec = build_records([_row()], sport="mlb", date_str="2026-08-15")[0]
        assert rec["v"] == LEDGER_VERSION
        # identity a close can be joined to
        assert (rec["game_pk"], rec["event_id"], rec["segment"]) == (824966, "1145a9db", "full")
        # the open half
        assert (rec["model_home_win_prob"], rec["market_fair_prob"], rec["edge_pp"]) == (0.6, 0.4069, 19.31)
        # what makes it interpretable later
        assert rec["sims_run"] == 120 and rec["prob_std_err"] == 0.04405
        assert rec["quote_age_seconds"] == 42.5

    def test_a_withheld_row_is_not_recorded(self):
        """Refusals already state their reason in the artifact counters;
        recording thousands per build would bury the few scoreable rows."""
        assert build_records([_row(priceable=False)], sport="mlb", date_str="2026-08-15") == []

    def test_sharp_books_and_pinnacle_are_flagged_separately(self):
        """`state.md`'s 100% sharp coverage is the sharp SET; Pinnacle
        specifically was 15/30 in production, so the join must know which."""
        rec = build_records([_row(books=("novig", "fanduel"))], sport="mlb", date_str="d")[0]
        assert rec["sharp_books"] == ["novig"] and rec["has_pinnacle"] is False
        rec2 = build_records([_row(books=("pinnacle", "novig"))], sport="mlb", date_str="d")[0]
        assert rec2["has_pinnacle"] is True

    @pytest.mark.parametrize("grid", [None, [], "rows", [None], [{}], [{"live_gameline": None}]])
    def test_malformed_grid_is_empty_not_an_exception(self, grid):
        assert build_records(grid, sport="mlb", date_str="d") == []


class TestDeduplication:
    """The reason the file does not grow by the build rate."""

    def test_an_unchanged_market_is_not_rewritten(self, tmp_path):
        p = tmp_path / "led.jsonl"
        recs = build_records([_row()], sport="mlb", date_str="d")
        assert append_records(p, recs)["written"] == 1
        second = append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        assert second["written"] == 0 and second["skipped_unchanged"] == 1
        assert len(p.read_text(encoding="utf-8").strip().splitlines()) == 1

    def test_a_MOVED_market_is_appended_so_the_file_is_a_movement_history(self, tmp_path):
        p = tmp_path / "led.jsonl"
        append_records(p, build_records([_row(market=0.4069)], sport="mlb", date_str="d"))
        out = append_records(p, build_records([_row(market=0.4500)], sport="mlb", date_str="d"))
        assert out["written"] == 1
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(x)["market_fair_prob"] for x in lines] == [0.4069, 0.4500]

    def test_the_same_game_on_a_different_segment_is_a_different_record(self, tmp_path):
        p = tmp_path / "led.jsonl"
        recs = build_records([_row(segment="full"), _row(segment="first5")],
                             sport="mlb", date_str="d")
        assert append_records(p, recs)["written"] == 2

    def test_differing_book_sets_do_not_collapse_onto_each_other(self, tmp_path):
        """Same market, different book consensus, genuinely different prices --
        keying without the book set would keep only whichever was written last."""
        p = tmp_path / "led.jsonl"
        a = _row(books=("pinnacle",), market=0.40)
        b = _row(books=("fanduel",), market=0.44)
        assert record_key(build_records([a], sport="mlb", date_str="d")[0]) != \
               record_key(build_records([b], sport="mlb", date_str="d")[0])
        assert append_records(p, build_records([a, b], sport="mlb", date_str="d"))["written"] == 2


class TestDurability:
    def test_a_truncated_final_line_does_not_discard_the_history(self, tmp_path):
        """Expected after a SIGKILL mid-append, and this worker is OOM-killed."""
        p = tmp_path / "led.jsonl"
        append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        with p.open("a", encoding="utf-8") as h:
            h.write('{"game_pk": 999, "segm')
        assert len(read_last_by_key(p)) == 1

    def test_an_unwritable_path_returns_an_error_and_does_not_raise(self, tmp_path):
        """A ledger failure must never take down the board build."""
        target = tmp_path / "afile"
        target.write_text("x", encoding="utf-8")
        out = append_records(target / "nested" / "led.jsonl",
                             build_records([_row()], sport="mlb", date_str="d"))
        assert out["written"] == 0 and "error" in out

    def test_the_build_cap_is_reported_not_silent(self, tmp_path):
        """A silent cap reads as 'that is all that happened'."""
        p = tmp_path / "led.jsonl"
        rows = [_row(game_pk=i) for i in range(600)]
        out = append_records(p, build_records(rows, sport="mlb", date_str="d"))
        assert out["truncated_build_cap"] == 100 and out["written"] == 500

    def test_the_kill_switch_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLB_LIVE_GAMELINE_LEDGER_ENABLED", "0")
        p = tmp_path / "led.jsonl"
        out = append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        assert out["enabled"] is False and out["written"] == 0 and not p.exists()
