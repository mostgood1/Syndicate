"""The slate-hygiene verifier must go RED on the pre-fix shape and GREEN on a clean one.

A gate that cannot read unhealthy proves nothing when it reads healthy, so every
check here is pinned both ways (off != on).
"""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_wnba_slate_hygiene.py"
_SPEC = importlib.util.spec_from_file_location("verify_wnba_slate_hygiene", _PATH)
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _slate(*picks):
    return {"date": "2026-09-17", "counts": {"games": 1, "picks": len(picks)},
            "per_game": [{"home": "ATL", "away": "CON", "picks": list(picks)}]}


CLEAN_GAME = {"market": "ML", "p_win": 0.62, "ev_pct": 4.1, "odds": -150}
CLEAN_PROP = {"market": "Points", "p_win": 0.55, "ev_pct": 6.0, "odds": -110}


def test_clean_slate_passes():
    verdict, reason, detail = gate.evaluate_slate(_slate(CLEAN_GAME, CLEAN_PROP))
    assert verdict == gate.PASS, reason
    assert detail["picks"] == 2


def test_certainty_claim_fails():
    verdict, reason, _ = gate.evaluate_slate(_slate(CLEAN_GAME, {**CLEAN_PROP, "p_win": 1.0}))
    assert verdict == gate.FAIL
    assert "certainty" in reason


def test_total_pick_fails_unless_totals_were_enabled():
    total = {"market": "TOTAL", "p_win": 0.55, "ev_pct": 3.0, "odds": -110}
    assert gate.evaluate_slate(_slate(CLEAN_GAME, total))[0] == gate.FAIL
    assert gate.evaluate_slate(_slate(CLEAN_GAME, total), allow_totals=True)[0] == gate.PASS


def test_implausible_game_ev_fails():
    verdict, reason, _ = gate.evaluate_slate(_slate({**CLEAN_GAME, "ev_pct": 2264.8}))
    assert verdict == gate.FAIL
    assert "EV refusal" in reason


def test_implausible_prop_ev_is_reported_not_gated():
    # The slate's prop loop never calls `_plausible_ev_pct`; failing on it would
    # fail the slate for a fix nobody shipped, and hiding it would overstate the fix.
    verdict, _, detail = gate.evaluate_slate(_slate(CLEAN_GAME, {**CLEAN_PROP, "ev_pct": 150.0}))
    assert verdict == gate.PASS
    assert detail["prop_ev_over_100 (REPORTED, not gated)"] == 1


def test_empty_slate_is_unreadable_not_pass():
    assert gate.evaluate_slate({"date": "2026-09-17", "per_game": []})[0] == gate.UNREADABLE
    no_picks = {"date": "2026-09-17", "per_game": [{"home": "ATL", "away": "CON", "picks": []}]}
    assert gate.evaluate_slate(no_picks)[0] == gate.UNREADABLE


def test_unwrap_export_reads_the_exact_path():
    path = "wnba_source/data/processed/recommendations_slate_2026-09-17.json"
    assert gate.unwrap_export({"ok": True, "count": 1, "artifacts": {path: "{}"}}, path) == "{}"
    assert gate.unwrap_export({"ok": True, "count": 0, "artifacts": {}}, path) is None


FROZEN = [{"sport": "wnba", "matchup": "CON @ DAL", "state": "final", "start_time_utc": ""}]
REAL = [{"sport": "wnba", "matchup": "CON @ ATL", "state": "pregame", "start_time_utc": "2026-09-17T23:30:00+00:00"}]


def _board(ingest=None, served=None):
    payload = {"written_at": "x", "active_sports": [], "per_sport": {}, "per_sport_ingest": {}}
    if ingest is not None:
        payload["per_sport_ingest"]["wnba"] = ingest
    if served is not None:
        payload["per_sport"]["wnba"] = served
    return payload


def test_layer2_pass_only_when_wnba_is_selected():
    assert gate.evaluate_layer2(_board({"quote_rows": 9}, {"selected": 5}), REAL)[0] == gate.PASS
    assert gate.evaluate_layer2(_board({"quote_rows": 9, "opportunities": 3}, {"selected": 0}), REAL)[0] == gate.FAIL


def test_layer2_names_the_gate():
    assert "gate 1" in gate.evaluate_layer2(_board(), REAL)[1]
    assert "gate 3" in gate.evaluate_layer2(_board({"error": "boom"}), REAL)[1]
    assert "gate 4" in gate.evaluate_layer2(_board({"quote_rows": 50, "opportunities": 0}), REAL)[1]
    assert "gate 5" in gate.evaluate_layer2(_board({"quote_rows": 50, "opportunities": 7}), REAL)[1]


def test_layer2_zero_quotes_fails_on_a_real_slate_and_is_unreadable_on_a_frozen_one():
    pending = {"quote_rows": 0, "sweep_state": "pending", "scheduled_games": 4}
    assert gate.evaluate_layer2(_board(pending), REAL)[0] == gate.FAIL
    verdict, reason, detail = gate.evaluate_layer2(_board(pending), FROZEN)
    assert verdict == gate.UNREADABLE
    assert detail["frozen_chips"] and "FROZEN" in reason


def test_layer2_without_a_board_is_unreadable():
    assert gate.evaluate_layer2({"ok": False, "error": "no_shortlist_artifact"})[0] == gate.UNREADABLE
