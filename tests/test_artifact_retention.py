"""`#396` -- retention for a disk that had none and fills in ~43 days.

Measured 2026-08-12: ~700 MB/day on a 50 GB volume at ~40%. The only `unlink()`
calls anywhere in the publish path are temp-file cleanup during atomic writes.

The tests that matter here are the REFUSALS, not the deletions. Render is the
source of truth and the git tree is a lossy mirror, so a file removed here may
be the only copy in existence.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from syndicate.features.shared import artifact_retention as ar

TODAY = date(2026, 8, 12)


def _touch(root, rel, size=1024):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x" * size, encoding="utf-8")
    return p


def test_it_defaults_to_dry_run_and_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", raising=False)
    old = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.dry_run is True
    assert out.matched == 1 and out.deleted == 0
    assert out.bytes_reclaimable > 0 and out.bytes_deleted == 0
    assert old.exists(), "dry run deleted a file"


def test_it_deletes_only_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    old = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 1 and out.bytes_deleted > 0
    assert not old.exists()


def test_an_unmatched_path_is_kept_even_when_ancient(tmp_path, monkeypatch):
    """An unknown path is not evidence that a file is disposable."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    keep = _touch(tmp_path, "something_new/invented_2019-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and keep.exists()


def test_an_undated_file_is_never_aged_out(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    keep = _touch(tmp_path, "mlb_source/data/book_grid/current_week.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and keep.exists()


def test_captures_get_a_far_longer_window_than_derived(tmp_path, monkeypatch):
    """A book_grid is rebuildable from book_quotes; a quote is a fact. A single
    window would either shred captures or never reclaim the derived bulk."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    derived = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2026-08-01.json")
    source = _touch(tmp_path, "mlb_source/tracking/book_quotes/2026-08-01.jsonl")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not derived.exists(), "an 11-day-old derived grid should be reclaimed"
    assert source.exists(), "an 11-day-old CAPTURE must be kept"
    assert out.by_tier == {"derived": 1}


def test_todays_artifacts_are_never_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    live = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2026-08-12.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and live.exists()


@pytest.mark.parametrize("junk", ["", "nope", "0", "-5"])
def test_a_junk_window_falls_back_to_the_default_not_to_zero(tmp_path, monkeypatch, junk):
    """A window of 0 would delete every dated artifact. An unparseable value
    must never map onto the most destructive branch."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_RETENTION_SOURCE_DAYS", junk)
    keep = _touch(tmp_path, "mlb_source/tracking/book_quotes/2026-08-10.jsonl")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert keep.exists(), f"junk value {junk!r} destroyed a recent capture"


def test_a_missing_root_does_not_raise(tmp_path):
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path / "nope")
    assert out.scanned == 0 and out.deleted == 0


# ---------------------------------------------------------------------------
# Settlement evidence: age is the WRONG axis (owner decision 2026-08-12 --
# "keep settlement_inputs for 30 days after settlement").
#
# The tests that matter are the two KEEP branches. A two-valued resolver has to
# map "could not tell" onto settled or unsettled, and mapping it onto settled
# deletes evidence exactly when the join is broken.
# ---------------------------------------------------------------------------

BASE_COLUMNS = "away_team,captured_at,closing_price,date,event_id,home_team,market,selection,sport"
GRADED_COLUMNS = BASE_COLUMNS + ",actual,away_score,home_score,result"


def _closing(root, date_str, *, graded, populated=True):
    p = root / "settlement_inputs" / f"closing_lines_{date_str}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    if graded:
        row = "ATH,x,-110,%s,e1,TB,h2h,home,mlb,1,3,4,%s" % (date_str, "win" if populated else "")
        p.write_text(GRADED_COLUMNS + "\n" + row + "\n", encoding="utf-8")
    else:
        p.write_text(BASE_COLUMNS + "\n" + "ATH,x,-110,%s,e1,TB,h2h,home,mlb\n" % date_str, encoding="utf-8")
    return p


def test_settlement_evidence_for_an_UNGRADED_date_is_kept_forever(tmp_path, monkeypatch):
    """closing_lines_2026-07-14.csv is real: 15 columns, nothing graded. It is
    exactly the evidence needed to grade that date later."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    _closing(tmp_path, "2020-01-01", graded=False)
    finals = _touch(tmp_path, "settlement_inputs/finals_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 0
    assert out.unsettled_kept >= 1
    assert out.unknown_settlement == 0
    assert finals.exists()


def test_an_UNRESOLVABLE_settlement_join_keeps_the_file_and_is_counted_apart(tmp_path, monkeypatch):
    """No closing_lines file at all -> unknown, not 'old enough'."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    finals = _touch(tmp_path, "settlement_inputs/finals_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 0
    assert out.unknown_settlement >= 1
    assert out.unsettled_kept == 0, "unknown must not be reported as a real 'unsettled' answer"
    assert finals.exists()


def test_graded_columns_present_but_empty_is_not_settled(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    _closing(tmp_path, "2020-01-01", graded=True, populated=False)
    finals = _touch(tmp_path, "settlement_inputs/finals_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 0 and out.unsettled_kept >= 1
    assert finals.exists()


def test_a_settled_date_inside_the_30_day_grace_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    recent = (TODAY - timedelta(days=10)).isoformat()
    _closing(tmp_path, recent, graded=True)
    finals = _touch(tmp_path, f"settlement_inputs/finals_{recent}.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 0
    assert finals.exists()


def test_a_settled_date_past_the_30_day_grace_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    old = (TODAY - timedelta(days=45)).isoformat()
    _closing(tmp_path, old, graded=True)
    finals = _touch(tmp_path, f"settlement_inputs/finals_{old}.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not finals.exists()
    assert out.deleted >= 1
    assert out.by_tier.get("settlement", 0) >= 1


def test_settlement_grace_is_measured_from_settlement_not_from_the_derived_window(tmp_path, monkeypatch):
    """A 45-day-old settled date is past BOTH windows; a 45-day-old UNGRADED one
    is past the derived window and must still survive."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    old = (TODAY - timedelta(days=45)).isoformat()
    _closing(tmp_path, old, graded=False)
    finals = _touch(tmp_path, f"settlement_inputs/finals_{old}.json")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert finals.exists(), "age rule leaked onto settlement evidence"


# ---------------------------------------------------------------------------
# Coverage holes measured against the real production inventory 2026-08-12:
# 1,960.7 MB across 2,826 files matched no rule at all.
# ---------------------------------------------------------------------------

def test_the_artifacts_odds_history_twin_is_retained_like_its_tracking_copy(tmp_path, monkeypatch):
    """655.3 MB unmanaged against 655.0 MB managed -- the same bytes twice, one
    of them subject to a window. Retiring a shard must retire every copy."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    tracked = _touch(tmp_path, "mlb_source/tracking/odds_history/2020-01-01.json")
    twin = _touch(tmp_path, "mlb_source/artifacts/mlb/odds_history/2020-01-01.json")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not tracked.exists() and not twin.exists()


def test_the_second_daily_tree_is_covered(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    ladder = _touch(tmp_path, "mlb_source/data/daily/ladders/daily_ladders_2020_01_01.json")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not ladder.exists()


def test_dated_intelligence_snapshots_age_but_the_live_one_never_does(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    dated = _touch(tmp_path, "reports/intelligence/intelligence_state_2020_01_01.json")
    live = _touch(tmp_path, "reports/intelligence/intelligence_state.json")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not dated.exists()
    assert live.exists(), "the live board state was aged out"


def test_eval_output_gets_its_own_longer_window(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    recent = _touch(tmp_path, "mlb_source/source_artifacts/data/eval/batches/x/sim_vs_actual_%s.json"
                    % (TODAY - timedelta(days=100)).isoformat())
    ancient = _touch(tmp_path, "mlb_source/source_artifacts/data/eval/batches/x/sim_vs_actual_2020-01-01.json")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert recent.exists(), "100d eval output deleted by the 7d derived window"
    assert not ancient.exists()
