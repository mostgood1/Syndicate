"""The Layer 1 board PAGE, rendered one way for every sport (`#329`).

The API half of this landed first and the pages did not, which left
`/api/board/layer1` correct and invisible: every `/<sport>/market-board` still
rendered its own bespoke builder's payload, so none of `#328`'s sim enrichment,
`#330`'s soccer leagues or the pregame/live split reached a user.

A FUNCTION, NOT EIGHT ROUTE BODIES. Each blueprint owns `/<sport>/market-board`
under its own `url_prefix`, so the route has to be declared per blueprint --
but the body must not be, or this becomes the six-divergent-builders problem in
its second life. Every sport calls this and differs only by slug.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import render_template, request

from syndicate.features.shared.timezone import central_today_iso

# The sports the board offers in its own switcher. All eight, including the two
# that had no page at all before this -- NHL and NCAAB returned 404 on
# production 2026-08-10 while `/api/board/book-grid` served them by parameter.
# An out-of-season sport renders an empty board that says WHY (`#296`), which is
# the correct answer and a different one from "no such page".
LAYER1_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")


def _selected_date() -> str:
    raw = str(request.args.get("date") or "").strip()
    if not raw:
        return central_today_iso()
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        # A malformed date falls back to today rather than 500ing or, worse,
        # reaching the artifact reader as a path fragment.
        return central_today_iso()
    return raw


def render_layer1_board(sport: str):
    """Render the shared Layer 1 board for one sport.

    Rows are fetched client-side from `/api/board/layer1`, so this handler does
    no artifact IO at all -- the page is a shell. That keeps the web service on
    the right side of the rule this repo keeps paying for: web reads precomputed
    artifacts, and it does not do it inside a template render.
    """
    slug = str(sport or "").strip().lower()
    selected = _selected_date()
    parsed = datetime.strptime(selected, "%Y-%m-%d").date()
    return render_template(
        "shared/layer1_board.html",
        sport=slug,
        sports=LAYER1_SPORTS,
        selected_date=selected,
        prev_date=(parsed - timedelta(days=1)).isoformat(),
        next_date=(parsed + timedelta(days=1)).isoformat(),
        nav_path=request.path,
    )
