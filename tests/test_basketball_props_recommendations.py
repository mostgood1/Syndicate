from __future__ import annotations

import ast
import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.basketball_props_recommendations import OUTPUT_COLUMNS
from syndicate.features.shared.basketball_props_recommendations import export_props_recommendations_local


class BasketballPropsRecommendationsTests(unittest.TestCase):
    def test_export_props_recommendations_local_builds_top_play_metadata(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_name,team,pred_reb,pred_pts,pred_ast\n"
                "Jane Doe,HTM,5.0,12.0,3.0\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "player_name,team,stat,side,line,price,edge,ev,bookmaker\n"
                "Jane Doe,HTM,reb,OVER,4.5,-110,0.05,0.08,draftkings\n"
                "Jane Doe,HTM,reb,OVER,4.5,-108,0.04,0.06,fanduel\n"
                "Jane Doe,HTM,reb,OVER,4.5,-107,0.03,0.05,betmgm\n",
                encoding="utf-8",
            )

            rows, out_path = export_props_recommendations_local(processed_root=processed_root, date_str=date_str)

            self.assertEqual(rows, 1)
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                written = list(reader)

        self.assertEqual(reader.fieldnames, OUTPUT_COLUMNS)
        self.assertEqual(len(written), 1)
        row = written[0]
        top_play = ast.literal_eval(row["top_play"])
        reasons = ast.literal_eval(row["top_play_reasons"])
        model = ast.literal_eval(row["model"])
        self.assertEqual(top_play["market"], "reb")
        self.assertEqual(top_play["side"], "OVER")
        self.assertIn("model 5.0 vs line 4.5 (+0.5)", row["top_play_explain"])
        self.assertIn("EV 8.0%", reasons)
        self.assertIn("Consensus: 3 books aligned", reasons)
        self.assertIn("Best line available", reasons)
        self.assertEqual(float(row["top_play_baseline"]), 5.0)
        self.assertEqual(float(row["top_play_consensus"]), 0.5)
        self.assertEqual(float(row["top_play_line_adv"]), 1.0)
        self.assertEqual(model["reb"], 5.0)
        self.assertEqual(model["pr"], 17.0)

    def test_export_props_recommendations_local_supports_model_only_rows(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_name,team,pred_pts,pred_reb,pred_ast\n"
                "Jane Doe,HTM,12.0,5.0,3.0\n",
                encoding="utf-8",
            )

            rows, out_path = export_props_recommendations_local(processed_root=processed_root, date_str=date_str)

            self.assertEqual(rows, 1)
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                written = list(reader)

        row = written[0]
        self.assertEqual(ast.literal_eval(row["plays"]), [])
        self.assertEqual(ast.literal_eval(row["sim_ladders"]), [])
        self.assertEqual(row["top_play"], "")
        self.assertEqual(float(ast.literal_eval(row["model"])["pa"]), 15.0)


if __name__ == "__main__":
    unittest.main()