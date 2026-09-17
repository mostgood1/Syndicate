"""Settlement reads each date's chunk ONCE for every sport and writes it ONCE.

Measured on production 2026-09-17: ledger chunks were 45-258 MB, the autorun
read each date once PER SPORT (14 whole-chunk reads for 7 dates x mlb,wnba), and
every settled record rewrote its entire chunk file -- the worker's stack dumps
during the >= 53-minute run sat in `settle_result`. Grading MLB game markets
from final scores raises the settled count several-fold, which would have
multiplied that rewrite cost with it.

Parity is the point of these tests: one pass over two sports must produce the
same per-sport results and the same ledger as the per-sport calls it replaces.
Graded rows are the real 2026-09-11 card payload plus real final-score feeds;
records are the production unmatched samples plus the card's own prop rows.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import syndicate.features.shared.evaluation_settlement as evaluation_settlement
import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.features.shared import graded_outcomes as go
from syndicate.features.shared.intelligence_evaluation import _iter_record_payloads
from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation

FIXTURES = Path(__file__).parent / "fixtures" / "settlement_final_scores"
DATE = "2026-09-11"
FINAL_GAMES = (822684, 824227, 823012, 824711, 824954)


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _mlb_rows() -> list[dict]:
    feeds = {pk: _json(f"feed_live_{pk}.json") for pk in FINAL_GAMES}
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=_json(f"card_payload_{DATE}.json")), \
         patch.object(go, "_mlb_slate_game_pks", return_value=set(FINAL_GAMES)), \
         patch.object(go, "_load_cached_mlb_feed", side_effect=lambda _date, pk: feeds.get(pk)):
        return go.graded_rows_for_date("mlb", DATE)


def _recommendations() -> list[dict]:
    out: list[dict] = []
    for sample in _json("unmatched_samples_2026-09-17.json")["unmatched_samples"]:
        identity = sample["record_identity"]
        line = f"{sample['record_line']:.1f}"
        out.append(
            {
                "game_id": identity["game_ids"][0], "gamePk": int(identity["game_ids"][0]), "sport": "MLB", "sport_slug": "mlb",
                "matchup": f"{identity['away'].upper()} @ {identity['home'].upper()}", "market": "Total", "market_key": "totals",
                "pick": f"Over {line}", "team": "-", "line": line, "odds": "-110",
            }
        )
    for row in _json(f"card_payload_{DATE}.json")["days"][0]["rows"]["all"]:
        if row["market"] == "ml":
            continue
        out.append(
            {
                "game_id": str(row["game_pk"]), "gamePk": row["game_pk"], "sport": "MLB", "sport_slug": "mlb", "matchup": row["matchup"],
                "market": "Hitter Hits", "market_key": "batter_hits", "pick": f"{row['selection'].upper()} {row['player_name']}",
                "player_name": row["player_name"], "entity": row["player_name"], "team": row["team"], "line": str(row["line"]), "odds": row["odds"],
            }
        )
    # A WNBA record in the same chunk: its grader has nothing for the date.
    out.append({"sport": "WNBA", "sport_slug": "wnba", "market": "Total", "pick": "Over 165.5", "line": "165.5", "matchup": "NYL @ LVA", "odds": "-110"})
    return out


def _build_ledger(root: Path) -> Path:
    ledger_path = root / "evaluation_ledger.jsonl"
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
        for recommendation in _recommendations():
            sport = recommendation["sport_slug"]
            prediction = record_prediction(
                query={"question": "board", "selected_date": DATE, "sport": sport},
                response={"selected_date": DATE, "recommendations": []},
                persist=True,
                ledger_path=ledger_path,
            )
            record_recommendation(prediction_record=prediction, recommendation=recommendation, persist=True, ledger_path=ledger_path)
    return ledger_path


def _graded_rows(mlb_rows: list[dict]):
    return lambda sport, _date: list(mlb_rows) if sport == "mlb" else []


SETTLEMENT_FIELDS = ("result", "pnl", "closing_line", "closing_price", "implied_probability", "stake")


def _stored(ledger_path: Path) -> dict[str, dict]:
    """Settlement outcome per recommendation, keyed by the recommendation's
    CONTENT: two ledgers built separately mint different record ids."""
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
        records = [
            record for record in _iter_record_payloads(ledger_path=ledger_path) if record.get("record_type") == "recommendation"
        ]
    out = {
        json.dumps(record["recommendation"], sort_keys=True): {key: record.get(key) for key in SETTLEMENT_FIELDS}
        for record in records
    }
    assert len(out) == len(records)
    return out


def _strip(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "score_row_diagnostics"}


@pytest.fixture()
def two_ledgers():
    """Two identical ledgers, each BUILT separately. (A copied directory would
    carry an index whose absolute paths point back at the first ledger's chunk.)"""
    mlb_rows = _mlb_rows()
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        yield mlb_rows, _build_ledger(root / "a"), _build_ledger(root / "b")


def test_one_pass_opens_the_chunk_once_for_two_sports(two_ledgers):
    mlb_rows, ledger_path, _other = two_ledgers
    chunk = _ledger_chunk_path(ledger_path, DATE)
    reads: list[Path] = []
    real_iter = evaluation_settlement._iter_chunk_records
    real_open = Path.open

    def counting_iter(path):
        reads.append(Path(path))
        return real_iter(path)

    opens: list[str] = []

    def counting_open(self, *args, **kwargs):
        if Path(self) == chunk:
            opens.append(str(args[0] if args else kwargs.get("mode", "r")))
        return real_open(self, *args, **kwargs)

    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)), \
         patch.object(evaluation_settlement, "_iter_chunk_records", side_effect=counting_iter), \
         patch.object(Path, "open", counting_open):
        dry = evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb", "wnba"], ledger_path=ledger_path, dry_run=True)
        assert reads == [chunk] and opens == ["r"]
        assert [r["sport"] for r in dry["results"]] == ["mlb", "wnba"]

        reads.clear()
        opens.clear()
        wet = evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb", "wnba"], ledger_path=ledger_path)
    settled = wet["totals"]["settled"]
    assert settled >= 10, wet["totals"]
    # One streamed read, and ONE rewrite for all of them -- not one per record.
    assert reads == [chunk]
    assert opens == ["r", "rb"], opens


def test_single_pass_results_and_ledger_equal_the_per_sport_calls(two_ledgers):
    mlb_rows, single_path, per_sport_path = two_ledgers
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", single_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)):
        single = evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb", "wnba"], ledger_path=single_path)["results"]
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", per_sport_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)):
        per_sport = [
            evaluation_settlement.settle_ledger_for_date(DATE, sport=sport, ledger_path=per_sport_path) for sport in ("mlb", "wnba")
        ]
    assert [_strip(r) for r in single] == [_strip(r) for r in per_sport]
    mlb, wnba = single
    assert mlb["pending"] == 15 and mlb["settled"] == 15 - mlb["unmatched"] and mlb["settled"] >= 10
    assert mlb["matched_by_phase"]["game_score"] == 5
    assert wnba["pending"] == 1 and wnba["unmatched_no_graded_rows"] == 1
    assert mlb["total_ledger_records"] == wnba["total_ledger_records"]
    assert _stored(single_path) == _stored(per_sport_path)


def test_an_overlapping_scope_sees_what_the_earlier_scope_settled(two_ledgers):
    mlb_rows, single_path, per_sport_path = two_ledgers
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", single_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)):
        single = evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb", "mlb"], ledger_path=single_path)["results"]
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", per_sport_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)):
        per_sport = [evaluation_settlement.settle_ledger_for_date(DATE, sport="mlb", ledger_path=per_sport_path) for _ in range(2)]
    assert [_strip(r) for r in single] == [_strip(r) for r in per_sport]
    assert single[1]["settled"] == 0 and single[1]["already_resolved_records"] == single[0]["settled"]


def test_the_per_record_fallback_writes_the_same_ledger_and_says_so(two_ledgers, capsys):
    mlb_rows, batch_path, fallback_path = two_ledgers
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", batch_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)):
        evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb"], ledger_path=batch_path)
    assert "path=batch" in capsys.readouterr().out

    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", fallback_path), \
         patch.object(evaluation_settlement, "_graded_rows_for_date", side_effect=_graded_rows(mlb_rows)), \
         patch.object(evaluation_settlement, "_replace_ledger_lines", side_effect=OSError("disk full")):
        evaluation_settlement.settle_ledger_for_dates([DATE], sports=["mlb"], ledger_path=fallback_path)
    out = capsys.readouterr().out
    assert "path=per_record_fallback" in out and "disk full" in out
    assert _stored(batch_path) == _stored(fallback_path)
    assert {record["result"] for record in _stored(batch_path).values()} >= {"win", "loss", "push"}


def test_a_rewrite_that_dies_leaves_the_chunk_untouched(two_ledgers):
    mlb_rows, ledger_path, _other = two_ledgers
    chunk = _ledger_chunk_path(ledger_path, DATE)
    before = chunk.read_bytes()
    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
        stored = [json.loads(line) for line in before.decode("utf-8").splitlines() if line.strip()]
        target = next(record for record in stored if record.get("record_type") == "recommendation")
        settled = dict(target, result="win", pnl=1.0)
        with patch.object(evaluation_settlement, "_canonical_payload", side_effect=RuntimeError("killed mid-write")):
            with pytest.raises(RuntimeError):
                evaluation_settlement._replace_ledger_lines(chunk, {target["recommendation_id"]: settled})
    assert chunk.read_bytes() == before
    assert not any(name.endswith(".tmp") for name in os.listdir(chunk.parent))


def test_a_line_appended_during_the_rewrite_is_kept(two_ledgers):
    mlb_rows, ledger_path, _other = two_ledgers
    chunk = _ledger_chunk_path(ledger_path, DATE)
    stored = [json.loads(line) for line in chunk.read_text(encoding="utf-8").splitlines() if line.strip()]
    target = next(record for record in stored if record.get("record_type") == "recommendation")
    appended = json.dumps({"record_type": "prediction", "prediction_id": "pred_appended_mid_pass"}) + "\n"
    real_getsize = os.path.getsize

    def append_then_measure(path):
        # The recorder appends to today's chunk AFTER the stream reached its
        # end and before the replace -- the window the tail copy exists for.
        with open(chunk, "a", encoding="utf-8") as handle:
            handle.write(appended)
        return real_getsize(path)

    with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path), \
         patch.object(os.path, "getsize", side_effect=append_then_measure):
        replaced = evaluation_settlement._replace_ledger_lines(chunk, {target["recommendation_id"]: dict(target, result="loss")})
    assert replaced == {target["recommendation_id"]}
    lines = [json.loads(line) for line in chunk.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == len(stored) + 1
    assert lines[-1]["prediction_id"] == "pred_appended_mid_pass"
    assert next(line for line in lines if line.get("recommendation_id") == target["recommendation_id"])["result"] == "loss"
