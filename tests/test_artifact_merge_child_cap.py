"""A CEILING on concurrent artifact-merge subprocesses (`#632`).

WHY THIS EXISTS. `#630` moved the odds_history merge out of the gunicorn worker
and into a child process, which fixed the arena ratchet it was measured to
cause. Nothing, however, bounded HOW MANY children could run at once: the spawn
appended to `_PENDING_MERGE_CHILDREN` and no caller ever read that list's
length. Concurrency was therefore set by the publish arrival rate.

Measured on the live 2 GB web service, 2026-09-03, sampling `/api/ops/memory`
every 1.5 s while any child was alive:

    peak 19 concurrent children holding 334.6 MB
    a different burst: 365.9 MB across only 6 children
    children alive 34% of the wall clock
    unreclaimable: idle 840.4 MB -> burst max 1,053.4 MB  (+213 MB)

The excursion is transient — the children return their memory — so this is NOT
the anon ratchet `#632` is chasing. It is what converts a high baseline into a
kill: `#632` records anon peaking at 1,823.8 MB, and 1,823.8 + 213 = 2,037 MB
against a 2,048 MB limit.

THE TWO CEILINGS. A count alone does not bound memory: per-child cost varied
~10x in the same measurement (19 children / 334.6 MB against 6 / 365.9 MB), so
four small shards and four large ones are the same count and a quarter of a
gigabyte apart. The second ceiling is on INPUT BYTES in flight, which is known
before the spawn and which `#630` measured as a ~3.13x predictor of peak.

WHAT A REFUSAL MUST NOT DO, and each of these is a test below:
  * it must not stage the incoming file (the caller still owns that temp path),
  * it must not touch the target (that is `#630`'s clobber),
  * it must not fall through to the plain replace,
  * and it must never starve the first child on size alone.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints import ops
from syndicate.features.shared import artifact_merge as am

TOKEN = "test-admin-token"
ODDS_HISTORY = "mlb_source/tracking/odds_history/2026-09-01.json"
EARLY = "2026-09-01T18:00:00+00:00"
LATE = "2026-09-01T19:00:00+00:00"


def _doc(markets: dict, updated_at: str) -> dict:
    return {"schema_version": 1, "sport": "soccer", "shard_key": "2026-09-05",
            "date": "2026-09-01", "updated_at": updated_at, "history_limit": 20,
            "markets": markets}


def _entry(stamp: str, line: float) -> dict:
    return {"history": [{"stamp": stamp, "line": line}], "is_live": False,
            "last_line": line, "previous_line": line, "last_odds": line}


class _Running:
    """A child that never finishes, so it holds a slot."""

    def __init__(self, nbytes: int = 0) -> None:
        # The attribute name is written out rather than read from the module, so
        # that WITHOUT the ceiling these tests fail on their own assertions --
        # "a spawn happened that should have been refused" -- instead of dying
        # on a missing constant. A test that can only fail by AttributeError
        # proves the symbol exists, not that the behaviour is right.
        self._syndicate_merge_input_bytes = nbytes

    def poll(self):
        return None


class _Done:
    def poll(self):
        return 0


class MergeChildCapTests(unittest.TestCase):

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._ops = patch.object(ops, "data_root", return_value=self.root)
        self._am = patch.object(am, "data_root", return_value=self.root)
        self._ops.start()
        self._am.start()
        self.target = self.root / ODDS_HISTORY
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text(json.dumps(_doc({"mine": _entry(EARLY, 1.0)}, EARLY)),
                               encoding="utf-8")
        ops._PENDING_MERGE_CHILDREN.clear()

    def tearDown(self) -> None:
        ops._PENDING_MERGE_CHILDREN.clear()
        self._ops.stop()
        self._am.stop()
        self._tmp.cleanup()

    def _incoming(self) -> Path:
        path = self.root / "incoming.json"
        path.write_text(json.dumps(_doc({"theirs": _entry(LATE, 2.0)}, LATE)),
                        encoding="utf-8")
        return path

    def _fill(self, n: int, nbytes: int = 0) -> None:
        ops._PENDING_MERGE_CHILDREN.extend(_Running(nbytes) for _ in range(n))

    # -- reachability first: the ceiling must be OFF as well as ON ----------

    def test_BELOW_the_ceiling_a_spawn_still_happens(self) -> None:
        """The `off != on` half. A cap that refused everything would pass every
        refusal test below and be a total outage."""
        self._fill(ops._merge_child_cap() - 1)
        with patch("subprocess.Popen", return_value=_Running()):
            result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                               self.target, self._incoming())
        self.assertTrue(result["spawned"])
        self.assertNotIn("at_capacity", result)

    def test_AT_the_count_ceiling_the_spawn_is_refused(self) -> None:
        self._fill(ops._merge_child_cap())
        with patch("subprocess.Popen") as popen:
            result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                               self.target, self._incoming())
        self.assertTrue(result["at_capacity"])
        self.assertEqual(result["reason"], "count")
        self.assertFalse(result["spawned"])
        self.assertEqual(popen.call_count, 0, "no child may be started")

    # -- what a refusal must NOT do ----------------------------------------

    def test_a_refusal_does_NOT_stage_the_incoming_file(self) -> None:
        """The ceiling is checked BEFORE staging. If it staged and then refused,
        the caller's temp path would vanish under it and the next `os.replace`
        would turn a clean 503 into a 500."""
        incoming = self._incoming()
        self._fill(ops._merge_child_cap())
        with patch("subprocess.Popen"):
            ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history", self.target, incoming)
        self.assertTrue(incoming.exists(), "the caller still owns its temp file")
        self.assertEqual(list(self.target.parent.glob("*.staged")), [])

    def test_a_refusal_leaves_the_TARGET_untouched(self) -> None:
        """Stale by one publish is the pre-merge behaviour. A clobber is not."""
        before = self.target.read_bytes()
        self._fill(ops._merge_child_cap())
        with patch("subprocess.Popen"):
            ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                      self.target, self._incoming())
        self.assertEqual(self.target.read_bytes(), before)

    def test_reaping_a_finished_child_FREES_a_slot(self) -> None:
        """Otherwise the first burst would wedge the ceiling shut forever."""
        self._fill(ops._merge_child_cap() - 1)
        ops._PENDING_MERGE_CHILDREN.append(_Done())
        with patch("subprocess.Popen", return_value=_Running()):
            result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                               self.target, self._incoming())
        self.assertTrue(result["spawned"], "the dead child's slot must be reusable")
        self.assertEqual(result["reaped"], 1)

    # -- the byte ceiling ---------------------------------------------------

    def test_the_INPUT_BYTES_ceiling_refuses_below_the_count_ceiling(self) -> None:
        """A count cap does not bound memory: per-child cost varied ~10x."""
        big = int(ops._merge_inflight_input_mb_cap() * 1024 * 1024)
        self._fill(1, nbytes=big)
        with patch("subprocess.Popen") as popen:
            result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                               self.target, self._incoming())
        self.assertTrue(result["at_capacity"])
        self.assertEqual(result["reason"], "inflight_mb")
        self.assertEqual(popen.call_count, 0)
        self.assertLess(1, ops._merge_child_cap(),
                        "this case must sit strictly below the COUNT ceiling")

    def test_the_FIRST_child_is_never_refused_on_size_alone(self) -> None:
        """Otherwise an artifact larger than the whole budget could never merge
        at all -- permanent starvation of the biggest shard, the one whose rows
        matter most."""
        huge = self.root / "huge.json"
        huge.write_text(" " * int(ops._merge_inflight_input_mb_cap() * 1024 * 1024 * 2),
                        encoding="utf-8")
        with patch("subprocess.Popen", return_value=_Running()):
            result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history", self.target, huge)
        self.assertTrue(result["spawned"], "nothing in flight -- it must be allowed")

    # -- configuration ------------------------------------------------------

    def test_an_unparseable_cap_falls_back_to_the_DEFAULT_not_to_unlimited(self) -> None:
        """Mapping a bad value onto the permissive branch would silently restore
        the uncapped behaviour this exists to remove."""
        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_MERGE_CHILD_CAP": "lots"}, clear=False):
            self.assertEqual(ops._merge_child_cap(), ops._MERGE_CHILD_CAP_DEFAULT)
        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_MERGE_INFLIGHT_MB": ""}, clear=False):
            self.assertEqual(ops._merge_inflight_input_mb_cap(),
                             ops._MERGE_INFLIGHT_INPUT_MB_DEFAULT)

    def test_a_non_positive_cap_DISABLES_the_ceiling(self) -> None:
        """The documented escape hatch, so the ceiling can be turned off in
        production without a deploy if it is ever the wrong call."""
        self._fill(50)
        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_MERGE_CHILD_CAP": "0",
                                     "SYNDICATE_ARTIFACT_MERGE_INFLIGHT_MB": "0"}, clear=False):
            with patch("subprocess.Popen", return_value=_Running()):
                result = ops._spawn_artifact_merge(ODDS_HISTORY, "odds_history",
                                                   self.target, self._incoming())
        self.assertTrue(result["spawned"])

    def test_inflight_bytes_ignores_a_handle_carrying_no_size(self) -> None:
        """Older handles and test doubles contribute 0 rather than raising --
        the accounting must never be able to break the reaper."""
        ops._PENDING_MERGE_CHILDREN.append(_Done())      # no size attribute
        self.assertEqual(ops._merge_inflight_input_bytes(), 0)

    # -- the endpoint contract ---------------------------------------------

    def test_the_ENDPOINT_answers_503_and_does_not_replace_the_target(self) -> None:
        """503 is load-bearing. It is NOT in `artifact_publisher`'s
        `_PUBLISH_STREAM_UNSUPPORTED_STATUSES` ({400,404,405,415}), so it does
        not trip the fall-back-to-JSON branch that would resend the same
        artifact as an envelope and parse it whole in THIS process."""
        before = self.target.read_bytes()
        self._fill(ops._merge_child_cap())
        with patch("subprocess.Popen") as popen, \
             patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                data=json.dumps(_doc({"theirs": _entry(LATE, 2.0)}, LATE)).encode("utf-8"),
                content_type="application/octet-stream",
                headers={"Authorization": f"Bearer {TOKEN}",
                         "X-Artifact-Path": ODDS_HISTORY,
                         "X-Artifact-Publisher": "refresh-worker"},
            )
        self.assertEqual(response.status_code, 503)
        body = response.get_json()
        self.assertEqual(body["merge"], "at_capacity")
        self.assertFalse(body["ok"])
        self.assertEqual(popen.call_count, 0)
        self.assertEqual(self.target.read_bytes(), before,
                         "a refusal must never replace the target")

    def test_the_endpoint_still_defers_normally_when_there_is_room(self) -> None:
        """Pairs with the case above: proves the 503 is the CEILING talking and
        not the endpoint being broken."""
        with patch("subprocess.Popen", return_value=_Running()), \
             patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                data=json.dumps(_doc({"theirs": _entry(LATE, 2.0)}, LATE)).encode("utf-8"),
                content_type="application/octet-stream",
                headers={"Authorization": f"Bearer {TOKEN}",
                         "X-Artifact-Path": ODDS_HISTORY,
                         "X-Artifact-Publisher": "refresh-worker"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["merge"], "deferred")


if __name__ == "__main__":
    unittest.main()
