---
name: run-syndicate
description: Launch the Syndicate Flask app and drive it with a headless browser to prove real pages (home, portfolio, betting board) render -- use when asked to run, start, test, smoke-test, or screenshot Syndicate, or to confirm a change works in the actual app rather than just the test suite.
---

# Run Syndicate

Paths below are relative to the repo root (this file's own path from
there is `.claude/skills/run-syndicate/driver.py`).

Syndicate is a Flask app (`syndicate/app.py`, entrypoint `app.py` /
`wsgi.py`) with server-rendered HTML pages and some client-side JS
polling. It's driven with **Playwright** (already a declared dev
dependency in `requirements-dev.txt`, and the browser binaries were
already installed in this environment -- `p.chromium.launch()` just
worked, no `playwright install` needed). There is no `chromium-cli` on
this machine, so the driver is a small committed Python script, not an
inline heredoc.

## Prerequisites

Already satisfied in this environment (Python 3.11, Flask 3.1,
`playwright` 1.60 with chromium installed). On a fresh machine:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium
```

## Run (agent path) -- use the driver

```bash
python .claude/skills/run-syndicate/driver.py smoke
```

This launches the dev server on `127.0.0.1:5057`, drives it through
the representative flow, and exits cleanly:

1. Home (`/`) -- screenshot, `.home-command-center` if it hydrated in time.
2. Portfolio (`/portfolio`) -- screenshot.
3. Betting board (`/intelligence`), cards view -- screenshot.
4. Betting board, blotter view (clicks the `Blotter` toggle) -- screenshot.

Screenshots land in `.claude/skills/run-syndicate/screenshots/` (`home.png`,
`portfolio.png`, `board_cards.png`, `board_blotter.png`). Console errors
and page errors are collected across the whole run; the script exits
non-zero and prints them if any occurred.

Other driver commands:

```bash
# Screenshot one arbitrary route (own server lifecycle, cleans up after)
# NOTE: from Git Bash on Windows, a leading-slash arg like `/mlb` gets
# silently rewritten to a Windows path (e.g. "C:/Program Files/Git/mlb")
# by MSYS's path conversion, which then fails as an invalid URL. Prefix
# with MSYS_NO_PATHCONV=1 to stop that:
MSYS_NO_PATHCONV=1 python .claude/skills/run-syndicate/driver.py shoot /mlb out.png

# Kill whatever's listening on the driver's port (127.0.0.1:5057) if a
# previous run didn't exit cleanly
python .claude/skills/run-syndicate/driver.py stop
```

## Run (human path)

```powershell
py -3 app.py
```

Opens on `http://127.0.0.1:5000` with the Werkzeug dev server
(`debug=True` per `app.py`'s `__main__` block). Useless headless;
`Ctrl-C` to stop. This is what the project README documents -- the
driver above is the programmatic equivalent, on a different port so
the two don't collide.

## Test suite

```bash
python -m pytest tests/test_home.py tests/test_intelligence.py -q
```

Ran clean at 33/33 for `test_home.py`. `test_intelligence.py` has a
large number of pre-existing failures unrelated to any given change --
see Gotchas.

## Gotchas

- **`/api/home` latency: root cause found and partially fixed, residual
  still open.** The home page's client JS (`hydrateHomeRails()`) fetches
  `/api/home` in the background right after first paint, running the
  real per-sport dashboard build (`_build_home_dashboard` in
  `syndicate/blueprints/home.py`). One real, confirmed cause: MLB's live
  score enrichment (`_apply_mlb_live_scores`) used to fetch each game's
  live feed **sequentially**, and each fetch could fall through to a
  real network call (`_fetch_mlb_feed_live` -> statsapi.mlb.com) with its
  own 5s socket timeout -- a full 15-game slate run sequentially could
  total 70s+ of blocking I/O in one request, past gunicorn's 60s worker
  timeout in production (`render.yaml`: `GUNICORN_TIMEOUT=60`, only
  `WEB_CONCURRENCY=2` workers at 1 thread each) -- exactly the shape of
  "cold Render deploy" trouble: a slow/killed worker on the very requests
  that should be proving the deploy healthy. Fixed 2026-07-21: games now
  fetch concurrently (`_mlb_feed_live_states`, one thread per game) with
  a hard 8s wall-clock ceiling regardless of external API behavior --
  verified with a synthetic test where every fetch was mocked to hang 60s
  and the function still returned in ~8s (`os._exit(0)` after the assert
  to skip waiting on the now-irrelevant straggler threads at process
  exit, which is a test-harness artifact, not a production concern for a
  long-lived gunicorn worker).

  **What's still open:** direct in-process calls to `_home_payload()`
  (bypassing Flask/HTTP entirely) are consistently fast after this fix
  (~1-5s, including a deliberate cache-expiry cold-miss reproduction).
  But hitting the real HTTP endpoint through this local dev server
  (subprocess + urllib/Playwright) has still, on some runs, taken 30s+
  even after the fix -- and that gap (fast in-process, slow over real
  HTTP, on the *same* machine) points at something in the WSGI/socket
  layer of this local Windows dev-server sandbox rather than remaining
  application code, but that wasn't confirmed before running out of
  productive diagnostic avenues (a faulthandler/signal-based thread-dump
  attempt failed on Windows subprocess signal handling). **Don't assume
  this is fully resolved without checking real Render behavior** (worker
  restart frequency, cold-deploy response times) after this fix ships --
  that's a different OS and WSGI server (gunicorn on Linux) from this
  local Werkzeug-on-Windows sandbox, and is the authoritative test bed
  for whether "Render deploy on cold" is actually resolved.

  For the driver: **don't chain page visits behind a visit to `/`**
  regardless of the above -- `smoke()` gives the home page its own,
  throwaway server process, never reused for anything else, and waits on
  `.home-command-center` with a bounded (30s) non-fatal timeout,
  screenshotting the light placeholder shell instead of hanging if
  hydration hasn't landed in time.
- **Don't use Playwright's `wait_until="networkidle"` anywhere on this
  app.** The home page polls `/api/home` on a 30s interval
  (`SyndicatePolling.start`) indefinitely, so the network never goes
  idle and `networkidle` just times out at its own limit (30s) for no
  useful reason. Use `"domcontentloaded"` plus an explicit
  `wait_for_selector` on the real content marker instead.
- **`/portfolio` and `/intelligence` are fast and reliable** (~0.1s for
  the initial page, `/api/intelligence/query` POST also ~0.1s in
  isolated testing) as long as they aren't run in a process that already
  took an `/api/home` hit first.
- **The dev server is single-process** (`app.run(..., use_reloader=False)`,
  no `threaded=True`), matching `app.py`. This alone would explain one
  slow request blocking a second, unrelated one queued behind it -- but
  it doesn't fully explain the residual latency gap above (fast
  in-process, slow over real HTTP for the *same* single request, not two
  competing ones), so treat single-threading as a contributing factor,
  not the full explanation. Don't add `threaded=True` to "fix" it without
  first confirming that's actually the remaining cause -- it would also
  mask whatever the real cause turns out to be.
- **Home's command-center markup only renders once `dashboard.summary_cards`
  is non-empty** (`syndicate/templates/shared/_home_dashboard.html`).
  The initial `GET /` deliberately passes a placeholder `dashboard` with
  all-empty lists for a fast first paint (see `home()` in
  `syndicate/blueprints/home.py`) -- a looser `{% if dashboard %}` check
  would render the command center prematurely with all-zero stats. If
  you touch that template, don't weaken that guard.
- **Pre-existing `test_intelligence.py` failures are unrelated to UI
  changes.** As of 2026-07-21 that file has ~58 failing tests out of
  ~158; spot-checked causes include an assertion for
  `id="intel-query-form"` (an id that doesn't exist in the current
  `intelligence.html` -- the real toolbar id is `board-toolbar`, so this
  is a stale pre-refactor assertion) and a mocked-overview test where the
  route pulled from a real, stale on-disk snapshot instead of the mock.
  Don't assume a change broke these without running the specific test
  fresh and reading the traceback -- most of them were already broken.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `RuntimeError: Port 5057 already in use` | `python .claude/skills/run-syndicate/driver.py stop`, then retry. |
| `page.goto` / `wait_for_selector` timeout on `/` | Expected sometimes -- see the `/api/home` Gotcha above. The smoke flow already tolerates this (screenshots the light shell); don't raise the timeout further, isolate instead. |
| `python driver.py smoke` hangs for minutes | You're likely hitting the wedge described above from a leftover process. `Ctrl-C`, run `driver.py stop`, retry -- each `smoke()` run starts fresh server processes so a clean retry is reliable. |
| `Page.navigate) Cannot navigate to invalid URL` mentioning a `C:/Program Files/Git/...` path when using `shoot` | Git Bash rewrote your leading-slash route arg into a Windows path. Prefix the command with `MSYS_NO_PATHCONV=1`. |
