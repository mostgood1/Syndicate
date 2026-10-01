"""Basketball prop features are fed (lane basketball-player-logs-shot-columns).

`#477` (2026-08-19) built `player_logs.csv` from `boxscores_history.csv` with
only PTS/REB/AST/FG3M/STL/BLK/TOV/MIN. The props feature loader PREFERS
`player_logs.csv`, so from then on 64 of the ONNX model's 140 features were
empty and `PureONNXPredictorLocal.predict` zero-filled them: WNBA pred_pts fell
to ~0.35x the player's 10-game average (Render-built July files: 0.94-1.06).
Measured on the local production fleet, 2026-10-01.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts import build_basketball_player_logs as bpl

SHOT_COLUMNS = ("FGM", "FGA", "FG3A", "FTM", "FTA", "OREB", "DREB", "PF", "PLUS_MINUS")


@pytest.fixture()
def built(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    box = pd.DataFrame([
        {"game_id": "g1", "TEAM_ABBREVIATION": "LVA", "PLAYER_ID": 1, "PLAYER_NAME": "A Wilson", "MIN": 35,
         "PTS": 34, "REB": 10, "AST": 4, "STL": 1, "BLK": 0, "TOV": 1, "OREB": 3, "DREB": 7, "PF": 2,
         "FGM": 13, "FGA": 22, "FG3M": 1, "FG3A": 2, "FTM": 7, "FTA": 8, "PLUS_MINUS": 9, "date": "2026-09-30"},
        {"game_id": "g1", "TEAM_ABBREVIATION": "IND", "PLAYER_ID": 2, "PLAYER_NAME": "C Clark", "MIN": 30,
         "PTS": 21, "REB": 4, "AST": 9, "STL": 2, "BLK": 0, "TOV": 5, "OREB": 0, "DREB": 4, "PF": 3,
         "FGM": 7, "FGA": 18, "FG3M": 3, "FG3A": 10, "FTM": 4, "FTA": 4, "PLUS_MINUS": -9, "date": "2026-09-30"},
    ])
    box.to_csv(processed / "boxscores_history.csv", index=False)
    sched = tmp_path / "schedule_2026.csv"
    pd.DataFrame([{"game_id": "g1", "home_tricode": "LVA", "away_tricode": "IND"}]).to_csv(sched, index=False)
    monkeypatch.setattr(bpl, "_processed_root", lambda league_code: processed)
    monkeypatch.setattr(bpl, "_schedule_path", lambda league_code, season: sched)
    result = bpl.build_player_logs(league_code="wnba", season=2026, min_rows=1)
    assert result.get("ok"), result
    return result["frame"]


def test_player_logs_carry_every_shot_column_the_feature_builder_reads(built):
    missing = [c for c in SHOT_COLUMNS if c not in built.columns]
    assert missing == [], f"player_logs.csv drops {missing}; the props features built from it go unfed"
    wilson = built[built["PLAYER_NAME"] == "A Wilson"].iloc[0]
    assert (wilson["FGA"], wilson["FTA"], wilson["OREB"], wilson["PLUS_MINUS"]) == (22, 8, 3, 9)


def test_the_split_mechanism_columns_are_unchanged(built):
    for column in ("GAME_DATE", "PLAYER_NAME", "TEAM_ABBREVIATION", "MATCHUP", "MIN", "GAME_ID", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV"):
        assert column in built.columns
    assert built[built["PLAYER_NAME"] == "C Clark"].iloc[0]["MATCHUP"] == "IND @ LVA"


def test_a_shot_column_absent_from_the_source_stays_absent_not_zero(tmp_path, monkeypatch):
    # Absence must not be faked as 0 -- a zero FGA is a real, wrong number to a model.
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame([{"game_id": "g1", "TEAM_ABBREVIATION": "LVA", "PLAYER_NAME": "A Wilson", "MIN": 35, "PTS": 34,
                   "date": "2026-09-30"}]).to_csv(processed / "boxscores_history.csv", index=False)
    sched = tmp_path / "s.csv"
    pd.DataFrame([{"game_id": "g1", "home_tricode": "LVA", "away_tricode": "IND"}]).to_csv(sched, index=False)
    monkeypatch.setattr(bpl, "_processed_root", lambda league_code: processed)
    monkeypatch.setattr(bpl, "_schedule_path", lambda league_code, season: sched)
    frame = bpl.build_player_logs(league_code="wnba", season=2026, min_rows=1)["frame"]
    assert "FGA" not in frame.columns or frame["FGA"].isna().all()


# ---------------------------------------------------------------- predictor guard
def test_unfed_features_are_refused_not_zero_filled(monkeypatch, tmp_path):
    """The predictor zero-filled every missing/NaN feature; with 46% unfed it
    published numbers at a third of reality and said nothing. Above the
    threshold it must fall back to the rolling-stat path and say so."""
    from syndicate.features.shared import basketball_props_onnx as onnx

    feats = [f"f{i}" for i in range(10)]

    class FakePredictor:
        feature_columns = feats

        def __init__(self, models_dir):
            pass

        def predict(self, df):
            raise AssertionError("ONNX path used with unfed features")

    fallback_calls = []
    monkeypatch.setattr(onnx, "PureONNXPredictorLocal", FakePredictor)
    monkeypatch.setattr(onnx, "_predict_props_without_models_local",
                        lambda *, features_df, processed_root: fallback_calls.append(1) or features_df)
    frame = pd.DataFrame({**{f: [1.0] for f in feats[:5]}, **{f: [None] for f in feats[5:]}})
    onnx.predict_props_pure_onnx_local(features_df=frame, models_dir=tmp_path, processed_root=tmp_path)
    assert fallback_calls == [1]


def test_fed_features_still_use_the_model(monkeypatch, tmp_path):
    from syndicate.features.shared import basketball_props_onnx as onnx

    feats = [f"f{i}" for i in range(10)]
    used = []

    class FakePredictor:
        feature_columns = feats

        def __init__(self, models_dir):
            pass

        def predict(self, df):
            used.append(1)
            return df

    monkeypatch.setattr(onnx, "PureONNXPredictorLocal", FakePredictor)
    frame = pd.DataFrame({f: [1.0] for f in feats})
    onnx.predict_props_pure_onnx_local(features_df=frame, models_dir=tmp_path, processed_root=tmp_path)
    assert used == [1]
