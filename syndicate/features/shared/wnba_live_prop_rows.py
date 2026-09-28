"""Join the live per-player capture to its pregame sim anchor, per stat.

PHASE 3(a) of live WNBA props, and the shape of it is a recorded user decision
`[2026-08-21]`. Phase 1 persists the live lines; phase 2 projects one stat from
one line; this pairs each live player with their pregame anchor and emits a row
per stat.

**IT NOW EMITS `liveModelProbOver`, AND ONLY BECAUSE THE ERROR WAS MEASURED.**
Phase 3(a) deliberately published a projection and no probability, because the
live remainder distribution was unmeasured and a probability off an unmeasured
estimator is the same act as pricing the un-backtested totals transform this
board refuses by name. Phase 3(b) removed that objection the honest way:
`scripts/grade_wnba_live_prop_projection.py` replayed ESPN play-by-play, drove
the SHIPPED projection at every scoring play and scored it against the official
final -- n=796 over 5 slates, the replay reconciling 100% against the official
boxscore on every one. `wnba_live_prop_probability` turns that measurement into
`P(final >= line)`; see it for the bucketed sigma and the three choices behind
it.

A ROW IS PRICED ONLY WHEN A LINE IS SUPPLIED for its `(player, market)`. A
probability needs something to be a probability ABOUT, and inventing a line
would price a market nobody quoted. Rows without one still carry
`liveProjectedStat` and say why they are unpriced.

THIS DOES NOT OPEN THE JOIN'S GATE. `attach_live_projections_for_sport` still
returns early on `sport != "mlb"`; that is phase 4 and a separate decision.
Emitting the field makes these rows ELIGIBLE, and the join's own
`prob_std_err`/`PRICEABLE_SIGMA` refusal still applies on top exactly as it does
for MLB.

MATCHING IS BY NAME, AND THE MISSES ARE COUNTED. The live capture carries
`player` + `team_tri`; the sim carries `player_name` under `sim.players.{home,
away}`. There is no shared id, so this normalises and joins on the name. That is
the same machinery whose 91% miss rate the prop join records
(`miss_no_market_alias` 903 of 989), so the counters here are deliberate: a
silent zero and a zero with a named cause need different fixes, and the first
has already cost this project a full investigation.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterable, Mapping

from syndicate.features.shared.wnba_live_prop_probability import (
    expected_remaining_minutes,
    grid_center_and_sd,
    live_prop_prob_over,
)
from syndicate.features.shared.wnba_live_prop_projection import project_live_player_stat

# (live-capture key, sim mean key, market label). Declared rather than derived:
# the capture and the sim use different vocabularies for the same stat
# (`threes_made` vs `threes_mean`), and a loop that guessed the mapping would
# silently drop whichever side it guessed wrong.
STAT_MAP: tuple[tuple[str, str, str], ...] = (
    ("pts", "pts_mean", "points"),
    ("reb", "reb_mean", "rebounds"),
    ("ast", "ast_mean", "assists"),
    ("threes_made", "threes_mean", "threes"),
)

# OUR LABEL -> THE BOARD'S MARKET KEY. Verified against production
# `/api/board/book-grid?sport=wnba` (player_points 45 rows, player_assists 21,
# player_rebounds 14, player_threes 8), NOT guessed.
#
# `_snapshot_market` reads `prop` first and the board speaks OddsAPI. Keying on
# anything else is `#412` exactly: `miss_no_market_alias = 1385 of 1385`, the
# join missing literally every row while the correct key sat in the next field.
# Markets the board carries but this cannot project (`player_double_double`,
# `player_points_rebounds_assists`, `player_triple_double`) are deliberately
# ABSENT rather than mapped to something close -- a wrong alias prices the wrong
# market, which is worse than not pricing it.
BOARD_MARKET_KEYS: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
}

# AN APOSTROPHE IS INTRA-WORD; A HYPHEN SEPARATES WORDS. They cannot share a
# rule. Caught by this module's own test: substituting a space for BOTH turned
# `A'ja Wilson` into `a ja wilson`, which matches nothing -- the player would
# have been silently absent from the board, which is exactly the name-join
# failure this file's counters exist to make visible. Apostrophes (straight and
# typographic) are DELETED; everything else non-alphanumeric becomes a space.
_APOSTROPHE = re.compile(r"['‘’ʼ]+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalize_name(value: Any) -> str:
    """Fold accents, drop punctuation, collapse spaces.

    Names arrive from two independent feeds. `A'ja Wilson` and `Aja Wilson`,
    `Nelson-Ododa` and `Nelson Ododa` must land on the same key or the player
    is simply absent from the board with no reason attached.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _APOSTROPHE.sub("", text.lower())
    text = _PUNCT.sub(" ", text.replace("-", " "))
    return " ".join(text.split())


def index_sim_players(sim_game: Any) -> dict[str, dict[str, Any]]:
    """`normalized name -> sim row`, across both sides of one game."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(sim_game, Mapping):
        return out
    players = sim_game.get("players")
    if not isinstance(players, Mapping):
        return out
    for side in ("home", "away"):
        rows = players.get(side)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            key = normalize_name(row.get("player_name"))
            if key and key not in out:
                out[key] = dict(row)
    return out


def build_live_prop_rows(
    live_players: Iterable[Mapping[str, Any]],
    sim_game: Any,
    *,
    game_minutes_remaining: Any = None,
    lines: Mapping[tuple[str, str], Any] | None = None,
    grid_markets: Iterable[str] = (),
    team_margins: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One row per (player, stat, line), plus the counters that make a zero readable.

    `grid_markets` `[2026-09-28, lane live-props-model-probability]`: for a listed
    market, price every half-point line within `GRID_SIGMAS` measured residual
    sigmas of the live projection, in ADDITION to the supplied line. The supplied
    line is the PREGAME consensus and live board lines move off it -- measured
    2026-09-27: the lens indexed 3-5 keys per build against 147-196 live board
    props, e.g. jackie young assists board 6.5 vs lens 8.5. The probability is the
    unchanged `live_prop_prob_over`, so a grid line is priced by exactly the rule
    a supplied line is. Default `()` is today's behaviour.

    ONLY list a market whose residual was MEASURED (`MEASURED_MARKETS` in
    `wnba_live_prop_probability`); widening an unmeasured market multiplies an
    assumption, not coverage. Each market's grid reaches 3 of ITS OWN sigmas.
    """
    grid = frozenset(str(m) for m in grid_markets or ())
    sim_index = index_sim_players(sim_game)
    rows: list[dict[str, Any]] = []
    players_seen = 0
    players_matched = 0
    players_unmatched: list[str] = []
    projected = 0
    priced_rows = 0
    withheld_by_reason: dict[str, int] = {}
    unpriced_by_reason: dict[str, int] = {}
    grid_rows = 0

    for player in live_players or ():
        if not isinstance(player, Mapping):
            continue
        players_seen += 1
        name = player.get("player")
        anchor = sim_index.get(normalize_name(name))
        if anchor is None:
            # NAMED, not dropped. An unmatched player is the failure mode this
            # join family has already paid for once.
            players_unmatched.append(str(name))
            continue
        players_matched += 1
        for live_key, mean_key, market in STAT_MAP:
            verdict = project_live_player_stat(
                current_stat=player.get(live_key),
                minutes_played=player.get("mp"),
                pregame_stat=anchor.get(mean_key),
                pregame_minutes=anchor.get("min_mean"),
                game_minutes_remaining=game_minutes_remaining,
            )
            row = {
                "player": name,
                "team_tri": player.get("team_tri"),
                "market": market,
                "current": verdict.get("current"),
                "minutes_played": verdict.get("minutes_played"),
                "minutes_remaining": verdict.get("minutes_remaining"),
                "pregame_mean": anchor.get(mean_key),
                "pregame_minutes": anchor.get("min_mean"),
                "liveProjectedStat": verdict.get("projected"),
                "rate": verdict.get("rate"),
                # The COUNT pricer's remaining minutes (a game-state model), which can
                # differ from `minutes_remaining` (the projection's rule) on purpose.
                "expected_remaining_minutes": expected_remaining_minutes(
                    anchor.get("min_mean"), player.get("mp"), game_minutes_remaining,
                    (team_margins or {}).get(str(player.get("team_tri") or "").strip().upper()),
                ),
                "basis": verdict.get("basis"),
                "unavailable_reason": verdict.get("unavailable_reason"),
            }
            # PHASE 3(b): the probability the prop join keys on, from the
            # MEASURED residual (see `wnba_live_prop_probability`). Emitted ONLY
            # when a line is supplied for this (player, market) -- a probability
            # needs something to be a probability ABOUT, and inventing a line
            # would price a market nobody quoted.
            line = None
            if lines:
                line = lines.get((normalize_name(name), market))
            line_set = [line]
            if market in grid:
                line_set = _grid_lines(
                    line,
                    projected=row["liveProjectedStat"],
                    current=row["current"],
                    minutes_remaining=verdict.get("minutes_remaining"),
                    market=market,
                    rate=row.get("rate"),
                    expected_minutes=row.get("expected_remaining_minutes"),
                )
                # Lines ADDED beyond the supplied one. A market that cannot be
                # gridded falls back to `[supplied]`, which may be `[None]` -- not a line.
                grid_rows += sum(1 for extra in line_set if extra is not None and extra != line)
            if row["liveProjectedStat"] is None:
                reason = str(verdict.get("unavailable_reason") or "unknown")
                withheld_by_reason[reason] = withheld_by_reason.get(reason, 0) + 1
            else:
                projected += 1
            base = row
            for line in line_set:
                row = dict(base)
                _price_row(row, line, verdict)
                if row.get("liveModelProbOver") is not None:
                    priced_rows += 1
                elif row["liveProjectedStat"] is not None:
                    reason = str(row.get("not_priced_reason") or "unknown")
                    unpriced_by_reason[reason] = unpriced_by_reason.get(reason, 0) + 1
                rows.append(row)

    return {
        "rows": rows,
        "players_seen": players_seen,
        "players_matched": players_matched,
        "players_unmatched": players_unmatched,
        "rows_projected": projected,
        "withheld_by_reason": withheld_by_reason,
        "priced": priced_rows,
        "unpriced_by_reason": unpriced_by_reason,
        # Rows ADDED by `grid_markets` beyond the supplied line. Reported beside
        # `priced` so a jump in priced rows is attributable to the grid.
        "grid_rows": grid_rows,
    }


# The grid's reach, in measured residual sigmas either side of the projection, and a
# hard cap per (player, market) so the published snapshot stays bounded: ~40 rows x
# ~20 players per game. 3 sigma covers >99% of where the final lands under the
# measured (tail-widened) normal; a line beyond it prices at ~0 or ~1 anyway.
GRID_SIGMAS = 3.0
GRID_MAX_LINES = 40


def _grid_lines(supplied: Any, *, projected: Any, current: Any, minutes_remaining: Any,
                market: str = "points", rate: Any = None, expected_minutes: Any = None) -> list[Any]:
    """The supplied line plus every half-point line near the projection, sorted.

    Lines at or below what is already banked are skipped: the over is decided and
    the join withholds it (`over_already_decided`) whatever is published. No
    projection or no measured sigma -> the supplied line alone, unchanged.
    """
    out: set[float] = set()
    if supplied is not None:
        out.add(supplied)
    # THIS market's priced distribution -- its centre and spread -- so the grid's reach
    # matches what prices it. For count markets that is the player-scaled NegBin
    # remainder (centred on banked + fitted mean), not the raw projection.
    placed = grid_center_and_sd(projected, current, minutes_remaining, market,
                                rate=rate, expected_minutes=expected_minutes)
    if placed is None or placed[1] <= 0.0:
        return sorted(out) if out else [supplied]
    center, sigma = placed
    try:
        banked = float(current) if current is not None else 0.0
    except (TypeError, ValueError):
        banked = 0.0
    low = max(center - GRID_SIGMAS * sigma, banked)
    high = center + GRID_SIGMAS * sigma
    candidate = math.floor(low) + 0.5
    grid: list[float] = []
    while candidate <= high:
        if candidate > banked:
            grid.append(candidate)
        candidate += 1.0
    if len(grid) > GRID_MAX_LINES:
        # Keep the lines NEAREST the projection -- where a live board quotes.
        grid = sorted(sorted(grid, key=lambda x: (abs(x - center), x))[:GRID_MAX_LINES])
    out.update(grid)
    return sorted(out)


def _price_row(row: dict[str, Any], line: Any, verdict: Mapping[str, Any]) -> None:
    """Stamp `line` and its measured-residual probability onto `row`."""
    priced = live_prop_prob_over(
        projected=row["liveProjectedStat"],
        line=line,
        minutes_remaining=verdict.get("minutes_remaining"),
        market=row.get("market") or "points",
        current=row.get("current"),
        rate=row.get("rate"),
        expected_minutes=row.get("expected_remaining_minutes"),
    )
    row["line"] = line
    row["residual_sigma"] = priced.get("residual_sigma")
    if priced.get("prob_over") is None:
        row["liveModelProbOver"] = None
        row["not_priced_reason"] = priced.get("unavailable_reason")
    else:
        row["liveModelProbOver"] = priced["prob_over"]
        row["not_priced_reason"] = None


def to_snapshot_live_props(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows in the shape `build_live_prop_index` reads off the lens snapshot.

    A SEPARATE VOCABULARY ON PURPOSE. This module's rows are internal
    (`player`, `market`, `liveProjectedStat`); the snapshot contract is
    `playerName` / `prop` / `liveProjection` / `liveModelProbOver`, and the
    index keys on `(player, market, line)` with `liveProjection` as the
    live-awareness evidence -- a row without it is skipped even when a
    probability is present. Translating here, once, keeps the two from drifting.

    Rows with no line, no projection or an unmappable market are DROPPED rather
    than emitted half-formed: the index counts a keyless row as
    `skipped_no_key`, which is a less useful signal than never claiming the row.
    """
    out: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        market_key = BOARD_MARKET_KEYS.get(str(row.get("market") or ""))
        if not market_key:
            continue
        if row.get("line") is None or row.get("liveProjectedStat") is None:
            continue
        out.append({
            "playerName": row.get("player"),
            "prop": market_key,
            "line": row.get("line"),
            "liveProjection": row.get("liveProjectedStat"),
            "liveModelProbOver": row.get("liveModelProbOver"),
            # THE ACTUAL-SO-FAR, AND IT WAS COMPUTED ALL ALONG. `current` is the
            # player's banked production for this market -- `project_live_player_stat`
            # is called with `current_stat=player[live_key]` and returns it as
            # `current`, which the internal row carries. It was simply not
            # translated here, so it died at the snapshot boundary while
            # `build_live_prop_index` read `actualSoFar` (then `actual`) two
            # files away and got None, and `layer2_board._live_projection_columns`
            # rendered a blank `actual` cell for every live WNBA prop.
            #
            # EMITTED UNDER THE SNAPSHOT VOCABULARY, not the internal one. This
            # function exists precisely because the two vocabularies are separate
            # (`player`/`market`/`liveProjectedStat` inside,
            # `playerName`/`prop`/`liveProjection` on the wire); adding `current`
            # verbatim would have been a third spelling nothing reads.
            #
            # A GENUINE ZERO MUST SURVIVE. A player who has scored 0 so far has
            # an actual of 0.0, not a missing one, and the consumer distinguishes
            # them (`layer2_board.py` parses this with `_as_float` for exactly
            # that reason). So this is a plain carry-through with no `or`
            # fallback, which would have collapsed 0.0 into null.
            "actualSoFar": row.get("current"),
            # Carried through so a refused row is still attributable on the
            # snapshot rather than only inside this process.
            "residualSigma": row.get("residual_sigma"),
            "notPricedReason": row.get("not_priced_reason"),
        })
    return out
