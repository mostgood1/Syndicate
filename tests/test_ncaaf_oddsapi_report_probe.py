"""`#558` -- the one-shot boot probe that runs the NCAAF resolver against REAL
OddsAPI.

The probe exists because no live call had ever been made: the sandbox this
fetcher was built in answers 403 to CONNECT for `api.the-odds-api.com`. So the
thing under test is not the report's content -- it is that the probe is
REACHABLE from the worker's boot, spends nothing when off, and cannot take the
worker down when it fails.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

worker = importlib.import_module("scripts.run_live_odds_refresh_worker")


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT", raising=False)


def _calls(monkeypatch):
    seen: list[list[str]] = []

    def fake_main(argv=None):
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr(
        "scripts.fetch_ncaaf_oddsapi_game_lines.main", fake_main, raising=True
    )
    return seen


def test_off_by_default_spends_no_credit(monkeypatch, capsys):
    """A probe that fetches on every boot is a standing cost, not a diagnostic.
    Absent flag must not reach the fetcher at all."""
    seen = _calls(monkeypatch)
    worker._ncaaf_oddsapi_report_at_boot()
    assert seen == []
    assert "NCAAF_ODDSAPI_REPORT_SKIPPED" in capsys.readouterr().out


def test_the_off_case_is_still_audible(capsys):
    """When this runs, the live question is 'did the flag reach this service'.
    A silent return answers that identically to a probe that crashed."""
    worker._ncaaf_oddsapi_report_at_boot()
    assert "flag=off" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " On "])
def test_flag_spellings_that_must_arm_it(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT", raw)
    seen = _calls(monkeypatch)
    worker._ncaaf_oddsapi_report_at_boot()
    assert seen == [["--report"]], raw


@pytest.mark.parametrize("raw", ["0", "off", "no", "", "maybe"])
def test_flag_spellings_that_must_not(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT", raw)
    seen = _calls(monkeypatch)
    worker._ncaaf_oddsapi_report_at_boot()
    assert seen == [], raw


def test_it_always_passes_report_and_never_writes(monkeypatch):
    """`--report` is what makes this safe to run before the sport is switched
    on: it fetches and prints, and returns before `append_quotes`. Dropping the
    flag would write a quote log for a sport the sweep is not yet running."""
    monkeypatch.setenv("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT", "1")
    seen = _calls(monkeypatch)
    worker._ncaaf_oddsapi_report_at_boot()
    assert seen[0] == ["--report"]


def test_a_failing_probe_cannot_stop_the_worker_booting(monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT", "1")

    def boom(argv=None):
        raise RuntimeError("odds api said no")

    monkeypatch.setattr(
        "scripts.fetch_ncaaf_oddsapi_game_lines.main", boom, raising=True
    )
    worker._ncaaf_oddsapi_report_at_boot()  # must not raise
    out = capsys.readouterr().out
    assert "NCAAF_ODDSAPI_REPORT_ERROR" in out
    assert "odds api said no" in out


def test_it_is_wired_into_the_boot_sequence_above_every_early_returning_probe():
    """REACHABILITY. This file's own comments record two probes that went
    several restarts without running because something above them returned
    early. Assert position, not merely presence."""
    src = Path(worker.__file__).read_text(encoding="utf-8")
    body = src.split("loop_started_at = time.monotonic()", 1)[1]
    mine = body.index("_ncaaf_oddsapi_report_at_boot()")
    for other in ("_kalshi_auth_probe_at_boot()", "_polymarket_us_auth_probe_at_boot()"):
        assert mine < body.index(other), other
