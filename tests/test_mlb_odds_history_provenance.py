"""#207: odds_history provenance diagnostic, written on the ODDS WORKER's disk.

odds_history is written to three paths, and the third
(reports/odds_control_plane/odds_history/) sits outside data_root() by
construction -- `is_hot_artifact_relative_path` can never match it, so it never
crosses services. Web's ops endpoints read web's disk and therefore cannot see
the copy the writing service keeps.

That gap is what made #205/#206 ambiguous: props appeared to carry no
`bookmaker` dimension and closing lines appeared captured on only 2% of markets,
but both were observed on the SYNCED copy. This diagnostic runs where the odds
are actually written, so the two can finally be compared -- deciding whether
those are capture defects (forward-only fixes, prop verdicts unrecoverable) or
publish defects (retroactive, prop verdicts recoverable and CLV measurable now).
"""

from __future__ import annotations

import json

import pytest

from scripts.fetch_mlb_oddsapi_local import diagnose_odds_history_provenance
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path


def _history(markets):
    return {"markets": markets}


def _key(event, market, book=None):
    parts = [f"event_id={event}", f"home_team=A", f"away_team=B", f"market={market}"]
    if book:
        parts.append(f"bookmaker={book}")
    return "|".join(parts)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the diagnostic at a fake odds_history and capture what it writes."""
    import scripts.fetch_mlb_oddsapi_local as mod
    from syndicate.features.shared import odds_control_plane, refresh_state_store

    hist = tmp_path / "odds_history.json"
    written = {}

    monkeypatch.setattr(odds_control_plane, "odds_history_paths_for_sport", lambda s, k: [hist])
    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr(refresh_state_store, "write_json_file", lambda p, payload: written.update({"path": p, "payload": payload}))
    # The fixture owns this too: publishing is a real network call otherwise, and
    # leaving it unpatched made a later test order-dependent.
    from syndicate.features.shared import artifact_publisher

    published: list = []
    monkeypatch.setattr(artifact_publisher, "publish_hot_artifact", lambda p, **k: (published.append(p), True)[1])
    written["published"] = published
    return hist, written


class TestAllowlist:
    def test_provenance_artifact_can_cross_services(self):
        # The whole point: web must be able to serve what the odds worker wrote.
        assert is_hot_artifact_relative_path("reports/mlb_odds_diag/odds_history_provenance_2026-08-05.json")

    def test_the_worker_only_odds_history_copy_still_cannot(self):
        # Documents the constraint that forced this diagnostic to exist.
        assert not is_hot_artifact_relative_path("reports/odds_control_plane/odds_history/mlb/2026-08-05.json")


class TestProvenanceSummary:
    def test_counts_bookmaker_coverage(self, wired):
        hist, written = wired
        hist.write_text(json.dumps(_history({
            _key("e1", "h2h", "fanduel"): {},
            _key("e1", "h2h", "draftkings"): {},
            _key("e1", "batter_hits"): {},          # prop with NO bookmaker
        })), encoding="utf-8")

        out = diagnose_odds_history_provenance("2026-08-05")
        s = out["freshest_summary"]

        assert s["entries"] == 3
        assert s["with_bookmaker"] == 2
        assert s["without_bookmaker"] == 1
        assert s["distinct_books"] == 2
        assert s["bookmaker_pct"] == pytest.approx(66.67, abs=0.01)

    def test_counts_closing_capture(self, wired):
        hist, written = wired
        hist.write_text(json.dumps(_history({
            _key("e1", "h2h", "fanduel"): {"closing_price": "-120"},
            _key("e2", "h2h", "fanduel"): {"closing_line": 1.5},
            _key("e3", "h2h", "fanduel"): {"closing_price": None, "closing_line": None},
            _key("e4", "h2h", "fanduel"): {},
        })), encoding="utf-8")

        s = diagnose_odds_history_provenance("2026-08-05")["freshest_summary"]

        assert s["with_closing"] == 2
        assert s["closing_pct"] == pytest.approx(50.0)

    def test_writes_to_the_allowlisted_path(self, wired):
        hist, written = wired
        hist.write_text(json.dumps(_history({_key("e1", "h2h", "fanduel"): {}})), encoding="utf-8")

        diagnose_odds_history_provenance("2026-08-05")

        assert written["path"].name == "odds_history_provenance_2026-08-05.json"
        assert written["path"].parent.name == "mlb_odds_diag"

    def test_reports_every_candidate_path_not_just_the_winner(self, wired):
        # Provenance is the point -- a reader must see which copies exist at all.
        hist, _ = wired
        hist.write_text(json.dumps(_history({_key("e1", "h2h", "fanduel"): {}})), encoding="utf-8")

        out = diagnose_odds_history_provenance("2026-08-05")

        assert len(out["candidate_paths"]) == 1
        assert out["candidate_paths"][0]["exists"] is True
        assert out["candidate_paths"][0]["market_count"] == 1

    def test_missing_history_is_reported_not_raised(self, wired):
        out = diagnose_odds_history_provenance("2026-08-05")
        assert out["candidate_paths"][0]["exists"] is False
        assert out["freshest_summary"] == {}

    def test_corrupt_history_is_reported_not_raised(self, wired):
        hist, _ = wired
        hist.write_text("{not json", encoding="utf-8")
        out = diagnose_odds_history_provenance("2026-08-05")
        assert "error" in out["candidate_paths"][0]

    def test_never_raises_even_if_everything_is_broken(self, monkeypatch):
        # A diagnostic must not be able to fail an odds refresh.
        from syndicate.features.shared import odds_control_plane

        def boom(*a, **k):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(odds_control_plane, "odds_history_paths_for_sport", boom)
        assert diagnose_odds_history_provenance("2026-08-05") is None


class TestCrossServicePublish:
    """Allowlisting only PERMITS a push -- something must actually make it.

    Verified live 2026-08-05: the sibling `live_events_coverage_*.json`
    diagnostic is allowlisted but absent from web for every date back to
    2026-07-20. It has never been readable off the writing service since it
    shipped, because `write_json_file` writes locally/keyvalue and nothing
    published it. Control: `intelligence_state.json`, which IS explicitly
    published, serves fine through the same endpoint. This artifact exists to be
    read from web, so it must publish explicitly.
    """

    def test_publishes_after_writing(self, wired):
        hist, written = wired
        hist.write_text(json.dumps(_history({_key("e1", "h2h", "fanduel"): {}})), encoding="utf-8")

        diagnose_odds_history_provenance("2026-08-05")

        published = written["published"]
        assert len(published) == 1
        assert published[0].name == "odds_history_provenance_2026-08-05.json"

    def test_publish_failure_does_not_break_the_refresh(self, wired, monkeypatch):
        hist, _ = wired
        hist.write_text(json.dumps(_history({_key("e1", "h2h", "fanduel"): {}})), encoding="utf-8")
        from syndicate.features.shared import artifact_publisher

        def boom(*a, **k):
            raise RuntimeError("web unreachable")

        monkeypatch.setattr(artifact_publisher, "publish_hot_artifact", boom)

        # Still returns the payload -- a diagnostic must never fail an odds refresh.
        assert diagnose_odds_history_provenance("2026-08-05") is not None
