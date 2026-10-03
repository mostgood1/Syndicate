"""An empty ESPN answer must not blank a recommendations file the schedule still backs.

Lane `soccer-recs-empty-overwrite`, 2026-10-03. `build_artifacts` wrote
`{"matches": []}` over `recommendations_<date>.json` whenever ESPN returned no
fixtures for the date. A failed request raises first, so this branch sees a 200
with nothing in it: a postponement (overwrite is right), a wrong-day unit
(measured: mls 10-02/10-07, `e26ba342`) or a stale/off-window 200. Only the
schedule tells them apart.

Every test goes through the real `build_artifacts`; ESPN and the schedule are the
only stubs, and the refusal tests assert the refusal line was emitted so a pass
cannot come from some cheaper path.
"""

from __future__ import annotations

import json

import pytest

from scripts import build_soccer_artifacts as B
from syndicate.features.soccer import sources

DATE = "2026-10-06"
KEPT = {"league": "mls", "date": DATE, "generated_at": "2026-10-03T05:08:36+00:00", "matches": [{"match_id": "761660"}], "player_props": []}
CHI_VAN = {"date": "2026-10-07T00:30Z", "event_id": "761660", "status_state": "pre"}  # local day 10-06


@pytest.fixture()
def rec_path(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_fetch_fixtures", lambda league, iso_date: [])
    path = tmp_path / "mls" / "api" / "recommendations" / f"recommendations_{DATE}.json"
    path.parent.mkdir(parents=True)
    return path


def _build(tmp_path):
    return B.build_artifacts("mls", DATE, source_root=tmp_path, out_root=tmp_path, simulations=10)


def _schedule(monkeypatch, payload):
    monkeypatch.setattr(sources, "schedule_payload", lambda league, season: payload)


def test_kept_while_the_schedule_lists_the_fixture(tmp_path, rec_path, monkeypatch, capsys):
    rec_path.write_text(json.dumps(KEPT), encoding="utf-8")
    before = rec_path.read_bytes()
    _schedule(monkeypatch, {"matches": [CHI_VAN]})
    payload = _build(tmp_path)
    assert rec_path.read_bytes() == before, "an empty ESPN answer blanked a schedule-backed file"
    assert len(payload["matches"]) == 1
    out = capsys.readouterr().out
    assert "SOCCER_RECS_EMPTY_OVERWRITE_REFUSED" in out and "reason=schedule_lists_fixtures" in out


def test_kept_when_the_schedule_is_unreadable(tmp_path, rec_path, monkeypatch, capsys):
    rec_path.write_text(json.dumps(KEPT), encoding="utf-8")
    before = rec_path.read_bytes()

    def boom(league, season):
        raise OSError("disk")

    monkeypatch.setattr(sources, "schedule_payload", boom)
    _build(tmp_path)
    assert rec_path.read_bytes() == before
    assert "reason=schedule_unreadable" in capsys.readouterr().out


def test_postponed_fixture_is_overwritten_empty(tmp_path, rec_path, monkeypatch, capsys):
    rec_path.write_text(json.dumps(KEPT), encoding="utf-8")
    _schedule(monkeypatch, {"matches": [{**CHI_VAN, "status_state": "void"}]})
    _build(tmp_path)
    assert json.loads(rec_path.read_text(encoding="utf-8"))["matches"] == []
    assert "REFUSED" not in capsys.readouterr().out


def test_fixture_moved_off_the_date_is_overwritten_empty(tmp_path, rec_path, monkeypatch):
    rec_path.write_text(json.dumps(KEPT), encoding="utf-8")
    _schedule(monkeypatch, {"matches": [{**CHI_VAN, "date": "2026-10-20T00:30Z"}]})
    _build(tmp_path)
    assert json.loads(rec_path.read_text(encoding="utf-8"))["matches"] == []


def test_utc_prefix_is_not_the_slate_date(tmp_path, monkeypatch, capsys):
    # The 10-07 file of the old bug: the schedule's only fixture with a 10-07 UTC
    # prefix belongs to local 10-06, so 10-07 is genuinely empty and may be written.
    monkeypatch.setattr(B, "_fetch_fixtures", lambda league, iso_date: [])
    path = tmp_path / "mls" / "api" / "recommendations" / "recommendations_2026-10-07.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**KEPT, "date": "2026-10-07"}), encoding="utf-8")
    _schedule(monkeypatch, {"matches": [CHI_VAN]})
    B.build_artifacts("mls", "2026-10-07", source_root=tmp_path, out_root=tmp_path, simulations=10)
    assert json.loads(path.read_text(encoding="utf-8"))["matches"] == []


@pytest.mark.parametrize("existing", [None, {"matches": []}, "not json"])
def test_nothing_to_protect_writes_empty(tmp_path, rec_path, monkeypatch, existing):
    if existing is not None:
        rec_path.write_text(existing if isinstance(existing, str) else json.dumps(existing), encoding="utf-8")
    _schedule(monkeypatch, {"matches": [CHI_VAN]})
    _build(tmp_path)
    assert json.loads(rec_path.read_text(encoding="utf-8"))["matches"] == []
