"""Forward-test input preservation: mirror path outside retention, filtering, freshness, fuller copy, restore."""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "preserve_forward_inputs", Path(__file__).resolve().parents[1] / "scripts" / "preserve_forward_inputs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def test_the_mirror_path_matches_no_retention_rule_but_the_original_does() -> None:
    from syndicate.features.shared import artifact_retention as ar

    p = _load()
    for sport in p.FAMILIES:
        assert ar._rule_for(f"{p.MIRROR.as_posix()}/{sport}/quotes/2026-10-20.jsonl.gz") is None
        assert ar._rule_for(f"{p.MIRROR.as_posix()}/{sport}/_status.json") is None
    assert ar._rule_for("nba_source/tracking/book_quotes/2026-10-20.jsonl.gz").name == "book_quotes"


def _write(path: Path, rows, gz=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in rows)
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def test_closed_days_are_filtered_mirrored_and_kept_fresh(tmp_path) -> None:
    p = _load()
    bq = tmp_path / "mlb_source" / "tracking" / "book_quotes"
    rows = [{"kind": "prop", "market": "batter_hits", "x": 1}, {"kind": "prop", "market": "batter_home_runs"},
            {"kind": "game", "market": "h2h"}, {"kind": "prop", "market": "strikeouts"}]
    _write(bq / "2026-10-20.jsonl", rows)
    _write(bq / "2026-10-21.jsonl", rows)                        # "today": still being written
    _write(bq / "2026-10-01.jsonl", rows)                        # before the forward windows
    (bq / "2026-10-20.state.json").write_text("{}", encoding="utf-8")
    s = p.preserve(tmp_path, today="2026-10-21")
    assert s["mlb"] == {"mirrored": 1, "fresh": 0, "rows": 2, "held": 1}
    dest = tmp_path / p.MIRROR / "mlb" / "quotes" / "2026-10-20.jsonl.gz"
    assert [r["market"] for r in _rows(dest)] == ["batter_hits", "strikeouts"] and _rows(dest)[0]["x"] == 1
    assert p.preserve(tmp_path, today="2026-10-21")["mlb"]["fresh"] == 1   # unchanged source: not re-mirrored
    os.utime(bq / "2026-10-20.jsonl", (dest.stat().st_mtime + 60,) * 2)
    assert p.preserve(tmp_path, today="2026-10-21")["mlb"]["mirrored"] == 1


def test_the_fuller_of_plain_and_gz_is_mirrored(tmp_path) -> None:
    p = _load()
    bq = tmp_path / "nhl_source" / "tracking" / "book_quotes"
    _write(bq / "2026-11-02.jsonl", [{"kind": "prop", "market": "SOG", "v": 1}])
    _write(bq / "2026-11-02.jsonl.gz", [{"kind": "prop", "market": "SOG", "v": 1}, {"kind": "prop", "market": "SOG", "v": 2}],
           gz=True)
    p.preserve(tmp_path, today="2026-11-05")
    assert len(_rows(tmp_path / p.MIRROR / "nhl" / "quotes" / "2026-11-02.jsonl.gz")) == 2


def test_weekly_files_wait_until_the_week_closes(tmp_path) -> None:
    p = _load()
    bq = tmp_path / "nfl_source" / "tracking" / "book_quotes"
    _write(bq / "2026_wk8.jsonl", [{"kind": "prop", "market": "Receptions"}])
    now = (bq / "2026_wk8.jsonl").stat().st_mtime
    assert p.preserve(tmp_path, today="2026-11-01", now=now + 3600)["nfl"]["mirrored"] == 0
    assert p.preserve(tmp_path, today="2026-11-01", now=now + 3 * 86400)["nfl"]["mirrored"] == 1


def test_restore_puts_back_only_what_retention_removed(tmp_path) -> None:
    p = _load()
    bq = tmp_path / "nba_source" / "tracking" / "book_quotes"
    _write(bq / "2026-10-20.jsonl", [{"kind": "prop", "market": "player_rebounds"}])
    _write(bq / "2026-10-21.jsonl", [{"kind": "prop", "market": "player_rebounds"}])
    p.preserve(tmp_path, today="2026-10-25")
    (bq / "2026-10-20.jsonl").unlink()                           # retention deleted it
    assert p.restore(tmp_path) == {"nba": 1}
    assert (bq / "2026-10-20.jsonl.gz").is_file() and not (bq / "2026-10-21.jsonl.gz").exists()
    assert p.restore(tmp_path) == {}
