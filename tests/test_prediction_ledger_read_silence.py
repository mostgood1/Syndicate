"""`#642`: a failed shared read must not leave as a confident zero.

`/api/portfolio/summary` reported `total_tracked: 0, settled_count: 0,
positions: []` on 2026-09-03 while the `prediction_ledger.json` keyvalue key
occupied ~2 MiB across 1 key, on a web service documented UNSTABLE against a
Redis at 86.8% with 12,203 evictions.

`_read_payload` could reach `_blank_payload()` two ways -- the shared read
FAILED, or the ledger is genuinely empty -- and left silently either way. That
is the exact ambiguity `read_text_file_result`'s own docstring exists to remove;
the fix that introduced `read_ok` applied it to the PROMOTION decision and not
to this return.

These tests pin the distinction in both directions. **The point is not that a
log line exists** -- it is that the two cases produce DIFFERENT lines, because a
single shared line would restore the ambiguity in a new place.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features import prediction_ledger  # noqa: E402


@pytest.fixture()
def keyvalue_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A keyvalue-backed ledger path whose disk copy does not exist."""
    monkeypatch.setattr(prediction_ledger, "_keyvalue_backed", lambda path: True)
    return tmp_path / "prediction_ledger.json"


def test_a_failed_shared_read_says_so_and_does_not_claim_the_ledger_is_empty(
    keyvalue_ledger: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """read_ok=False -- the backend errored. The blank payload is still returned
    (callers must keep working), but it is no longer silent."""
    monkeypatch.setattr(prediction_ledger, "read_text_file_result", lambda path: (None, False))

    payload = prediction_ledger._read_payload(keyvalue_ledger)

    assert payload["predictions"] == [], "a blank payload is still returned -- callers must not break"
    out = capsys.readouterr().out
    assert "PREDICTION_LEDGER_READ_FAILED" in out
    assert "shared_read_ok=False" in out
    assert "NOT evidence the ledger is empty" in out


def test_a_confirmed_empty_ledger_says_something_DIFFERENT(
    keyvalue_ledger: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """read_ok=True with no text -- the read SUCCEEDED and found nothing. That is
    a real answer and must be reported as a different fact."""
    monkeypatch.setattr(prediction_ledger, "read_text_file_result", lambda path: (None, True))

    payload = prediction_ledger._read_payload(keyvalue_ledger)

    assert payload["predictions"] == []
    out = capsys.readouterr().out
    assert "PREDICTION_LEDGER_CONFIRMED_EMPTY" in out
    assert "shared_read_ok=True" in out
    assert "PREDICTION_LEDGER_READ_FAILED" not in out, "the two cases must not share a token"


def test_the_two_tokens_are_distinct() -> None:
    """A single token for both states would restore the ambiguity this fixes."""
    import inspect

    source = inspect.getsource(prediction_ledger._read_payload)
    assert "PREDICTION_LEDGER_READ_FAILED" in source
    assert "PREDICTION_LEDGER_CONFIRMED_EMPTY" in source


def test_a_good_shared_read_is_unaffected_and_stays_quiet(
    keyvalue_ledger: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The working path must not change, and must not start logging on every
    read -- this is a 2 MiB payload read on a request path."""
    monkeypatch.setattr(
        prediction_ledger,
        "read_text_file_result",
        lambda path: ('{"schema_version": 1, "predictions": [{"id": "p1"}], "results": []}', True),
    )

    payload = prediction_ledger._read_payload(keyvalue_ledger)

    assert [p["id"] for p in payload["predictions"]] == ["p1"]
    out = capsys.readouterr().out
    assert "PREDICTION_LEDGER" not in out, "the healthy path must stay silent"


def test_disk_fallback_still_wins_over_a_failed_shared_read(
    keyvalue_ledger: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The failure branch is only for when there is NOTHING to fall back to. A
    real disk copy must still be returned, and quietly."""
    keyvalue_ledger.write_text(
        '{"schema_version": 1, "predictions": [{"id": "disk1"}], "results": []}', encoding="utf-8"
    )
    monkeypatch.setattr(prediction_ledger, "read_text_file_result", lambda path: (None, False))

    payload = prediction_ledger._read_payload(keyvalue_ledger)

    assert [p["id"] for p in payload["predictions"]] == ["disk1"]
    assert "PREDICTION_LEDGER_READ_FAILED" not in capsys.readouterr().out


def test_promotion_still_only_happens_on_a_CONFIRMED_absence(
    keyvalue_ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-existing `read_ok` guard at :180 must survive this change --
    promoting on a backend error would overwrite a good key with a stale disk
    copy. Regression cover for the behaviour I nearly mis-described as a bug."""
    keyvalue_ledger.write_text(
        '{"schema_version": 1, "predictions": [{"id": "disk1"}], "results": []}', encoding="utf-8"
    )
    promoted: list[str] = []
    monkeypatch.setattr(
        prediction_ledger, "_publish_shared_payload", lambda path, payload: promoted.append(str(path))
    )

    monkeypatch.setattr(prediction_ledger, "read_text_file_result", lambda path: (None, False))
    prediction_ledger._read_payload(keyvalue_ledger)
    assert promoted == [], "a FAILED read must never promote the disk copy"

    monkeypatch.setattr(prediction_ledger, "read_text_file_result", lambda path: (None, True))
    prediction_ledger._read_payload(keyvalue_ledger)
    assert len(promoted) == 1, "a CONFIRMED absence with real disk predictions should promote"
