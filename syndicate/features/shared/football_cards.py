"""Card helpers shared by the two football modules (NFL and NCAAF).

WHY THIS FILE EXISTS. NCAAF's board was rebuilt in 2026-08 -- projections
published into the shared contract, a compact strip modelled on soccer's, a
state-aware live lens -- and NFL got none of it. Measured on production
2026-09-07 (web `81213a32`), the same afternoon, on the two served pages:

    surface                     NCAAF                  NFL
    compact card height         181px, uniform x51     643-1085px, 16 of 16
                                                       cards a different height
    crest <img> in the strip     102 (2 per card)       0
    card_variant                 ncaaf_main             shared_default
    shared_predictions cover     51/51                  0/16
    shared_predictions over      51/51                  0/16
    ESPN status on the card      "Final" / "14:40 - 3rd"  "Week 1" x16

The heights are the load-bearing number: a uniform height is direct evidence
that nothing wraps, and 16 distinct heights on 16 cards is direct evidence that
every card is sized by a different-length paragraph of prose. Both boards ran
the SAME dispatcher (`shared/_scoreboard_strip.html`); NCAAF reached the
football branch and NFL fell through to the generic one, because the branch is
selected by `card_variant` and nothing else.

THE RULE THIS FILE IS HERE TO KEEP. `model_engine_standard.md` and the NCAAF
work it came out of both say the same thing: ONE HELPER, N CALLERS -- a
per-site copy is how one caller silently keeps the old behaviour. NCAAF grew
three card-contract builders and a per-site copy of the projection block was
exactly how `shared_predictions` stayed null on 51/51 cards while the numbers
sat on the card in `metrics`. Two SPORTS with two copies is the same failure
one level up, so the parts that are genuinely identical live here and both
sports call them.

WHAT IS NOT HERE, deliberately: anything whose CONTENT differs between the
codes. Team context (returning production, portal, conference) is NCAAF's and
has no NFL analogue; the projection engines, the market capture and the week
model are all per-sport. Only the presentation math is shared.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE


__all__ = [
    "cover_probability",
    "football_market_tiles",
    "football_shared_predictions",
    "format_kickoff_label",
    "safe_float",
]


def safe_float(value: Any) -> float | None:
    """`float(value)` or None -- never an exception, never a NaN/inf.

    A non-finite value reaching a card is worse than an absent one: it
    serialises to JSON as `NaN`, which is not valid JSON, and every downstream
    reader either throws or silently coerces it.
    """
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def format_kickoff_label(value: Any) -> str:
    """Human kickoff string for a card, in the platform's display timezone.

    Lifted verbatim from `ncaaf/cards.py:_format_kickoff_label`, which records
    why it exists: measured 2026-08-14 on production, NCAAF cards rendered
    `KICKOFF 2026-08-29T16:00:00.000Z` -- the raw schedule value reaching the
    UI unformatted.

    This is deliberately a SEPARATE key from `kickoff` rather than a reformat
    in place. `kickoff` is parsed as DATA downstream --
    `ncaaf/betting_card.py:_kickoff_date_and_label` calls
    `datetime.fromisoformat` on exactly that field to build its per-day
    grouping -- so formatting it at the producer would trade a cosmetic defect
    for a broken betting card.

    Central, because that is what every other display surface in this repo uses
    (`features/shared/timezone.py`, `SYNDICATE_BOARD_TZ`). Times are assembled
    with portable strftime directives only: `%-I`/`%-d` are POSIX-only and
    raise on Windows, where this also runs.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL_TIMEZONE)
    local = parsed.astimezone(CENTRAL_TIMEZONE)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    zone = local.strftime("%Z") or "CT"
    return (
        f"{local.strftime('%a')} {local.strftime('%b')} {local.day}, "
        f"{hour}:{local.strftime('%M')} {meridiem} {zone}"
    )


def cover_probability(*, line: float, mean: float | None, stdev: float | None) -> float | None:
    """P(actual > line) under a Normal(mean, stdev) model.

    Used for both "home covers this spread" and "this game goes over this
    total". Returns None when there is no real distribution to draw the
    probability from, rather than fabricating one from the point estimate
    alone: a raw margin/total point value (57.9 projected points) is not a
    probability and must never be dropped into a 0-1 field the board renders
    as a percentage.
    """
    if mean is None or stdev is None or stdev <= 0:
        return None
    return 1.0 - statistics.NormalDist(mean, stdev).cdf(line)


def football_shared_predictions(
    projection: Any,
    *,
    market_margin: Any = None,
    market_total: Any = None,
) -> dict[str, Any]:
    """The SHARED contract's `predictions` block for a football projection.

    `publication_adapter._shared_predictions` reads `game["predictions"]`
    FIRST, ahead of `sim.score`, `score` and `sim.periods.full`. Both football
    modules own a projection object carrying `home_score_mean`,
    `away_score_mean`, `margin_mean`, `total_mean`, `margin_stdev`,
    `total_stdev` and `home_win_rate`, so both can publish the same block.

    MEASURED 2026-09-07 on the served `/nfl/api/cards`, all 16 week-1 cards:

        shared_predictions.probabilities.home_cover   null  |  markets.spread.home  -3.5
        shared_predictions.probabilities.total_over   null  |  markets.total.line   44.5

    -- so the board carried a real book line AND a real model distribution and
    published no probability against either. NFL's `sim.periods.full` fallback
    supplied the four MEANS, which is why this reads as a half-populated block
    rather than an empty one, and why it was easy to miss.

    Market lines are OPTIONAL because only some builders have them in scope.
    Without them the means still publish and only the cover/over probabilities
    stay None, which is honest: absent must stay absent, never a neutral 0.5.

    TOP LEVEL, not inside a sport block. NCAAF's first cut of this put the
    result inside `ncaaf_card`, where nothing reads it -- production deployed
    clean and still served 0/51 non-null means, because the structural test
    asserted the builders CALL the helper and never WHERE the result lands.
    """
    if projection is None:
        return {}
    margin_mean = safe_float(getattr(projection, "margin_mean", None))
    total_mean = safe_float(getattr(projection, "total_mean", None))
    margin_stdev = safe_float(getattr(projection, "margin_stdev", None))
    total_stdev = safe_float(getattr(projection, "total_stdev", None))
    home_mean = safe_float(getattr(projection, "home_score_mean", None))
    away_mean = safe_float(getattr(projection, "away_score_mean", None))
    home_win = safe_float(getattr(projection, "home_win_rate", None))

    home_cover = away_cover = total_over = total_under = None
    margin_line = safe_float(market_margin)
    total_line = safe_float(market_total)
    if margin_line is not None:
        home_cover = cover_probability(line=margin_line, mean=margin_mean, stdev=margin_stdev)
        if home_cover is not None:
            away_cover = round(1.0 - home_cover, 6)
    if total_line is not None:
        total_over = cover_probability(line=total_line, mean=total_mean, stdev=total_stdev)
        if total_over is not None:
            total_under = round(1.0 - total_over, 6)

    return {
        "home_mean": home_mean,
        "away_mean": away_mean,
        "margin_mean": margin_mean,
        "total_mean": total_mean,
        # The DISTRIBUTION, not just the point estimate. `_shared_predictions`
        # does not read these, but the market board and the live re-sim do, and
        # a consumer that has the stdev can price a line the card never saw.
        "margin_stdev": margin_stdev,
        "total_stdev": total_stdev,
        "probabilities": {
            "home_win": home_win,
            "away_win": round(1.0 - home_win, 6) if home_win is not None else None,
            "home_cover": home_cover,
            "away_cover": away_cover,
            "total_over": total_over,
            "total_under": total_under,
        },
    }


def football_market_tiles(
    *,
    home_team: Any,
    away_team: Any,
    market_margin: Any = None,
    market_total: Any = None,
    market_book_count: Any = 0,
    market_source: Any = None,
    model_margin: Any = None,
    model_total: Any = None,
    home_win_rate: Any = None,
) -> list[dict[str, Any]]:
    """The four header tiles: the MODEL against the MARKET, on both codes.

    Generalised out of `ncaaf/cards.py:_smartsim2_standalone_market_tiles`,
    whose own comment states the reason for the shape: two of the four tiles
    used to be metadata ("Source: SmartSim 2.0", a book count), so a card could
    carry a full projection and a full market line and show the reader neither
    of them side by side. MLB's card is the reference -- `cards-market-row`
    puts the comparison above the fold.

    NFL had the mirror-image version of the same defect, measured on the served
    `/nfl/api/cards` 2026-09-07: its four tiles were `Home mean / Away mean /
    Projected spread / Win probability`, which are BYTE-IDENTICAL to that
    card's `metrics` list rendered directly above them. Four tiles of the
    model restating itself, on a card whose payload already carried
    `markets.spread.home -3.5` and `markets.total.line 44.5`.

    SIGN CONVENTION, stated because `state.md` records a whole NFL analysis
    lost to it: BOTH margins are HOME-RELATIVE and positive means the home side
    is favoured. The edge is model minus market, so positive = the model likes
    the HOME side more than the book does. A book's own home spread is the
    NEGATIVE of this (-3.5 = home favoured by 3.5), so a caller passing a book
    spread straight through would produce entirely plausible numbers pointing
    at the wrong team.

    Every tile says what it does not have in words ("No line", "No book quoted
    yet") rather than a dash, which reads as a broken tile.
    """
    margin = safe_float(market_margin)
    total = safe_float(market_total)
    try:
        books = int(market_book_count or 0)
    except (TypeError, ValueError):
        books = 0

    if margin is None:
        spread_title, spread_sub = "No line", "No book quoted yet"
    else:
        # Shown from the FAVOURITE's side, which is how a spread is read aloud.
        favourite = home_team if margin > 0 else away_team
        spread_title = "Pick'em" if margin == 0 else f"{favourite} -{abs(margin):.1f}"
        spread_sub = f"Market spread - {books} book{'s' if books != 1 else ''}"

    model_margin_value = safe_float(model_margin)
    model_total_value = safe_float(model_total)

    if model_margin_value is None:
        spread_model_sub = "No model spread"
    else:
        model_fav = home_team if model_margin_value > 0 else away_team
        model_spread_text = (
            "Pick'em" if model_margin_value == 0 else f"{model_fav} -{abs(model_margin_value):.1f}"
        )
        if margin is None:
            spread_model_sub = f"Model {model_spread_text}"
        else:
            spread_model_sub = f"Model {model_spread_text} · {model_margin_value - margin:+.1f} vs market"

    if model_total_value is None:
        total_model_sub = "No model total"
    elif total is None:
        total_model_sub = f"Model {model_total_value:.1f}"
    else:
        total_model_sub = f"Model {model_total_value:.1f} · {model_total_value - total:+.1f} vs market"

    home_win = safe_float(home_win_rate)
    if home_win is None:
        win_title, win_sub = "No model", "Win probability unavailable"
    else:
        win_side = home_team if home_win >= 0.5 else away_team
        win_title = f"{win_side} {max(home_win, 1.0 - home_win) * 100:.0f}%"
        win_sub = "Model win probability"

    return [
        {
            "label": "Spread",
            "title": spread_title,
            "sub": spread_model_sub if model_margin_value is not None else spread_sub,
        },
        {
            "label": "Total",
            "title": f"{total:.1f}" if total is not None else "No line",
            "sub": total_model_sub
            if model_total_value is not None
            else ("Market total" if total is not None else "No book quoted yet"),
        },
        {"label": "Win probability", "title": win_title, "sub": win_sub},
        {
            "label": "Books",
            "title": str(books) if books else "-",
            "sub": str(market_source or "No market capture"),
        },
    ]
