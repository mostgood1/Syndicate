"""`/api/ops/polymarket/slate` -- making the slate readable from web.

WHY THIS ENDPOINT AND NOT AN ALLOWLIST ENTRY. The obvious fix for "the slate is
invisible from ops" is to add it to `HOT_ARTIFACT_PATTERNS`. That would have
been an INERT no-op, and the test below pins the reason so nobody re-derives it:
both services run `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, so
`persist_game_slate` writes to the KEYVALUE STORE and never to disk, while the
export endpoint scans disk. The artifact was reachable from web all along --
what was missing was a reader.
"""

from __future__ import annotations

import json

import pytest

from syndicate.app import app


ADMIN = {"X-Admin-Token": "test-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _slate(markets):
    return {"fetched_at": 1.0, "markets": markets, "count": len(markets),
            "fetched_count": len(markets), "truncated": False, "dropped_for_size": 0}


def _install(monkeypatch, payload):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda *a, **k: payload,
        raising=False,
    )


def test_an_absent_slate_is_named_not_reported_as_empty(client, monkeypatch):
    """"No tick has written" must not read as "the venue lists nothing"."""
    _install(monkeypatch, None)
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is True
    assert body["slate"] is None
    assert body["reason"] == "no_slate_artifact_recorded"


def test_it_requires_the_admin_token(client):
    assert client.get("/api/ops/polymarket/slate").status_code in (401, 403)


def test_it_counts_by_venue_market_type(client, monkeypatch):
    _install(monkeypatch, _slate([
        {"slug": "mlbgame-mlb-bos-mia-2026-08-26", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
        {"slug": "mlbgame-mlb-col-wsh-2026-08-26", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
        {"slug": "astatc-lol-bam-gng-2026-08-20-game1", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP"},
    ]))
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is True
    assert body["by_venue_market_type"]["SPORTS_MARKET_TYPE_MONEYLINE"] == 2
    # PROP is counted as a market the venue sent, but must NOT appear in the
    # join cut -- it is deliberately out of scope for game lines, and merging
    # the two numbers is what makes "we dropped it" look like "they didn't
    # list it".
    assert body["by_venue_market_type"]["SPORTS_MARKET_TYPE_PROP"] == 1
    assert not any(k.endswith("|prop") for k in body["by_league_and_board_market"])


def test_an_unparseable_slug_is_counted_not_silently_dropped(client, monkeypatch):
    _install(monkeypatch, _slate([
        {"slug": "this-is-not-a-slug", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
    ]))
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["slug_unparseable"] == 1


def test_a_read_error_is_reported_not_raised(client, monkeypatch):
    """An ops read must not 500 -- it is the tool used when things are broken."""

    def boom(*a, **k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", boom, raising=False
    )
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is False
    assert "RuntimeError" in body["error"]


def test_the_two_truncation_facts_stay_separate(client, monkeypatch):
    """`truncated` and `dropped_for_size` answer different questions.

    "The venue had more than we asked for" is a bug; "we chose not to store the
    far end" is a budget decision. One number for both hides the first.
    """
    payload = _slate([])
    payload["truncated"] = True
    payload["dropped_for_size"] = 12
    _install(monkeypatch, payload)
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["truncated"] is True
    assert body["dropped_for_size"] == 12


# --------------------------------------------------------------------------
# LANE `venue-join-refusal-visibility` (2026-08-28)
# --------------------------------------------------------------------------


def test_the_reader_files_a_row_under_the_SAME_league_the_join_does(client, monkeypatch):
    """This endpoint's whole premise, finally true.

    Its docstring says it parses "with the join's OWN functions, not a local
    copy... a second parser here could disagree with the one that actually
    decides orders, and then this endpoint would describe a slate nobody joins
    against." It then called `_effective_league(parsed)` with the token set
    OMITTED -- the function's documented "no slate in hand" mode -- while
    `join_polymarket_to_board` passes `soccer_competition_tokens(markets)`.

    So the two disagreed in the direction that matters: a competition the JOIN
    reaches as `soccer` was reported here under its raw token. MEASURED
    2026-08-28, this endpoint reported `mls|h2h 30` and `epl|h2h 18` as
    separate leagues, which is why it could not be used to check the join's
    soccer coverage -- the only thing it exists for.

    Asserted as AGREEMENT with the join rather than against a hardcoded league,
    so the two cannot drift apart again without this failing.
    """
    from syndicate.features.shared import polymarket_board_join as join_mod
    import syndicate.features.shared.team_aliases as aliases

    # THE RESOLVERS ARE PINNED, and that is not decoration.
    #
    # `_soccer_alias_to_name` is DERIVED from the team artifacts under `data/`,
    # and `session_worktree.py open` excludes `data/` by default. In such a
    # tree every soccer alias map is empty, `mls` is never proven, and both
    # sides of this comparison answer "mls" -- so the test passes while
    # measuring nothing, against the fixed and the broken reader alike.
    # Verified: it did exactly that before these two lines were added.
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, name: None)
    monkeypatch.setattr(
        aliases,
        "soccer_fixture_clubs",
        # Slug is <away>-<home>: `atc-mls-tor-nyc-...` -> home=nyc, away=tor.
        lambda home, away: ("toronto fc", "new york city fc")
        if (home, away) == ("nyc", "tor")
        else None,
    )

    markets = [
        {
            "slug": "atc-mls-tor-nyc-2026-08-29-tor",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.40","0.60"]',
        }
    ]
    _install(monkeypatch, _slate(markets))

    # What the JOIN decides, from the same markets.
    tokens = join_mod.soccer_competition_tokens(markets)
    parsed = join_mod.parse_slug(markets[0]["slug"])
    join_league = join_mod._effective_league(parsed, tokens)

    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    reported = list(body["by_league_and_board_market"])
    assert reported == [f"{join_league}|h2h"], (
        f"reader said {reported}, join says {join_league!r} -- a reader that "
        "disagrees with the decider answers confidently and wrongly"
    )


def test_decode_refusals_are_split_by_whether_the_fixture_already_played(client, monkeypatch):
    """So `outcomes_count_mismatch: 372` stops being unanswerable.

    I read that counter, saw six sampled shapes dated 2026-08-15/16 at price
    `0.9900`, and called it a live soccer 3-way decode bug worth fixing. Six of
    372 is a sample, not a rate, and the two readings imply opposite work: a
    decode fix, or nothing at all. A refusal on a fixture that already played
    costs nothing; one on an upcoming fixture is lost coverage.
    """
    markets = [
        # Settled: two outcome names, one price. Costs nothing.
        {
            "slug": "atc-ligpor-bra-gil-2020-01-01-bra",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.9900"]',
        },
        # Upcoming and well-formed.
        {
            "slug": "atc-lg1-lil-psg-2099-01-01-lil",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.40","0.60"]',
        },
    ]
    _install(monkeypatch, _slate(markets))
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    cut = body["outcome_readability_by_reason_and_recency"]
    assert cut["outcomes_count_mismatch|past"] == 1
    assert cut["ok|upcoming"] == 1
    assert "outcomes_count_mismatch|upcoming" not in cut
