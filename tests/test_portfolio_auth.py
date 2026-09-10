"""The portfolio sign-in. `[user request 2026-09-10, lane portfolio-login-multibook]`

The property that matters most is the one that fails SILENTLY if it breaks: on
Render, a portfolio with no credentials configured must be LOCKED (503), never
open. An open page looks exactly like a working login until somebody who should
not be there reads it.

Every request here goes through the REAL app (`syndicate.app.app`), so the gate
is proven reachable -- installed, ordered ahead of the handlers, and matching
the real routes -- not merely correct in isolation. `CLAUDE.md`: a
reachability test (`off != on`) before correctness tests.
"""

from __future__ import annotations

import html
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.security import generate_password_hash

from syndicate.app import app as flask_app
from syndicate.blueprints import intelligence as intelligence_bp
from syndicate.features.shared import portfolio_auth, portfolio_books

_ENV_KEYS = (
    "SYNDICATE_PORTFOLIO_USERNAME",
    "SYNDICATE_PORTFOLIO_PASSWORD",
    "SYNDICATE_PORTFOLIO_PASSWORD_HASH",
    "SYNDICATE_PORTFOLIO_SESSION_SECRET",
    "SYNDICATE_PORTFOLIO_SESSION_DAYS",
    "SYNDICATE_PORTFOLIO_AUTH",
    "RENDER",
    "RENDER_EXTERNAL_URL",
    "RENDER_SERVICE_ID",
    "ADMIN_TOKEN",
    "SYNDICATE_ADMIN_TOKEN",
)
USER, PASSWORD = "owner", "correct horse battery"

# Every JSON endpoint under /api/portfolio that exists today.
GATED_API = (
    "/api/portfolio/live",
    "/api/portfolio/paper",
    "/api/portfolio/summary",
    "/api/portfolio/settings",
    "/api/portfolio/limits",
    "/api/portfolio/plan",
    "/api/portfolio/books",
    "/api/portfolio/books/manual",
)
GATED_PAGES = ("/portfolio", "/portfolio/paper", "/portfolio/live", "/portfolio/books/manual", "/portfolio/books")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(flask_app.config, "ADMIN_TOKEN", "")
    monkeypatch.setattr(portfolio_books, "store_path", lambda: tmp_path / "portfolio_books.json")
    portfolio_auth.reset_throttle()
    yield monkeypatch
    portfolio_auth.reset_throttle()


@pytest.fixture
def creds(env):
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD", PASSWORD)
    return env


@pytest.fixture
def handlers_must_not_run(monkeypatch):
    """Make the heavy handlers explode, so a 401/302/503 proves the gate
    answered BEFORE them -- not that a handler happened to fail the same way."""

    def boom(*_args, **_kwargs):
        raise AssertionError("a gated handler ran for a signed-out request")

    monkeypatch.setattr(intelligence_bp, "_live_portfolio_payload", boom)
    monkeypatch.setattr(intelligence_bp, "_paper_portfolio_payload", boom)
    monkeypatch.setattr(intelligence_bp, "build_portfolio_summary", boom)
    monkeypatch.setattr(intelligence_bp, "record_prediction", boom)
    monkeypatch.setattr(portfolio_books, "build_book_view", boom)
    monkeypatch.setattr(portfolio_books, "add_bet", boom)


@pytest.fixture
def client():
    return flask_app.test_client()


def _login(client, username=USER, password=PASSWORD, next_="/portfolio"):
    return client.post("/portfolio/login", data={"username": username, "password": password, "next": next_})


# ---------------------------------------------------------------- reachability


def test_the_gate_is_live_on_the_real_app_off_differs_from_on(env, client):
    """The same request, answered differently by the one thing that should
    change it. If this passes with both statuses equal, the gate is inert."""
    assert portfolio_auth.auth_mode() == "off"
    off = client.get("/api/portfolio/books")
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD", PASSWORD)
    on = client.get("/api/portfolio/books")
    assert (off.status_code, on.status_code) == (200, 401)


def test_the_gate_answers_before_the_handler(creds, client, handlers_must_not_run):
    for path in GATED_API:
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.get_json()["error"] == "portfolio_login_required", path


# ---------------------------------------------------------------- signed out


def test_a_signed_out_page_goes_to_sign_in_and_remembers_where_it_was(creds, client, handlers_must_not_run):
    response = client.get("/portfolio?date=2026-09-01&venue=kalshi")
    assert response.status_code == 302
    location = urlsplit(response.headers["Location"])
    assert location.path == "/portfolio/login"
    assert parse_qs(location.query)["next"] == ["/portfolio?date=2026-09-01&venue=kalshi"]
    for path in GATED_PAGES:
        assert client.get(path).status_code == 302, path


def test_signed_out_writes_are_refused_and_change_nothing(creds, client, handlers_must_not_run, monkeypatch, tmp_path):
    from syndicate.features.shared import portfolio_settings

    def boom(*_args, **_kwargs):
        raise AssertionError("settings were written by a signed-out request")

    monkeypatch.setattr(portfolio_settings, "update_settings", boom)
    response = client.post("/portfolio/settings", data={"bankroll_units": "5"})
    assert response.status_code == 303
    assert urlsplit(response.headers["Location"]).path == "/portfolio/login"

    assert client.post("/api/portfolio/bets", json={"sport": "nfl", "market": "ml", "selection": "x", "stake": 5}).status_code == 401

    response = client.post("/portfolio/books/manual/bets", data={"sportsbook": "DK"})
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["Location"]).query)["next"] == ["/portfolio/books/manual"]
    assert not (tmp_path / "portfolio_books.json").exists()


def test_other_pages_are_never_gated(creds, client):
    assert client.get("/").status_code == 200
    assert portfolio_auth.is_gated_path("/portfolio")
    assert portfolio_auth.is_gated_path("/portfolio/")
    assert portfolio_auth.is_gated_path("/api/portfolio/live")
    assert not portfolio_auth.is_gated_path("/portfolios")
    assert not portfolio_auth.is_gated_path("/market-board")
    assert not portfolio_auth.is_gated_path("/api/ops/version")
    assert not portfolio_auth.is_gated_path(portfolio_auth.LOGIN_PATH)
    assert not portfolio_auth.is_gated_path(portfolio_auth.LOGOUT_PATH)


# ---------------------------------------------------------------- signing in


def test_a_wrong_password_or_username_is_refused_without_a_cookie(creds, client):
    for username, password in ((USER, "nope"), ("someone", PASSWORD), ("", "")):
        response = _login(client, username, password)
        assert response.status_code == 401
        # The message is a template variable, so Jinja escapes its apostrophe.
        assert "don't match" in html.unescape(response.get_data(as_text=True))
        assert portfolio_auth.COOKIE_NAME not in response.headers.get("Set-Cookie", "")
    assert client.get("/api/portfolio/books").status_code == 401


def test_the_right_password_sets_a_hardened_cookie_that_opens_everything(creds, client):
    response = _login(client, next_="/portfolio/books/manual")
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/portfolio/books/manual")
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{portfolio_auth.COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert PASSWORD not in cookie
    assert client.get("/api/portfolio/books").status_code == 200
    assert client.get("/portfolio/books/manual").status_code == 200


def test_signed_in_pages_say_who_and_offer_sign_out(creds, client):
    _login(client)
    page = client.get("/portfolio/books/manual").get_data(as_text=True)
    assert f"Signed in as <strong>{USER}</strong>" in page
    assert 'action="/portfolio/logout"' in page
    # And a signed-out page (gate off) offers no sign-out at all.
    creds.delenv("SYNDICATE_PORTFOLIO_USERNAME")
    creds.delenv("SYNDICATE_PORTFOLIO_PASSWORD")
    assert 'action="/portfolio/logout"' not in flask_app.test_client().get("/portfolio/books/manual").get_data(as_text=True)


def test_signed_in_responses_are_not_cacheable(creds, client):
    _login(client)
    assert client.get("/api/portfolio/books").headers["Cache-Control"] == "private, no-store"


def test_a_password_hash_works_and_the_plaintext_is_never_needed(env, client):
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD_HASH", generate_password_hash("hashed secret"))
    assert _login(client, password="hashed secret").status_code == 303
    assert client.get("/api/portfolio/books").status_code == 200
    assert _login(flask_app.test_client(), password="wrong").status_code == 401


def test_changing_the_password_signs_every_browser_out(creds, client):
    _login(client)
    assert client.get("/api/portfolio/books").status_code == 200
    creds.setenv("SYNDICATE_PORTFOLIO_PASSWORD", "a new password")
    assert client.get("/api/portfolio/books").status_code == 401


def test_a_forged_or_expired_cookie_is_refused(creds, client, monkeypatch):
    client.set_cookie(portfolio_auth.COOKIE_NAME, "not-a-real-token")
    assert client.get("/api/portfolio/books").status_code == 401

    other = flask_app.test_client()
    _login(other)
    monkeypatch.setattr(portfolio_auth, "session_days", lambda: -1)
    assert other.get("/api/portfolio/books").status_code == 401


def test_sign_out_clears_the_cookie(creds, client):
    _login(client)
    response = client.post("/portfolio/logout")
    assert response.status_code == 303
    assert urlsplit(response.headers["Location"]).path == "/portfolio/login"
    assert client.get("/api/portfolio/books").status_code == 401


def test_repeated_failures_are_throttled_even_for_the_right_password(creds, client):
    for _ in range(portfolio_auth.MAX_FAILURES_PER_CLIENT):
        assert _login(client, password="guess").status_code == 401
    response = _login(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(portfolio_auth.FAILURE_WINDOW_SECONDS)


def test_sign_in_cannot_redirect_off_the_site(creds, client):
    for hostile in ("https://evil.example/portfolio", "//evil.example/portfolio", "/\\evil.example", "/api/portfolio/live", "/portfolio/login"):
        assert portfolio_auth.safe_next(hostile) == "/portfolio", hostile
    assert portfolio_auth.safe_next("/market-board?date=2026-09-10") == "/market-board?date=2026-09-10"
    assert portfolio_auth.safe_next("/portfolio/books/fanduel") == "/portfolio/books/fanduel"
    response = _login(client, next_="https://evil.example/")
    assert response.headers["Location"].endswith("/portfolio")
    assert "evil" not in response.headers["Location"]


# ---------------------------------------------------------------- tooling


def test_the_ops_admin_token_passes_without_a_cookie(creds, client):
    creds.setenv("ADMIN_TOKEN", "ops-token")
    assert client.get("/api/portfolio/books", headers={"X-Admin-Token": "ops-token"}).status_code == 200
    assert client.get("/api/portfolio/books?admin_token=ops-token").status_code == 200
    assert client.get("/api/portfolio/books", headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_no_admin_token_configured_means_no_token_passes(creds, client):
    assert client.get("/api/portfolio/books", headers={"X-Admin-Token": ""}).status_code == 401


# ---------------------------------------------------------------- absent is not off


def test_on_render_with_no_credentials_the_portfolio_is_locked_not_open(env, client, handlers_must_not_run):
    env.setenv("RENDER", "true")
    assert portfolio_auth.auth_mode() == "required"
    page = client.get("/portfolio")
    assert page.status_code == 503
    assert "isn't set up" in page.get_data(as_text=True)
    api = client.get("/api/portfolio/books")
    assert api.status_code == 503
    assert api.get_json()["error"] == "portfolio_login_not_configured"
    assert client.post("/portfolio/login", data={"username": "", "password": ""}).status_code == 503


def test_on_render_an_unrecognised_mode_still_locks(env, client):
    env.setenv("RENDER", "true")
    env.setenv("SYNDICATE_PORTFOLIO_AUTH", "requierd")
    assert portfolio_auth.auth_mode() == "required"
    assert client.get("/api/portfolio/books").status_code == 503


def test_an_explicit_off_is_honoured_even_on_render(env, client):
    env.setenv("RENDER", "true")
    env.setenv("SYNDICATE_PORTFOLIO_AUTH", "off")
    assert client.get("/api/portfolio/books").status_code == 200


def test_with_the_gate_off_the_sign_in_page_steps_aside(env, client):
    response = client.get("/portfolio/login?next=/portfolio/books/manual")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/portfolio/books/manual")


# ---------------------------------------------------------------- a malformed hash


def test_a_plain_password_in_the_hash_key_locks_loudly_instead_of_failing_every_login(env, client, handlers_must_not_run):
    """Measured on production 2026-09-10: the plain password went into
    SYNDICATE_PORTFOLIO_PASSWORD_HASH, werkzeug answered False to every login
    without raising, and nothing said why -- five `LOGIN_FAILED` and no cause.
    It is a CONFIGURATION error, so it must read as one, and never echo the value."""
    secret = "Plain-Text-Pw1!"
    env.setenv("RENDER", "true")
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD_HASH", secret)
    creds = portfolio_auth.credentials()
    assert creds.problem == "password_hash_not_a_hash"
    assert not creds.configured
    assert portfolio_auth.auth_mode() == "required"

    page = client.get("/portfolio")
    assert page.status_code == 503
    body = html.unescape(page.get_data(as_text=True))
    assert "doesn't hold a password hash" in body
    assert secret not in body
    login = client.post("/portfolio/login", data={"username": USER, "password": secret})
    assert login.status_code == 503
    assert secret not in login.get_data(as_text=True)
    api = client.get("/api/portfolio/books")
    assert (api.status_code, api.get_json()["error"]) == (503, "portfolio_login_not_configured")


def test_a_malformed_hash_locks_off_render_too(env, client):
    """Any credential key present means somebody meant to lock the page. A
    malformed one must not fall through to the off-Render default of OPEN."""
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD_HASH", "not-a-hash")
    assert portfolio_auth.auth_mode() == "required"
    assert client.get("/api/portfolio/books").status_code == 503


@pytest.mark.parametrize("method", ["scrypt", "pbkdf2:sha256", "pbkdf2:sha256:1000"])
def test_real_werkzeug_hashes_are_recognised_and_work(env, client, method):
    env.setenv("SYNDICATE_PORTFOLIO_USERNAME", USER)
    env.setenv("SYNDICATE_PORTFOLIO_PASSWORD_HASH", generate_password_hash("hashed secret", method=method))
    assert portfolio_auth.credentials().problem is None
    assert _login(client, password="hashed secret").status_code == 303
    assert client.get("/api/portfolio/books").status_code == 200
