"""Ops dashboards hub: the three Claude-free dashboards in one page, behind the portfolio sign-in.

User 2026-11-20: "I want all 3 of these available in one central dashboard hub" and dashboards that "dont use
claude credits", then "yes, open the lane and send the asks" (lane ops-dashboards-hub).

Each dashboard is rendered OFF the request path by its own Windows task, which writes one self-contained HTML file
onto the data root:

    reports/engine_watch/index.html     task SyndicateEngineWatch   (hourly, :15)
    reports/portfolio_watch/index.html  task SyndicatePortfolioWatch (:04 and :34)
    reports/rail_watch/index.html       task SyndicateRailWatch     (every 20 min, 10 AM to 2 AM CST)

Web only reads those files: no computation, no fleet calls, and no fallback build when one is missing. A missing
file shows that tab's "not built yet" panel; the other tabs still work.

Sign-in: these pages show live orders and P&L, so they sit behind the same sign-in as `/portfolio`
(`portfolio_auth`). The app-wide gate covers only `/portfolio*` paths, so this blueprint applies the same rules to
its own paths: sign-in off -> open; the admin token -> open; credentials not configured -> 503; not signed in ->
302 to the login page, which sends the user back here.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import Blueprint, Response, current_app, redirect, request

from syndicate.features.shared import portfolio_auth as auth

ops_dashboards_bp = Blueprint("ops_dashboards", __name__)

HUB_PATH = "/ops/dashboards"

# key -> (tab label, folder under reports/, when its builder writes it)
DASHBOARDS: dict[str, tuple[str, str, str]] = {
    "engine": ("Engine Watch", "engine_watch", "every hour at :15 by the SyndicateEngineWatch task"),
    "portfolio": ("Portfolio Watch", "portfolio_watch", "at :04 and :34 by the SyndicatePortfolioWatch task"),
    "rail": ("Rail Watch", "rail_watch", "every 20 minutes, 10 AM to 2 AM CST, by the SyndicateRailWatch task"),
}


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _page_path(key: str) -> Path:
    return _data_root() / "reports" / DASHBOARDS[key][1] / "index.html"


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _sign_in_refusal() -> Any:
    """None when the request may proceed, otherwise the response to send (portfolio_auth's rules)."""
    if auth.auth_mode() == "off":
        return None
    if auth.request_has_admin_token(request, current_app.config):
        return None
    if not auth.credentials().configured:
        return _no_store(Response(
            "<!doctype html><title>Dashboards</title><p>Sign-in is required on this server and no portfolio "
            "credentials are configured.</p>", status=503, mimetype="text/html"))
    if auth.current_user(request):
        return None
    target = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    return redirect(f"{auth.LOGIN_PATH}?next={quote(target, safe='/')}", code=302)


@ops_dashboards_bp.before_request
def _require_sign_in() -> Any:
    return _sign_in_refusal()


def _missing_panel(key: str) -> str:
    label, folder, cadence = DASHBOARDS[key]
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>" + escape(label) + "</title></head>"
        "<body style=\"font-family:system-ui,sans-serif;padding:24px;background:#fff;color:#222\">"
        "<h1 style=\"font-size:20px\">" + escape(label) + " has not been built yet</h1>"
        "<p>It is written " + escape(cadence) + " to <code>reports/" + escape(folder) + "/index.html</code> "
        "on the data root. This page only reads that file.</p></body></html>"
    )


@ops_dashboards_bp.get(HUB_PATH + "/<key>")
def ops_dashboard_frame(key: str) -> Any:
    if key not in DASHBOARDS:
        return _no_store(Response("Unknown dashboard.", status=404, mimetype="text/plain"))
    try:
        page = _page_path(key).read_text(encoding="utf-8")
    except OSError:
        return _no_store(Response(_missing_panel(key), status=404, mimetype="text/html"))
    return _no_store(Response(page, mimetype="text/html"))


_HUB = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Syndicate Dashboards</title>
<style>
  :root { --bg:#f6f7f9; --bar:#ffffff; --ink:#1d2330; --muted:#5b6475; --line:#dde1e8; --on:#1f5fbf; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#12151b; --bar:#1a1e26; --ink:#e6e9ef; --muted:#9aa3b2; --line:#2a303b; --on:#6ea2ff; }
  }
  * { box-sizing: border-box; }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display:flex; flex-direction:column; }
  nav { display:flex; gap:4px; align-items:center; padding:8px 16px; background:var(--bar);
    border-bottom:1px solid var(--line); flex-wrap:wrap; }
  nav .title { font-weight:600; margin-right:12px; }
  nav a { padding:6px 12px; border-radius:6px; color:var(--muted); text-decoration:none; font-size:14px; }
  nav a[aria-current="page"] { color:var(--on); background:color-mix(in srgb, var(--on) 12%, transparent);
    font-weight:600; }
  nav .open { margin-left:auto; font-size:13px; }
  main { flex:1; position:relative; }
  iframe { position:absolute; inset:0; width:100%; height:100%; border:0; background:#fff; display:none; }
  iframe.on { display:block; }
</style>
</head>
<body>
<nav>
  <span class="title">Dashboards</span>
  __TABS__
  <a class="open" id="open-tab" href="#" target="_blank" rel="noopener">Open in its own tab</a>
</nav>
<main>
  __FRAMES__
</main>
<script>
(function () {
  var keys = __KEYS__;
  var loaded = {};
  function show(key) {
    if (keys.indexOf(key) < 0) key = keys[0];
    keys.forEach(function (k) {
      var frame = document.getElementById("frame-" + k);
      var tab = document.getElementById("tab-" + k);
      var on = k === key;
      frame.classList.toggle("on", on);
      if (on) { tab.setAttribute("aria-current", "page"); } else { tab.removeAttribute("aria-current"); }
      if (on && !loaded[k]) { frame.src = frame.getAttribute("data-src"); loaded[k] = true; }
    });
    document.getElementById("open-tab").href = "__HUB__/" + key;
  }
  function fromHash() { show((location.hash || "").replace(/^#/, "")); }
  window.addEventListener("hashchange", fromHash);
  fromHash();
  // Reload the visible tab every 5 minutes, so an open page follows its builder.
  setInterval(function () {
    keys.forEach(function (k) {
      var frame = document.getElementById("frame-" + k);
      if (loaded[k] && frame.classList.contains("on")) {
        try { frame.contentWindow.location.reload(); } catch (e) { frame.src = frame.getAttribute("data-src"); }
      } else if (loaded[k]) { loaded[k] = false; }
    });
  }, 300000);
})();
</script>
</body>
</html>
"""


def hub_html() -> str:
    tabs = "\n  ".join(
        f'<a id="tab-{key}" href="#{key}">{escape(label)}</a>' for key, (label, _f, _c) in DASHBOARDS.items()
    )
    frames = "\n  ".join(
        f'<iframe id="frame-{key}" title="{escape(label)}" data-src="{HUB_PATH}/{key}"></iframe>'
        for key, (label, _f, _c) in DASHBOARDS.items()
    )
    keys = "[" + ", ".join(f'"{key}"' for key in DASHBOARDS) + "]"
    return (
        _HUB.replace("__TABS__", tabs)
        .replace("__FRAMES__", frames)
        .replace("__KEYS__", keys)
        .replace("__HUB__", HUB_PATH)
    )


@ops_dashboards_bp.get(HUB_PATH)
def ops_dashboards_hub() -> Any:
    return _no_store(Response(hub_html(), mimetype="text/html"))
