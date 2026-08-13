"""`#409` -- `/market-board/books` is retired and redirects to the Betting Board.

WHY IT WAS RETIRED, measured rather than asserted. `book_grid.html:590` reached
Fair only via `modelled_fair` or `proj.market_fair_prob_over`. On production
2026-08-12, core game rows:

    sport   core  modelled_fair  consensus  two-sided
    mlb      341        0           341        341
    wnba      40        0            40         40
    nfl      126        0           126        126
    soccer   275        0           275        275

`modelled_fair` is **0 on all 782** -- two-sided markets skip the margin model by
design -- so the Fair column was not "blank for WNBA" as `#407` recorded, it was
structurally blank everywhere, always. Its tooltip compounded it: "no two-sided
market, so no-vig fair value cannot be computed" on 782 rows that were ALL
two-sided with both sides priced. A tooltip naming the wrong condition is worse
than a blank.

The Betting Board reaches all 782 through its consensus-devig tier, carries
projections on 694 since `#364`/`#365`, and took the per-book layout in `#408`.

A REDIRECT, NOT A DELETE. `cross_book.html` links here twice, `market_board_hub`
once, and the URL is bookmarkable. A 404 turns a retirement into an outage for
anyone holding the link. Sport and date carry across so the reader lands on the
slate they asked for.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client():
    from syndicate.app import app

    app.config.update(TESTING=True)
    return app.test_client()


def test_the_old_url_redirects_rather_than_404s(client):
    r = client.get("/market-board/books")
    assert r.status_code == 302, "a retirement must not become an outage for a bookmarked URL"
    assert "/mlb/market-board" in r.headers["Location"]


def test_sport_and_date_survive_the_redirect(client):
    # Landing on a different slate than the one asked for is its own bug.
    r = client.get("/market-board/books?sport=wnba&date=2026-08-12")
    loc = r.headers["Location"]
    assert "/wnba/market-board" in loc
    assert "date=2026-08-12" in loc


def test_an_unknown_sport_falls_back_rather_than_erroring(client):
    r = client.get("/market-board/books?sport=bogus")
    assert r.status_code == 302
    assert "/mlb/market-board" in r.headers["Location"]


def test_the_template_is_gone(client):
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    assert not (repo / "syndicate" / "templates" / "book_grid.html").exists(), (
        "the template still exists -- retiring the route while leaving the file "
        "invites a future route to resurrect the broken fair-value logic"
    )


def test_nothing_still_renders_the_retired_template():
    # A dangling `render_template("book_grid.html")` would be a 500, not a 404,
    # and would only surface when someone hit that route.
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    for path in (repo / "syndicate").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert 'render_template(\n                "book_grid.html"' not in text
        assert 'render_template("book_grid.html"' not in text


def test_the_board_is_named_betting_board():
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    tpl = (repo / "syndicate" / "templates" / "shared" / "layer1_board.html").read_text(encoding="utf-8")
    assert "Betting Board{% endblock %}" in tpl
    # And it must not still advertise a link to the page that no longer exists.
    assert "Book grid &rarr;" not in tpl and "Book grid →" not in tpl
