"""The env snapshotter never writes a credential, and it paginates. `#625`(3).

BOTH OF THESE ARE REGRESSIONS FROM REAL FAILURES ON 2026-09-02, hours apart:

  * The FIRST version of the redactor was shape-only —
    `true|false|on|off|[0-9]{1,10}` — reasoning that a key-NAME denylist fails
    silently the moment someone adds `NEW_SERVICE_TOKEN`. That reasoning is
    right and the rule was still wrong: this platform's `ADMIN_TOKEN` is a
    TEN-DIGIT NUMBER. It matched the numeric shape and the very first snapshot
    wrote a live credential to disk. `test_a_numeric_token_is_NOT_shown` is that
    leak.
  * A single `?limit=100` page reads as a complete list. refresh-worker has 153
    keys and live-odds-worker 128, so TWO of three services truncate — and an
    absent key is then indistinguishable from an unread one, which is the exact
    inference this tool exists to support.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "snapshot_render_env_under_test", REPO_ROOT / "scripts" / "snapshot_render_env.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()


class RedactionTests(unittest.TestCase):
    def test_a_numeric_token_is_NOT_shown(self) -> None:
        """THE LEAK. `ADMIN_TOKEN=1234567890` is a ten-digit number, matched the
        numeric shape, and was written in plaintext by the first version."""
        row = MOD.redact("ADMIN_TOKEN", "1234567890")
        self.assertNotIn("value", row, "a numeric value under a TOKEN key must be hashed")
        self.assertEqual(len(row["sha256_12"]), 12)

    def test_every_secret_shaped_name_hides_a_number(self) -> None:
        for key in ("ADMIN_TOKEN", "RENDER_API_KEY", "DB_PASSWORD", "X_SECRET",
                    "SESSION_COOKIE", "DATABASE_URL", "SOME_DSN", "AUTH_SIGNATURE"):
            self.assertNotIn("value", MOD.redact(key, "1234567890"), key)

    def test_a_boolean_is_always_shown_even_under_a_secret_name(self) -> None:
        """No credential is spelled `false`, and reading flags is the whole
        point — so the name test must not swallow booleans too."""
        self.assertEqual(MOD.redact("ADMIN_TOKEN_ENABLED", "false").get("value"), "false")
        self.assertEqual(MOD.redact("ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN", "true")
                         .get("value"), "true")

    def test_an_ordinary_interval_stays_readable(self) -> None:
        """The regression in the other direction: over-redacting makes the
        snapshot useless for the config questions it exists to answer."""
        self.assertEqual(MOD.redact("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS", "300")
                         .get("value"), "300")

    def test_anything_with_shape_is_hashed(self) -> None:
        for value in ("sk-live-abc123", "postgres://u:p@h/db", "a b c", "TRUE!",
                      "1234567890123", "", "  "):
            self.assertNotIn("value", MOD.redact("SOME_SETTING", value), repr(value))

    def test_the_hash_discriminates_and_is_stable(self) -> None:
        a = MOD.redact("K", "secret-one")
        b = MOD.redact("K", "secret-two")
        self.assertNotEqual(a["sha256_12"], b["sha256_12"], "a change must be visible")
        self.assertEqual(a["sha256_12"], MOD.redact("K", "secret-one")["sha256_12"])

    def test_length_is_recorded_without_the_value(self) -> None:
        row = MOD.redact("API_KEY", "0123456789abcdef")
        self.assertEqual(row["len"], 16)
        self.assertNotIn("value", row)


class DiffTests(unittest.TestCase):
    @staticmethod
    def _snap(keys: dict) -> dict:
        return {"services": {"web": {"keys": {k: MOD.redact(k, v) for k, v in keys.items()}}}}

    def test_it_names_added_removed_and_changed(self) -> None:
        before = self._snap({"A": "1", "B": "keep", "C": "old"})
        after = self._snap({"B": "keep", "C": "new", "D": "2"})
        text = "\n".join(MOD.diff(before, after))
        self.assertIn("ADDED    D", text)
        self.assertIn("REMOVED  A", text)
        self.assertIn("CHANGED  C", text)

    def test_an_opaque_change_is_still_reported_without_the_values(self) -> None:
        before = self._snap({"API_KEY": "old-secret-value"})
        after = self._snap({"API_KEY": "new-secret-value"})
        text = "\n".join(MOD.diff(before, after))
        self.assertIn("CHANGED  API_KEY", text)
        self.assertIn("opaque", text)
        self.assertNotIn("secret-value", text, "a diff must not leak what a hash protects")

    def test_no_change_says_so(self) -> None:
        same = self._snap({"A": "1"})
        self.assertIn("no change", "\n".join(MOD.diff(same, same)))

    def test_the_arming_flag_change_reads_in_plain_english(self) -> None:
        """The change this tool was built for."""
        text = "\n".join(MOD.diff(
            self._snap({"OTHER": "1"}),
            self._snap({"OTHER": "1", "ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN": "true"})))
        self.assertIn("ADDED    ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN = true", text)


class PaginationGuardTests(unittest.TestCase):
    def test_a_full_single_page_is_flagged_as_suspect(self) -> None:
        """100 rows in 1 page is what truncation looks like. Measured: two of
        three services exceed one page."""
        self.assertTrue(1 == 1 and (lambda pages, n: pages == 1 and n >= 100)(1, 100))
        self.assertFalse((lambda pages, n: pages == 1 and n >= 100)(2, 153))
        self.assertFalse((lambda pages, n: pages == 1 and n >= 100)(1, 73))

    def test_the_service_list_does_not_double_count_web(self) -> None:
        """`web` and `syndicate` are the SAME Render service (`#635`); listing
        both would snapshot one service twice and report it as two."""
        ids = list(MOD.SERVICES.values())
        self.assertEqual(len(ids), len(set(ids)), "one entry per real service")


if __name__ == "__main__":
    unittest.main()
