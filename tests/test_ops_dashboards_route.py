"""`/ops/dashboards` shows the three prebuilt dashboards behind the portfolio sign-in, and only reads files."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from syndicate.app import app
from syndicate.blueprints import ops_dashboards as route


def _write(root, folder, body):
    page = root / "reports" / folder / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    return page


@pytest.fixture()
def open_http(tmp_path, monkeypatch):
    """Sign-in off (a dev machine)."""
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route.auth, "auth_mode", lambda: "off")
    return app.test_client(), tmp_path


@pytest.fixture()
def gated(tmp_path, monkeypatch):
    """Sign-in required with credentials configured; the test decides who is signed in."""
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route.auth, "auth_mode", lambda: "required")
    monkeypatch.setattr(route.auth, "credentials", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(route.auth, "request_has_admin_token", lambda request, config=None: False)
    user = {"name": None}
    monkeypatch.setattr(route.auth, "current_user", lambda request: user["name"])
    return app.test_client(), tmp_path, user


def test_routes_are_registered():
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/ops/dashboards" in rules
    assert "/ops/dashboards/<key>" in rules


def test_hub_has_one_tab_and_one_frame_per_dashboard(open_http):
    client, _root = open_http
    resp = client.get("/ops/dashboards")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    body = resp.get_data(as_text=True)
    for key, (label, _folder, _cadence) in route.DASHBOARDS.items():
        assert f'id="tab-{key}" href="#{key}">{label}</a>' in body
        assert f'data-src="/ops/dashboards/{key}"' in body
    assert set(route.DASHBOARDS) == {"engine", "portfolio", "rail"}
    assert "private, no-store" in resp.headers.get("Cache-Control", "")


@pytest.mark.parametrize("key,folder", [("engine", "engine_watch"), ("portfolio", "portfolio_watch"),
                                        ("rail", "rail_watch")])
def test_each_frame_serves_its_builder_file_byte_for_byte(open_http, key, folder):
    client, root = open_http
    body = f"<!doctype html><title>{folder}</title><p>built 10:15 AM · é</p>"
    _write(root, folder, body)
    resp = client.get(f"/ops/dashboards/{key}")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert resp.get_data(as_text=True) == body


def test_a_missing_file_is_that_tab_only(open_http):
    client, root = open_http
    _write(root, "engine_watch", "engine")
    _write(root, "rail_watch", "rail")
    missing = client.get("/ops/dashboards/portfolio")
    assert missing.status_code == 404
    assert "Portfolio Watch has not been built yet" in missing.get_data(as_text=True)
    assert client.get("/ops/dashboards/engine").get_data(as_text=True) == "engine"
    assert client.get("/ops/dashboards/rail").get_data(as_text=True) == "rail"
    assert client.get("/ops/dashboards").status_code == 200


def test_reads_the_newest_file_each_request(open_http):
    client, root = open_http
    page = _write(root, "rail_watch", "one")
    assert client.get("/ops/dashboards/rail").get_data(as_text=True) == "one"
    page.write_text("two", encoding="utf-8")
    assert client.get("/ops/dashboards/rail").get_data(as_text=True) == "two"


def test_unknown_dashboard_is_404_and_reads_nothing(open_http, monkeypatch):
    client, _root = open_http
    monkeypatch.setattr(route, "_page_path", lambda key: pytest.fail("no file may be read"))
    assert client.get("/ops/dashboards/secrets").status_code == 404


@pytest.mark.parametrize("path", ["/ops/dashboards", "/ops/dashboards/portfolio"])
def test_signed_out_is_sent_to_the_portfolio_login_and_back(gated, path):
    client, root, _user = gated
    _write(root, "portfolio_watch", "orders and P&L")
    resp = client.get(path)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/portfolio/login?next={path}")
    assert "orders and P&L" not in resp.get_data(as_text=True)


def test_signed_in_sees_the_pages(gated):
    client, root, user = gated
    user["name"] = "owner"
    _write(root, "portfolio_watch", "orders and P&L")
    assert client.get("/ops/dashboards").status_code == 200
    assert client.get("/ops/dashboards/portfolio").get_data(as_text=True) == "orders and P&L"


def test_admin_token_passes(gated, monkeypatch):
    client, root, _user = gated
    monkeypatch.setattr(route.auth, "request_has_admin_token", lambda request, config=None: True)
    _write(root, "engine_watch", "engine")
    assert client.get("/ops/dashboards/engine").get_data(as_text=True) == "engine"


def test_no_credentials_configured_locks_with_503(gated, monkeypatch):
    client, root, _user = gated
    monkeypatch.setattr(route.auth, "credentials", lambda: SimpleNamespace(configured=False))
    _write(root, "portfolio_watch", "orders and P&L")
    resp = client.get("/ops/dashboards/portfolio")
    assert resp.status_code == 503
    assert "orders and P&L" not in resp.get_data(as_text=True)


def test_the_login_page_accepts_the_hub_as_its_return_target():
    assert route.auth.safe_next("/ops/dashboards") == "/ops/dashboards"
