"""scripts/inplay_poll_gaps.py attributes a > 120 s gap to the list (capture cap) or to starvation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_poll_gaps as pg  # noqa: E402


def _night(tmp_path, cycles):
    """cycles: list of (start_second, [batch, ...]) with each batch a list of tickers, 1 s apart."""
    with open(tmp_path / "kalshi.jsonl", "w", encoding="utf-8") as fh:
        for start, batches in cycles:
            for k, batch in enumerate(batches):
                s = start + k
                ts = f"2026-11-14T{18 + s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}.000Z"
                for t in batch:
                    fh.write(json.dumps({"ts": ts, "t": t}) + "\n")
    (tmp_path / "log.jsonl").write_text('{"ts":"2026-11-14T20:00:00.000Z","event":"stopped"}\n', encoding="utf-8")
    return pg.analyse(str(tmp_path))


def test_a_ticker_the_cycles_pass_without_returning_is_a_list_gap(tmp_path):
    full = [["KXNCAAFGAME-A"], ["KXNCAAFSPREAD-B"], ["KXNCAAFTOTAL-C"]]
    dropped = [["KXNCAAFGAME-A"], ["KXNCAAFTOTAL-C"]]  # B out of the list; the cycle still reaches C
    rep = _night(tmp_path, [(0, full)] + [(30 * i, dropped) for i in range(1, 10)] + [(300, full)])
    assert rep["gaps_over_120_by_cause"]["list"]["n"] == 1
    assert "starve" not in rep["gaps_over_120_by_cause"]
    assert rep["markets"] == 3 and rep["markets_any_gap_over_120"] == 1


def test_a_ticker_no_cycle_reaches_is_a_starve_gap(tmp_path):
    full = [["KXNCAAFGAME-A"], ["KXNCAAFSPREAD-B"], ["KXNHLGAME-C"]]
    cut = [["KXNCAAFGAME-A"], ["KXNCAAFSPREAD-B"]]  # a 429 ends every cycle before C
    rep = _night(tmp_path, [(0, full)] + [(30 * i, cut) for i in range(1, 10)] + [(300, full)])
    assert rep["gaps_over_120_by_cause"]["starve"]["n"] == 1
    assert rep["gaps_over_120_by_cause"]["starve|nhl"]["n"] == 1
    assert rep["by_sport"]["nhl"]["gap_max"] == 300.0


def test_no_gap_over_120_when_every_cycle_is_whole(tmp_path):
    full = [["KXNBAGAME-A", "KXNBAGAME-B"], ["KXNBATOTAL-C"]]
    rep = _night(tmp_path, [(30 * i, full) for i in range(20)])
    assert rep["share_any_gap_over_120"] == 0.0 and rep["gap_p50"] == 30.0
    assert rep["gaps_over_120_by_cause"] == {}
