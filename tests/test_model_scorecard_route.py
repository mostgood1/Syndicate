"""The model scorecard routes read files the cron published; they compute nothing."""

from __future__ import annotations

import json

import pytest
from flask import Flask

from syndicate.blueprints import model_scorecard as route


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    app = Flask(__name__)
    app.register_blueprint(route.model_scorecard_bp)
    return app.test_client(), tmp_path


def _publish(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


def test_nothing_published_is_a_404_that_names_the_path(client):
    http, _root = client
    response = http.get("/api/model-scorecard")
    assert response.status_code == 404 and response.get_json()["path"] == route.LATEST


def test_latest_and_dated_scorecards_are_served_as_published(client):
    http, root = client
    _publish(root, route.LATEST, {"today_central": "2026-09-17", "windows": {}})
    _publish(root, "reports/model_scorecard/model_scorecard_20260917.json", {"today_central": "2026-09-17", "x": 1})
    _publish(root, "reports/model_scorecard/model_scorecard_20260917.md", "# Model scorecard 2026-09-17\n")
    assert http.get("/api/model-scorecard").get_json()["today_central"] == "2026-09-17"
    assert http.get("/api/model-scorecard/2026-09-17").get_json()["x"] == 1
    assert http.get("/api/model-scorecard/17-09-2026").status_code == 400
    page = http.get("/model-scorecard")
    assert page.status_code == 200 and page.data.decode().startswith("# Model scorecard")


def test_the_overlay_route_reports_the_file_and_the_scorer_state(client):
    http, root = client
    _publish(root, "reports/model_scorecard/measured_bucket_skill_overlay.json",
             {"source": "model_scorecard/1", "generated_at": "2026-09-17T13:00:00Z", "expires_at": "2000-01-01T00:00:00Z",
              "buckets": {}})
    body = http.get("/api/model-scorecard/overlay").get_json()
    assert body["file_status"] == 200 and body["valid"] is False and body["validation"] == "expired"
    assert "scorer_in_this_process" in body and body["switch_enabled"] is True
