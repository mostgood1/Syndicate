"""De-vigged home-win probabilities from the soccer odds CSV, for anchoring.

WHY THIS EXISTS. `market_anchoring.anchor_ratings_to_market` is validated
(-40..-51% MAE vs a HELD-OUT bookmaker consensus on the EPL, non-circular) and
has never run: `build_soccer_artifacts.py` builds fixtures carrying only
`match_id`, `home_team` and `away_team`, and the anchor skips any fixture with
no `market_odds`. Wired as-is it is a **silent no-op** — the same shape as the
evaluation autorun that shipped, passed its tests, and had never executed.

So this is the missing input, not a new mechanism. It reads
`<league>/api/odds/game_odds_current.csv`:

    league,event_id,home_team,away_team,commence_time,market,side,line,price,book
    epl,082f74f...,Sunderland,Arsenal,2026-09-12T19:00:00Z,h2h,Arsenal,,-205,draftkings

--------------------------------------------------------------------------
TWO RULES HERE ARE PAID FOR, AND BOTH WERE BROKEN IN THIS REPO THIS MONTH
--------------------------------------------------------------------------

**AVERAGE IN PROBABILITY SPACE, NEVER ON THE AMERICAN SCALE.** `-205` and `+180`
are not on a linear scale and their mean is meaningless; the WNBA card path
averaged American prices and **43% of the resulting card prices were
impossible** (`[wnba-consensus-price]`). Every book's price is converted to an
implied probability first, and the mean is taken there.

**A PRICE STRICTLY INSIDE (-100, +100) IS NOT AN AMERICAN PRICE.** It is a parse
or averaging artefact, and coercing one invents a probability. Refused, counted,
never silently dropped.

De-vig is proportional across the three outcomes (home/draw/away sum to 1). That
is the same normalisation `market_anchoring.devig_decimal_odds` performs, done
here because our source is AMERICAN and its input is decimal — converting
American -> decimal -> back would round twice for no gain.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from syndicate.features.soccer.features.team_names import match_team_name

_H2H_MARKETS = {"h2h", "moneyline", "ml"}
_DRAW_LABELS = {"draw", "tie", "x"}


def american_to_probability(price: Any) -> float | None:
    """Implied probability of an American price, or None if it is not one.

    A value strictly inside (-100, 100) is refused rather than coerced: it
    cannot be an American price, so treating it as one manufactures a number.
    """
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if -100.0 < value < 100.0:
        return None
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def _side_of(row: Mapping[str, Any], home: str, away: str) -> str | None:
    """Which of home/draw/away this row prices, or None if it names neither team."""
    side = str(row.get("side") or "").strip()
    if not side:
        return None
    if side.casefold() in _DRAW_LABELS:
        return "draw"
    if side.casefold() == str(home or "").strip().casefold():
        return "home"
    if side.casefold() == str(away or "").strip().casefold():
        return "away"
    return None


def home_win_probability_by_event(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """De-vigged P(home win) per event_id, with the counts to audit it.

    Returns `{event_id: {"home_win_probability", "books", "refused_prices",
    "sides_present"}}`. An event missing any of the three sides is EXCLUDED —
    a two-way de-vig of a three-way market would systematically overstate both
    remaining sides, which is worse than having no anchor at all.
    """
    by_event: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    context: dict[str, dict[str, str]] = {}
    refused: dict[str, int] = defaultdict(int)

    for row in rows:
        if str(row.get("market") or "").strip().casefold() not in _H2H_MARKETS:
            continue
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        context.setdefault(event_id, {"home_team": home, "away_team": away})
        side = _side_of(row, home, away)
        if side is None:
            continue
        probability = american_to_probability(row.get("price"))
        if probability is None:
            refused[event_id] += 1
            continue
        by_event[event_id][side].append(probability)

    out: dict[str, dict[str, Any]] = {}
    for event_id, sides in by_event.items():
        present = {side for side in ("home", "draw", "away") if sides.get(side)}
        if present != {"home", "draw", "away"}:
            continue
        # Mean per side IN PROBABILITY SPACE, then proportional de-vig.
        means = {side: sum(values) / len(values) for side, values in sides.items()}
        overround = sum(means.values())
        if overround <= 0:
            continue
        out[event_id] = {
            "home_win_probability": means["home"] / overround,
            "books": max(len(values) for values in sides.values()),
            "refused_prices": refused.get(event_id, 0),
            "overround": overround,
            "home_team": context.get(event_id, {}).get("home_team", ""),
            "away_team": context.get(event_id, {}).get("away_team", ""),
        }
    return out


def _fuzzy_event_for(fixture: Mapping[str, Any], probabilities: Mapping[str, Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str]:
    """The priced event this fixture names, resolved through the repo's own
    team matcher. Returns (entry, reason) where reason names the refusal.

    WHY THIS STAGE EXISTS. The two id spaces never collide -- `match_id` is an
    ESPN event id, `event_id` in the odds CSV is an OddsAPI one -- so the join
    always fell through to an EXACT string compare on both team names, and the
    two feeds do not share a naming convention. Measured 2026-09-02 against
    production, 10 leagues over the live 7-day horizon: **56 of the 70 skipped
    fixtures named a priced event that `match_team_name` resolves**, against 14
    genuinely unpriced. `Sint-Truidense` vs `Sint Truiden`, `KAA Gent` vs
    `Gent`, `Royal Charleroi SC` vs `Charleroi`.

    BEST-OF-ALL-CANDIDATES, NOT PAIRWISE THRESHOLD, AND THAT DISTINCTION IS THE
    WHOLE SAFETY ARGUMENT. `match_team_name` is called ONCE against the full
    candidate list per side, so it returns the best match rather than the first
    name to clear 0.72. Both sides must resolve, and the resolved pair must
    identify EXACTLY ONE event -- two candidates is a refusal, not a coin flip.
    A wrong join here feeds a wrong market price into a ratings anchor, which is
    worse than no join at all, so ambiguity is counted and dropped.
    """
    home = str(fixture.get("home_team") or "")
    away = str(fixture.get("away_team") or "")
    if not home or not away:
        return None, "fixture_missing_team_name"

    home_names = sorted({str(row.get("home_team") or "") for row in probabilities.values() if row.get("home_team")})
    away_names = sorted({str(row.get("away_team") or "") for row in probabilities.values() if row.get("away_team")})
    matched_home = match_team_name(home, home_names)
    matched_away = match_team_name(away, away_names)
    if matched_home is None or matched_away is None:
        return None, "no_name_match"

    hits = [row for row in probabilities.values()
            if row.get("home_team") == matched_home and row.get("away_team") == matched_away]
    if len(hits) > 1:
        return None, "ambiguous_name_match"
    if not hits:
        # Each side matched something, but not the same fixture -- e.g. both
        # clubs are in the feed on different match-ups. Not a join.
        return None, "name_match_pair_disagreed"
    return hits[0], "fuzzy"


def attach_market_odds(fixtures: list[dict], probabilities: Mapping[str, Mapping[str, Any]]) -> dict:
    """Attach `market_odds` to fixtures that have a price, and COUNT the rest.

    The counts are the point. `anchor_ratings_to_market` silently `continue`s on
    a fixture with no `market_odds`, so without a published attached/skipped
    split the anchor can be entirely inert while everything downstream looks
    healthy. Mutates `fixtures` in place and returns the audit.

    Three join stages, tried in order and COUNTED SEPARATELY (`by_stage`) so a
    later regression in any one of them is attributable rather than showing up
    as a single number drifting down: the event id, an exact team-pair compare,
    then `_fuzzy_event_for`.
    """
    attached = 0
    skipped: list[str] = []
    by_stage: dict[str, int] = {"event_id": 0, "exact_pair": 0, "fuzzy": 0}
    refusals: dict[str, int] = {}
    for fixture in fixtures:
        event_id = str(fixture.get("match_id") or "").strip()
        entry = probabilities.get(event_id)
        stage = "event_id"
        if not entry:
            # match_id is synthesised when event_id is absent, so fall back to
            # the team pair rather than dropping a fixture the feed does cover.
            entry = next(
                (row for row in probabilities.values()
                 if row.get("home_team") == fixture.get("home_team")
                 and row.get("away_team") == fixture.get("away_team")),
                None,
            )
            stage = "exact_pair"
        if not entry:
            entry, reason = _fuzzy_event_for(fixture, probabilities)
            stage = "fuzzy"
            if entry is None:
                refusals[reason] = refusals.get(reason, 0) + 1
        if not entry:
            skipped.append(f"{fixture.get('home_team')} v {fixture.get('away_team')}")
            continue
        fixture["market_odds"] = {"home_win_probability": entry["home_win_probability"]}
        by_stage[stage] += 1
        attached += 1
    return {
        "fixtures": len(fixtures),
        "attached": attached,
        "skipped": len(skipped),
        "skipped_examples": skipped[:5],
        "priced_events": len(probabilities),
        "by_stage": by_stage,
        "skipped_reasons": refusals,
    }
