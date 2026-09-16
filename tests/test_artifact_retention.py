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


# ---------------------------------------------------------------------------
# The bounded walk. Measured 2026-08-12: an unbounded rglob over 65,025 files
# took 18 MINUTES and blocked refresh-worker's main poll loop for all of it.
# Streaming fixed the memory shape and left the wall-clock shape untouched.
#
# "Dry run" describes what this does not DELETE. It says nothing about what it
# COSTS -- a read-only walk is exactly as expensive as a destructive one.
# ---------------------------------------------------------------------------

def test_a_pass_stops_at_the_file_cap_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", "5")
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    for i in range(30):
        _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-%02d.json" % (i + 1))
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.hit_pass_limit is True
    assert out.scanned <= 6, out.scanned


def test_a_truncated_pass_resumes_where_it_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", "5")
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    for i in range(20):
        _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-%02d.json" % (i + 1))

    first = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert first.hit_pass_limit is True
    cursor = ar._read_resume_cursor(tmp_path)
    assert cursor, "no resume cursor written after a truncated pass"

    second = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert ar._read_resume_cursor(tmp_path) != cursor, "second pass did not advance"


def test_a_completed_pass_clears_the_cursor_so_the_next_starts_from_the_top(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", "1000")
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.hit_pass_limit is False
    assert ar._read_resume_cursor(tmp_path) == ""


def test_a_zero_cap_does_not_mean_scan_nothing(tmp_path, monkeypatch):
    """Same rule as every other knob here: unparseable or absurd config maps to
    the default, never to a degenerate branch."""
    monkeypatch.setenv("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", "0")
    assert ar._env_int("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", ar._MAX_FILES_PER_PASS) == ar._MAX_FILES_PER_PASS


# ---------------------------------------------------------------------------
# Lane `worker-disk-auto-retention` (2026-09-16): the rule table, its reader
# lookback guard, directory dates, the sorted cursor, dedupe_twin, and a dry run
# that is proven to touch nothing.
# ---------------------------------------------------------------------------

import hashlib
import json
import math
import os
import random


def test_a_rule_inside_its_readers_lookback_is_refused_at_construction():
    with pytest.raises(ar.RetentionRuleError):
        ar.Rule("too_short", "x/*", "derived", days=7, min_reader_lookback_days=1)
    with pytest.raises(ar.RetentionRuleError):
        ar.Rule("way_too_short", "x/*", "ops", days=10, min_reader_lookback_days=30)
    # Exactly lookback + 7 is allowed.
    ar.Rule("just_enough", "x/*", "derived", days=8, min_reader_lookback_days=1)


def test_every_shipped_rule_passes_the_guard_and_names_its_reader():
    for rule in ar.RULES:
        assert rule.days >= rule.min_reader_lookback_days + ar.LOOKBACK_MARGIN_DAYS, rule.name
        assert rule.reader, f"{rule.name} does not say where its lookback came from"
    assert len({rule.name for rule in ar.RULES}) == len(ar.RULES)


def test_an_env_override_that_crosses_a_readers_window_refuses_that_rule(tmp_path, monkeypatch):
    """SYNDICATE_RETENTION_DERIVED_DAYS=10 is fine for book_grid (lookback 0) and
    must NOT shorten live_lens (lookback 30) to 10 days."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_RETENTION_DERIVED_DAYS", "10")
    grid = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2026-07-30.json")
    signals = _touch(tmp_path, "nba_source/data/live_lens/live_lens_signals_2026-07-20.jsonl")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not grid.exists()
    assert signals.exists(), "an env override shortened a rule past its reader's window"
    assert out.by_rule["live_lens_data"].refused_lookback is True


def test_live_lens_signals_inside_the_30_day_accuracy_window_are_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    inside = _touch(tmp_path, "nba_source/data/live_lens/live_lens_signals_%s.jsonl" % (TODAY - timedelta(days=25)).isoformat())
    outside = _touch(tmp_path, "nba_source/data/live_lens/live_lens_signals_%s.jsonl" % (TODAY - timedelta(days=60)).isoformat())
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert inside.exists()
    assert not outside.exists()


@pytest.mark.parametrize("root_part", ["source_artifacts/data", "data"])
def test_live_prop_observations_survive_past_the_derived_7_days(tmp_path, monkeypatch, root_part):
    """Captures, and read by a 60-day accuracy window -- not derived."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    base = f"mlb_source/{root_part}/live_lens/prop_registry"
    d30 = (TODAY - timedelta(days=30)).strftime("%Y_%m_%d")
    d100 = (TODAY - timedelta(days=100)).strftime("%Y_%m_%d")
    d130 = (TODAY - timedelta(days=130)).strftime("%Y_%m_%d")
    obs30 = _touch(tmp_path, f"{base}/live_prop_observations_{d30}.jsonl")
    obs100 = _touch(tmp_path, f"{base}/live_prop_observations_{d100}.jsonl")
    reg100 = _touch(tmp_path, f"{base}/live_prop_registry_{d100}.json")
    obs130 = _touch(tmp_path, f"{base}/live_prop_observations_{d130}.jsonl")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert obs30.exists() and obs100.exists() and reg100.exists()
    assert not obs130.exists(), "the source window still applies at 120 days"


def test_directory_dated_paths_are_matched_by_dirname(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", raising=False)
    old = _touch(tmp_path, "reports/migration_runs/2026-07-01/odds_refresh_20260701T120000Z/odds_refresh.json")
    recent = _touch(tmp_path, "reports/migration_runs/2026-08-05/odds_refresh_20260805T120000Z/odds_refresh.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    stats = out.by_rule["migration_runs"]
    assert stats.files == 1
    assert stats.oldest == date(2026, 7, 1)
    assert old.exists() and recent.exists()
    assert ar._dirname_date("reports/migration_runs/2026-07-01/odds_refresh_x/f.json") == date(2026, 7, 1)
    # A stamp that merely CONTAINS digits is not a date directory.
    assert ar._dirname_date("reports/migration_runs/odds_refresh_20260701T1200/f.json") is None


def test_new_rules_never_act_on_the_legacy_enable_flag_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.delenv("SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY", raising=False)
    events = _touch(tmp_path, "odds_events/2026-07-01.jsonl")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert events.exists()
    assert out.by_rule["odds_events"].files == 1
    assert out.rule_acts["odds_events"] is False


def test_new_delete_rules_act_only_with_both_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY", "true")
    old = _touch(tmp_path, "odds_events/2026-07-01.jsonl")
    inside = _touch(tmp_path, "odds_events/%s.jsonl" % (TODAY - timedelta(days=7)).isoformat())
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not old.exists()
    assert inside.exists(), "inside the 7-day load_recent_odds_events window"


def _shard(root, rel, size):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"{" + b"x" * (size - 2) + b"}")
    return p


def test_dedupe_twin_refuses_when_tracking_copy_missing_or_smaller(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY", "true")
    no_twin = _shard(tmp_path, "reports/odds_control_plane/odds_history/nba/2026-07-01.json", 500)
    smaller = _shard(tmp_path, "reports/odds_control_plane/odds_history/mlb/2026-07-01.json", 500)
    _shard(tmp_path, "mlb_source/tracking/odds_history/2026-07-01.json", 499)
    ok = _shard(tmp_path, "reports/odds_control_plane/odds_history/mlb/2026-07-02.json", 500)
    _shard(tmp_path, "mlb_source/tracking/odds_history/2026-07-02.json", 500)

    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    stats = out.by_rule["odds_control_plane_history_twin"]
    assert stats.refused_twin == 2
    assert stats.files == 1 and stats.bytes == 500
    # dedupe_twin has no acting path, even with both flags set.
    assert out.rule_acts["odds_control_plane_history_twin"] is False
    assert no_twin.exists() and smaller.exists() and ok.exists()


def test_cursor_covers_every_file_across_capped_passes_with_an_unsorted_listing(tmp_path, monkeypatch):
    """THE CURSOR BUG: the cursor is 'last path examined' and later passes skip
    everything <= it, which is only a seek if the walk is in string order. With
    `rglob` it was not, so capped passes silently skipped paths."""
    disk = tmp_path / "disk"
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "state"))
    cap = 7
    monkeypatch.setenv("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", str(cap))
    expected = set()
    rels = [
        "a.txt",
        "a/b.json",
        "a-b/c.json",
        "a/z/deep_2020-01-01.json",
        "mlb_source/data/book_grid/book_grid_2020-01-01.json",
        "mlb_source/data/book_grid/book_grid_2020-01-02.json",
        "odds_events/2020-01-01.jsonl",
        "zz/last.json",
        "reports/migration_runs/2020-01-01/odds_refresh_1/odds_refresh.json",
        "b/c/d/e/f.json",
    ] + ["mlb_source/tracking/book_quotes/2020-02-%02d.jsonl" % i for i in range(1, 21)]
    for rel in rels:
        _touch(disk, rel, size=8)
        expected.add(rel)

    real_scandir = os.scandir
    rng = random.Random(1234)

    class _Shuffled:
        def __init__(self, path):
            self._inner = real_scandir(path)
            self._entries = list(self._inner)
            rng.shuffle(self._entries)

        def __enter__(self):
            return iter(self._entries)

        def __exit__(self, *exc):
            self._inner.close()
            return False

    monkeypatch.setattr(ar.os, "scandir", _Shuffled)
    seen = []
    real_rule_for = ar._rule_for

    def _recording(rel):
        seen.append(rel)
        return real_rule_for(rel)

    monkeypatch.setattr(ar, "_rule_for", _recording)

    passes = 0
    max_passes = math.ceil(len(expected) / cap) + 1
    out = None
    while passes < max_passes:
        passes += 1
        out = ar.sweep_expired_artifacts(today=TODAY, root=disk)
        if not out.hit_pass_limit:
            break
    assert out is not None and not out.hit_pass_limit, "never completed a cycle"
    assert set(seen) == expected, sorted(expected - set(seen))
    assert len(seen) == len(expected), "a file was examined twice in one cycle"
    assert seen == sorted(seen)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("enabled_env", [None, "true"])
def test_dry_run_deletes_nothing_byte_identical_and_logs_path_and_summary(tmp_path, monkeypatch, capsys, enabled_env):
    """Default env: dry run. ENABLED=true plus force_dry_run: still dry run."""
    disk = tmp_path / "disk"
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY", "true")
    if enabled_env:
        monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", enabled_env)
    else:
        monkeypatch.delenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", raising=False)
    rels = [
        "mlb_source/data/book_grid/book_grid_2020-01-01.json",
        "mlb_source/tracking/book_quotes/2020-01-01.jsonl",
        "mlb_source/source_artifacts/data/eval/batches/x/sim_vs_actual_2020-01-01.json",
        "reports/intelligence/intelligence_state_2020_01_01.json",
        "odds_events/2020-01-01.jsonl",
        "reports/migration_runs/2020-01-01/odds_refresh_1/odds_refresh.json",
        "reports/intelligence/venue_odds/kalshi__mlb__2020_01_01.json",
        "reports/odds_control_plane/odds_history/mlb/2020-01-01.json",
        "mlb_source/tracking/odds_history/2020-01-01.json",
        "settlement_inputs/finals_2020-01-01.json",
    ]
    for rel in rels:
        _touch(disk, rel, size=64)
    _closing(disk, "2020-01-01", graded=True)
    before = {p: _hash(p) for p in disk.rglob("*") if p.is_file()}

    out = ar.run_retention_sweep(today=TODAY, root=disk, force_dry_run=bool(enabled_env))

    after = {p: _hash(p) for p in disk.rglob("*") if p.is_file()}
    assert after == before, "a dry run changed the disk"
    assert out.deleted == 0 and out.matched >= len(rels)
    assert not any(out.rule_acts.values())

    lines = capsys.readouterr().out.splitlines()
    path_lines = [line for line in lines if "DISK_RETENTION_PATH " in line]
    summary_lines = [line for line in lines if "DISK_RETENTION_SUMMARY " in line]
    assert len(path_lines) == len(ar.RULES)
    assert len(summary_lines) == 1
    row = json.loads(path_lines[0].split("DISK_RETENTION_PATH ", 1)[1])
    assert {"rule", "action", "files", "bytes", "oldest", "newest_affected", "dry_run"} <= set(row)
    summary = json.loads(summary_lines[0].split("DISK_RETENTION_SUMMARY ", 1)[1])
    assert summary["dry_run"] is True
    assert summary["cursor_complete"] is True
    assert "elapsed_s" in summary
    assert summary["per_action"]["delete"]["files"] >= 1
    assert summary["per_action"]["dedupe_twin"]["files"] == 1


def test_yesterday_is_never_touched_by_any_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setattr(ar, "check_lookback", lambda *a, **k: None)
    monkeypatch.setenv("SYNDICATE_RETENTION_DERIVED_DAYS", "1")
    y = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_%s.json" % (TODAY - timedelta(days=1)).isoformat())
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert y.exists()
