"""The one-shot production reading of the fuller-copy resolver.

Lane `book-quotes-prefer-fuller-copy`, user decision 2026-09-15 "force the
book-quotes read". `57b67127` shipped and stayed unexercised because nothing
reads a closed past date on its own, so this probe reads every dual-form shard
through the READ path once per disk and logs what a reader gets.
"""
from __future__ import annotations

import gzip
import json

import pytest

from syndicate.features.shared import odds_book_quotes as obq


def _rows(n):
    return [{"sport": "mlb", "market": "h2h", "selection": "home", "price": -110 - i, "i": i} for i in range(n)]


def _write_plain(root, sport, date_str, rows):
    p = root / f"{sport}_source" / "tracking" / "book_quotes" / f"{date_str}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    return p


def _write_gz(plain, rows):
    packed = plain.with_name(plain.name + ".gz")
    with gzip.open(packed, "wb") as dst:
        for r in rows:
            dst.write((json.dumps(r, separators=(",", ":")) + "\n").encode("utf-8"))
    return packed


def _probe_lines(out):
    return [json.loads(line.split("RESOLVE_PROBE ", 1)[1]) for line in out.splitlines() if "RESOLVE_PROBE {" in line]


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    obq._BOOK_QUOTES_CACHE.clear()
    obq._GZIP_COMPLETE_CACHE.clear()
    return tmp_path


def test_reports_the_copy_a_reader_gets_and_its_line_count(_root, capsys):
    """The production shape: a fuller .gz (mlb 09-03: gz 140,236 vs plain 140,224)
    and a longer plain copy (mlb 09-13: plain 123,949 vs gz 123,947)."""
    _write_gz(_write_plain(_root, "mlb", "2026-09-03", _rows(40)), _rows(52))
    _write_gz(_write_plain(_root, "mlb", "2026-09-13", _rows(30)), _rows(28))
    _write_plain(_root, "mlb", "2026-09-14", _rows(5))  # plain only: not dual-form
    summary = obq.probe_dual_form_shards(sports=["mlb"])

    records = {r["date"]: r for r in _probe_lines(capsys.readouterr().out)}
    assert set(records) == {"2026-09-03", "2026-09-13"}
    assert (records["2026-09-03"]["chosen"], records["2026-09-03"]["lines"]) == ("gz", 52)
    assert (records["2026-09-13"]["chosen"], records["2026-09-13"]["lines"]) == ("plain", 30)
    assert summary["shards"] == 2 and summary["chose_gz"] == 1 and summary["chose_plain"] == 1
    assert records["2026-09-03"]["lines"] == len(list(obq.iter_book_quotes("mlb", "2026-09-03")))


def test_it_reads_through_the_resolver_not_its_own_rule(_root, monkeypatch, capsys):
    """Reachability: if the resolver says plain, the probe must report plain."""
    plain = _write_plain(_root, "mlb", "2026-09-03", _rows(40))
    _write_gz(plain, _rows(52))
    monkeypatch.setattr(obq, "resolve_book_quotes_path", lambda sport, date_str: plain)
    obq.probe_dual_form_shards(sports=["mlb"])
    (record,) = _probe_lines(capsys.readouterr().out)
    assert (record["chosen"], record["lines"]) == ("plain", 40)


def test_runs_once_per_disk_unless_forced(_root, capsys):
    _write_gz(_write_plain(_root, "mlb", "2026-09-03", _rows(40)), _rows(52))
    assert obq.probe_dual_form_shards(sports=["mlb"])["shards"] == 1
    second = obq.probe_dual_form_shards(sports=["mlb"])
    assert second["shards"] == 0 and second["skipped_done"] == ["mlb"]
    assert "RESOLVE_PROBE_DONE" in capsys.readouterr().out
    assert obq.probe_dual_form_shards(sports=["mlb"], force=True)["shards"] == 1


def test_a_failed_read_is_named_and_leaves_no_marker(_root, monkeypatch, capsys):
    _write_gz(_write_plain(_root, "mlb", "2026-09-03", _rows(40)), _rows(52))

    def _boom(path):
        raise OSError("disk went away")

    monkeypatch.setattr(obq, "_open_book_quotes_text", _boom)
    summary = obq.probe_dual_form_shards(sports=["mlb"])
    (record,) = _probe_lines(capsys.readouterr().out)
    assert summary["errors"] == 1 and "disk went away" in record["error"]
    marker = _root / "mlb_source" / "tracking" / "book_quotes" / f".resolve_probe_{obq._RESOLVE_PROBE_VERSION}.done"
    assert not marker.exists()


def test_an_empty_disk_still_says_it_ran(capsys):
    summary = obq.probe_dual_form_shards(sports=["mlb"])
    assert summary["shards"] == 0
    assert "RESOLVE_PROBE_DONE" in capsys.readouterr().out


# --- reachability from the worker (off != on) --------------------------------

def _maintenance(monkeypatch, *, enabled: bool, service: str) -> list[float]:
    from syndicate.features.shared import disk_compaction as dc
    from syndicate.features.shared import disk_inventory as inv
    from syndicate.features.shared import disk_maintenance as dm

    calls: list[float] = []
    monkeypatch.setattr(inv, "start_disk_inventory_once", lambda *a, **k: False)
    monkeypatch.setattr(dc, "start_disk_compaction_once", lambda *a, **k: False)
    monkeypatch.setattr(obq, "start_resolve_probe_once", lambda delay_seconds=600.0: calls.append(delay_seconds) or True)
    monkeypatch.setattr(dm, "_due", lambda: False)
    monkeypatch.setenv("RENDER_SERVICE_NAME", service)
    monkeypatch.delenv("SYNDICATE_REFRESH_LANE", raising=False)
    if enabled:
        monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    else:
        monkeypatch.delenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", raising=False)
    dm.run_disk_maintenance()
    return calls


def test_refresh_worker_maintenance_starts_the_probe(monkeypatch):
    assert _maintenance(monkeypatch, enabled=True, service="refresh-worker") == [600.0]


def test_other_services_never_start_it(monkeypatch):
    assert _maintenance(monkeypatch, enabled=True, service="live-odds-worker") == []


def test_disabled_maintenance_never_starts_it(monkeypatch):
    assert _maintenance(monkeypatch, enabled=False, service="refresh-worker") == []


def test_start_once_is_once_per_process(monkeypatch):
    started: list[float] = []
    monkeypatch.setattr(obq, "_RESOLVE_PROBE_STARTED", False)
    monkeypatch.setattr(obq, "start_resolve_probe_after", lambda delay_seconds=600.0: started.append(delay_seconds))
    assert obq.start_resolve_probe_once(600.0) is True
    assert obq.start_resolve_probe_once(600.0) is False
    assert started == [600.0]
