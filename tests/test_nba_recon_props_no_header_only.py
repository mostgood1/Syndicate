"""NBA recon_props is never written, or reused, without data rows.

Found 2026-10-01: `recon_props_2026-06-13.csv` (the NBA Finals) was header-only.
`_build_local_recon_props_artifact` wrote the header whenever
`boxscores_<date>.csv` was missing and returned the path as built, and
`_export_recon_props_artifact` then reused that empty file as "already there"
on every later run, so it was never rebuilt. The live-prop audit graded
nothing for those days. The WNBA twin already had both guards.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.refresh_nba_oddsapi_props import _build_local_recon_props_artifact
from scripts.refresh_nba_oddsapi_props import _export_recon_props_artifact

_DATE = "2026-06-13"
_BOX_HEADER = "game_id,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,FG3M"
_RECON_HEADER = "game_id,player_id,player_name,team_abbr,pts,reb,ast,threes,stl,blk,tov,pr,pa,ra,pra"


class NbaReconPropsNoHeaderOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source_root = Path(tmp.name)
        self.processed = self.source_root / "data" / "processed"
        self.processed.mkdir(parents=True)
        self.recon = self.processed / f"recon_props_{_DATE}.csv"

    def _write_box(self, *rows: str) -> None:
        (self.processed / f"boxscores_{_DATE}.csv").write_text("\n".join([_BOX_HEADER, *rows]) + "\n", encoding="utf-8")

    def _recon_rows(self) -> list[dict[str, str]]:
        with self.recon.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _export(self) -> str | None:
        return _export_recon_props_artifact(source_root=self.source_root, date_str=_DATE, processed_root=self.processed)

    # --- builder ---------------------------------------------------------

    def test_missing_boxscores_writes_nothing(self) -> None:
        self.assertEqual(_build_local_recon_props_artifact(processed_root=self.processed, date_str=_DATE), (0, None))
        self.assertFalse(self.recon.exists())

    def test_header_only_boxscores_write_nothing(self) -> None:
        self._write_box()
        self.assertEqual(_build_local_recon_props_artifact(processed_root=self.processed, date_str=_DATE), (0, None))
        self.assertFalse(self.recon.exists())

    def test_real_boxscores_still_build(self) -> None:
        self._write_box("401859967,SAS,1,Victor Wembanyama,38,31,12,4,1,5,3,2")
        count, path = _build_local_recon_props_artifact(processed_root=self.processed, date_str=_DATE)
        self.assertEqual((count, path), (1, self.recon))
        self.assertEqual(self._recon_rows()[0]["pra"], "47")

    # --- export ----------------------------------------------------------

    def test_an_existing_header_only_recon_is_rebuilt_once_boxscores_exist(self) -> None:
        self.recon.write_text(_RECON_HEADER + "\n", encoding="utf-8")
        self._write_box("401859967,SAS,1,Victor Wembanyama,38,31,12,4,1,5,3,2")
        self.assertEqual(self._export(), str(self.recon))
        self.assertEqual([row["player_name"] for row in self._recon_rows()], ["Victor Wembanyama"])

    def test_an_existing_header_only_recon_without_boxscores_is_not_reported_as_built(self) -> None:
        self.recon.write_text(_RECON_HEADER + "\n", encoding="utf-8")
        self.assertIsNone(self._export())
        # Left as found: this fix stops creating and accepting such files, it
        # does not delete what is already on a disk.
        self.assertEqual(self.recon.read_text(encoding="utf-8"), _RECON_HEADER + "\n")

    def test_an_existing_recon_with_rows_is_reused_untouched(self) -> None:
        original = _RECON_HEADER + "\n401859967,1,Victor Wembanyama,SAS,31,12,4,2,1,5,3,43,35,16,47\n"
        self.recon.write_text(original, encoding="utf-8")
        self._write_box("401859967,SAS,1,Victor Wembanyama,38,99,99,99,1,5,3,2")
        self.assertEqual(self._export(), str(self.recon))
        self.assertEqual(self.recon.read_text(encoding="utf-8"), original)

    def test_no_inputs_at_all_exports_nothing_and_writes_nothing(self) -> None:
        self.assertIsNone(self._export())
        self.assertFalse(self.recon.exists())


if __name__ == "__main__":
    unittest.main()
