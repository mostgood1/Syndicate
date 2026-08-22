"""The portfolio ledger has to cross the web/refresh-worker service boundary.

`#502`. The bet slip (POST /api/portfolio/bets) writes the ledger on the WEB
service; the only thing that settles it -- `_launch_autorun_reconciliation` in
scripts/run_refresh_worker.py, via `record_result` -- runs on REFRESH-WORKER.
Both resolve `data_root()` to `/opt/render/project/data` because all three
services set the same `SYNDICATE_DATA_ROOT`, but Render gives each service its
own disk, so that one path string named two different files. Reconciliation
settled an empty ledger while web served the real one as pending forever.

WHAT THESE TESTS MODEL, AND WHY IT IS SHAPED THIS WAY. The keyvalue key is the
resolved absolute path (`_state_key_for_path`), so in production the two
services agree on the key precisely BECAUSE they agree on the path string. A
test that pointed two "services" at two different temp dirs would therefore
generate two different keys and fail for a reason production does not have --
it would be testing the harness. So the boundary is modelled the way production
actually presents it: one constant data-root path, one shared keyvalue store,
and a local disk whose contents differ between the two readers.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features import prediction_ledger


class FakeKeyValueClient:
    """Stands in for the one Redis instance shared by all three services.

    `ex` is accepted because `write_text_file` passes a TTL on every keyvalue
    write; a fake without it raises TypeError inside
    `_execute_keyvalue_operation`, which is not retried but re-raised.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)


class PredictionLedgerServiceBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_root = Path(self._tmp.name) / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.client = FakeKeyValueClient()

        env = patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_DATA_ROOT": str(self.data_root),
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

        client_patch = patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client",
            return_value=self.client,
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    @property
    def ledger_path(self) -> Path:
        # Resolved rather than assumed: tests/conftest.py has a suite-wide
        # autouse fixture that repoints `_default_ledger_path` at a per-test
        # tmp dir, so `SYNDICATE_DATA_ROOT` does not decide this under pytest.
        # Asking the module keeps the file honest under BOTH runners -- CI runs
        # `python -m unittest`, which never loads conftest.py at all.
        return prediction_ledger._default_ledger_path()

    def _drop_local_disk_copy(self) -> None:
        """Model the OTHER service: same path, its own disk, no such file."""
        if self.ledger_path.exists():
            self.ledger_path.unlink()

    def _log_a_bet(self) -> str:
        recorded = prediction_ledger.record_prediction(
            sport="mlb",
            market="moneyline",
            selection="NYY",
            stake=100.0,
            odds=-120,
        )
        return str(recorded["id"])

    # ------------------------------------------------------------------
    # The regression itself
    # ------------------------------------------------------------------
    def test_a_bet_logged_on_web_is_visible_to_the_worker(self) -> None:
        """FAILS on the pre-`#502` code: the worker saw an empty ledger."""
        prediction_id = self._log_a_bet()

        self._drop_local_disk_copy()

        visible = prediction_ledger.load_all_predictions()
        self.assertEqual(
            [str(item.get("id")) for item in visible],
            [prediction_id],
            "the worker must see the bet the web service logged",
        )

    def test_the_worker_settles_the_same_ledger_the_web_service_serves(self) -> None:
        """End-to-end shape of the reported symptom: everything stays pending.

        Web logs a bet -> worker (whose own disk has no ledger) settles it ->
        web reads the settled result back.
        """
        prediction_id = self._log_a_bet()
        web_disk_copy = self.ledger_path.read_text(encoding="utf-8")

        # --- refresh-worker: its disk carries no ledger of its own ---
        self._drop_local_disk_copy()
        prediction_ledger.record_result(
            prediction_id=prediction_id,
            outcome="win",
            pnl=83.33,
        )

        # --- back on web, whose disk still holds only the unsettled copy ---
        self.ledger_path.write_text(web_disk_copy, encoding="utf-8")

        served = prediction_ledger.load_all_predictions()
        self.assertEqual(len(served), 1)
        result = served[0].get("result")
        self.assertIsInstance(result, dict, "the position must not still read as pending")
        self.assertEqual(str(result.get("outcome")), "win")

    # ------------------------------------------------------------------
    # The migration hazard: existing bets live on the web disk only
    # ------------------------------------------------------------------
    def test_an_existing_disk_ledger_is_promoted_into_the_shared_store(self) -> None:
        self.ledger_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "predictions": [{"id": "legacy-1", "sport": "mlb", "stake": 50.0}],
                    "results": [],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.client.store, {}, "precondition: nothing shared yet")

        loaded = prediction_ledger.load_all_predictions()
        self.assertEqual([str(item.get("id")) for item in loaded], ["legacy-1"])
        self.assertTrue(self.client.store, "a pre-existing ledger must be promoted, not stranded")

        self._drop_local_disk_copy()
        self.assertEqual(
            [str(item.get("id")) for item in prediction_ledger.load_all_predictions()],
            ["legacy-1"],
            "after promotion the other service must see it too",
        )

    def test_an_empty_ledger_never_shadows_real_bets(self) -> None:
        """The worker ticks constantly; a user opens /portfolio rarely.

        If an empty local ledger could promote, the worker would define the
        shared key first and the user's bets would vanish from the page.
        """
        prediction_id = self._log_a_bet()

        self._drop_local_disk_copy()
        self.ledger_path.write_text(
            json.dumps({"schema_version": 1, "predictions": [], "results": []}),
            encoding="utf-8",
        )

        loaded = prediction_ledger.load_all_predictions()
        self.assertEqual(
            [str(item.get("id")) for item in loaded],
            [prediction_id],
            "an empty ledger must not overwrite the shared one",
        )

    # ------------------------------------------------------------------
    # Durability: Redis here is a 256MB instance measured at 96% with
    # 34,529 LRU-evicted keys, so it cannot be the only copy.
    # ------------------------------------------------------------------
    def test_disk_remains_the_durable_copy(self) -> None:
        prediction_id = self._log_a_bet()

        self.assertTrue(self.ledger_path.exists(), "the bet must also be on disk")
        on_disk = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual([str(item.get("id")) for item in on_disk["predictions"]], [prediction_id])

    def test_the_ledger_survives_an_eviction_of_the_shared_key(self) -> None:
        prediction_id = self._log_a_bet()

        self.client.store.clear()  # LRU eviction

        loaded = prediction_ledger.load_all_predictions()
        self.assertEqual([str(item.get("id")) for item in loaded], [prediction_id])
        self.assertTrue(self.client.store, "the surviving disk copy must be re-promoted")

    def test_a_keyvalue_failure_never_loses_a_bet(self) -> None:
        with patch(
            "syndicate.features.shared.refresh_state_store.write_text_file",
            side_effect=RuntimeError("backend down"),
        ):
            prediction_id = self._log_a_bet()

        on_disk = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual([str(item.get("id")) for item in on_disk["predictions"]], [prediction_id])

    def test_a_backend_read_error_does_not_promote_a_stale_disk_copy(self) -> None:
        """A failed read returns None too. Promoting on one would clobber."""
        self._log_a_bet()
        good_key, good_value = next(iter(self.client.store.items()))

        self.ledger_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "predictions": [{"id": "stale-1", "sport": "mlb", "stake": 1.0}],
                    "results": [],
                }
            ),
            encoding="utf-8",
        )

        with patch(
            "syndicate.features.shared.refresh_state_store.read_text_file_result",
            return_value=(None, False),
        ):
            prediction_ledger.load_all_predictions()

        self.assertEqual(
            self.client.store.get(good_key),
            good_value,
            "a transient read failure must not overwrite the shared ledger",
        )


class PredictionLedgerFilesystemBackendTest(unittest.TestCase):
    """Local dev and CI run the filesystem backend; behaviour must not change."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_root = Path(self._tmp.name) / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)

        env = patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "filesystem",
                "SYNDICATE_DATA_ROOT": str(self.data_root),
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

    def test_round_trips_on_disk_without_touching_the_shared_store(self) -> None:
        with patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client"
        ) as client_factory:
            recorded = prediction_ledger.record_prediction(
                sport="mlb",
                market="moneyline",
                selection="NYY",
                stake=100.0,
                odds=-120,
            )
            loaded = prediction_ledger.load_all_predictions()
            client_factory.assert_not_called()

        self.assertEqual([str(item.get("id")) for item in loaded], [str(recorded["id"])])
        self.assertTrue(prediction_ledger._default_ledger_path().exists())


if __name__ == "__main__":
    unittest.main()
