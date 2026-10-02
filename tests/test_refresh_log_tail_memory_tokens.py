"""A failed step's tail must reach its error line past LIST_MEMORY / DATAFRAME_MEMORY.

29 failed WNBA props-fetch steps on 2026-10-01/02 stored a 1600-char tail made
only of `LIST_MEMORY` lines -- a token `diagnostic_tail` did not know, so it was
kept, and the real error never reached the run artifacts.
"""

from __future__ import annotations

import json
import unittest

from syndicate.features.shared.refresh_log_tail import diagnostic_tail


def _list_memory(i: int) -> str:
    return "LIST_MEMORY " + json.dumps({"length": i, "list_id": 270949081355520 + i,
                                        "name": "refresh_wnba_oddsapi_props.states", "pad": "x" * 200})


def _dataframe_memory(i: int) -> str:
    return "DATAFRAME_MEMORY " + json.dumps({"rows": i, "name": "props", "pad": "y" * 200})


class MemoryTokenTailTests(unittest.TestCase):
    def test_error_line_survives_trailing_list_and_dataframe_dumps(self) -> None:
        stderr = "\n".join(
            ["STEP_START wnba_oddsapi_props_job",
             "requests.exceptions.HTTPError: 422 Client Error: Unprocessable Entity for url: https://api.the-odds-api.com/..."]
            + [_list_memory(i) for i in range(40)]
            + [_dataframe_memory(i) for i in range(20)]
        )
        tail = diagnostic_tail(stderr, limit=1600)
        self.assertIn("HTTPError: 422", tail)
        self.assertNotIn("LIST_MEMORY", tail)
        self.assertNotIn("DATAFRAME_MEMORY", tail)

    def test_unknown_lines_are_still_kept(self) -> None:
        tail = diagnostic_tail("SOME_NEW_MARKER value=1\n" + _list_memory(1), limit=1600)
        self.assertIn("SOME_NEW_MARKER value=1", tail)
        self.assertNotIn("LIST_MEMORY", tail)


if __name__ == "__main__":
    unittest.main()
