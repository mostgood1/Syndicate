"""`#635`: one lock per SERVICE, not per name.

MEASURED 2026-09-02, and every test here is that incident. Lane
`book-quotes-publish-clobber` held `--service web` with a build in flight. I ran
`--service syndicate`, was GRANTED it, preflighted CLEAR, and deployed. Render
cancelled their build 0.6 seconds later. Both claims were valid at once, because
the claim file was keyed on whichever string you typed and `web` and `syndicate`
are two names for `srv-d88ahvrbc2fs73eodu30`.

No `--force`, no `SYNDICATE_DEPLOY_GUARD=off`, and the claim step was run by both
sessions. The lock simply was not a lock.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "deploy-guard.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CLAIM = _load("deploy_claim_alias_under_test", REPO_ROOT / "scripts" / "deploy_claim.py")

# The guard is RUN, never imported: it calls sys.exit(main()) at module scope,
# and `tests/test_deploy_guard.py` already established that executing it with a
# JSON payload on stdin is the interface the harness actually uses.
DEPLOY_CMD = (
    "curl -X POST "
    "https://api.render.com/v1/services/srv-d88ahvrbc2fs73eodu30/deploys"
)


def run_guard(root, lane, session="sess-alias-test"):
    (Path(root) / ".syndicate").mkdir(parents=True, exist_ok=True)
    (Path(root) / ".syndicate" / f".current-lane.{session}").write_text(lane, encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop("SYNDICATE_DEPLOY_GUARD", None)
    payload = {"tool_name": "Bash", "session_id": session,
               "tool_input": {"command": DEPLOY_CMD}}
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env, timeout=60)


class _Dir:
    """Point the claim module at a scratch directory."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)

    def __enter__(self):
        self._prev = CLAIM.CLAIM_DIR
        CLAIM.CLAIM_DIR = self.tmp
        self.tmp.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *a):
        CLAIM.CLAIM_DIR = self._prev
        return False


def _write(directory, name, holder, age_s=0.0, ttl=2700):
    (Path(directory) / f"{name}.json").write_text(json.dumps({
        "service": name, "holder": holder, "token": "t-" + holder,
        "acquired_at": time.time() - age_s, "ttl_seconds": ttl,
    }), encoding="utf-8")


class CanonicalTests(unittest.TestCase):
    def test_web_and_syndicate_are_one_service(self):
        self.assertEqual(CLAIM.canonical("syndicate"), "web")
        self.assertEqual(CLAIM.canonical("web"), "web")

    def test_both_names_resolve_to_the_same_lock_file(self):
        """THE defect. Two files meant two locks on one box."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, _Dir(tmp):
            self.assertEqual(CLAIM._path("syndicate"), CLAIM._path("web"))

    def test_workers_are_not_collapsed_into_web(self):
        for name in ("refresh-worker", "live-odds-worker"):
            self.assertEqual(CLAIM.canonical(name), name)
        self.assertNotEqual(CLAIM.canonical("refresh-worker"), CLAIM.canonical("web"))

    def test_an_unknown_name_maps_to_itself_not_to_web(self):
        """A new service must not silently share another's lock. Unknown must
        not land on some other box's branch."""
        self.assertEqual(CLAIM.canonical("brand-new-service"), "brand-new-service")

    def test_status_PRINTS_one_row_per_box(self):
        """The status output was the PROXIMATE cause: `web HELD` and
        `syndicate free` on consecutive lines read as two services.

        Asserts on what it PRINTS. An earlier version of this test checked the
        CANONICAL_SERVICES constant instead, and a mutation that reverted the
        listing to `SERVICES` sailed straight through it."""
        import argparse
        import io
        import contextlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, _Dir(tmp):
            _write(tmp, "web", "peer-lane")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                CLAIM.cmd_status(argparse.Namespace(service=None))
            out = buf.getvalue()
        rows = [ln for ln in out.splitlines() if ln.strip()]
        self.assertTrue(any("web" in ln and "peer-lane" in ln for ln in rows), out)
        self.assertFalse(any(ln.strip().startswith("syndicate") for ln in rows),
                         "`syndicate` must not print as its own row: " + out)


class CollisionTests(unittest.TestCase):
    """The 2026-09-02 incident, both directions."""

    def test_syndicate_cannot_be_taken_while_web_is_held(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, _Dir(tmp):
            _write(tmp, "web", "peer-lane")
            claim = CLAIM._read("syndicate")
        self.assertIsNotNone(claim, "the alias must SEE the peer's claim")
        self.assertEqual(claim["holder"], "peer-lane")

    def test_web_cannot_be_taken_while_a_legacy_syndicate_claim_is_held(self):
        """Migration. An older copy of this script wrote `syndicate.json`; if
        this fix stopped reading it, upgrading would silently free a held lock
        -- the exact failure it exists to prevent."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, _Dir(tmp):
            _write(tmp, "syndicate", "peer-lane")
            claim = CLAIM._read("web")
        self.assertIsNotNone(claim, "a legacy syndicate.json must still block web")
        self.assertEqual(claim["holder"], "peer-lane")

    def test_an_expired_alias_claim_does_not_block(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, _Dir(tmp):
            _write(tmp, "syndicate", "peer-lane", age_s=99_999, ttl=2700)
            claim = CLAIM._read("web")
            expired = claim is None or CLAIM.age_and_expiry(claim)[1]
        self.assertTrue(expired, "TTL is the real bound; an expired claim frees the box")


class GuardAliasOrderTests(unittest.TestCase):
    """The guard already knew the alias. It returned the FIRST match.

    Run as a subprocess with a payload, which is how the harness runs it.
    """

    def test_a_peers_web_claim_BLOCKS_you_even_when_you_hold_syndicate(self):
        """THE incident, end to end. First-match across aliases could read your
        own `syndicate` claim as permission and let you cancel their build."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            claims = Path(tmp) / ".syndicate" / "deploy_claims"
            claims.mkdir(parents=True)
            # THE ARRANGEMENT THAT DISCRIMINATES. ALIASES iterates
            # ("web", "syndicate"), so putting the peer in `web` blocks under
            # first-match too and proves nothing. The peer must be in the
            # SECOND alias and your own claim in the first.
            _write(claims, "web", "my-lane")
            _write(claims, "syndicate", "peer-lane")
            got = run_guard(tmp, "my-lane")
        self.assertNotEqual(got.returncode, 0, "must BLOCK: a peer holds this box")
        self.assertIn(b"peer-lane", got.stdout + got.stderr,
                      "the block must name the peer, not your own claim")

    def test_your_own_claim_alone_does_not_block(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            claims = Path(tmp) / ".syndicate" / "deploy_claims"
            claims.mkdir(parents=True)
            _write(claims, "web", "my-lane")
            got = run_guard(tmp, "my-lane")
        self.assertIn(b"preflight", (got.stdout + got.stderr).lower(),
                      "with the claim yours, the remaining gate is the preflight")


if __name__ == "__main__":
    unittest.main()
