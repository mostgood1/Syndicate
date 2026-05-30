from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from urllib.request import urlopen
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from syndicate.app import create_app

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised in local CLI usage.
    PlaywrightError = Exception
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None


WAIT_FOR_SETTLED_JS = """
(spec) => {
    const normalizeLoadingText = (value) => String(value || '')
        .trim()
        .toLowerCase()
        .replace(/…/g, '...');
  const settled = (selector, loadingText) => {
    if (!selector) return true;
    const element = document.querySelector(selector);
    if (!element) return false;
    if (!loadingText) return true;
    const currentText = (element.textContent || '').trim();
                const normalizedCurrent = normalizeLoadingText(currentText);
                const normalizedLoading = normalizeLoadingText(loadingText);
    if (element.children && element.children.length > 1) return true;
        return !normalizedCurrent.startsWith(normalizedLoading);
  };
    const exists = (selector) => {
        if (!selector) return false;
        return Boolean(document.querySelector(selector));
    };
  const text = (selector) => {
    if (!selector) return '';
    const element = document.querySelector(selector);
    return element ? (element.textContent || '').trim() : '';
  };
    const extrasSettled = (spec.extra_settled_checks || []).every((entry) => settled(entry.selector, entry.loading_text));
    const extrasReady = (spec.extra_required_nonempty_selectors || []).every((selector) => text(selector));
    const extrasExist = (spec.extra_required_selectors || []).every((selector) => exists(selector));
  const boardText = text(spec.board_selector);
  const emptyText = text(spec.empty_selector);
  return settled(spec.header_selector, spec.header_loading_text)
    && settled(spec.board_selector, spec.board_loading_text)
    && settled(spec.scoreboard_selector, spec.scoreboard_loading_text)
    && settled(spec.status_selector, spec.status_loading_text)
        && extrasSettled
        && extrasReady
        && extrasExist
    && Boolean(boardText || emptyText);
}
"""

SNAPSHOT_JS = """
(spec) => {
  const text = (selector) => {
    if (!selector) return '';
    const element = document.querySelector(selector);
    return element ? (element.textContent || '').trim() : '';
  };
  return {
    title: document.title,
    header_text: text(spec.header_selector),
    board_text: text(spec.board_selector),
    scoreboard_text: text(spec.scoreboard_selector),
    empty_text: text(spec.empty_selector),
    status_text: text(spec.status_selector),
        extra_text: Object.fromEntries((spec.extra_required_nonempty_selectors || []).map((selector) => [selector, text(selector)])),
        extra_settled_text: Object.fromEntries((spec.extra_settled_checks || []).map((entry) => [entry.selector, text(entry.selector)])),
  };
}
"""


@dataclass(frozen=True)
class SettledCheck:
        selector: str
        loading_text: str


@dataclass(frozen=True)
class RouteSpec:
    name: str
    path: str
    header_selector: str
    board_selector: str
    header_loading_text: str
    board_loading_text: str
    scoreboard_selector: str | None = None
    scoreboard_loading_text: str | None = None
    empty_selector: str | None = None
    status_selector: str | None = None
    status_loading_text: str | None = None
    extra_required_selectors: tuple[str, ...] = ()
    extra_required_nonempty_selectors: tuple[str, ...] = ()
    extra_settled_checks: tuple[SettledCheck, ...] = ()


@dataclass
class RouteResult:
    name: str
    url: str
    ok: bool
    board_state: str
    title: str
    header_text: str
    board_excerpt: str
    empty_excerpt: str
    status_text: str
    extra_excerpt: dict[str, str]
    page_errors: list[str]
    console_errors: list[str]
    failure_reason: str | None = None


SYNTHETIC_SPORT = {
    "slug": "test-sport",
    "name": "Test Sport",
    "status": "Planned",
    "phase": "Shared shell",
    "summary": "Synthetic fallback hub used to verify the generic shared visual shell.",
    "primary_href": "/test-sport/cards",
    "primary_label": "Open Test Sport cards",
    "surfaces": ["cards", "archive"],
    "next_step": "Keep the fallback hub on the shared visual shell.",
}


ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        name="Syndicate home",
        path="/",
        header_selector=".home-controls__title",
        board_selector="#syndicate-home-sport-stack",
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".home-controls", ".home-topbar__date-form", ".sport-stack-card"),
        extra_required_nonempty_selectors=(".home-controls__title", '.sport-stack-card h3'),
    ),
    RouteSpec(
        name="MLB source cards",
        path="/mlb/cards?client=source",
        header_selector="#cardsHeaderMeta",
        board_selector="#cardsGrid",
        header_loading_text="Loading slate...",
        board_loading_text="Loading cards...",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="Loading scoreboard...",
        extra_required_selectors=("#cardsHrTargets",),
        extra_settled_checks=(
            SettledCheck(selector="#cardsHrTargets", loading_text="Loading HR targets"),
        ),
    ),
    RouteSpec(
        name="MLB shared board",
        path="/mlb/cards?client=board",
        header_selector="#cardsHeaderMeta",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill", ".cards-game-card", "#cardsHeaderMeta"),
        extra_required_nonempty_selectors=("#cardsHrTargets", "#cardsGrid .cards-game-card", ".cards-date-form", "#cardsHeaderMeta"),
    ),
    RouteSpec(
        name="NBA source cards",
        path="/nba/cards",
        header_selector="#cardsHeaderMeta",
        board_selector="#cardsGrid",
        header_loading_text="Loading slate...",
        board_loading_text="Loading cards...",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="Loading scoreboard...",
        extra_required_selectors=("#cardsSourceMeta", "#cardsFilters", "#cardsPropsStrip"),
        extra_required_nonempty_selectors=("#cardsSourceMeta", "#cardsFilters"),
        extra_settled_checks=(
            SettledCheck(selector="#cardsSourceMeta", loading_text="Loading slate"),
            SettledCheck(selector="#cardsPropsStrip", loading_text="Loading player prop strip"),
        ),
    ),
    RouteSpec(
        name="NBA shared board",
        path="/nba/cards?client=board",
        header_selector=".cards-date-form",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        empty_selector="#cardsGrid .hub-content-panel",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill", "#cardsHrTargets"),
        extra_required_nonempty_selectors=(".cards-date-form", "#cardsHrTargets"),
    ),
    RouteSpec(
        name="NHL source cards",
        path="/nhl/cards",
        header_selector="#cardsHeaderMeta",
        board_selector="#cards",
        header_loading_text="Loading slate...",
        board_loading_text="Loading cards…",
        empty_selector="#empty",
        status_selector="#status",
        status_loading_text="Loading",
        extra_required_selectors=("#cardsSourceMeta", "#cardsFilters", "#propsStrip"),
        extra_required_nonempty_selectors=(),
    ),
    RouteSpec(
        name="NHL shared board",
        path="/nhl/cards?client=board",
        header_selector=".cards-control-card h2",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        empty_selector="#cardsGrid .hub-content-panel",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill"),
        extra_required_nonempty_selectors=(".cards-date-form",),
    ),
    RouteSpec(
        name="WNBA source cards",
        path="/wnba/cards",
        header_selector="#cardsHeaderMeta",
        board_selector="#cardsGrid",
        header_loading_text="Loading slate...",
        board_loading_text="Loading cards...",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="Loading scoreboard...",
        extra_required_selectors=("#cardsSourceMeta", "#cardsFilters"),
        extra_required_nonempty_selectors=("#cardsSourceMeta", "#cardsFilters"),
        extra_settled_checks=(
            SettledCheck(selector="#cardsSourceMeta", loading_text="Loading slate"),
        ),
    ),
    RouteSpec(
        name="WNBA shared board",
        path="/wnba/cards?client=board",
        header_selector=".cards-date-form",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill", ".feature-game-card", "#cardsHrTargets"),
        extra_required_nonempty_selectors=("#cardsGrid .feature-game-card", ".cards-date-form", "#cardsHrTargets"),
    ),
    RouteSpec(
        name="NFL shared board",
        path="/nfl/cards",
        header_selector=".cards-date-form",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill", ".feature-game-card"),
        extra_required_nonempty_selectors=("#cardsGrid .feature-game-card", ".cards-date-form"),
    ),
    RouteSpec(
        name="NCAAF shared board",
        path="/ncaaf/cards",
        header_selector=".cards-date-form",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill", ".feature-game-card", "#cardsHrTargets"),
        extra_required_nonempty_selectors=("#cardsGrid .feature-game-card", ".cards-date-form", "#cardsHrTargets"),
    ),
    RouteSpec(
        name="NCAAB shared board",
        path="/ncaab/cards",
        header_selector=".cards-date-form",
        board_selector="#cardsGrid",
        header_loading_text="",
        board_loading_text="",
        scoreboard_selector="#cardsScoreboard",
        scoreboard_loading_text="",
        empty_selector="#cardsGrid .hub-content-panel",
        extra_required_selectors=(".cards-control-card", ".cards-date-form", ".cards-nav-pill"),
        extra_required_nonempty_selectors=(".cards-date-form",),
    ),
    RouteSpec(
        name="MLB hub",
        path="/mlb/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="MLB route groups"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="MLB route groups"] .sport-card h3'),
    ),
    RouteSpec(
        name="NBA hub",
        path="/nba/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="Available NBA slates"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="Available NBA slates"] .sport-card h3'),
    ),
    RouteSpec(
        name="NHL hub",
        path="/nhl/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="Available NHL slates"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="Available NHL slates"] .sport-card h3'),
    ),
    RouteSpec(
        name="NFL hub",
        path="/nfl/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="Available NFL weeks"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="Available NFL weeks"] .sport-card h3'),
    ),
    RouteSpec(
        name="WNBA hub",
        path="/wnba/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="Available WNBA slates"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="Available WNBA slates"] .sport-card h3'),
    ),
    RouteSpec(
        name="NCAAF hub",
        path="/ncaaf/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="Available NCAAF weeks"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel",),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="Available NCAAF weeks"] .sport-card h3'),
    ),
    RouteSpec(
        name="NCAAB hub",
        path="/ncaab/hub",
        header_selector=".cards-control-card h2",
        board_selector='section[aria-label="NCAAB module launches"]',
        header_loading_text="",
        board_loading_text="",
        extra_required_selectors=(".hub-content-panel", 'section[aria-label="Available NCAAB dates"]'),
        extra_required_nonempty_selectors=(".hub-content-panel h3", 'section[aria-label="NCAAB module launches"] .sport-card h3'),
    ),
    RouteSpec(
        name="Generic fallback hub",
        path="/test-sport",
        header_selector=".cards-control-card h2",
        board_selector=".hub-content-panel",
        header_loading_text="",
        board_loading_text="",
        extra_required_nonempty_selectors=(".hub-content-panel h3", ".cards-control-card .action-row", ".hub-content-panel"),
    ),
)


class LocalServer(AbstractContextManager["LocalServer"]):
    def __init__(self) -> None:
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "LocalServer":
        app = create_app()
        sports = list(app.config.get("SYNDICATE_SPORTS", []))
        if not any(item.get("slug") == SYNTHETIC_SPORT["slug"] for item in sports if isinstance(item, dict)):
            app.config["SYNDICATE_SPORTS"] = [*sports, dict(SYNTHETIC_SPORT)]
        port = self._find_free_port()
        self._server = make_server("127.0.0.1", port, app, request_handler=_SilentRequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])


class _SilentRequestHandler(WSGIRequestHandler):
    def log(self, type: str, message: str, *args) -> None:  # noqa: A003 - Werkzeug API name.
        return


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run browser-level smoke checks for source-shell cards routes and shared module hubs.",
    )
    parser.add_argument(
        "--base-url",
        help="Reuse an already-running Syndicate server instead of starting one in-process.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Per-route timeout in milliseconds. Default: 60000.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium in headed mode for local debugging.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full route report as JSON.",
    )
    return parser.parse_args(argv)


def ensure_playwright_available() -> None:
    if sync_playwright is not None:
        return
    raise SystemExit(
        "Playwright is not installed. Run `python -m pip install -r requirements-dev.txt` "
        "and `python -m playwright install chromium` first."
    )


def run_route_check(page, base_url: str, spec: RouteSpec, timeout_ms: int) -> RouteResult:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    url = f"{base_url.rstrip('/')}{spec.path}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_function(WAIT_FOR_SETTLED_JS, arg=asdict(spec), timeout=timeout_ms)
        snapshot = capture_snapshot(page, spec, timeout_ms)
        board_text = str(snapshot.get("board_text") or "").strip()
        empty_text = str(snapshot.get("empty_text") or "").strip()
        board_state = "empty" if empty_text and not board_text else "populated"
        ok = bool((board_text or empty_text) and not page_errors and not console_errors)
        extra_excerpt = {
            str(key): _excerpt(str(value or ""))
            for key, value in {**(snapshot.get("extra_text") or {}), **(snapshot.get("extra_settled_text") or {})}.items()
            if str(value or "").strip()
        }
        failure_reason = None
        if not ok:
            failure_reason = "browser_error" if (page_errors or console_errors) else "missing_rendered_content"
        return RouteResult(
            name=spec.name,
            url=url,
            ok=ok,
            board_state=board_state,
            title=str(snapshot.get("title") or "").strip(),
            header_text=str(snapshot.get("header_text") or "").strip(),
            board_excerpt=_excerpt(board_text),
            empty_excerpt=_excerpt(empty_text),
            status_text=str(snapshot.get("status_text") or "").strip(),
            extra_excerpt=extra_excerpt,
            page_errors=page_errors,
            console_errors=console_errors,
            failure_reason=failure_reason,
        )
    except PlaywrightTimeoutError:
        snapshot = capture_snapshot(page, spec, timeout_ms)
        return RouteResult(
            name=spec.name,
            url=url,
            ok=False,
            board_state="timeout",
            title=str(snapshot.get("title") or "").strip(),
            header_text=str(snapshot.get("header_text") or "").strip(),
            board_excerpt=_excerpt(str(snapshot.get("board_text") or "")),
            empty_excerpt=_excerpt(str(snapshot.get("empty_text") or "")),
            status_text=str(snapshot.get("status_text") or "").strip(),
            extra_excerpt={},
            page_errors=page_errors,
            console_errors=console_errors,
            failure_reason="timeout",
        )
    except PlaywrightError as error:
        return RouteResult(
            name=spec.name,
            url=url,
            ok=False,
            board_state="error",
            title="",
            header_text="",
            board_excerpt="",
            empty_excerpt="",
            status_text="",
            extra_excerpt={},
            page_errors=page_errors,
            console_errors=console_errors,
            failure_reason=str(error),
        )
    finally:
        page.close()


def capture_snapshot(page, spec: RouteSpec, timeout_ms: int) -> dict[str, object]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return page.evaluate(SNAPSHOT_JS, arg=asdict(spec))
        except PlaywrightError as error:
            last_error = error
            if "Execution context was destroyed" not in str(error):
                raise
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    if last_error is not None:
        raise last_error
    return {}


def _excerpt(value: str, limit: int = 180) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def print_human_report(results: Sequence[RouteResult]) -> None:
    for result in results:
        verdict = "PASS" if result.ok else "FAIL"
        print(f"[{verdict}] {result.name}")
        print(f"  URL: {result.url}")
        print(f"  Board: {result.board_state}")
        if result.header_text:
            print(f"  Header: {result.header_text}")
        if result.status_text:
            print(f"  Status: {result.status_text}")
        if result.empty_excerpt:
            print(f"  Empty: {result.empty_excerpt}")
        elif result.board_excerpt:
            print(f"  Board excerpt: {result.board_excerpt}")
        if result.extra_excerpt:
            for selector, excerpt in sorted(result.extra_excerpt.items()):
                print(f"  {selector}: {excerpt}")
        if result.page_errors:
            print(f"  Page errors: {' | '.join(result.page_errors)}")
        if result.console_errors:
            print(f"  Console errors: {' | '.join(result.console_errors)}")
        if result.failure_reason:
            print(f"  Failure: {result.failure_reason}")


def prewarm_routes(base_url: str, route_specs: Sequence[RouteSpec], timeout_ms: int) -> None:
    timeout_seconds = max(120.0, timeout_ms / 1000.0)
    seen_urls: set[str] = set()
    for spec in route_specs:
        url = f"{base_url.rstrip('/')}{spec.path}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                response.read(1)
        except Exception:
            # Let the browser check surface real failures with full route context.
            continue


def run_checks(base_url: str, timeout_ms: int, headed: bool, include_synthetic: bool = True) -> list[RouteResult]:
    ensure_playwright_available()
    route_specs = ROUTE_SPECS if include_synthetic else tuple(spec for spec in ROUTE_SPECS if spec.name != "Generic fallback hub")
    prewarm_routes(base_url, route_specs, timeout_ms)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        try:
            results = [
                run_route_check(context.new_page(), base_url, spec, timeout_ms)
                for spec in route_specs
            ]
        finally:
            context.close()
            browser.close()
    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.base_url:
        results = run_checks(args.base_url, args.timeout_ms, args.headed, include_synthetic=False)
    else:
        with LocalServer() as server:
            results = run_checks(server.base_url, args.timeout_ms, args.headed, include_synthetic=True)

    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print_human_report(results)

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())