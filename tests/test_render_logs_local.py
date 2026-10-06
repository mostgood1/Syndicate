"""render_logs' LOCAL backend: the fleet's own log files, read with the same
service/text/time filters as the Render API, and never a faked timestamp."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import render_logs  # noqa: E402


def _write(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    # .log.2 is the OLDEST rotation, then .log.1, then the live .log.
    _write(tmp_path / "refresh-worker.log.2",
           "==== start 2026-10-01T10:00:00Z",
           "2026-10-01T10:00:05Z ORDER_PATH a",
           "ORDER_PATH carried")
    _write(tmp_path / "refresh-worker.log.1",
           "2026-10-01T11:00:00Z ORDER_PATH b")
    _write(tmp_path / "refresh-worker.log",
           "2026-10-01T12:00:00.250Z ORDER_PATH c",
           "2026-10-01T12:00:01Z something else",
           "ORDER_PATH generated_at 2026-09-30T22:54:00Z")
    _write(tmp_path / "web.log",
           '127.0.0.1 - - [01/Oct/2026:07:30:00 -0500] "GET /healthz HTTP/1.1" 200 2')
    return tmp_path


def test_reads_rotations_oldest_first_and_filters_text(log_dir: Path) -> None:
    lines, info = render_logs.fetch_local_window(
        service="refresh-worker", text="order_path", start="2026-10-01T00:00:00Z", log_dir=log_dir)
    assert info["files"] == ["refresh-worker.log.2", "refresh-worker.log.1", "refresh-worker.log"]
    assert [m for _, m in lines] == ["ORDER_PATH a", "ORDER_PATH carried", "ORDER_PATH b", "ORDER_PATH c",
                                     "ORDER_PATH generated_at 2026-09-30T22:54:00Z"]
    assert lines[3][0] == "2026-10-01T12:00:00.250Z"


def test_unprefixed_line_inherits_previous_stamp_marked_approximate(log_dir: Path) -> None:
    lines, info = render_logs.fetch_local_window(
        service="refresh-worker", text="ORDER_PATH", start="2026-10-01T00:00:00Z", log_dir=log_dir)
    stamps = dict((m, t) for t, m in lines)
    assert stamps["ORDER_PATH carried"] == "2026-10-01T10:00:05.000Z~"
    # The in-message ISO time is a DATA time and must not become the line's time.
    assert stamps["ORDER_PATH generated_at 2026-09-30T22:54:00Z"] == "2026-10-01T12:00:01.000Z~"
    assert (info["exact"], info["approximate"]) == (3, 2)


def test_exact_only_drops_and_counts_approximate(log_dir: Path) -> None:
    lines, info = render_logs.fetch_local_window(
        service="refresh-worker", text="ORDER_PATH", start="2026-10-01T00:00:00Z", log_dir=log_dir,
        exact_only=True)
    assert all(not t.endswith("~") for t, _ in lines)
    assert info["approximate_dropped"] == 2 and len(lines) == 3


def test_time_window_bounds(log_dir: Path) -> None:
    lines, _ = render_logs.fetch_local_window(
        service="refresh-worker", text="ORDER_PATH", start="2026-10-01T10:30:00Z",
        end="2026-10-01T11:30:00Z", log_dir=log_dir)
    assert [m for _, m in lines] == ["ORDER_PATH b"]


def test_web_access_log_stamp_is_exact_and_converted_to_utc(log_dir: Path) -> None:
    lines, info = render_logs.fetch_local_window(
        service="web", text="healthz", start="2026-10-01T00:00:00Z", log_dir=log_dir)
    assert lines[0][0] == "2026-10-01T12:30:00.000Z"
    assert info["exact"] == 1


def test_line_before_any_stamp_is_skipped_and_counted(tmp_path: Path) -> None:
    _write(tmp_path / "live-odds-worker.log", "ORDER_PATH orphan", "2026-10-01T09:00:00Z ORDER_PATH ok")
    lines, info = render_logs.fetch_local_window(
        service="live-odds-worker", text="ORDER_PATH", start="2026-10-01T00:00:00Z", log_dir=tmp_path)
    assert [m for _, m in lines] == ["ORDER_PATH ok"]
    assert info["unstamped_skipped"] == 1


def test_unknown_service_refused(log_dir: Path) -> None:
    with pytest.raises(SystemExit):
        render_logs.fetch_local_window(service="cron", text="x", start="2026-10-01T00:00:00Z", log_dir=log_dir)


def test_fetch_window_dispatches_to_local_and_records_source(log_dir: Path, monkeypatch) -> None:
    monkeypatch.setenv("SYNDICATE_LOCAL_LOG_DIR", str(log_dir))
    lines, pages = render_logs.fetch_window(
        service="refresh-worker", text="ORDER_PATH b", start="2026-10-01T00:00:00Z", source="local")
    assert [m for _, m in lines] == ["ORDER_PATH b"]
    assert pages == 3
    assert render_logs.LAST_FETCH["source"] == "local" and render_logs.LAST_FETCH["why"] == "explicit"


def test_resolve_source_unset_is_local_without_render_call(monkeypatch) -> None:
    monkeypatch.delenv("SYNDICATE_LOG_SOURCE", raising=False)

    def forbidden(*_a, **_k):
        raise AssertionError("the default must not touch the Render API")

    monkeypatch.setattr(render_logs, "_api_key", forbidden)
    monkeypatch.setattr(render_logs, "render_suspended", forbidden)
    source, why = render_logs.resolve_source()
    assert source == "local" and why.startswith("default:")
    assert render_logs.resolve_source("render") == ("render", "explicit")


def test_resolve_source_auto(monkeypatch) -> None:
    monkeypatch.setenv("SYNDICATE_LOG_SOURCE", "auto")

    def no_key():
        raise SystemExit("RENDER_API_KEY not set")

    monkeypatch.setattr(render_logs, "_api_key", no_key)
    assert render_logs.resolve_source()[0] == "local"

    monkeypatch.setattr(render_logs, "_api_key", lambda: "k")
    monkeypatch.setattr(render_logs, "render_suspended", lambda key: True)
    assert render_logs.resolve_source() == ("local", "auto: Render reports the web service suspended")
    monkeypatch.setattr(render_logs, "render_suspended", lambda key: False)
    assert render_logs.resolve_source()[0] == "render"
    assert render_logs.resolve_source("auto")[0] == "render"
    monkeypatch.setenv("SYNDICATE_LOG_SOURCE", "local")
    assert render_logs.resolve_source() == ("local", "SYNDICATE_LOG_SOURCE")
