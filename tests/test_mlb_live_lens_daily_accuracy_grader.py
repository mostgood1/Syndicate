"""`#616` -- the MLB live-lens grader must not settle from a running tally.

THE PRODUCTION READING THAT FORCED THIS. Pooled over 2026-07-01..08-31, the
served `/mlb/api/live-lens-accuracy` reported `by_klass` as **over: 0 wins /
1,578** and **under: 206 / 206**. No model goes 0-for-1578 and 206-for-206.

The cause is arithmetic, not modelling. When the feed was unavailable the
grader fell back to `lastSeenSnapshot.actual` -- the stat SO FAR. For a line of
0.5 an early tally of 0 grades every `over` a loss and every `under` a win,
whatever happened later.

It cannot be fixed by reading the snapshot more carefully: a snapshot carries
`actual` / `actualSoFar` / `modelMean` / `liveProjection` and NO game state, so
in-progress and final are indistinguishable there.

AND THE FALLBACK WAS NOT AN EDGE CASE. `feedResolved` was **0 on every one of
the 11 days that produced rows**, against `feed_live_miss: 1,802` -- 100% of
everything this instrument ever graded came from that branch. The feed tree
(`data/raw/statsapi/feed_live/`) is not in `HOT_ARTIFACT_PATTERNS`, so it never
reaches the web service that serves the endpoint. That is a separate decision
with a real disk cost and is deliberately NOT taken here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.mlb import live_lens_daily_accuracy as acc


def _entry(selection="over", line=0.5, actual_so_far=0.0, game_pk=777, prop="hits"):
    return {
        "owner": "Test Batter",
        "market": "hitter_props",
        "prop": prop,
        "selection": selection,
        "marketLine": line,
        "gamePk": game_pk,
        "playerId": 12345,
        "firstSeenSnapshot": {"selection": selection, "marketLine": line, "actual": actual_so_far},
        "lastSeenSnapshot": {"selection": selection, "marketLine": line, "actual": actual_so_far},
        "firstSeenAt": "2026-08-09T18:05:00Z",
        "lastSeenAt": "2026-08-09T19:40:00Z",
    }


def _feed(hits):
    """A statsapi feed_live shaped the way `_feed_stat_indexes` reads it."""
    return {
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "players": {
                            "ID12345": {
                                "person": {"id": 12345, "fullName": "Test Batter"},
                                "stats": {"batting": {"hits": hits, "runs": 0, "rbi": 0,
                                                      "totalBases": hits, "homeRuns": 0}},
                            }
                        }
                    },
                    "away": {"players": {}},
                }
            }
        }
    }


@pytest.fixture
def registry(monkeypatch):
    """Drive `_registry_rows` without touching disk. `state["feed"]` is the
    ONLY switch the tests flip, so a difference in outcome can only come from
    the feed being present or absent."""
    state = {"entries": {}, "feed": None}
    monkeypatch.setattr(acc, "load_json_file", lambda _p: {"entries": state["entries"]})
    monkeypatch.setattr(acc, "raw_feed_live_path", lambda _d, _g: Path("feed.json"))
    monkeypatch.setattr(acc, "load_json_or_gz_file", lambda _p: state["feed"])
    return state


def _run(state, entries):
    state["entries"] = {str(i): e for i, e in enumerate(entries)}
    return acc._registry_rows(Path("registry.json"), "2026-08-09")


# ---------------------------------------------------------------------------
# Reachability: the grader must still WORK when the feed is there
# ---------------------------------------------------------------------------


def test_OFF_IS_NOT_ON_a_real_feed_still_settles(registry):
    """If this fails, the fix has simply disabled the instrument rather than
    corrected it, and every other test here would pass on a dead grader."""
    registry["feed"] = _feed(hits=2)
    rows, meta = _run(registry, [_entry(selection="over", line=0.5)])
    assert len(rows) == 1
    assert rows[0]["result"] == "win"
    assert rows[0]["actual"] == 2
    assert rows[0]["actual_source"] == "feed_live"
    assert meta["signals"]["feedResolved"] == 1
    assert meta["signals"]["snapshotActualNotFinal"] == 0


def test_a_real_feed_grades_a_loss_as_a_loss(registry):
    registry["feed"] = _feed(hits=0)
    rows, _ = _run(registry, [_entry(selection="over", line=0.5)])
    assert rows[0]["result"] == "loss"


# ---------------------------------------------------------------------------
# The defect: an in-progress tally must not settle anything
# ---------------------------------------------------------------------------


def test_no_feed_means_NO_settled_row_even_though_a_snapshot_value_exists(registry):
    registry["feed"] = None
    rows, meta = _run(registry, [_entry(selection="over", line=0.5, actual_so_far=0.0)])
    assert rows == []
    assert meta["signals"]["snapshotActualNotFinal"] == 1
    assert meta["signals"]["registryFallback"] == 1
    assert meta["signals"]["feedResolved"] == 0


def test_THE_PRODUCTION_SHAPE_over_no_longer_always_loses_and_under_always_wins(registry):
    """The exact signature that surfaced this: at a line of 0.5 with an early
    tally of 0, the old grader returned over=loss and under=win for every row
    in the book. Both must now simply refuse."""
    registry["feed"] = None
    entries = [_entry(selection="over", line=0.5, actual_so_far=0.0) for _ in range(50)]
    entries += [_entry(selection="under", line=0.5, actual_so_far=0.0) for _ in range(50)]
    rows, meta = _run(registry, entries)

    assert rows == [], "an in-progress tally settled 100 bets"
    assert meta["signals"]["snapshotActualNotFinal"] == 100

    summary = acc._summary(rows)
    assert summary["wins"] == 0 and summary["losses"] == 0
    assert summary["hit_rate"] is None, "an empty book must report no rate, not 0%"

    klass = {item["key"]: item for item in acc._group_rows(rows, "klass")}
    assert klass == {}, "no side may carry a 0-for-N or N-for-N record from a tally"


def test_the_refusal_is_NAMED_so_an_empty_day_is_not_read_as_no_projections(registry):
    """`nothing was gradeable` and `nothing was projected` are opposite facts.
    The old code could not tell them apart and neither could a reader."""
    registry["feed"] = None
    _, meta = _run(registry, [_entry(), _entry(selection="under")])
    assert "snapshot_actual_not_final:2" in meta["warnings"]


def test_an_entry_with_no_value_at_all_is_pending_not_not_final(registry):
    """Two different absences. A row the registry never carried a value for is
    PENDING; a row we have a tally for but refuse to trust is NOT_FINAL.
    Collapsing them would hide which problem a day actually has."""
    registry["feed"] = None
    entry = _entry()
    entry["firstSeenSnapshot"]["actual"] = None
    entry["lastSeenSnapshot"]["actual"] = None
    _, meta = _run(registry, [entry])
    assert meta["signals"]["snapshotActualNotFinal"] == 0
    assert meta["signals"]["registryFallback"] == 0
    assert any(w.startswith("pending_actuals:") for w in meta["warnings"])


def test_a_snapshot_that_happens_to_be_correct_is_STILL_refused(registry):
    """Deliberate. A snapshot carries no game state, so a tally that happens to
    equal the final line is indistinguishable from one that does not. Grading
    the lucky ones would put the instrument's correctness back on timing."""
    registry["feed"] = None
    rows, meta = _run(registry, [_entry(selection="over", line=0.5, actual_so_far=3.0)])
    assert rows == []
    assert meta["signals"]["snapshotActualNotFinal"] == 1


def test_the_feed_miss_counter_still_reports_the_structural_blocker(registry):
    """`feed_live_miss` is what says the feed tree never reaches this service.
    Refusing to settle must not silence the reason."""
    registry["feed"] = None
    _, meta = _run(registry, [_entry()])
    assert any(w.startswith("feed_live_miss:") for w in meta["warnings"])
