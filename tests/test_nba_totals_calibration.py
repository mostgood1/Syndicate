"""NBA totals calibration builder (lane basketball-scenario-calibration, Phase 2 #1e)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_nba_totals_calibration as b  # noqa: E402


def _sim(root: Path, day: str, home: str, away: str, raw_total: float, raw_margin: float = 0.0) -> None:
    (root / f"smart_sim_{day}_{home}_{away}.json").write_text(json.dumps(
        {"home": home, "away": away, "market_anchor": {"model_total_raw": raw_total, "model_margin_raw": raw_margin}}), encoding="utf-8")


def _recon(root: Path, day: str, rows) -> None:
    lines = ["date,game_id,gameId,home_tri,away_tri,home_pts,visitor_pts,actual_margin,total_actual,source"]
    for h, a, hp, ap in rows:
        lines.append(f"{day},1,1,{h},{a},{hp},{ap},{hp - ap},{hp + ap},espn")
    (root / f"recon_games_{day}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def regular(monkeypatch):
    import syndicate.features.shared.nba_season_phase as ph

    monkeypatch.setattr(ph, "phase_for_date", lambda d, **_k: "preseason" if d < "2025-10-21" else "regular")


def test_applied_shift_matches_the_reader_order_and_clamps():
    cal = {"global": {"game_total_bias": 20.0, "sim_game_total_bias": 1.0}, "team": {"BOS": 5.0, "NYK": -1.5}}
    total, margin = b.applied_shift(cal, "BOS", "NYK")
    assert total == pytest.approx(4.0 - 1.5 + 15.0)      # team terms +/-4, global (bias + sim bias) +/-15
    assert margin == pytest.approx(4.0 + 1.5)
    assert b.applied_shift(None, "BOS", "NYK") == (0.0, 0.0)


def test_fit_backs_out_the_file_in_effect_so_it_always_sees_the_uncalibrated_model(tmp_path, regular):
    days = [f"2025-11-{d:02d}" for d in range(1, 13)]
    for i, day in enumerate(days):
        # Uncalibrated raw is always 215; real totals are 230. From 11-06 a file (+10 global) was in effect, so the
        # recorded raw reads 225 -- the fit must still see 215 and recover a +15 bias, not +5.
        recorded = 225.0 if day >= "2025-11-06" else 215.0
        _sim(tmp_path, day, "BOS", "NYK", recorded)
        _sim(tmp_path, day, "LAL", "GSW", recorded)
        _recon(tmp_path, day, [("BOS", "NYK", 115, 115), ("LAL", "GSW", 115, 115)])
    (tmp_path / "calibration_totals_2025-11-05.json").write_text(json.dumps({"global": {"game_total_bias": 10.0}, "team": {}}), encoding="utf-8")
    terms = b.build(tmp_path, "2025-11-13")
    assert terms["global"]["game_total_bias"] == pytest.approx(15.0)
    assert terms["meta"]["n_season"] == 24


def test_preseason_sims_never_feed_it_and_seed_applies_under_eight_games(tmp_path, regular, monkeypatch):
    for day in ("2025-10-10", "2025-10-12"):                      # preseason: ignored
        _sim(tmp_path, day, "BOS", "NYK", 200.0)
        _recon(tmp_path, day, [("BOS", "NYK", 120, 120)])
    _sim(tmp_path, "2025-10-21", "BOS", "NYK", 215.0)             # 1 regular-season game < 8
    _recon(tmp_path, "2025-10-21", [("BOS", "NYK", 115, 115)])
    monkeypatch.setattr(b, "SEED_GAME_TOTAL_BIAS", None)
    assert b.build(tmp_path, "2025-10-22") == {}
    monkeypatch.setattr(b, "SEED_GAME_TOTAL_BIAS", 12.5)
    terms = b.build(tmp_path, "2025-10-22")
    assert terms["global"]["game_total_bias"] == 12.5 and terms["meta"]["window"] == "seed" and terms["team"] == {}
    assert terms["meta"]["n_season"] == 1                          # the preseason games were not counted


def test_main_writes_the_anchor_file_atomically_and_respects_exists(tmp_path, regular):
    for day in [f"2025-11-{d:02d}" for d in range(1, 6)]:
        for h, a in (("BOS", "NYK"), ("LAL", "GSW")):
            _sim(tmp_path, day, h, a, 215.0)
        _recon(tmp_path, day, [("BOS", "NYK", 115, 115), ("LAL", "GSW", 115, 115)])
    assert b.main(["--date", "2025-11-06", "--processed-root", str(tmp_path)]) == 0
    out = tmp_path / "calibration_totals_2025-11-05.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["global"]["game_total_bias"] == pytest.approx(15.0) and data["meta"]["anchor"] == "2025-11-05"
    assert not list(tmp_path.glob("*.tmp"))
    out.write_text(json.dumps({"global": {"game_total_bias": 1.0}}), encoding="utf-8")
    b.main(["--date", "2025-11-06", "--processed-root", str(tmp_path)])            # exists: untouched
    assert json.loads(out.read_text(encoding="utf-8"))["global"]["game_total_bias"] == 1.0
