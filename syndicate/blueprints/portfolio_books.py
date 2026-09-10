"""Portfolio sign-in, and the manual portfolios. `[user request 2026-09-10, lane portfolio-login-multibook]`

The gate itself is `portfolio_auth.install_portfolio_auth`, installed on the
app in `create_app` so it covers `intelligence.py`'s portfolio routes as well as
these. This blueprint holds the page the gate sends people to, the manual
books (`syndicate/features/shared/portfolio_books.py` says what they are and
why their bets are not in the prediction ledger), and the context processor
that gives every portfolio page its dropdown.

Every write is a plain form POST answered by a 303, matching the rest of
`/portfolio`: the page is server-rendered, and the outcome rides back on the
query string (`?msg=` / `?error=`) so a refusal shows on the page instead of
being swallowed by the redirect.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request

from syndicate.features.shared import portfolio_auth as auth
from syndicate.features.shared import portfolio_books as books

portfolio_books_bp = Blueprint("portfolio_books", __name__)

_NOTICES = {
    "added": "Bet added.",
    "settled": "Bet settled.",
    "reopened": "Bet reopened.",
    "deleted": "Bet deleted.",
    "created": "Portfolio created.",
    "renamed": "Portfolio renamed.",
    "book_deleted": "Portfolio deleted.",
}


def _active_portfolio_id(path: str) -> str | None:
    if path.startswith("/portfolio/books/"):
        return path[len("/portfolio/books/"):].split("/", 1)[0] or None
    if path.startswith("/portfolio/paper"):
        return "paper"
    if path == "/portfolio" or path.startswith("/portfolio/"):
        return "live"
    return None


@portfolio_books_bp.app_context_processor
def _portfolio_chrome() -> dict[str, Any]:
    """The dropdown and the signed-in user, for portfolio pages only -- this
    runs on every template render in the app, so it returns early elsewhere."""
    try:
        path = request.path
    except RuntimeError:  # rendered outside a request
        return {}
    if not auth.is_gated_path(path) and path != auth.LOGIN_PATH:
        return {}
    chrome: dict[str, Any] = {"portfolio_auth": {"mode": auth.auth_mode(), "user": auth.current_user(request)}}
    if path != auth.LOGIN_PATH:
        chrome["portfolio_nav"] = books.portfolio_nav(_active_portfolio_id(path))
    return chrome


def _no_store(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    return response


def _book_url(book_id: str, **params: Any) -> str:
    query = urlencode({key: value for key, value in params.items() if value})
    return f"/portfolio/books/{quote(book_id)}" + (f"?{query}" if query else "")


def _back(book_id: str, **params: Any) -> Any:
    return redirect(_book_url(book_id, **params), code=303)


def _first_error(exc: books.InputError) -> str:
    return next(iter(exc.errors.values()), "That didn't work.")


# ---------------------------------------------------------------- sign-in


@portfolio_books_bp.route("/portfolio/login", methods=["GET", "POST"])
def portfolio_login():
    next_target = auth.safe_next(request.values.get("next"))
    if auth.auth_mode() == "off":
        return redirect(next_target, code=303 if request.method == "POST" else 302)
    if not auth.credentials().configured:
        return (
            render_template(
                "portfolio_login.html",
                next_target=next_target,
                not_configured=True,
                problem=auth.credentials().problem,
                error=None,
            ),
            503,
        )
    if request.method == "GET":
        if auth.current_user(request):
            return redirect(next_target, code=302)
        return render_template("portfolio_login.html", next_target=next_target, not_configured=False, error=None)

    key = auth.client_key(request)
    if auth.throttled(key):
        print("[portfolio_auth] LOGIN_THROTTLED", flush=True)
        response = make_response(
            render_template(
                "portfolio_login.html",
                next_target=next_target,
                not_configured=False,
                error="Too many attempts. Wait ten minutes and try again.",
            ),
            429,
        )
        response.headers["Retry-After"] = str(auth.FAILURE_WINDOW_SECONDS)
        return response
    if not auth.check_credentials(request.form.get("username"), request.form.get("password")):
        auth.note_failure(key)
        # Never log the attempted username: a password typed into the wrong box
        # would land in Render's logs.
        print("[portfolio_auth] LOGIN_FAILED", flush=True)
        return (
            render_template(
                "portfolio_login.html",
                next_target=next_target,
                not_configured=False,
                error="That username and password don't match.",
                username=request.form.get("username") or "",
            ),
            401,
        )
    auth.clear_failures(key)
    print("[portfolio_auth] LOGIN_OK", flush=True)
    response = redirect(next_target, code=303)
    auth.set_login_cookie(response, request)
    return response


@portfolio_books_bp.route("/portfolio/logout", methods=["GET", "POST"])
def portfolio_logout():
    response = redirect(auth.LOGIN_PATH, code=303)
    auth.clear_login_cookie(response)
    return response


# ---------------------------------------------------------------- books


def _render_book(book_id: str, *, status: int = 200, form_values=None, form_errors=None, error=None):
    try:
        view = books.build_book_view(book_id)
    except books.BookNotFound:
        abort(404)
    notice = _NOTICES.get(str(request.args.get("msg") or ""))
    return (
        render_template(
            "portfolio_book.html",
            view=view,
            options=books.form_options(),
            form_values=form_values or {},
            form_errors=form_errors or {},
            form_open=bool(form_errors),
            notice=notice,
            error=error or request.args.get("error"),
        ),
        status,
    )


@portfolio_books_bp.get("/portfolio/books")
def portfolio_books_index():
    return redirect(_book_url(books.DEFAULT_BOOK_ID), code=302)


@portfolio_books_bp.post("/portfolio/books")
def portfolio_book_create():
    try:
        book = books.create_book(request.form.get("name"))
    except books.InputError as exc:
        return _back(books.DEFAULT_BOOK_ID, error=_first_error(exc))
    except books.BookStoreError as exc:
        return _back(books.DEFAULT_BOOK_ID, error=f"Couldn't save: {exc}")
    return _back(book["id"], msg="created")


@portfolio_books_bp.get("/portfolio/books/<book_id>")
def portfolio_book_page(book_id: str):
    return _render_book(book_id)


@portfolio_books_bp.post("/portfolio/books/<book_id>/rename")
def portfolio_book_rename(book_id: str):
    try:
        books.rename_book(book_id, request.form.get("name"))
    except books.BookNotFound:
        abort(404)
    except books.InputError as exc:
        return _back(book_id, error=_first_error(exc))
    except books.BookStoreError as exc:
        return _back(book_id, error=f"Couldn't save: {exc}")
    return _back(book_id, msg="renamed")


@portfolio_books_bp.post("/portfolio/books/<book_id>/delete")
def portfolio_book_delete(book_id: str):
    try:
        books.delete_book(book_id)
    except books.BookNotFound:
        abort(404)
    except books.InputError as exc:
        return _back(book_id, error=_first_error(exc))
    except books.BookStoreError as exc:
        return _back(book_id, error=f"Couldn't save: {exc}")
    return _back(books.DEFAULT_BOOK_ID, msg="book_deleted")


@portfolio_books_bp.post("/portfolio/books/<book_id>/bets")
def portfolio_book_add_bet(book_id: str):
    try:
        books.add_bet(book_id, request.form)
    except books.BookNotFound:
        abort(404)
    except books.InputError as exc:
        return _render_book(book_id, status=400, form_values=request.form.to_dict(), form_errors=exc.errors)
    except books.BookStoreError as exc:
        return _render_book(book_id, status=503, form_values=request.form.to_dict(), error=f"Couldn't save the bet: {exc}")
    return _back(book_id, msg="added")


def _bet_action(book_id: str, bet_id: str, manual, slip, msg: str):
    source = str(request.form.get("source") or "manual").strip().lower()
    try:
        (slip if source == "slip" else manual)()
    except books.BookNotFound:
        abort(404)
    except books.InputError as exc:
        return _back(book_id, error=_first_error(exc))
    except books.BookStoreError as exc:
        return _back(book_id, error=f"Couldn't save: {exc}")
    return _back(book_id, msg=msg)


@portfolio_books_bp.post("/portfolio/books/<book_id>/bets/<bet_id>/settle")
def portfolio_book_settle_bet(book_id: str, bet_id: str):
    outcome, cashout = request.form.get("outcome"), request.form.get("cashout_amount")
    return _bet_action(
        book_id,
        bet_id,
        lambda: books.settle_bet(book_id, bet_id, outcome, cashout),
        lambda: books.settle_slip_bet(book_id, bet_id, outcome, cashout),
        "settled",
    )


@portfolio_books_bp.post("/portfolio/books/<book_id>/bets/<bet_id>/reopen")
def portfolio_book_reopen_bet(book_id: str, bet_id: str):
    return _bet_action(
        book_id,
        bet_id,
        lambda: books.reopen_bet(book_id, bet_id),
        lambda: books.reopen_slip_bet(book_id, bet_id),
        "reopened",
    )


@portfolio_books_bp.post("/portfolio/books/<book_id>/bets/<bet_id>/delete")
def portfolio_book_delete_bet(book_id: str, bet_id: str):
    return _bet_action(
        book_id,
        bet_id,
        lambda: books.delete_bet(book_id, bet_id),
        lambda: books.delete_slip_bet(book_id, bet_id),
        "deleted",
    )


# ---------------------------------------------------------------- JSON


@portfolio_books_bp.get("/api/portfolio/books")
def api_portfolio_books():
    """What the bet slip's portfolio picker lists. Reads the manual store only,
    never the multi-MB prediction ledger."""
    return _no_store(
        jsonify(
            {
                "ok": True,
                "default": books.DEFAULT_BOOK_ID,
                "books": [
                    {"id": book["id"], "name": book["name"], "default": book["default"], "url": _book_url(book["id"])}
                    for book in books.list_books()
                ],
                "builtin": [dict(item) for item in books.BUILTIN_PORTFOLIOS],
            }
        )
    )


@portfolio_books_bp.get("/api/portfolio/books/<book_id>")
def api_portfolio_book(book_id: str):
    try:
        view = books.build_book_view(book_id)
    except books.BookNotFound:
        response = jsonify({"ok": False, "error": "unknown_portfolio", "portfolio_id": book_id})
        response.status_code = 404
        return _no_store(response)
    return _no_store(jsonify({"ok": True, **view}))
