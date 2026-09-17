"""`model_scorecard` -- the scheduled scorecard over the Layer 2 priced population.

Lane `model-scorecard-cron` `[2026-09-17]`. The load-bearing tests:
- PARITY: the per-game-SUM evaluator returns exactly what `bucket_search.evaluate_buckets`
  returns on the same graded rows, for buckets AND for category cells. The module keeps a
  second copy of that logic so a month of history fits in a state file; this test is what
  stops the copy drifting.
- a game is committed once, only when final (or forced after FORCE_COMMIT_AFTER_DAYS), and a
  scoreboard that could not be READ never commits a game;
- a grader-signature change resets history instead of pooling across versions;
- the overlay carries only validated buckets under bucket_search's unchanged bar.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import model_scorecard as msc

bs = msc.load_bucket_search()
NOW = datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc)
FAST = {"resamples": 400, "seed": 11, "q": 0.10}


def _graded_rows(seed: int = 3, *, dates: int = 8, games_per_date: int = 12, planted: float = 0.0):
    """Graded rows in `grade_population`'s output shape, bucketed by the real `bucket_ids`."""
    rng = random.Random(seed)
    rows = []
    for d in range(dates):
        day = f"2026-09-{d + 1:02d}"
        for g in range(games_per_date):
            game = f"mlb|evt-{d}-{g}"
            for side_edge in (rng.uniform(-12, 12), rng.uniform(-12, 12), rng.uniform(-4, 4)):
                fair = rng.uniform(0.3, 0.7)
                view = {"sport": "mlb", "market": "totals", "segment": "full",
                        "phase": "live" if g % 3 == 0 else "pregame", "model_edge_pct": side_edge,
                        "fair_probability": fair, "book_age_seconds": rng.choice([30.0, 300.0, 900.0]),
                        "books_quoting": rng.choice([2.0, 5.0, 9.0]), "fair_method": "consensus"}
                truth = min(0.95, max(0.05, fair + (planted * side_edge / 100.0)))
                y = 1.0 if rng.random() < truth else 0.0
                p_model = min(bs.P_CEIL, max(bs.P_FLOOR, fair + side_edge / 100.0))
                rows.append({"date": day, "sport": "mlb", "game": game, "buckets": mbs.bucket_ids(view), "y": y,
                             "p_market": fair, "p_model": p_model, "model_edge_pct": side_edge,
                             "pnl": (1.0 if y else -1.0)})
    return rows


def _games_from(rows):
    games = {}
    for row in rows:
        entry = games.setdefault(row["game"], {"date": row["date"], "sport": row["sport"], "rows": 0, "ids": {}})
        entry["rows"] += 1
        msc._accumulate(entry["ids"], row)
    return list(games.values())


_COMPARED = ("games", "dates", "roi_games", "roi_dates", "verdict", "profit_verdict", "lodo_stable",
             "roi_lodo_stable", "established_loss_rel")
_FLOATS = ("brier_diff", "p", "market_brier", "roi_model_side", "roi_p")


def _assert_same(left, right):
    assert [r["bucket_id"] for r in left] == [r["bucket_id"] for r in right]
    for a, b in zip(left, right):
        for field in _COMPARED:
            assert a[field] == b[field], (a["bucket_id"], field)
        for field in _FLOATS:
            if a[field] is None or b[field] is None:
                assert a[field] is b[field] is None, (a["bucket_id"], field)
            else:
                assert a[field] == pytest.approx(b[field], abs=1e-12), (a["bucket_id"], field)
        for field in ("ci95", "roi_ci95"):
            assert (a[field] is None) == (b[field] is None)
            if a[field] is not None:
                assert a[field] == pytest.approx(b[field], abs=1e-12)


@pytest.mark.parametrize("planted", [0.0, 1.5])
def test_the_sum_evaluator_matches_bucket_search_on_buckets(planted):
    rows = _graded_rows(planted=planted)
    expected = bs.evaluate_buckets(rows, min_games=20, min_dates=5, **FAST)
    got = msc.evaluate_ids(_games_from(rows), bs=bs, select=msc.is_bucket, min_games=20, min_dates=5,
                           resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])
    _assert_same(got, expected)
    assert any(r["verdict"] != mbs.VERDICT_INSUFFICIENT for r in got), "the fixture must reach a verdict"


def test_the_sum_evaluator_matches_bucket_search_on_category_cells():
    rows = _graded_rows(planted=1.5)
    as_cells = [dict(row, buckets=["|".join(row["buckets"][0].split("|")[:4])]) for row in rows]
    expected = bs.evaluate_buckets(as_cells, min_games=20, min_dates=5, **FAST)
    got = msc.evaluate_ids(_games_from(rows), bs=bs, select=msc.is_cell, min_games=20, min_dates=5,
                           resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])
    _assert_same(got, expected)
    assert {r["bucket_id"] for r in got} == {"mlb|totals|full|pregame", "mlb|totals|full|live"}


# --------------------------------------------------------------------------
# state and incremental grading
# --------------------------------------------------------------------------


def _record(event="evt-1", sport="mlb", market="totals", side="over", line=8.5, ct="2026-09-18T23:05:00Z",
            t="2026-09-18T15:00:00Z", gs="pregame"):
    return {"k": f"{event}|{market}||full|{side}|{line!r}", "t": t, "sport": sport, "ct": ct, "ht": "Home",
            "at": "Away", "px": -110, "fp": 0.5, "me": 3.0, "gs": gs, "sc": 1.2, "ln": "opportunity"}


def test_merge_keeps_one_record_per_sighting_and_counts_late_records():
    state = msc.empty_state("sig")
    first = msc.merge_board_date(state, "2026-09-18", [_record(), _record(), _record(gs="live", t="2026-09-19T00:10:00Z")],
                                 today="2026-09-20", central_date=bs.SCORECARD.central_date, fetched_at="x")
    assert first == {"added": 2, "duplicate": 1}
    assert set(state["pending"]["mlb|evt-1"][0]) <= set(msc.KEEP_FIELDS), "records are stripped"
    state["games"]["mlb|evt-2"] = {"date": "2026-09-18"}
    second = msc.merge_board_date(state, "2026-09-19", [_record(event="evt-2")], today="2026-09-20",
                                  central_date=bs.SCORECARD.central_date, fetched_at="x")
    assert second == {"late": 1} and state["late_records"] == 1
    assert state["board_dates"]["2026-09-18"]["complete"] is True
    assert state["board_dates"]["2026-09-19"]["complete"] is False


def _fake_grade(outcomes):
    def grade(records, chips_by_date, event_teams=None, *, today=None, ungraded_by_sport=None, **_):
        graded, ungraded = outcomes(records)
        if ungraded_by_sport is not None:
            ungraded_by_sport["mlb"] = dict(ungraded)
        return graded, ungraded
    return grade


def test_a_game_waits_for_its_final_then_commits_once():
    state = msc.empty_state("sig")
    msc.merge_board_date(state, "2026-09-18", [_record()], today="2026-09-19", central_date=bs.SCORECARD.central_date,
                         fetched_at="x")
    row = _graded_rows(dates=1, games_per_date=1)[0]
    waiting = msc.grade_pending(state, today="2026-09-19", grade=_fake_grade(lambda r: ([], {"game_not_final": 1})),
                                chips_for=lambda day: [], central_date=bs.SCORECARD.central_date)
    assert waiting == {"waiting_for_final": 1} and "mlb|evt-1" in state["pending"]
    done = msc.grade_pending(state, today="2026-09-19", grade=_fake_grade(lambda r: ([row], {"push": 1})),
                             chips_for=lambda day: [], central_date=bs.SCORECARD.central_date)
    assert done == {"committed": 1, "committed_final": 1}
    assert state["pending"] == {} and state["games"]["mlb|evt-1"]["rows"] == 1
    assert state["ungraded"]["2026-09-18"] == {"mlb": {"push": 1}}


def test_a_game_still_not_final_is_force_committed_after_the_grace_days():
    state = msc.empty_state("sig")
    msc.merge_board_date(state, "2026-09-18", [_record()], today="2026-09-21", central_date=bs.SCORECARD.central_date,
                         fetched_at="x")
    counts = msc.grade_pending(state, today="2026-09-21",
                               grade=_fake_grade(lambda r: ([], {"extra_segment_not_complete": 1})),
                               chips_for=lambda day: [], central_date=bs.SCORECARD.central_date)
    assert counts == {"committed": 1, "committed_forced": 1}


def test_a_scoreboard_that_could_not_be_read_never_commits_a_game():
    state = msc.empty_state("sig")
    msc.merge_board_date(state, "2026-09-18", [_record()], today="2026-09-25", central_date=bs.SCORECARD.central_date,
                         fetched_at="x")

    def boom(day):
        raise TimeoutError("scoreboard timed out")

    counts = msc.grade_pending(state, today="2026-09-25", grade=_fake_grade(lambda r: ([], {"no_chip_match": 1})),
                               chips_for=boom, central_date=bs.SCORECARD.central_date)
    assert counts == {"chips_unavailable": 1} and "mlb|evt-1" in state["pending"]


def test_a_game_that_has_not_kicked_off_is_not_graded():
    state = msc.empty_state("sig")
    msc.merge_board_date(state, "2026-09-20", [_record(ct="2026-09-20T23:05:00Z")], today="2026-09-20",
                         central_date=bs.SCORECARD.central_date, fetched_at="x")
    called = []
    counts = msc.grade_pending(state, today="2026-09-20", grade=lambda *a, **k: called.append(1),
                               chips_for=lambda day: [], central_date=bs.SCORECARD.central_date)
    assert counts == {"not_yet": 1} and called == []


def test_a_new_grader_signature_resets_history_and_says_so():
    saved = dict(msc.empty_state("old"), games={"mlb|evt-1": {"date": "2026-09-18"}})
    state, reason = msc.load_state(saved, "new", now=NOW)
    assert reason == "grader_signature_changed" and state["games"] == {}
    assert state["resets"][-1]["from"] == "old" and state["resets"][-1]["to"] == "new"
    kept, none = msc.load_state(saved, "old", now=NOW)
    assert none is None and kept["games"] == saved["games"]
    fresh, first = msc.load_state(None, "new", now=NOW)
    assert first is None and fresh["games"] == {}


def test_board_dates_always_include_today_and_yesterday_then_incomplete_oldest_first():
    state = msc.empty_state("sig")
    state["board_dates"]["2026-09-14"] = {"complete": True}
    wanted = msc.board_dates_to_fetch(state, "2026-09-18", limit=10)
    assert wanted == ["2026-09-18", "2026-09-17", "2026-09-15", "2026-09-16"]
    assert msc.board_dates_to_fetch(state, "2026-09-18", limit=3) == ["2026-09-18", "2026-09-17", "2026-09-15"]


# --------------------------------------------------------------------------
# the scorecard and the overlay
# --------------------------------------------------------------------------


def _state_with(rows):
    state = msc.empty_state("sig")
    for game in _games_from(rows):
        state["games"][f"{game['sport']}|{id(game)}"] = game
    return state


def test_the_scorecard_reports_windows_cells_and_coverage_and_the_overlay_holds_only_validated_buckets():
    rows = [dict(r, date=r["date"].replace("2026-09-0", "2026-09-1")) for r in _graded_rows(dates=8, games_per_date=12,
                                                                                            planted=1.5)]
    state = _state_with(rows)
    scorecard, overlay = msc.build_scorecard(state, bs=bs, today="2026-09-19", now=NOW, grader={"g": 1}, run={},
                                             resamples=300)
    assert set(scorecard["windows"]) == {"7d", "28d"}
    cov = scorecard["windows"]["28d"]["coverage"]
    assert cov["by_sport"]["mlb"]["games"] == 96 and cov["dates_with_graded_games"] == 8
    cells = {(c["phase"], c["verdict"]) for c in scorecard["windows"]["28d"]["cells"]}
    assert {phase for phase, _ in cells} == {"pregame", "live"}
    for bucket_id, entry in overlay["buckets"].items():
        assert entry["verdict"] in (mbs.VERDICT_SKILL_POCKET, mbs.VERDICT_SKILL_LOSS)
        assert entry["games"] >= bs.MIN_GAMES and entry["dates"] >= bs.MIN_DATES
        assert bucket_id.count("|") == 4
    assert overlay["source"] == msc.SCORECARD_VERSION and overlay["expires_at"] > overlay["generated_at"]


def test_verdict_changes_name_the_cell_and_both_verdicts():
    previous = {"windows": {"7d": {"cells": [{"sport": "mlb", "market": "totals", "segment": "full",
                                              "phase": "live", "verdict": "parity"}]}}}
    now = [{"sport": "mlb", "market": "totals", "segment": "full", "phase": "live", "verdict": "loses_to_market"}]
    assert msc.verdict_changes(previous, now, "7d") == [
        {"cell": "mlb|totals|full|live", "from": "parity", "to": "loses_to_market"}]


def test_overlay_diff():
    before = {"buckets": {"a": {"verdict": "skill_loss"}, "b": {"verdict": "skill_loss"}}}
    after = {"buckets": {"b": {"verdict": "skill_pocket"}, "c": {"verdict": "skill_loss"}}}
    assert msc.overlay_diff(before, after) == {"added": ["c"], "removed": ["a"], "verdict_changed": ["b"]}


def test_published_names_carry_no_iso_date_so_date_scoped_worker_pulls_skip_them():
    for relative in (msc.scorecard_path("2026-09-17"), msc.markdown_path("2026-09-17"), msc.STATE_PATH,
                     msc.OVERLAY_PATH, msc.LATEST_PATH):
        assert "2026-09-17" not in relative


def test_every_published_path_is_allowlisted():
    from syndicate.features.shared import artifact_publisher as ap

    for relative in (msc.scorecard_path("2026-09-17"), msc.markdown_path("2026-09-17"), msc.STATE_PATH,
                     msc.OVERLAY_PATH, msc.LATEST_PATH, f"{msc.REPORT_DIR}/weekly/weekly_backtests_20260921.json"):
        assert ap.is_hot_artifact_relative_path(relative), relative


def test_the_allowlist_names_the_family_explicitly_not_an_open_directory():
    """An open `reports/model_scorecard/*` would list-and-stat an accumulating directory on every export walk."""
    from syndicate.features.shared import artifact_publisher as ap

    patterns = [p for p in ap.HOT_ARTIFACT_PATTERNS if p.startswith("reports/model_scorecard/")]
    assert patterns and "reports/model_scorecard/*" not in patterns
    assert not ap.is_hot_artifact_relative_path("reports/model_scorecard/anything_else.json")
