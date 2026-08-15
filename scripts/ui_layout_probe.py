"""Re-runnable version of the 2026-08-14 UI audit's measurements.

The audit that produced `.syndicate/audit_2026-08-14_ui.md` was a set of
throwaway probes; its findings were real but nobody could reproduce them
without rewriting the probes. This is those measurements as a script, so a
regression shows up as a number moving rather than as someone noticing a card
looks wrong.

What it measures, per sport, at both widths:

  * horizontal page overflow      documentElement.scrollWidth - clientWidth
  * card-height spread            max - min over the slate's game cards
  * tab/panel id agreement        every tab addresses a panel, and vice versa
  * tab click-through             a TRUSTED click on each tab leaves exactly
                                  one panel active and a card taller than its
                                  header strip
  * touch targets                 tab width/height against WCAG 2.5.5's 44x44
  * type scale                    computed font-size/weight per named class,
                                  reported PER SURFACE (card vs scoreboard
                                  strip) -- see the second caveat below
  * tabular figures               computed font-variant-numeric on the classes
                                  carrying odds and projections
  * unstyled links                any anchor inside a card still rendering the
                                  user-agent's default link colour
  * repeated copy                 the same string rendered more than once in
                                  one card, per panel
  * empty regions                 empty-state blocks, `—` placeholder cells and
                                  zero-bin distribution bars, per panel

METHOD CAVEAT 1, and it is not optional reading. The original audit's tab
results were produced with synthetic `el.click()` and one of them was WRONG
and had to be retracted (WNBA's tabs were reported broken; they work). Only
Playwright's `locator.click()` -- a real input event through the browser's own
dispatch -- is trusted here. If you extend this script, do not reach for
`page.evaluate("el.click()")` to save a scroll.

METHOD CAVEAT 2, added 2026-08-15 after this script produced its own wrong
number. The type-scale table was built with `document.querySelector(selector)`
-- the FIRST match on the page. `.cards-head-team-name` is used by both the
scoreboard strip and the game card, and soccer ships a bespoke strip that
deliberately sets 13px. So the table read "soccer 13px / NFL 16px" and the
audit turned that into a defect ("raise soccer's team names to 16px") for an
element that had been 16px all along, against a rule Lane E had just written
down for the OTHER element. One class, two surfaces, one sample. The table is
now keyed by surface, and a class appearing on more than one surface at
different sizes is reported as `conflated`, not silently collapsed to its
first hit. Any per-class table over a shared stylesheet needs this.

A sport that serves zero cards is reported as `cards: 0`, NOT as a pass. NBA,
NHL and NCAAB were out of season on 2026-08-14 and their rows in the audit's
divergence matrix are code-only for that reason.

Usage:

    py -3 scripts/ui_layout_probe.py                       # serve in-process
    py -3 scripts/ui_layout_probe.py --base-url http://127.0.0.1:5000
    py -3 scripts/ui_layout_probe.py --json --write reports/ui_layout/latest.json
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from syndicate.app import create_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - CLI-only path.
    sync_playwright = None


# Route per sport. Soccer is per-league; EPL is the league the audit measured.
SPORT_ROUTES: dict[str, str] = {
    "mlb": "/mlb/cards",
    "nfl": "/nfl/cards",
    "ncaaf": "/ncaaf/cards",
    "ncaab": "/ncaab/cards",
    "nba": "/nba/cards",
    "nhl": "/nhl/cards",
    "wnba": "/wnba/cards",
    "soccer": "/soccer/epl/cards",
}

VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 1200},
    "mobile": {"width": 390, "height": 844},
}

# Classes the audit tabulated. Kept as one list so the type-scale table stays
# comparable across runs rather than drifting with whatever was interesting
# that day.
TYPE_CLASSES = [
    ".cards-mini-copy",
    ".cards-market-label",
    ".cards-market-main",
    ".cards-market-sub",
    ".cards-tab",
    ".cards-head-team-name",
    ".cards-data-pair span",
    ".cards-data-pair strong",
]

# The classes that carry numbers which change on the 30s poll.
NUMERIC_CLASSES = [".cards-data-pair strong", ".cards-market-main", ".cards-mini-metric strong"]

WCAG_TARGET_PX = 44

# Sports whose season has not opened, where 0 cards is the correct answer and
# not a failure. Measured 2026-08-14: NBA, NHL and NCAAB served 0 cards, so
# their rows in the audit's divergence matrix are code-only. REVIEW THIS LIST
# IN OCTOBER -- leaving a sport here after its season opens turns a real
# outage into a green run. Override on the command line with --expect-cards.
OUT_OF_SEASON = {"nba", "nhl", "ncaab"}


MEASURE_JS = """
(spec) => {
  const doc = document.documentElement;
  const cards = [...document.querySelectorAll('.cards-game-card, .cards-strip-card')];
  const gameCards = [...document.querySelectorAll('.cards-game-card')];
  const heights = gameCards.map((c) => Math.round(c.getBoundingClientRect().height));

  // Tab/panel id agreement, per card. A tab whose target has no panel blanks
  // the card when clicked (NCAAF, measured 2026-08-14); a panel with no tab is
  // markup shipped to the browser that no user can reach.
  const tabsWithoutPanel = [];
  const panelsWithoutTab = [];
  gameCards.forEach((card) => {
    card.querySelectorAll('.cards-tab[data-tab-target]').forEach((tab) => {
      const id = tab.getAttribute('data-tab-target');
      if (!card.querySelector('.cards-panel[data-panel-id="' + id + '"]')) tabsWithoutPanel.push(id);
    });
    card.querySelectorAll('.cards-panel[data-panel-id]').forEach((panel) => {
      const id = panel.getAttribute('data-panel-id');
      if (!card.querySelector('.cards-tab[data-tab-target="' + id + '"]')) panelsWithoutTab.push(id);
    });
  });

  // Per SURFACE, not per page. See METHOD CAVEAT 2: one `querySelector` per
  // class reported soccer's strip size as the card's and produced a defect
  // that did not exist.
  const surfaceOf = (el) => el.closest('.cards-strip-card') ? 'strip'
                          : el.closest('.cards-game-card') ? 'card'
                          : 'other';
  const typeScale = {};
  (spec.typeClasses || []).forEach((selector) => {
    const bySurface = {};
    document.querySelectorAll(selector).forEach((el) => {
      const cs = getComputedStyle(el);
      const key = surfaceOf(el);
      if (!bySurface[key]) bySurface[key] = new Set();
      bySurface[key].add(cs.fontSize + '/' + cs.fontWeight);
    });
    const entry = {};
    Object.keys(bySurface).forEach((k) => { entry[k] = [...bySurface[k]].sort(); });
    if (Object.keys(entry).length) {
      const all = new Set(Object.keys(entry).map((k) => entry[k]).flat());
      typeScale[selector] = all.size > 1 ? Object.assign({conflated: true}, entry) : entry;
    }
  });

  // An anchor inside a card that nobody restyled. rgb(0, 0, 238) is Chromium's
  // default link colour; measured on soccer's card-head team names 2026-08-15,
  // underlined, against a #0a1522 card.
  const unstyledLinks = [...document.querySelectorAll('.cards-game-card a, .cards-strip-card a')]
    .map((a) => {
      const cs = getComputedStyle(a);
      return {text: a.textContent.trim().slice(0, 40), cls: String(a.className || ''),
              color: cs.color, decoration: cs.textDecorationLine};
    })
    .filter((a) => a.color === 'rgb(0, 0, 238)' || a.color === 'rgb(85, 26, 139)');

  // Repeated copy: the same rendered string appearing more than once inside a
  // single card. Soccer carried its projected-score sentence six times.
  const firstCard = document.querySelector('.cards-game-card');
  const repeatedCopy = [];
  const emptyRegions = [];
  if (firstCard) {
    const counts = new Map();
    firstCard.querySelectorAll('*').forEach((el) => {
      if (el.children.length) return;
      const t = (el.textContent || '').trim();
      if (t.length < 12) return;
      const panel = el.closest('.cards-panel');
      const hit = counts.get(t) || {text: t.slice(0, 70), count: 0, panels: []};
      hit.count += 1;
      hit.panels.push(panel ? panel.getAttribute('data-panel-id') : '(head)');
      counts.set(t, hit);
    });
    [...counts.values()].filter((h) => h.count > 1)
      .sort((a, b) => b.count - a.count).slice(0, 8)
      .forEach((h) => repeatedCopy.push(h));

    firstCard.querySelectorAll('.cards-panel[data-panel-id]').forEach((p) => {
      const emptyCopy = p.querySelectorAll('.cards-empty-copy').length;
      const placeholders = [...p.querySelectorAll('*')]
        .filter((e) => !e.children.length && e.textContent.trim() === '—').length;
      const emptyBars = [...p.querySelectorAll('.cards-run-dist-bar')]
        .filter((b) => b.children.length === 0).length;
      if (emptyCopy || placeholders || emptyBars) {
        emptyRegions.push({panel: p.getAttribute('data-panel-id'),
                           emptyCopy, placeholders, emptyBars});
      }
    });
  }

  const tabularFigures = {};
  (spec.numericClasses || []).forEach((selector) => {
    const el = document.querySelector(selector);
    if (!el) return;
    tabularFigures[selector] = getComputedStyle(el).fontVariantNumeric;
  });

  const tabBoxes = [...document.querySelectorAll('.cards-tab')].map((t) => {
    const r = t.getBoundingClientRect();
    return {w: Math.round(r.width), h: Math.round(r.height)};
  });

  // Mid-word breaking is not directly observable, but its precondition is: a
  // team-name box narrower than the longest word it has to render.
  const nameBoxes = [...document.querySelectorAll('.cards-head-team-name')].map((el) => ({
    text: el.textContent.trim(),
    surface: surfaceOf(el),
    width: Math.round(el.getBoundingClientRect().width),
    fontSize: getComputedStyle(el).fontSize,
    wrap: getComputedStyle(el).overflowWrap,
  }));

  return {
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    overflowPx: doc.scrollWidth - doc.clientWidth,
    boxSizing: cards.length ? getComputedStyle(cards[0]).boxSizing : null,
    cards: gameCards.length,
    stripCards: cards.length - gameCards.length,
    cardHeightMin: heights.length ? Math.min(...heights) : null,
    cardHeightMax: heights.length ? Math.max(...heights) : null,
    cardHeightSpread: heights.length ? Math.max(...heights) - Math.min(...heights) : null,
    tabsWithoutPanel: [...new Set(tabsWithoutPanel)],
    panelsWithoutTab: [...new Set(panelsWithoutTab)],
    typeScale,
    tabularFigures,
    tabBoxes,
    nameBoxes: nameBoxes.slice(0, 8),
    unstyledLinks,
    repeatedCopy,
    emptyRegions,
  };
}
"""


def _tab_click_through(page, sport: str) -> list[dict[str, Any]]:
    """Trusted click on every tab of the first card. See the method caveat."""
    card = page.locator(".cards-game-card").first
    if card.count() == 0:
        return []
    tabs = card.locator(".cards-tab[data-tab-target]")
    results: list[dict[str, Any]] = []
    for index in range(tabs.count()):
        tab = tabs.nth(index)
        target = tab.get_attribute("data-tab-target")
        try:
            tab.scroll_into_view_if_needed(timeout=5000)
            tab.click(timeout=5000)
        except Exception as exc:  # pragma: no cover - reported, not raised.
            results.append({"tab": target, "error": type(exc).__name__})
            continue
        state = card.evaluate(
            """(node) => ({
                active: [...node.querySelectorAll('.cards-panel.is-active')].map((p) => p.getAttribute('data-panel-id')),
                height: Math.round(node.getBoundingClientRect().height),
            })"""
        )
        results.append(
            {
                "tab": target,
                "activePanels": state["active"],
                "cardHeight": state["height"],
                # One panel active, and a card taller than a bare header strip.
                # The NCAAF failure rendered 0 panels and a 187px card.
                "ok": len(state["active"]) == 1 and state["active"][0] == target and state["height"] > 250,
            }
        )
    return results


def probe(base_url: str, sports: Sequence[str], timeout_ms: int) -> dict[str, Any]:
    if sync_playwright is None:
        raise SystemExit(
            "playwright is not installed. pip install -r requirements-dev.txt && playwright install chromium"
        )
    report: dict[str, Any] = {"baseUrl": base_url, "sports": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for sport in sports:
                route = SPORT_ROUTES[sport]
                sport_report: dict[str, Any] = {"route": route}
                for label, viewport in VIEWPORTS.items():
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    try:
                        # The status is not decoration. Run against a 502ing
                        # production on 2026-08-15 this script printed a clean
                        # table and exit code 0: every sport measured 0 cards
                        # and 0px of overflow, because Render's error page has
                        # no cards and does not overflow. A probe that passes
                        # on an error page is worse than no probe.
                        response = page.goto(f"{base_url}{route}", timeout=timeout_ms, wait_until="load")
                        page.wait_for_timeout(400)
                        measured = page.evaluate(
                            MEASURE_JS,
                            {"typeClasses": TYPE_CLASSES, "numericClasses": NUMERIC_CLASSES},
                        )
                        measured["httpStatus"] = response.status if response is not None else None
                        measured["touchTargetFailures"] = [
                            box
                            for box in measured.pop("tabBoxes", [])
                            if box["h"] < WCAG_TARGET_PX or box["w"] < WCAG_TARGET_PX
                        ]
                        if label == "desktop":
                            measured["tabClickThrough"] = _tab_click_through(page, sport)
                        sport_report[label] = measured
                    except Exception as exc:  # pragma: no cover - reported, not raised.
                        sport_report[label] = {"error": f"{type(exc).__name__}: {exc}"}
                    finally:
                        context.close()
                report["sports"][sport] = sport_report
        finally:
            browser.close()
    return report


def summarize(report: dict[str, Any]) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True
    out_of_season = set(report.get("outOfSeason") or ())
    header = f"{'sport':8} {'width':8} {'cards':>5} {'overflow':>9} {'spread':>7}  tabs"
    lines.append(header)
    lines.append("-" * len(header))
    for sport, sport_report in report["sports"].items():
        for label in VIEWPORTS:
            measured = sport_report.get(label) or {}
            if "error" in measured:
                lines.append(f"{sport:8} {label:8} {'ERR':>5}  {measured['error'][:60]}")
                ok = False
                continue
            overflow = measured.get("overflowPx")
            spread = measured.get("cardHeightSpread")
            cards = measured.get("cards") or 0
            issues = []
            if overflow:
                issues.append(f"overflow {overflow}px")
                ok = False
            if measured.get("tabsWithoutPanel"):
                issues.append("tab->missing panel " + ",".join(measured["tabsWithoutPanel"]))
                ok = False
            if measured.get("panelsWithoutTab"):
                issues.append("unreachable panel " + ",".join(measured["panelsWithoutTab"]))
                ok = False
            failed_clicks = [r for r in measured.get("tabClickThrough", []) if not r.get("ok")]
            if failed_clicks:
                issues.append("tab click " + ",".join(str(r.get("tab")) for r in failed_clicks))
                ok = False
            if label == "mobile" and measured.get("touchTargetFailures"):
                issues.append(f"{len(measured['touchTargetFailures'])} tabs < 44px")
            # An anchor left on the user-agent's default link colour is
            # unambiguous and cheap to fix, so it fails the run.
            if measured.get("unstyledLinks"):
                issues.append(f"{len(measured['unstyledLinks'])} unstyled link(s)")
                ok = False
            # These two are REPORTED, not failed. They are counts that should
            # trend down; hard-failing them on day one across seven sports
            # would make the harness something people skip rather than run.
            repeats = measured.get("repeatedCopy") or []
            if repeats:
                worst = max(r["count"] for r in repeats)
                issues.append(f"copy repeated up to {worst}x")
            empties = measured.get("emptyRegions") or []
            if empties:
                total = sum(e["emptyCopy"] + e["placeholders"] + e["emptyBars"] for e in empties)
                issues.append(f"{total} empty slot(s) in {len(empties)} panel(s)")
            conflated = [k for k, v in (measured.get("typeScale") or {}).items() if isinstance(v, dict) and v.get("conflated")]
            if conflated:
                issues.append("type conflated: " + ",".join(c.lstrip(".") for c in conflated))
            status = measured.get("httpStatus")
            if status is not None and status >= 400:
                issues.append(f"HTTP {status} -- NOTHING BELOW IS A MEASUREMENT")
                ok = False
            # This used to be reported and then passed: the docstring said "0
            # cards is NOT a pass" and the exit code said 0 anyway. An
            # out-of-season sport is a legitimate 0, so it is opt-out by name
            # rather than silently tolerated -- which is what makes a 0 on a
            # sport you EXPECTED to have cards fail the run.
            if not cards:
                issues.append("0 cards served -- NOT a pass, re-measure in season")
                if sport not in out_of_season:
                    ok = False
            lines.append(
                f"{sport:8} {label:8} {cards:>5} {str(overflow) + 'px':>9} {str(spread) + 'px':>7}  "
                + ("; ".join(issues) if issues else "ok")
            )
    return lines, ok


class LocalServer(AbstractContextManager["LocalServer"]):
    def __init__(self) -> None:
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "LocalServer":
        app = create_app()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = int(sock.getsockname()[1])
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


class _SilentRequestHandler(WSGIRequestHandler):
    def log(self, type: str, message: str, *args) -> None:  # noqa: A003 - Werkzeug API name.
        return


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help="Probe a running server instead of serving in-process.")
    parser.add_argument("--sports", default=",".join(SPORT_ROUTES), help="Comma-separated sport slugs.")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--expect-cards",
        default="",
        help=f"Comma-separated sports that MUST serve cards even though they are in {sorted(OUT_OF_SEASON)}.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--write", default=None, help="Write the full JSON report to this path.")
    args = parser.parse_args(argv)

    sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    unknown = [s for s in sports if s not in SPORT_ROUTES]
    if unknown:
        parser.error(f"unknown sport(s): {', '.join(unknown)}")

    if args.base_url:
        report = probe(args.base_url.rstrip("/"), sports, args.timeout_ms)
    else:
        with LocalServer() as server:
            report = probe(server.base_url, sports, args.timeout_ms)

    expect_cards = {s.strip() for s in args.expect_cards.split(",") if s.strip()}
    report["outOfSeason"] = sorted(OUT_OF_SEASON - expect_cards)
    lines, ok = summarize(report)
    report["ok"] = ok
    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(lines))
        print("\nOK" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
