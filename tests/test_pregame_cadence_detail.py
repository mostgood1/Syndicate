"""`#382` -- the cadence filter said WHAT it decided, never what it read.

THE CHAIN SO FAR, each step measured rather than assumed:

  Layer 1   WNBA served 848 rows priced off quotes 9h old, board otherwise healthy
  sidecar   wnba_source/tracking/book_quotes/2026-08-12.state.json last write 07:18:51Z
            (mlb's updated 13:25:57Z off the same loop)
  `#378`    WNBA produces NO ODDS_SWEEP_OUTCOME line at all -- 15 lines, all nfl.
            A sport is graded only once stamped as launched, so this ruled OUT
            "sweeps run and write nothing" and left "never launches".

WHAT WAS STILL MISSING. A sport reaches the skip branch only when

    0 < (now_epoch - marker) < interval

so the marker IS the decision. WNBA's interval is the 2h fallback and its real
capture last wrote 9h ago, which means its marker is advancing with no capture
behind it. Consistent by construction: markers are recorded BEFORE the launch
(`#25` -- so a launch that dies costs one missed window rather than a duplicate
sweep). If the launch dies EVERY time, the marker advances forever and the sport
is skipped forever. That is a permanent stall, not the single missed window the
rule anticipates.

Printing the marker age turns that last step from an inference into a reading.
I have been wrong twice in this thread already -- I claimed WNBA "ran and wrote
nothing" from one service's skip list, and I claimed MLB's 88m was a bug before
reading that its interval is a deliberate 2h -- so the remaining step gets an
instrument rather than a third guess.
"""

from __future__ import annotations

import importlib

import pytest

MODULE = "syndicate.features.shared.live_refresh_loop"


@pytest.fixture
def loop():
    return importlib.import_module(MODULE)


def test_a_skipped_sport_reports_the_marker_it_was_judged_on(loop, monkeypatch, capsys):
    now = 1_000_000.0
    # Marker 10 minutes old against a 2h interval -- skipped, and the reason is
    # the marker, which is exactly what was invisible.
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {"wnba": now - 600}, raising=False)
    monkeypatch.setattr(loop, "_pregame_sweep_interval_seconds", lambda s: 7200, raising=False)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"wnba": lambda d: False}, raising=False)

    kept, skipped = loop._apply_pregame_sport_cadence(["wnba"], now_epoch=now, force_sports=set())
    assert kept == [] and skipped == ["wnba"]
    out = capsys.readouterr().out
    assert "PREGAME_CADENCE_DETAIL" in out, "the filter still reports only its decision"
    assert "wnba:marker_age_s=600/interval_s=7200" in out


def test_the_detail_line_is_silent_when_nothing_is_skipped(loop, monkeypatch, capsys):
    # It runs on every tick. A line per tick per sport would be the log spam
    # `_soccer_autorun_skipped` exists to avoid.
    now = 1_000_000.0
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {}, raising=False)
    monkeypatch.setattr(loop, "_pregame_sweep_interval_seconds", lambda s: 7200, raising=False)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"wnba": lambda d: False}, raising=False)

    kept, skipped = loop._apply_pregame_sport_cadence(["wnba"], now_epoch=now, force_sports=set())
    assert kept == ["wnba"] and skipped == []
    assert "PREGAME_CADENCE_DETAIL" not in capsys.readouterr().out


def test_every_skipped_sport_appears(loop, monkeypatch, capsys):
    now = 1_000_000.0
    monkeypatch.setattr(
        loop, "_read_pregame_sport_sweep_epochs",
        lambda: {"wnba": now - 600, "mlb": now - 1200, "soccer": now - 300}, raising=False)
    monkeypatch.setattr(loop, "_pregame_sweep_interval_seconds", lambda s: 7200, raising=False)
    monkeypatch.setattr(
        loop, "_LIVE_STATUS_CHECKERS",
        {s: (lambda d: False) for s in ("wnba", "mlb", "soccer")}, raising=False)

    _, skipped = loop._apply_pregame_sport_cadence(["wnba", "mlb", "soccer"], now_epoch=now, force_sports=set())
    out = capsys.readouterr().out
    assert sorted(skipped) == ["mlb", "soccer", "wnba"]
    for sport in ("wnba", "mlb", "soccer"):
        assert f"{sport}:marker_age_s=" in out


def test_the_existing_return_contract_is_unchanged(loop, monkeypatch, capsys):
    # `cadence_skipped` is joined into PREGAME_CADENCE_SKIPPED and stored in
    # meta. Enriching the DIAGNOSTIC must not change the returned shape -- a
    # decorated sport name would break both consumers silently.
    now = 1_000_000.0
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {"wnba": now - 600}, raising=False)
    monkeypatch.setattr(loop, "_pregame_sweep_interval_seconds", lambda s: 7200, raising=False)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"wnba": lambda d: False}, raising=False)

    _, skipped = loop._apply_pregame_sport_cadence(["wnba"], now_epoch=now, force_sports=set())
    assert skipped == ["wnba"], "skipped entries must stay bare sport slugs"


def test_a_live_sport_is_never_skipped_and_reports_nothing(loop, monkeypatch, capsys):
    # Fail-open rules are unchanged; the instrument must not alter behaviour.
    now = 1_000_000.0
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {"wnba": now - 60}, raising=False)
    monkeypatch.setattr(loop, "_pregame_sweep_interval_seconds", lambda s: 7200, raising=False)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"wnba": lambda d: True}, raising=False)

    kept, skipped = loop._apply_pregame_sport_cadence(["wnba"], now_epoch=now, force_sports=set())
    assert kept == ["wnba"] and skipped == []
    assert "PREGAME_CADENCE_DETAIL" not in capsys.readouterr().out
