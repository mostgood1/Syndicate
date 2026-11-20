"""`/rail-watch` serves the file the SyndicateRailWatch task renders onto the data root, and nothing else."""
from __future__ import annotations

import pytest

from syndicate.app import app
from syndicate.blueprints import rail_watch as route


@pytest.fixture()
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    return app.test_client(), tmp_path


def test_route_is_registered():
    assert any(rule.rule == "/rail-watch" for rule in app.url_map.iter_rules())


def test_serves_the_rendered_file_byte_for_byte(http):
    client, root = http
    page = root / "reports" / "rail_watch" / "index.html"
    page.parent.mkdir(parents=True)
    body = "<!doctype html><title>Rail Watch</title><p>slate 2026-11-20 · updated 10:23 AM</p>"
    page.write_text(body, encoding="utf-8")
    resp = client.get("/rail-watch")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert resp.get_data(as_text=True) == body
    assert resp.headers.get("Cache-Control") == "no-store"


def test_missing_file_is_a_404_page_not_a_build(http, monkeypatch):
    client, _root = http
    resp = client.get("/rail-watch")
    assert resp.status_code == 404
    assert resp.mimetype == "text/html"
    assert "has not been rendered yet" in resp.get_data(as_text=True)


def test_reads_the_newest_file_each_request(http):
    client, root = http
    page = root / "reports" / "rail_watch" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("one", encoding="utf-8")
    assert client.get("/rail-watch").get_data(as_text=True) == "one"
    page.write_text("two", encoding="utf-8")
    assert client.get("/rail-watch").get_data(as_text=True) == "two"
