"""The live-gameline score must be RETAINED by the worker, not by a laptop cron.

WHY THESE EXIST. The score was computed on every board build and kept by
`scripts/snapshot_live_gameline_score.py`, run from a Windows scheduled task at
23:25 CT. It lost 7 of its first 8 nights: six to the task sitting disabled, and
one to Modern Standby suspending its python child for 9h13m (measured
2026-08-28 -- the scheduler fired and the model emitted the tool call, the
process never ran, and the slate rolled). Retention now rides the board build.

THE FIRST TEST IS A REACHABILITY TEST, and that ordering is deliberate. A
correctness test over a fixture proves the function works; it does not prove the
board build ever calls it. Four inert features in this repo were caught by
`off != on` and by nothing else, so `test_board_build_reaches_the_recorder` and
`test_kill_switch_is_reachable` come before any assertion about the numbers.

THE SECOND THING ASSERTED IS THAT THE WRITE IS ON DISK. `write_json_file` routes
every path outside `migration_runs/` to the keyvalue store and returns BEFORE
touching disk, so a `HOT_ARTIFACT_PATTERNS` entry for such a path is inert -- it
turns a 403 into an empty result and looks exactly like a fix
(`learnings.md`, 2026-08-27 FORBIDDEN). `test_write_lands_on_real_disk` is what
makes the allowlist entry meaningful rather than decorative.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.shared import live_gameline_accuracy as acc  # noqa: E402
from syndicate.features.shared.artifact_publisher import (  # noqa: E402
    HOT_ARTIFACT_PATTERNS, is_hot_artifact_relative_path)


def _score(games: int, *, date_ok: bool = True) -> dict:
    """A score payload shaped like `score_ledger_records` output."""
    return {
        "enabled": True,
        "games_with_outcome": games,
        "records_considered": games * 250,
        "all_records": {
            "model": {"brier": 0.29, "n": 1672},
            "model_paired": {"brier": 0.294, "n": 1577},
            "market": {"brier": 0.243, "n": 1577},
            "model_minus_market_brier": 0.051,
            "populations_matched": True,
            "rows_without_market_prob": 95,
        },
        "priceable_only": {
            "model": {"brier": 0.319, "n": 1016},
            "model_paired": {"brier": 0.319, "n": 1016},
            "market": {"brier": 0.244, "n": 1016},
            "model_minus_market_brier": 0.075,
            "populations_matched": True,
            "rows_without_market_prob": 0,
        },
        "finals_index": {"sport": "mlb", "finals_seen": 1462},
    }


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Point `data_root()` at a tmp dir so nothing touches the real mirror."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_LIVE_GAMELINE_ACCURACY_ENABLED", raising=False)
    return tmp_path


# --------------------------------------------------------------------------
# REACHABILITY -- these come first on purpose. See the module docstring.
# --------------------------------------------------------------------------


def test_board_build_reaches_the_recorder(monkeypatch, tmp_path):
    """The builder must CALL the recorder and surface its counters.

    Asserting on the retained file instead would pass on a build that never
    called anything, because absent and empty look identical there. This spies
    on the seam, so a future refactor that drops the call fails loudly.
    """
    from syndicate.features.shared import board_enrichment, book_grid_artifact

    seen: dict = {}

    def _spy(score, *, sport, date_str, board_generated_at=""):
        seen["score"] = score
        seen["sport"] = sport
        seen["date_str"] = date_str
        seen["board_generated_at"] = board_generated_at
        return {"enabled": True, "written": 1, "spy": True}

    # The import in `book_grid_artifact` is function-level, so the SOURCE module
    # is the seam that has to be patched -- patching the builder's namespace
    # would silently not take, and the test would pass while asserting nothing.
    monkeypatch.setattr(acc, "record_live_gameline_score", _spy)

    shard = tmp_path / "book_quotes_2026-08-10.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(book_grid_artifact, "book_quotes_path", lambda *a, **k: shard)
    monkeypatch.setattr(book_grid_artifact, "read_quote_last_seen", lambda *a, **k: {})
    monkeypatch.setattr(
        book_grid_artifact,
        "iter_book_quotes",
        lambda *a, **k: iter([{
            "sport": "mlb", "kind": "game", "event_id": "evt-1", "segment": "full_game",
            "market": "h2h", "player_name": "", "selection": "home", "line": None,
            "price": -110, "bookmaker": "draftkings",
            "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
            "commence_time": "2026-08-10T23:05:00Z", "snapshot_ts": "2026-08-10T19:55:00Z",
        }]),
    )
    monkeypatch.setattr(board_enrichment, "attach_game_state", lambda g, **k: {"chips": 1})
    monkeypatch.setattr(board_enrichment, "attach_projections", lambda g, **k: {"supported": True})
    monkeypatch.setattr(board_enrichment, "attach_margin_model", lambda g, **k: {"rows_modelled": 0})

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-08-10")

    assert payload is not None, "builder returned None -- fixture shard not picked up"
    assert seen, "build_book_grid_artifact never reached record_live_gameline_score"
    assert seen["sport"] == "mlb"
    assert seen["date_str"] == "2026-08-10"
    assert payload["live_gameline_accuracy"] == {"enabled": True, "written": 1, "spy": True}, (
        "the recorder's counters must ride the served payload -- without them a "
        "stalled history is invisible off-worker"
    )


def test_board_generated_at_is_the_same_instant_the_payload_publishes(monkeypatch, tmp_path):
    """One clock read, not two.

    `board_generated_at` is how a retained row is joined back to the build that
    produced it. A second `datetime.now()` would differ by microseconds and make
    an exact join impossible.
    """
    from syndicate.features.shared import board_enrichment, book_grid_artifact

    seen: dict = {}
    monkeypatch.setattr(
        acc, "record_live_gameline_score",
        lambda score, *, sport, date_str, board_generated_at="": seen.update(
            {"stamp": board_generated_at}) or {"written": 0},
    )
    shard = tmp_path / "book_quotes_2026-08-10.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(book_grid_artifact, "book_quotes_path", lambda *a, **k: shard)
    monkeypatch.setattr(book_grid_artifact, "read_quote_last_seen", lambda *a, **k: {})
    # A real row: an empty shard makes the builder return None (an absent grid
    # is not an empty one), and the assertion below would then be vacuous.
    monkeypatch.setattr(
        book_grid_artifact,
        "iter_book_quotes",
        lambda *a, **k: iter([{
            "sport": "mlb", "kind": "game", "event_id": "evt-1", "segment": "full_game",
            "market": "h2h", "player_name": "", "selection": "home", "line": None,
            "price": -110, "bookmaker": "draftkings",
            "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
            "commence_time": "2026-08-10T23:05:00Z", "snapshot_ts": "2026-08-10T19:55:00Z",
        }]),
    )
    monkeypatch.setattr(board_enrichment, "attach_game_state", lambda g, **k: {})
    monkeypatch.setattr(board_enrichment, "attach_projections", lambda g, **k: {})
    monkeypatch.setattr(board_enrichment, "attach_margin_model", lambda g, **k: {})

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-08-10")
    assert payload is not None
    assert seen["stamp"] == payload["generated_at"]


def test_kill_switch_is_reachable(root, monkeypatch):
    """`off != on`. A flag nothing consults is not a flag."""
    on = acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    assert on.get("written") == 1 and on.get("enabled") is True

    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_ACCURACY_ENABLED", "0")
    off = acc.record_live_gameline_score(_score(9), sport="mlb", date_str="2026-08-26")
    assert off.get("enabled") is False
    assert off.get("written") == 0
    assert not acc.history_path("mlb").read_text(encoding="utf-8").count("2026-08-26"), (
        "the kill switch did not actually gate the write"
    )


def test_absent_env_means_ENABLED(root, monkeypatch):
    """Absent != off. The same edit is a no-op or a behaviour change depending
    on this default, and `render.yaml` syncs rewrite the whole env block."""
    monkeypatch.delenv("SYNDICATE_LIVE_GAMELINE_ACCURACY_ENABLED", raising=False)
    assert acc._enabled() is True


# --------------------------------------------------------------------------
# THE WRITE IS ON DISK -- what makes the allowlist entry meaningful
# --------------------------------------------------------------------------


def test_write_lands_on_real_disk(root):
    """A real file must exist at `history_path`.

    If this ever routed through `write_json_file`, the keyvalue store would take
    it and return before touching disk -- no file, and the allowlist entry below
    would gate a read of something never written there.
    """
    acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    path = acc.history_path("mlb")
    assert path.is_file(), "nothing on disk -- the allowlist entry would be inert"
    assert path.stat().st_size > 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1 and rows[0]["date"] == "2026-08-27"


def test_history_path_is_under_data_not_reports(root):
    """`reports/**` is keyvalue-backed with an 8 MB ceiling on a 256 MB shared
    store. This has to live under `data/<sport>_source/`."""
    rel = acc.history_path("mlb").as_posix()
    assert "/mlb_source/data/live_gameline_accuracy/" in rel
    assert "/reports/" not in rel


# --------------------------------------------------------------------------
# ALLOWLIST -- both matchers, because they disagree
# --------------------------------------------------------------------------

HISTORIES = [
    "mlb_source/data/live_gameline_accuracy/live_gameline_accuracy_mlb.jsonl",
    "soccer_source/data/live_gameline_accuracy/live_gameline_accuracy_soccer.jsonl",
    "mlb_source/source_artifacts/data/live_gameline_accuracy/live_gameline_accuracy_mlb.jsonl",
]


def _glob_like(path: str, pattern: str) -> bool:
    """Path.glob semantics: `*` does NOT cross a directory separator."""
    return re.match("^" + re.escape(pattern).replace(r"\*", "[^/]*") + "$", path) is not None


@pytest.mark.parametrize("rel", HISTORIES)
def test_read_path_allows_the_history(rel):
    assert is_hot_artifact_relative_path(rel), (
        f"{rel} is not allowlisted -- /api/ops/artifacts/export will 403 and the "
        "retained score stays unreadable off-worker"
    )


@pytest.mark.parametrize("rel", HISTORIES)
def test_sweep_semantics_also_match(rel):
    """fnmatch is not sufficient: the publisher walks with `Path.glob`, where
    `*` does not cross `/`. A pattern satisfying only fnmatch reads as
    allowlisted while publishing nothing -- that hid a bug for hours on
    2026-08-20."""
    pats = [p for p in HOT_ARTIFACT_PATTERNS if "live_gameline_accuracy" in p]
    assert pats, "no live_gameline_accuracy pattern registered at all"
    assert any(_glob_like(rel, p) for p in pats), (
        f"{rel} matches fnmatch but NOT glob -- the sweep would never publish it"
    )


def test_the_publish_sweep_actually_reaches_the_file(tmp_path, monkeypatch):
    """The whole chain, against a REAL glob over a REAL file.

    Matching a pattern is not the same as being published. `sweep_changed_hot_artifacts`
    walks `root.glob(pattern)` and then asks `_publish_skip_reason`, which
    refuses anything whose parsed artifact date is older than
    `_PUBLISH_MAX_AGE_DAYS`. This filename carries NO date, so `_artifact_date`
    must return None -- if it ever parsed one, the file would be classified
    `stale_slate` forever and the sweep would skip it silently while every
    pattern test above still passed.
    """
    from syndicate.features.shared import artifact_publisher as ap

    root = Path(str(tmp_path)).resolve()
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(root))

    path = acc.history_path("mlb")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"date":"2026-08-27","games_with_outcome":4}\n', encoding="utf-8")

    assert ap._artifact_date(path) is None, (
        "a parsed artifact date would make this permanently stale_slate"
    )
    assert ap._publish_skip_reason(path, ap.central_today()) is None, (
        "the sweep would skip this file"
    )
    matched = [
        pat for pat in ap.HOT_ARTIFACT_PATTERNS
        for c in root.glob(pat) if c.resolve() == path.resolve()
    ]
    assert matched, "no HOT_ARTIFACT_PATTERNS entry is reached by the sweep's own glob"


def test_pattern_does_not_drag_in_neighbours():
    pats = [p for p in HOT_ARTIFACT_PATTERNS if "live_gameline_accuracy" in p]
    assert not any(
        _glob_like("mlb_source/data/live_gameline_accuracy/notes.txt", p) for p in pats
    )


# --------------------------------------------------------------------------
# CORRECTNESS
# --------------------------------------------------------------------------


def test_appends_only_when_games_with_outcome_improves(root):
    """The board rebuilds every few minutes. Recording unconditionally would
    multiply the file by the build rate for no information."""
    path = acc.history_path("mlb")
    first = acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    assert first["written"] == 1

    same = acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    assert same["written"] == 0 and same["skipped_not_improved"] == 1
    assert same["previous_best"] == 4

    worse = acc.record_live_gameline_score(_score(2), sport="mlb", date_str="2026-08-27")
    assert worse["written"] == 0

    better = acc.record_live_gameline_score(_score(15), sport="mlb", date_str="2026-08-27")
    assert better["written"] == 1

    rows = acc.read_rows(path)
    assert [r["games_with_outcome"] for r in rows] == [4, 15]


def test_a_new_date_is_not_blocked_by_a_richer_previous_date(root):
    """The improvement rule is PER DATE. A 15-game yesterday must not suppress a
    1-game today -- that would silently lose thin slates entirely."""
    acc.record_live_gameline_score(_score(15), sport="mlb", date_str="2026-08-26")
    out = acc.record_live_gameline_score(_score(1), sport="mlb", date_str="2026-08-27")
    assert out["written"] == 1
    assert {r["date"] for r in acc.read_rows(acc.history_path("mlb"))} == {"2026-08-26", "2026-08-27"}


def test_zero_games_is_never_recorded(root):
    """A build with no final game is the NORMAL mid-slate state. Retaining a
    zero row would be indistinguishable from the old collector's 9-hour-late
    empty capture -- the exact thing this module exists to stop recording."""
    out = acc.record_live_gameline_score(_score(0), sport="mlb", date_str="2026-08-28")
    assert out["written"] == 0
    assert out["reason"] == "no_games_with_outcome"
    assert not acc.history_path("mlb").exists()


def test_the_retained_row_keeps_the_paired_populations(root):
    """The headline diff is meaningless without `populations_matched` and the
    paired `n`. Reducing to a single number here would reintroduce, one layer
    down, the exact defect `model_paired` was added to fix."""
    acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    row = acc.read_rows(acc.history_path("mlb"))[0]
    cut = row["priceable_only"]
    assert cut["populations_matched"] is True
    assert cut["model_paired"]["n"] == cut["market"]["n"]
    assert row["all_records"]["rows_without_market_prob"] == 95
    assert row["finals_index"]["finals_seen"] == 1462
    assert row["captured_by"] == "board_build"


def test_best_by_date_takes_the_max_not_the_last(root):
    """Never average Briers across days unweighted, and never take the LAST row
    for a date -- a late thin build would beat a complete earlier one."""
    rows = [
        {"date": "2026-08-27", "games_with_outcome": 15},
        {"date": "2026-08-27", "games_with_outcome": 4},
        {"date": "2026-08-26", "games_with_outcome": 9},
    ]
    best = acc.best_by_date(rows)
    assert best["2026-08-27"]["games_with_outcome"] == 15
    assert best["2026-08-26"]["games_with_outcome"] == 9


def test_never_raises_on_a_broken_score_payload(root):
    """The board is the product; this is instrumentation."""
    for bad in (None, "not-a-mapping", 17, []):
        out = acc.record_live_gameline_score(bad, sport="mlb", date_str="2026-08-27")
        assert out["written"] == 0
        assert "error" in out or "reason" in out


def test_never_raises_when_the_disk_refuses(root, monkeypatch):
    """An unwritable path must be reported in the counters, not raised, and not
    swallowed into a silent zero."""
    def _boom(*a, **k):
        raise OSError("disk is full")

    monkeypatch.setattr(Path, "mkdir", _boom)
    out = acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    assert out["written"] == 0
    assert "OSError" in out.get("error", "")


def test_a_half_written_line_does_not_destroy_the_history(root):
    """A process killed mid-append must cost one row, not every night recorded."""
    acc.record_live_gameline_score(_score(4), sport="mlb", date_str="2026-08-27")
    path = acc.history_path("mlb")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"date": "2026-08-28", "games_with_ou')
    rows = acc.read_rows(path)
    assert len(rows) == 1 and rows[0]["date"] == "2026-08-27"
