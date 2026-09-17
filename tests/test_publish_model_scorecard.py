"""`scripts/publish_model_scorecard.py` -- the cron's refusals are the contract.

A cron that cannot read its own saved state must not publish a fresh one (that erases a
month of graded history and reads as a quiet first run); a run that fetched no recorder
data must not replace a real overlay with an empty table; a missing token refuses.
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import urllib.error

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_model_scorecard.py"
_spec = importlib.util.spec_from_file_location("publish_model_scorecard", _SRC)
pms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pms)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(script):
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        step = script[min(len(calls), len(script)) - 1]
        if isinstance(step, Exception):
            raise step
        return _Response(json.dumps(step).encode("utf-8"))

    opener.calls = calls
    return opener


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(pms.time, "sleep", lambda s: None)


def _http(code):
    return urllib.error.HTTPError("u", code, "x", None, None)


def test_reader_returns_content_none_for_not_found_and_raises_for_anything_else():
    ok = pms.WebReader("https://web", "t", opener=_opener([{"ok": True, "artifacts": {"p": "hello"}}]))
    assert ok.text("p") == "hello"
    missing = pms.WebReader("https://web", "t", opener=_opener([_http(404)]))
    assert missing.text("p") is None
    empty = pms.WebReader("https://web", "t", opener=_opener([{"ok": True, "artifacts": {}}]))
    assert empty.text("p") is None
    broken = pms.WebReader("https://web", "t", opener=_opener([_http(502), _http(502), _http(502)]))
    with pytest.raises(pms.FetchError):
        broken.text("p")
    assert broken.calls == 3
    recovers = pms.WebReader("https://web", "t", opener=_opener([TimeoutError("slow"), {"artifacts": {"p": "x"}}]))
    assert recovers.text("p") == "x"


def test_the_token_goes_in_a_header_never_the_url():
    opener = _opener([{"artifacts": {"p": "x"}}])
    pms.WebReader("https://web", "SECRET", opener=opener).text("reports/a b.json")
    assert "SECRET" not in opener.calls[0] and "reports%2Fa%20b.json" in opener.calls[0]


def test_no_token_refuses(monkeypatch):
    monkeypatch.setattr(pms, "admin_token", lambda: "")
    assert pms.main([]) == 2


def test_an_unreadable_state_refuses_before_anything_is_written(monkeypatch, tmp_path):
    monkeypatch.setattr(pms, "admin_token", lambda: "t")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))

    def failing_json(self, relative):
        raise pms.FetchError(f"{relative}: 502")

    monkeypatch.setattr(pms.WebReader, "json", failing_json)
    assert pms.main(["--weekly", "off"]) == 4
    assert not any(tmp_path.rglob("*")), "nothing may be written when the saved state could not be read"


def test_no_recorder_data_at_all_refuses_to_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(pms, "admin_token", lambda: "t")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(pms.WebReader, "json", lambda self, relative: None)

    def failing_fetch(reader, bs, day, sports):
        raise pms.FetchError("export down")

    monkeypatch.setattr(pms, "fetch_board_date", failing_fetch)
    assert pms.main(["--weekly", "off"]) == 3
    assert not any(tmp_path.rglob("*"))


@pytest.mark.parametrize("mode, day, expected", [
    ("auto", "2026-09-21", True), ("auto", "2026-09-17", False), ("on", "2026-09-17", True), ("off", "2026-09-21", False),
])
def test_weekly_runs_on_central_mondays_unless_forced(mode, day, expected):
    assert pms.weekly_due(mode, day) is expected
