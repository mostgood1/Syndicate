"""Login for the portfolio pages. `[user request 2026-09-10, lane portfolio-login-multibook]`

WHAT IS GATED. Every `/portfolio` page and every `/api/portfolio/*` endpoint --
the Kalshi/Polymarket live book, paper, the manual books, their JSON, and the
form posts that edit caps and settings. `/portfolio/login` and
`/portfolio/logout` are the only exceptions. Nothing else on the site changes:
the boards, the sport pages and `/api/ops/*` (which has its own token) are
untouched.

WHO GETS IN.
  * a browser holding the signed cookie `/portfolio/login` issues against
    `SYNDICATE_PORTFOLIO_USERNAME` + `SYNDICATE_PORTFOLIO_PASSWORD`, or
    `SYNDICATE_PORTFOLIO_PASSWORD_HASH` (a werkzeug hash, so the plaintext never
    has to sit in the dashboard; the hash wins when both are set);
  * a request carrying the ops `ADMIN_TOKEN`, as `X-Admin-Token` or
    `?admin_token=` -- the same two places `/api/ops/*` reads it -- so scripts
    and verification sessions that read `/api/portfolio/live` keep working
    without a browser.

ABSENT IS NOT OFF. On Render the gate is REQUIRED whether or not credentials
are configured: a web service with none set answers 503 on every gated path
rather than falling open. A missing env var is exactly the "unknown" that
`learnings.md` says must not default permissive, and the failure it prevents is
silent -- an open page looks identical to a working login until somebody who
should not be there reads it. Off Render with no credentials (a laptop, the
test suite) the gate is off: there is nobody to keep out, and ~20 existing test
files drive these routes. `SYNDICATE_PORTFOLIO_AUTH=required|off` overrides
either default; an unrecognised value falls through to the default.

THE COOKIE CARRIES NO PASSWORD. It is an `itsdangerous` timed signature over
the username and a fingerprint of the configured credential, so changing the
password signs every browser out. The signing key is
`SYNDICATE_PORTFOLIO_SESSION_SECRET` when set, else derived from the credential
itself: one env var fewer to forget, and still unguessable by anyone who does
not already hold the password. HttpOnly, and SameSite=Lax -- Lax withholds the
cookie from cross-site POSTs, which is the CSRF protection the settings, limits
and bet forms on these pages rely on.

TWO GUNICORN WORKERS (`WEB_CONCURRENCY=2`). Nothing here is per-process except
the failed-login throttle, which is a speed bump rather than a lockout.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE_NAME = "syndicate_portfolio"
LOGIN_PATH = "/portfolio/login"
LOGOUT_PATH = "/portfolio/logout"
DEFAULT_SESSION_DAYS = 30
FAILURE_WINDOW_SECONDS = 600
MAX_FAILURES_PER_CLIENT = 8
# A ceiling across ALL clients as well, because the client key comes from a
# proxy header a caller can vary -- per-client alone lets one caller rotate it.
MAX_FAILURES_GLOBAL = 40

_SALT = "syndicate-portfolio-auth-v1"
_EXEMPT_PATHS = frozenset({LOGIN_PATH, LOGOUT_PATH})
_GLOBAL_KEY = "*"
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()
_not_configured_reported = False

# What a werkzeug password hash looks like: `<method>$<salt>$<hex>`, the method
# `scrypt[:n:r:p]` or `pbkdf2:<digest>[:iterations]`. ANYTHING ELSE in the HASH
# key is a configuration error -- most likely the plain password pasted into the
# wrong box -- and `check_password_hash` answers False to it for every login,
# without raising and without a word. Measured on production 2026-09-10: exactly
# that, five failed sign-ins and nothing anywhere saying why. So a malformed
# hash is refused AS A MISCONFIGURATION, loudly, instead of as a wrong password.
_WERKZEUG_HASH = re.compile(r"(?:scrypt(?::\d+){0,3}|pbkdf2:[A-Za-z0-9_]+(?::\d+)?)\$[^$\s]+\$[0-9a-f]+")


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _on_render() -> bool:
    # Same predicate as `syndicate.app._is_render_web_dyno`, restated rather
    # than imported because that module imports this one.
    return bool(
        _env("RENDER").lower() in {"1", "true", "yes", "on"}
        or _env("RENDER_EXTERNAL_URL")
        or _env("RENDER_SERVICE_ID")
    )


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    password_hash: str

    @property
    def problem(self) -> str | None:
        """A named configuration error, or None. Names only -- never the value."""
        if self.password_hash and not _WERKZEUG_HASH.fullmatch(self.password_hash):
            return "password_hash_not_a_hash"
        return None

    @property
    def any_set(self) -> bool:
        return bool(self.username or self.password or self.password_hash)

    @property
    def configured(self) -> bool:
        return bool(self.username and (self.password or self.password_hash)) and self.problem is None

    def _material(self) -> str:
        return f"{self.username}\0{self.password_hash or self.password}"

    def fingerprint(self) -> str:
        return hashlib.sha256(("fingerprint\0" + self._material()).encode("utf-8")).hexdigest()[:24]

    def signing_key(self) -> str:
        explicit = _env("SYNDICATE_PORTFOLIO_SESSION_SECRET")
        if explicit:
            return explicit
        return hashlib.sha256(("syndicate-portfolio-session-v1\0" + self._material()).encode("utf-8")).hexdigest()


def credentials() -> Credentials:
    return Credentials(
        username=_env("SYNDICATE_PORTFOLIO_USERNAME"),
        password=_env("SYNDICATE_PORTFOLIO_PASSWORD"),
        password_hash=_env("SYNDICATE_PORTFOLIO_PASSWORD_HASH"),
    )


def auth_mode() -> str:
    """`required` or `off`. Absent means REQUIRED on Render -- see the module docstring."""
    raw = _env("SYNDICATE_PORTFOLIO_AUTH").lower()
    if raw in {"off", "0", "false", "no", "disabled"}:
        return "off"
    if raw in {"required", "on", "1", "true", "yes"}:
        return "required"
    # ANY credential key present means somebody meant to lock this -- a
    # malformed one included, which must lock (503) rather than open.
    return "required" if (_on_render() or credentials().any_set) else "off"


def is_gated_path(path: str) -> bool:
    path = str(path or "")
    if path in _EXEMPT_PATHS:
        return False
    return (
        path == "/portfolio"
        or path.startswith("/portfolio/")
        or path == "/api/portfolio"
        or path.startswith("/api/portfolio/")
    )


def check_credentials(username: Any, password: Any) -> bool:
    creds = credentials()
    if not creds.configured:
        return False
    # Both halves are always evaluated, so a wrong username costs the same time
    # as a wrong password and the response cannot be used to find the username.
    user_ok = hmac.compare_digest(str(username or "").strip().encode("utf-8"), creds.username.encode("utf-8"))
    if creds.password_hash:
        try:
            from werkzeug.security import check_password_hash

            password_ok = bool(check_password_hash(creds.password_hash, str(password or "")))
        except Exception as exc:  # noqa: BLE001
            # Said out loud: a hash the runtime cannot check reads to the user as
            # a wrong password, which is the silent failure this module refuses.
            print(f"[portfolio_auth] PORTFOLIO_AUTH_HASH_CHECK_ERROR type={type(exc).__name__}", flush=True)
            password_ok = False
    else:
        password_ok = hmac.compare_digest(str(password or "").encode("utf-8"), creds.password.encode("utf-8"))
    return bool(user_ok and password_ok)


def session_days() -> int:
    try:
        days = int(_env("SYNDICATE_PORTFOLIO_SESSION_DAYS") or DEFAULT_SESSION_DAYS)
    except ValueError:
        days = DEFAULT_SESSION_DAYS
    return max(1, min(days, 365))


def _serializer(creds: Credentials) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(creds.signing_key(), salt=_SALT)


def issue_token() -> str:
    creds = credentials()
    return str(_serializer(creds).dumps({"u": creds.username, "f": creds.fingerprint()}))


def token_user(token: Any) -> str | None:
    """The username a cookie proves, or None. Never raises."""
    if not token:
        return None
    creds = credentials()
    if not creds.configured:
        return None
    try:
        data = _serializer(creds).loads(str(token), max_age=session_days() * 86400)
    except BadSignature:  # includes SignatureExpired
        return None
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("u") != creds.username or data.get("f") != creds.fingerprint():
        return None
    return creds.username


def current_user(request: Any) -> str | None:
    return token_user(request.cookies.get(COOKIE_NAME))


def _configured_admin_token(config: Mapping[str, Any] | None) -> str:
    # Same resolution order as `ops._configured_admin_token`.
    configured = (config or {}).get("ADMIN_TOKEN") if config is not None else None
    if configured:
        return str(configured).strip()
    return _env("ADMIN_TOKEN") or _env("SYNDICATE_ADMIN_TOKEN")


def request_has_admin_token(request: Any, config: Mapping[str, Any] | None = None) -> bool:
    configured = _configured_admin_token(config)
    if not configured:
        return False
    # Header or query only. Reading `request.form` here would parse the body of
    # every gated POST before its handler sees it.
    supplied = str(request.headers.get("X-Admin-Token") or request.args.get("admin_token") or "").strip()
    return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8"))


def safe_next(value: Any) -> str:
    """A post-login destination that can only be a page on THIS site.

    Any same-site page is allowed, so the bet slip's "Sign in" link can bring
    the user back to the board they were on. Refused: anything with a scheme or
    host (an open redirect), `//host` and backslash forms that browsers read as
    one, JSON endpoints, and the sign-in pages themselves (a loop).
    """
    target = str(value or "").strip()
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/portfolio"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.path.startswith("/api/") or parts.path in _EXEMPT_PATHS:
        return "/portfolio"
    return target


def client_key(request: Any) -> str:
    # The LAST hop is the one Render's proxy appended; earlier hops are
    # whatever the caller sent.
    forwarded = [part.strip() for part in str(request.headers.get("X-Forwarded-For") or "").split(",") if part.strip()]
    return forwarded[-1] if forwarded else str(getattr(request, "remote_addr", None) or "unknown")


def _recent(key: str, now: float) -> list[float]:
    kept = [stamp for stamp in _failures.get(key, []) if now - stamp < FAILURE_WINDOW_SECONDS]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)
    return kept


def throttled(key: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    with _failures_lock:
        return (
            len(_recent(key, now)) >= MAX_FAILURES_PER_CLIENT
            or len(_recent(_GLOBAL_KEY, now)) >= MAX_FAILURES_GLOBAL
        )


def note_failure(key: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _failures_lock:
        _failures.setdefault(key, []).append(now)
        _failures.setdefault(_GLOBAL_KEY, []).append(now)
        if len(_failures) > 10_000:
            for stale in [k for k in list(_failures) if k != _GLOBAL_KEY]:
                _recent(stale, now)


def clear_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)


def reset_throttle() -> None:
    """Tests only."""
    with _failures_lock:
        _failures.clear()


def set_login_cookie(response: Any, request: Any) -> None:
    secure = bool(getattr(request, "is_secure", False)) or (
        str(request.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"
    )
    response.set_cookie(
        COOKIE_NAME,
        issue_token(),
        max_age=session_days() * 86400,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )


def clear_login_cookie(response: Any) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _report_not_configured(path: str) -> None:
    global _not_configured_reported
    if _not_configured_reported:
        return
    _not_configured_reported = True
    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        "[portfolio_auth] PORTFOLIO_AUTH_NOT_CONFIGURED "
        f"path={path} problem={credentials().problem or 'missing'} -- serving 503 on "
        "every portfolio path. Set SYNDICATE_PORTFOLIO_USERNAME and "
        "SYNDICATE_PORTFOLIO_PASSWORD (or a real SYNDICATE_PORTFOLIO_PASSWORD_HASH) "
        "on this service.",
        flush=True,
    )


def _post_login_target(path: str) -> str:
    # A refused POST cannot be replayed after sign-in, so send the user back to
    # the page the form lived on.
    parts = path.split("/")
    if path.startswith("/portfolio/books/") and len(parts) >= 4 and parts[3]:
        return "/".join(parts[:4])
    return "/portfolio"


def gate(request: Any, config: Mapping[str, Any] | None = None) -> Any:
    """None when the request may proceed, otherwise the response to send instead."""
    if not is_gated_path(request.path) or auth_mode() == "off":
        return None
    if request_has_admin_token(request, config):
        return None

    from flask import jsonify, redirect, render_template

    is_api = request.path.startswith("/api/")
    if not credentials().configured:
        _report_not_configured(request.path)
        if is_api:
            response = jsonify(
                {
                    "ok": False,
                    "error": "portfolio_login_not_configured",
                    "detail": "Portfolio sign-in is required on this server and no credentials are configured.",
                }
            )
            response.status_code = 503
            return response
        return (
            render_template(
                "portfolio_login.html",
                next_target="/portfolio",
                not_configured=True,
                problem=credentials().problem,
                error=None,
            ),
            503,
        )

    if current_user(request):
        return None
    if is_api:
        response = jsonify({"ok": False, "error": "portfolio_login_required", "login_url": LOGIN_PATH})
        response.status_code = 401
        return response
    if request.method in {"GET", "HEAD"}:
        target = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
        return redirect(f"{LOGIN_PATH}?next={quote(target, safe='/')}", code=302)
    return redirect(f"{LOGIN_PATH}?next={quote(_post_login_target(request.path), safe='/')}", code=303)


def install_portfolio_auth(app: Any) -> None:
    """Register the gate on the whole app, so it covers `intelligence.py`'s
    portfolio routes as well as the manual-book blueprint's."""

    @app.before_request
    def _portfolio_login_gate() -> Any:
        from flask import current_app, request

        return gate(request, current_app.config)

    @app.after_request
    def _portfolio_private_cache(response: Any) -> Any:
        from flask import request

        try:
            if is_gated_path(request.path) and auth_mode() == "required":
                # Signed-in pages must not outlive the sign-out in a shared cache
                # or the back button.
                response.headers["Cache-Control"] = "private, no-store"
        except Exception:
            pass
        return response

    # One line per boot, so a deploy can be verified from the log: which mode
    # the gate came up in, and whether it has credentials to check against.
    # Never the username.
    creds = credentials()
    print(
        "[portfolio_auth] PORTFOLIO_AUTH_MODE "
        f"mode={auth_mode()} credentials_configured={creds.configured} "
        f"hash={'yes' if creds.password_hash else 'no'} problem={creds.problem or 'none'} "
        f"on_render={_on_render()}",
        flush=True,
    )


__all__ = [
    "COOKIE_NAME",
    "LOGIN_PATH",
    "LOGOUT_PATH",
    "auth_mode",
    "check_credentials",
    "clear_login_cookie",
    "client_key",
    "credentials",
    "current_user",
    "gate",
    "install_portfolio_auth",
    "is_gated_path",
    "note_failure",
    "request_has_admin_token",
    "safe_next",
    "set_login_cookie",
    "throttled",
    "token_user",
]
