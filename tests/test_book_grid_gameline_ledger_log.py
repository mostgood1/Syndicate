"""Every book-grid build prints ONE line saying what the live-gameline attach and
the ledger write did.

Lane `book-grid-gameline-ledger-log`. Why it exists, measured 2026-09-14 on MLB
2026-09-12: the scorer capped at 5 of 15 games with every final present
(`unscored: {}`). The per-record ledger held `segment=full` rows from only 4 of
139 builds, while refresh-worker's layer2 join logged full-game `live_mc`
projections for 1-9 games. The hop between the book-grid build's attach and its
ledger write printed NOTHING per build. Its counters rode the artifact, which the
next build overwrites, so the hop was unmeasurable after the fact.

The line is machine-read, so presence is not the predicate (`learnings.md`
2026-09-06: a duplicate is present twice). These tests assert the field set, no
name emitted twice, dict-valued fields last, and a length that survives Render's
logs API (`learnings.md` 2026-09-02: it cut a payload at ~1,200 chars).
"""

from __future__ import annotations

import json
import re

import pytest

from syndicate.features.shared import board_enrichment, book_grid_artifact
from syndicate.features.shared import live_gameline_accuracy, live_gameline_ledger
from syndicate.features.shared.live_gameline_join import REFUSAL_KEY
from syndicate.features.shared.live_gameline_ledger import append_records, build_records

TAG = "[book_grid] LIVE_GAMELINE_BUILD"

_SCALARS = {
    "sport", "date", "index", "seg_index", "considered", "projected", "priceable",
    "withheld", "full_games", "candidates", "written", "skipped_unchanged",
    "truncated_build", "truncated_file", "error", "clipped",
}
_DICTS = {
    "attached_by_segment", "refused_by_segment", "written_by_segment",
    "skipped_by_segment", "withheld_by_reason", "index_why",
}

_COVERAGE = {
    "supported": True,
    "index_size": 9,
    "segment_index_size": 6,
    "rows_live_gameline_considered": 227,
    "rows_live_gameline_projected": 40,
    "rows_live_gameline_priceable": 0,
    "rows_live_gameline_withheld": 187,
    "withheld_by_reason": {"segment_pricing_disabled": 124, "quote_older_than_live_pricing_ceiling": 35},
    "index_diagnostics": {
        "games_in_snapshot": 15, "indexed": 9, "skipped_no_team_names": 0,
        "skipped_no_accepted_lane": 6,
        "sources_seen": {"live_mc": 18, "segment_projection": 54, "live_mc_first5": 6},
        "accepted_sources": ["live_mc"],
    },
}
_LEDGER = {
    "candidates": 50, "written": 12, "skipped_unchanged": 38, "truncated_build_cap": 0,
    "truncated_file_cap": 0, "enabled": True,
    "written_by_segment": {"first5": 10, "full": 2},
    "skipped_unchanged_by_segment": {"first5": 30, "full": 8},
}


def _lg_row(game_pk, *, segment="full", market="h2h", model=0.6):
    return {
        "kind": "game", "market": market, "segment": segment, "line": None,
        "event_id": f"evt-{game_pk}", "home_team": "Home", "away_team": "Away",
        "books": ["pinnacle"], "age_seconds": 10.0, "updated_at": "2026-09-12T18:00:00Z",
        "game": {"state": "live", "home_score": 1, "away_score": 0},
        "live_gameline": {
            "game_pk": game_pk, "priceable": False, "model_prob": model,
            "market_prob": 0.5, "edge_pp": 1.0, "prob_std_err": 0.04, "sims_run": 120,
            "as_of": None, "carried_forward": False, "withheld_reason": "x", "sigma": 2.0,
        },
    }


def _line(grid=(), coverage=_COVERAGE, ledger=_LEDGER):
    return book_grid_artifact.live_gameline_build_line(
        "mlb", "2026-09-12", list(grid), coverage, ledger
    )


def _fields(line):
    assert line.startswith(TAG + " "), line
    return re.findall(r"(\w+)=(\S+)", line[len(TAG):])


class TestTheLine:
    def test_every_field_is_emitted_exactly_once_and_dicts_come_last(self):
        fields = _fields(_line())
        names = [name for name, _ in fields]
        assert len(names) == len(set(names)), names
        assert set(names) == (_SCALARS - {"clipped"}) | _DICTS
        first_dict = next(i for i, (name, _) in enumerate(fields) if name in _DICTS)
        assert all(name in _DICTS for name, _ in fields[first_dict:]), names
        assert all(value.startswith("{") for _, value in fields[first_dict:])

    def test_counters_are_read_from_the_coverage_and_the_ledger(self):
        f = dict(_fields(_line()))
        assert (f["index"], f["seg_index"], f["projected"], f["withheld"]) == ("9", "6", "40", "187")
        assert (f["candidates"], f["written"], f["skipped_unchanged"]) == ("50", "12", "38")
        assert json.loads(f["written_by_segment"]) == {"first5": 10, "full": 2}
        assert json.loads(f["skipped_by_segment"]) == {"first5": 30, "full": 8}
        assert json.loads(f["index_why"])["sources_seen"]["live_mc"] == 18
        assert f["error"] == "none"

    def test_full_games_counts_distinct_full_game_pks_not_segment_rows(self):
        """The number that was missing on 09-12: how many GAMES the book-grid
        build actually attached a full-game projection to. Rows are not games
        (one game carries h2h, spreads and totals), and first5 rows must never
        inflate it."""
        refused = {"kind": "game", "market": "totals_alt", "segment": "first5",
                   REFUSAL_KEY: {"reason": "segment_pricing_disabled"}}
        grid = [
            _lg_row(1), _lg_row(1, market="spreads"), _lg_row(2),
            _lg_row(3, segment="first5"), _lg_row(4, segment="first5"),
            refused, {"kind": "game", "market": "h2h", "segment": "full"},
        ]
        f = dict(_fields(_line(grid)))
        assert f["full_games"] == "2"
        assert json.loads(f["attached_by_segment"]) == {"first5": 2, "full": 3}
        assert json.loads(f["refused_by_segment"]) == {"first5": 1}

    def test_a_blank_segment_counts_as_full(self):
        """`build_records` and the scorer both read a blank segment as the full
        game; a line that read it otherwise would disagree with the ledger."""
        row = _lg_row(7)
        row["segment"] = None
        f = dict(_fields(_line([row])))
        assert f["full_games"] == "1"
        assert json.loads(f["attached_by_segment"]) == {"full": 1}

    def test_error_text_cannot_break_key_value_parsing(self):
        f = _fields(_line(coverage={"supported": True, "error": "live gameline join failed",
                                    "rows_live_gameline_edged": 0}))
        names = [name for name, _ in f]
        assert len(names) == len(set(names))
        assert dict(f)["error"] == "live_gameline_join_failed"

    def test_the_ledger_error_is_reported_when_the_join_had_none(self):
        f = dict(_fields(_line(ledger={"written": 0, "error": "OSError: disk full"})))
        assert f["error"] == "ledger:OSError:_disk_full"

    def test_line_stays_under_the_render_log_truncation(self):
        coverage = dict(_COVERAGE)
        coverage["withheld_by_reason"] = {f"reason_number_{i:03d}": i for i in range(300)}
        line = _line(coverage=coverage)
        assert len(line) <= book_grid_artifact.LIVE_GAMELINE_BUILD_MAX_CHARS <= 1100
        fields = _fields(line)
        names = [name for name, _ in fields]
        assert len(names) == len(set(names))
        f = dict(fields)
        # Scalars are never the casualty: the counters survive, the widest
        # dicts are dropped and COUNTED.
        assert _SCALARS - {"clipped"} <= set(names)
        assert int(f["clipped"]) >= 1

    @pytest.mark.parametrize("grid, coverage, ledger", [
        (None, None, None),
        ("rows", {"index_size": "x", "withheld_by_reason": "bad"}, []),
        ([None, {}, {"live_gameline": "nope"}], {"index_diagnostics": 5}, {"written": None}),
    ])
    def test_never_raises_on_malformed_inputs(self, grid, coverage, ledger):
        line = book_grid_artifact.live_gameline_build_line("mlb", "d", grid, coverage, ledger)
        assert line.startswith(TAG + " ")


class TestLedgerCountersBySegment:
    def test_written_and_skipped_are_split_by_segment(self, tmp_path):
        """`written` alone lumps first5 with full, and first5 outnumbered full
        about 170 to 1 in the 09-12 ledger, so a total cannot show whether the
        full-game rows were written."""
        path = tmp_path / "led.jsonl"
        recs = build_records([_lg_row(1), _lg_row(3, segment="first5")], sport="mlb", date_str="d")
        first = append_records(path, recs)
        assert first["written"] == 2
        assert first["written_by_segment"] == {"first5": 1, "full": 1}
        assert first["skipped_unchanged_by_segment"] == {}
        second = append_records(path, recs)
        assert second["written"] == 0 and second["written_by_segment"] == {}
        assert second["skipped_unchanged_by_segment"] == {"first5": 1, "full": 1}

    def test_the_split_sums_to_the_totals(self, tmp_path):
        path = tmp_path / "led.jsonl"
        recs = build_records([_lg_row(i, segment=s) for i, s in
                              enumerate(["full", "first5", "first5", None, "first3"])],
                             sport="mlb", date_str="d")
        append_records(path, recs[:2])
        cov = append_records(path, recs)
        assert sum(cov["written_by_segment"].values()) == cov["written"]
        assert sum(cov["skipped_unchanged_by_segment"].values()) == cov["skipped_unchanged"]


def _quote(market="h2h", selection="home", price=-110):
    return {
        "sport": "mlb", "kind": "game", "event_id": "evt-1", "segment": "full_game",
        "market": market, "player_name": "", "selection": selection, "line": None,
        "price": price, "bookmaker": "draftkings", "home_team": "Baltimore Orioles",
        "away_team": "Los Angeles Angels", "commence_time": "2026-09-12T23:05:00Z",
        "snapshot_ts": "2026-09-12T19:55:00Z",
    }


def test_the_build_prints_the_line_exactly_once(monkeypatch, tmp_path, capsys):
    """REACHABILITY, not formatting: the real `build_book_grid_artifact` must
    emit the line, once, with the coverage the attach returned and the counters
    the ledger returned. This is the test that fails against HEAD."""
    shard = tmp_path / "book_quotes_2026-09-12.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(book_grid_artifact, "book_quotes_path", lambda *a, **k: shard)
    monkeypatch.setattr(book_grid_artifact, "read_quote_last_seen", lambda *a, **k: {})
    quotes = [_quote(selection="home", price=-120), _quote(selection="away", price=100)]
    monkeypatch.setattr(book_grid_artifact, "iter_book_quotes", lambda *a, **k: iter(list(quotes)))

    def _stub(value):
        return lambda grid, **kwargs: dict(value)

    monkeypatch.setattr(board_enrichment, "attach_game_state", _stub({"chips": 1}))
    monkeypatch.setattr(board_enrichment, "attach_live_game_state_from_lens", _stub({}))
    monkeypatch.setattr(board_enrichment, "attach_projections", _stub({"supported": True}))
    monkeypatch.setattr(board_enrichment, "attach_live_projections_for_sport", _stub({}))
    monkeypatch.setattr(board_enrichment, "attach_live_gamelines_for_sport", _stub(_COVERAGE))
    monkeypatch.setattr(board_enrichment, "attach_margin_model", _stub({}))
    monkeypatch.setattr(live_gameline_ledger, "record_live_gamelines", lambda grid, **k: dict(_LEDGER))
    monkeypatch.setattr(book_grid_artifact, "score_block_for_grid", lambda grid, **k: {"enabled": False})
    monkeypatch.setattr(live_gameline_accuracy, "record_live_gameline_score", lambda *a, **k: {"written": 0})

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-09-12")
    assert payload is not None and payload["live_gameline_ledger"] == _LEDGER

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(TAG)]
    assert len(lines) == 1, lines
    f = dict(_fields(lines[0]))
    assert (f["sport"], f["date"], f["index"], f["written"]) == ("mlb", "2026-09-12", "9", "12")
