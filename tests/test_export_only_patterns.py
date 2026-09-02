"""`#625`(2): the artifact allowlist is now TWO lists, and the asymmetry is the point.

One list used to gate both directions. `artifact_publisher.py`'s own
`roster_objs` note said so — *"hundreds of large files per date, and this
allowlist drives publishing as well as reading"* — so a family that merely
needed to be READABLE could only be made readable by also making it WRITABLE
and swept.

For most families that is an egress bill. For `raw/statsapi/feed_live` it is a
live defect: `_mlb_feed_live_payload` returns the cached file IF IT EXISTS, so a
`feed_live` file on web's disk freezes that game's state at whenever it was
captured (`#413`; measured 2026-08-13, MIL @ SD read `live / TOP 9` against a
live lens reading `Final`, on a board artifact five minutes old).

**An export-only list that quietly became publishable would look identical from
the read side.** So these tests assert BOTH directions, and they go through the
real Flask routes rather than the predicate alone — the predicate being right is
not the same fact as the right predicate being wired into the right handler.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared.artifact_publisher import (  # noqa: E402
    EXPORT_ONLY_ARTIFACT_PATTERNS,
    HOT_ARTIFACT_PATTERNS,
    is_export_only_artifact_relative_path,
    is_exportable_artifact_relative_path,
    is_hot_artifact_relative_path,
)

# One realistic path per export-only family, taken from paths that are ACTUALLY
# git-tracked in this repo (`git ls-files`), not invented to fit the globs.
EXPORT_ONLY_SAMPLES = (
    "mlb_source/source_artifacts/data/raw/statsapi/feed_live/2026/2026-06-14/822722.json.gz",
    "mlb_source/source_artifacts/data/raw/statsapi/feed_live/2026/2026-06-14/822722.json",
    "mlb_source/tracking/odds_mlb_hitter_props_history_2026-06-10.csv",
    # Reconciliation outputs -- the graded "what actually happened" side of the
    # evaluation chain, and the OUTPUT a `build_mlb_actuals` replay-diff needs
    # to compare against. They were in neither list, so that output was
    # unauditable from outside.
    "mlb_source/reconciliation/props_actuals_2026-06-14.csv",
    "mlb_source/reconciliation/game_results_2026-06-14.json",
)

FEED_LIVE_SAMPLE = EXPORT_ONLY_SAMPLES[0]

# Paths `#625` NAMES as worker-local that are in fact ALREADY exportable. Kept
# as a test rather than a note: if either stops being hot, the mirror silently
# loses a family it has been pulling, and `roster_objs` in particular is hot
# only because fnmatch `*` crosses `/`, which is easy to "tidy up" by accident.
ALREADY_HOT_SAMPLES = (
    # 51 files / 199,281,869 bytes on web, measured 2026-09-02.
    "mlb_source/source_artifacts/data/eval/batches/season_2026_ui_daily_live/sim_vs_actual_2026-06-14.json",
    # Production's real layout: directly under snapshots/<date>/, not roster_objs/.
    # A mirror pull fetched 16 of these from web on 2026-09-02.
    "mlb_source/source_artifacts/data/daily/snapshots/2026-09-01/roster_9_ATH_at_TEX_pk822854_g1.json",
)


@pytest.mark.parametrize("relative_path", ALREADY_HOT_SAMPLES)
def test_families_625_calls_worker_local_are_already_exportable(relative_path: str) -> None:
    assert is_hot_artifact_relative_path(relative_path), (
        "this family is already published and mirrored; `#625`(2)'s premise that it "
        "is worker-local was checked and is false"
    )
    assert is_exportable_artifact_relative_path(relative_path)


@pytest.mark.parametrize("relative_path", EXPORT_ONLY_SAMPLES)
def test_export_only_samples_are_readable_but_not_writable(relative_path: str) -> None:
    assert is_export_only_artifact_relative_path(relative_path), "must match an export-only pattern"
    assert is_exportable_artifact_relative_path(relative_path), "the READ predicate must accept it"
    assert not is_hot_artifact_relative_path(relative_path), (
        "the WRITE predicate must REFUSE it -- if this fails the sweep will start "
        "publishing this family to web"
    )


def test_feed_live_is_never_publishable() -> None:
    """The `#413` regression test. Not a style rule: a `feed_live` file on web's
    disk freezes live game state for every reader of that game."""
    assert not is_hot_artifact_relative_path(FEED_LIVE_SAMPLE)
    assert not any(
        "feed_live" in pattern for pattern in HOT_ARTIFACT_PATTERNS
    ), "no hot pattern may mention feed_live, however it is spelled"


def test_the_two_lists_do_not_overlap() -> None:
    """A path in both lists would be publishable while reading as export-only —
    the exact confusion this split exists to remove."""
    for relative_path in EXPORT_ONLY_SAMPLES:
        assert not (
            is_hot_artifact_relative_path(relative_path)
            and is_export_only_artifact_relative_path(relative_path)
        )


def test_every_export_only_pattern_matches_something_real() -> None:
    """A pattern that matches nothing is inert while reading as correct — the
    defect class `#625` exists to catch. Every pattern must claim a sample."""
    for pattern in EXPORT_ONLY_ARTIFACT_PATTERNS:
        import fnmatch

        # Every pattern must be reachable by at least one real sample, or it
        # is decoration -- the inert-rule class this repo keeps rediscovering.
        matched = any(fnmatch.fnmatch(sample, pattern) for sample in EXPORT_ONLY_SAMPLES)
        assert matched, f"{pattern!r} matches none of the real sample paths"


@pytest.mark.parametrize(
    "relative_path",
    ["/etc/passwd", "../../../etc/passwd", "mlb_source/../../secrets.json", "", "   "],
)
def test_the_read_predicate_still_rejects_traversal(relative_path: str) -> None:
    assert not is_exportable_artifact_relative_path(relative_path)
    assert not is_export_only_artifact_relative_path(relative_path)


def test_the_sweep_never_offers_an_export_only_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sweep is the mechanism that would turn a read-only family into a
    published one without anybody deciding to."""
    from syndicate.features.shared import artifact_publisher

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    target = tmp_path / FEED_LIVE_SAMPLE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"{}")

    offered: list[str] = []
    monkeypatch.setattr(
        artifact_publisher, "publish_hot_artifact", lambda path, **kw: offered.append(str(path)) or True
    )
    artifact_publisher.sweep_changed_hot_artifacts(0.0)
    assert not any("feed_live" in candidate for candidate in offered)


# --------------------------------------------------------------------------
# THROUGH THE REAL ROUTES. The predicate being right and the right predicate
# being wired into the right handler are two different facts.
# --------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("SYNDICATE_BOOTSTRAP_ON_START", "0")
    from syndicate.app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), tmp_path


AUTH = {"X-Admin-Token": "test-token"}


def test_export_serves_an_export_only_path_that_publish_refuses(client) -> None:
    test_client, root = client
    target = root / FEED_LIVE_SAMPLE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"gamePk": 822722}', encoding="utf-8")

    # READ: accepted, and the body comes back.
    response = test_client.get(
        f"/api/ops/artifacts/export?path={FEED_LIVE_SAMPLE}", headers=AUTH
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["count"] == 1
    assert FEED_LIVE_SAMPLE in payload["artifacts"]

    # WRITE: refused, with 403 specifically -- 403 and 404 are different facts
    # and collapsing them is how "not permitted" becomes "absent".
    response = test_client.post(
        "/api/ops/artifacts/publish",
        json={"relative_path": FEED_LIVE_SAMPLE, "content": "{}"},
        headers=AUTH,
    )
    assert response.status_code == 403, response.get_data(as_text=True)


def test_stream_serves_an_export_only_path(client) -> None:
    test_client, root = client
    sample = EXPORT_ONLY_SAMPLES[1]
    target = root / sample
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"roster": []}', encoding="utf-8")

    response = test_client.get(f"/api/ops/artifacts/stream?path={sample}", headers=AUTH)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"roster" in response.get_data()


def test_names_only_inventory_discovers_export_only_artifacts(client) -> None:
    """The inventory walk is the ONLY way a mirror learns these exist. Before
    this change it could not see them, and 403-vs-absent is indistinguishable
    to the caller."""
    test_client, root = client
    for sample in EXPORT_ONLY_SAMPLES:
        target = root / sample
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    response = test_client.get("/api/ops/artifacts/export?names_only=1", headers=AUTH)
    assert response.status_code == 200
    listed = set(response.get_json()["artifacts"])
    for sample in EXPORT_ONLY_SAMPLES:
        assert sample in listed, f"{sample} not discoverable in the inventory"


def test_unpatterned_body_export_still_excludes_export_only_families(client) -> None:
    """THE BACKUP WORKFLOW'S GUARANTEE. It calls export with no pattern and a
    24MB budget; adding thousands of roster_objs and feed_live files to that
    candidate set would silently change which artifacts fit under the budget,
    in a caller that never asked for them."""
    test_client, root = client
    for sample in EXPORT_ONLY_SAMPLES:
        target = root / sample
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    response = test_client.get("/api/ops/artifacts/export", headers=AUTH)
    assert response.status_code == 200
    returned = set(response.get_json()["artifacts"])
    for sample in EXPORT_ONLY_SAMPLES:
        assert sample not in returned, "an un-patterned export must behave exactly as before"

    # ...but naming a pattern opts in.
    response = test_client.get(
        f"/api/ops/artifacts/export?pattern={EXPORT_ONLY_SAMPLES[0]}", headers=AUTH
    )
    assert response.status_code == 200
    assert EXPORT_ONLY_SAMPLES[0] in response.get_json()["artifacts"]


def test_binary_artifact_gets_an_actionable_415_not_a_500(client) -> None:
    """`export?path=` returns a JSON envelope of DECODED TEXT, so a binary
    artifact cannot cross it. Making the gzipped `feed_live` family readable
    reached this branch for the first time and it answered HTTP 500 in
    production -- which reads as "the server is broken" when the truth is
    "wrong transport, and there is a right one"."""
    test_client, root = client
    target = root / FEED_LIVE_SAMPLE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff")  # gzip magic

    response = test_client.get(f"/api/ops/artifacts/export?path={FEED_LIVE_SAMPLE}", headers=AUTH)
    assert response.status_code == 415, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["transport"] == "/api/ops/artifacts/stream", "the error must name the right transport"

    # ...and that transport serves it.
    response = test_client.get(f"/api/ops/artifacts/stream?path={FEED_LIVE_SAMPLE}", headers=AUTH)
    assert response.status_code == 200
    assert response.get_data().startswith(b"\x1f\x8b"), "bytes, not decoded text"
