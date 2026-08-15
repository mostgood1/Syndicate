"""The alarm for the failure mode where every other instrument reads green.

MEASURED 2026-08-15 (`.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`): MLB
quote capture stopped at 11:07:48Z and resumed at 16:56:49Z -- 5.8 hours. During
it the tick loop ran every 60 s and reported ok, Layer 2 rebuilt every ~5 min
(the healthiest gaps ever measured), and the board served 150 normal-looking
rows. Nothing computed the age of the newest sample, so nothing noticed.

THE CENTRAL PROPERTY IS THAT UNKNOWN IS NOT OK. The failure being guarded is
"the feed stopped and everything looked fine". An implementation that maps a
missing or unreadable shard onto its healthy branch reproduces that exact bug
one layer down, which is why `test_missing_*`/`test_unparseable_*` matter more
than the happy path.

MUTATION-PINNED. Changing `status = STATUS_UNKNOWN` to `STATUS_OK` as the
initial value in `feed_age` must turn the three unknown tests plus
`test_report_worst_status_prefers_unknown_over_ok` RED and leave every
threshold test GREEN -- the discrimination that shows those tests are pinning
the fail-closed property specifically, not incidentally.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared.quote_feed_age import (
    STATUS_OK,
    STATUS_STALE,
    STATUS_UNKNOWN,
    feed_age,
    feed_age_report,
    newest_captured_at,
    stale_threshold_seconds,
)

DATE = "2026-08-15"
# The real numbers from the measured outage, used as the fixture so the test
# fails if the module stops reproducing the incident it was written for.
STOP = datetime(2026, 8, 15, 11, 7, 48, tzinfo=timezone.utc)
RESUME = datetime(2026, 8, 15, 16, 56, 49, tzinfo=timezone.utc)


def _shard(tmp_path, stamps, sport="mlb"):
    """Write a shard shaped like production's and point the module at it."""
    root = tmp_path / sport / "tracking" / "book_quotes"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{DATE}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for stamp in stamps:
            handle.write(json.dumps({
                "captured_at": stamp.isoformat().replace("+00:00", "Z"),
                "sport": sport, "bookmaker": "fanduel", "price": -110,
            }) + "\n")
    return path


@pytest.fixture
def patched(monkeypatch, tmp_path):
    def fake_path(sport, date_str):
        return tmp_path / str(sport).lower() / "tracking" / "book_quotes" / f"{date_str}.jsonl"

    monkeypatch.setattr(
        "syndicate.features.shared.odds_book_quotes.book_quotes_path", fake_path
    )
    return tmp_path


# --- the incident, replayed ------------------------------------------------


def test_reports_ok_before_the_threshold_is_crossed(patched):
    """14:00Z during the real outage: 10,332 s old, UNDER the 10,800 s threshold.

    Pinned deliberately, because the lane opened claiming this case was `stale`
    and it is not. A test that asserted the comfortable answer would have
    preserved the error.
    """
    _shard(patched, [STOP])
    got = feed_age("mlb", DATE, now=datetime(2026, 8, 15, 14, 0, 0, tzinfo=timezone.utc))
    assert got["age_seconds"] == pytest.approx(10332.0)
    assert got["status"] == STATUS_OK


def test_fires_at_the_measured_time_and_stays_lit(patched):
    _shard(patched, [STOP])
    fires = STOP + timedelta(seconds=10800)  # 14:07:48Z
    assert feed_age("mlb", DATE, now=fires - timedelta(seconds=1))["status"] == STATUS_OK
    assert feed_age("mlb", DATE, now=fires + timedelta(seconds=1))["status"] == STATUS_STALE
    # still lit when capture finally resumed, 2.8 h later
    at_resume = feed_age("mlb", DATE, now=RESUME)
    assert at_resume["status"] == STATUS_STALE
    assert at_resume["age_seconds"] == pytest.approx(20941.0, abs=1.0)


def test_recovers_immediately_once_capture_resumes(patched):
    _shard(patched, [STOP, RESUME])
    got = feed_age("mlb", DATE, now=RESUME + timedelta(seconds=29))
    assert got["status"] == STATUS_OK
    assert got["age_seconds"] == pytest.approx(29.0)


def test_healthy_pregame_gap_does_not_false_alarm(patched):
    """The 123-min gap measured 09:06->11:07Z is normal and must stay quiet.

    This is the constraint that forces the threshold above 2 h and therefore
    causes the 3 h detection lag. If someone lowers the default, this goes red
    and the tradeoff is visible instead of silent.
    """
    _shard(patched, [STOP])
    got = feed_age("mlb", DATE, now=STOP + timedelta(minutes=123))
    assert got["status"] == STATUS_OK


# --- unknown is not ok: the property the whole module exists for ------------


def test_missing_shard_is_unknown_not_ok(patched):
    got = feed_age("mlb", DATE, now=RESUME)
    assert got["status"] == STATUS_UNKNOWN
    assert got["age_seconds"] is None
    assert "no quote shard" in got["reason"]


def test_empty_shard_is_unknown_not_ok(patched):
    _shard(patched, [])
    assert feed_age("mlb", DATE, now=RESUME)["status"] == STATUS_UNKNOWN


def test_unparseable_shard_is_unknown_not_ok(patched):
    path = _shard(patched, [STOP])
    path.write_text("not json at all\n{also not\n", encoding="utf-8")
    got = feed_age("mlb", DATE, now=RESUME)
    assert got["status"] == STATUS_UNKNOWN
    assert "no parseable captured_at" in got["reason"]


# --- the O(1) tail read ----------------------------------------------------


def test_tail_read_finds_the_newest_of_many_rows(patched):
    stamps = [STOP + timedelta(seconds=i) for i in range(5000)]
    path = _shard(patched, stamps)
    assert path.stat().st_size > 65536  # genuinely larger than the tail window
    assert newest_captured_at(path) == stamps[-1].isoformat().replace("+00:00", "Z")


def test_torn_final_line_falls_back_to_the_previous_row(patched):
    """A shard being appended to concurrently can end mid-line.

    That must read as the previous complete row, not as "no data" -- otherwise
    a healthy feed intermittently reports UNKNOWN and the alarm trains people
    to ignore it.
    """
    path = _shard(patched, [STOP, RESUME])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"captured_at": "2026-08-15T17:0')
    assert newest_captured_at(path) == RESUME.isoformat().replace("+00:00", "Z")


# --- roll-up ---------------------------------------------------------------


def test_report_worst_status_prefers_stale_over_ok(patched):
    _shard(patched, [RESUME], sport="mlb")
    _shard(patched, [STOP], sport="nfl")
    report = feed_age_report(["mlb", "nfl"], DATE, now=RESUME)
    assert report["worst_status"] == STATUS_STALE
    assert report["stale_sports"] == ["nfl"]


def test_report_worst_status_prefers_unknown_over_ok(patched):
    """One dead feed must not be averaged away by healthy ones.

    Today's outage was one sport out of eight.
    """
    _shard(patched, [RESUME], sport="mlb")
    report = feed_age_report(["mlb", "nfl"], DATE, now=RESUME)
    assert report["worst_status"] == STATUS_UNKNOWN
    assert report["unknown_sports"] == ["nfl"]


def test_report_all_healthy_is_ok(patched):
    _shard(patched, [RESUME], sport="mlb")
    _shard(patched, [RESUME], sport="nfl")
    assert feed_age_report(["mlb", "nfl"], DATE, now=RESUME)["worst_status"] == STATUS_OK


# --- threshold config ------------------------------------------------------


def test_threshold_is_env_tunable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_QUOTE_FEED_STALE_SECONDS", "600")
    assert stale_threshold_seconds() == 600


def test_bad_or_nonpositive_threshold_falls_back_to_the_default(monkeypatch):
    for bad in ("", "abc", "0", "-5"):
        monkeypatch.setenv("SYNDICATE_QUOTE_FEED_STALE_SECONDS", bad)
        assert stale_threshold_seconds() == 10800
