from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb import live_lens


class MlbLiveLensSnapshotReaderTests(unittest.TestCase):
    def test_read_latest_live_lens_snapshot_uses_keyvalue_aware_reader(self) -> None:
        # Regression: the background live_lens_loop writes snapshots via
        # refresh_state_store.write_json_file(), which goes to the shared
        # keyvalue store when SYNDICATE_REFRESH_STATE_BACKEND=keyvalue. The
        # read side must use the matching keyvalue-aware read_json_file(),
        # not a plain local-filesystem read, or the loop's writes are
        # invisible to whichever service serves the request.
        snapshot = {"date": "2026-07-13", "games": []}
        with patch.object(live_lens, "read_json_file", return_value=snapshot) as mocked_read:
            result = live_lens.read_latest_live_lens_snapshot()

        self.assertEqual(result, snapshot)
        mocked_read.assert_called_once_with(live_lens.live_lens_snapshot_path())


if __name__ == "__main__":
    unittest.main()
