"""NFL player props -- Layer 1 inventory rows (folded into
syndicate.features.nfl.cards.build_nfl_market_board) and a Layer 2 ranked
"props ladder" page, both built on real season-to-date player rates
(syndicate.features.nfl.player_stats) rather than a trained model -- see
that module's docstring and this session's plan notes for why (no
NBA/WNBA-style trained per-player model exists or is being built here).

Real player-prop ODDS (data/nfl_source/oddsapi_player_props_{season}_wk{week}.csv)
are populated for very few weeks (the-odds-api's live-odds-only fetch
script has no historical-backfill capability) -- both entry points here
degrade gracefully to empty output for any week without real rows, rather
than erroring or fabricating.
"""

from __future__ import annotations

import csv
import math
import os
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nfl.player_stats import STAT_KEYS
from syndicate.features.nfl.game_context import favoured_by_delta, implied_total_ratio
from syndicate.features.nfl.player_stats import anytime_td_rate, player_team_by_week
from syndicate.features.nfl.player_stats import player_rate
from syndicate.features.nfl.player_stats import resolve_player_id
from syndicate.features.nfl.sources import nfl_source_roots
from syndicate.features.nfl.sources import nfl_props_path
from syndicate.features.nfl.sources import nfl_roster_snapshot_path
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.rank_board import build_rank_page_context

_NFL_PROP_MARKET_TO_STAT: dict[str, str] = {
    "Passing Yards": "passing_yards",
    "Passing Attempts": "passing_attempts",
    "Passing TDs": "passing_tds",
    "Rushing Yards": "rushing_yards",
    "Rushing Attempts": "rushing_attempts",
    "Receptions": "receptions",
    "Anytime TD": "anytime_td",
    # Added 2026-08-03, when this map was found to be dropping two markets the
    # fetcher requested. CORRECTION 2026-08-20: the note here used to say "real
    # odds rows for these two markets reached the CSV and were discarded" --
    # they never did. The keys the fetcher asked OddsAPI for were themselves
    # invalid (`player_rec_yds`, `player_interceptions`; the real keys are
    # `player_reception_yds` and `player_pass_interceptions`), so both markets
    # 422'd at the API and no row was ever produced to drop. Adding them here
    # was still correct -- it is what makes them usable now that the fetcher
    # asks for keys that exist.
    "Receiving Yards": "receiving_yards",
    "Interceptions": "interceptions",
}


def nfl_props_available_weeks(season: int) -> list[int]:
    """Weeks that actually have real (non-empty) player-prop rows -- most
    weeks are header-only stubs (see module docstring), so this is NOT
    the same as "every oddsapi_player_props_*.csv file that exists on
    disk"."""
    import re

    # `#441`: globbing ONE root -- and specifically the one
    # `default_nfl_source_root()` picks by probing for `upcoming_recs_*.csv` --
    # enumerated the ephemeral CHECKOUT. A week is only visible there if git
    # happens to track a stub for it, so a week captured to the mounted disk
    # after the last mirror refresh could never be listed, no matter how much
    # real market it held. Union the candidate roots instead; the content check
    # below is what decides, and `_nfl_raw_player_props` now resolves per file.
    weeks: list[int] = []
    for root in nfl_source_roots():
        try:
            paths = list(root.glob(f"oddsapi_player_props_{season}_wk*.csv"))
        except OSError:
            continue
        for path in paths:
            match = re.search(r"_wk(\d+)\.csv$", path.name)
            if not match:
                continue
            week = int(match.group(1))
            if week in weeks:
                continue
            if _nfl_raw_player_props(season, week):
                weeks.append(week)
    return sorted(set(weeks))


def nfl_props_key(away_full_name: str, home_full_name: str) -> str:
    return f"{away_full_name.strip()}|{home_full_name.strip()}"


def _props_path(season: int, week: int) -> Path:
    """`#441`, fourth call site -- see `nfl_props_path`'s docstring.

    This used to be `default_nfl_source_root() / ...`, which resolves a root by
    probing for the UNRELATED `upcoming_recs_*.csv` family. git ships 5 of those
    and the mounted disk has none, so it always chose the ephemeral checkout --
    where this same file is tracked as a 5-BYTE HEADER-ONLY STUB. The real
    42,753-byte week-1 capture on the mounted disk was never read by anything.
    """
    return nfl_props_path(season, week)


@lru_cache(maxsize=16)
def _nfl_raw_player_props(season: int, week: int) -> tuple[dict[str, Any], ...]:
    """Real quoted player-prop rows for this week -- () for any week the
    real odds feed was never populated for (the common case today, not an
    error)."""
    path = _props_path(season, week)
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(row for row in csv.DictReader(handle) if row.get("player") and row.get("market"))
    return rows


def _best_price_player_props(season: int, week: int) -> list[dict[str, Any]]:
    """One row per selection, at the BEST price any book quoted.

    THE COMPATIBILITY SEAM for the multi-book capture. The CSV now carries every
    bookmaker (see `fetch_nfl_oddsapi_props_local.parse_events_to_rows`), which
    is what price shopping needs -- but every consumer of
    `nfl_props_rows_for_week` was written against a file that held exactly one
    book, and would otherwise start counting the same bet once per book. The ROI
    report's 64,007-bet denominator is the reading that would have moved most,
    and a denominator that changes for a reason unrelated to the thing being
    measured is how a model looks like it improved.

    Best price is chosen PER SIDE independently: the book with the best `over`
    is frequently not the book with the best `under`, and taking both from one
    row would quietly re-impose the single-book choice this change removes.

    Higher american odds pay more on the same stake on both sides of zero, so
    `max` is correct without converting to decimal.
    """
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _nfl_raw_player_props(season, week):
        player = str(row.get("player") or "").strip()
        market = str(row.get("market") or "").strip()
        if not player or not market:
            continue
        line = _safe_float(row.get("line"))
        key = (player, market, "" if line is None else f"{line:g}")
        current = best.get(key)
        if current is None:
            best[key] = dict(row)
            continue
        for side in ("over_price", "under_price"):
            incoming = _safe_float(row.get(side))
            if incoming is None:
                continue
            held = _safe_float(current.get(side))
            if held is None or incoming > held:
                current[side] = row.get(side)
                current[f"{side}_book"] = row.get("book")
    return list(best.values())


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# `#471` defect 1: `_nfl_prop_model_probability`'s plain Normal-CDF cover
# probability is overconfident near its own mean (predicts ~50% cover
# where NFL's real, right-skewed box-score distributions actually cover
# ~37-44%) -- a Normal is symmetric by construction and real yardage/count
# stats have a hard floor at 0 plus occasional big games, so mean >
# median. `scripts/compare_nfl_cover_probability_models.py` measured that
# a PURE log-normal correction (method-of-moments, same mean/stdev inputs)
# OVERCORRECTS on 4 of 8 markets -- the mid-decile gap often flips sign
# and grows rather than shrinks. `scripts/calibrate_nfl_cover_probability_
# blend.py` found the right answer is a PER-MARKET BLEND weight `w` in
# [0, 1] between the current Normal probability and the log-normal one,
# with a closed-form Brier-minimizing solution (Brier is convex in a
# linear blend of two fixed probabilities), TUNED out-of-sample (selected
# on 2022-2023, only ever reported on 2024-2025 -- never re-selected
# there): passing_attempts got the largest correction (w=1.0, clipped from
# an unclipped optimum of 1.14 -- the data wanted MORE than pure
# log-normal, capped at the model actually validated), receptions/
# receiving_yards the smallest real ones (w=0.137/0.216). `passing_tds`
# and `interceptions` showed NO real out-of-sample benefit (improvement
# -0.0009 and -0.0002, both roughly noise-sized next to the ~+0.002 to
# +0.006 improvements elsewhere) and are deliberately left at w=0 (today's
# Normal-only behavior) rather than shipping a fitted correction that
# didn't generalize. Full sweep: reports/nfl_cover_probability_blend_
# calibration.json.
_COVER_PROBABILITY_BLEND_WEIGHT: dict[str, float] = {
    "passing_yards": 0.689,
    "passing_attempts": 1.0,
    "passing_tds": 0.0,
    "rushing_yards": 0.573,
    "rushing_attempts": 0.550,
    "receptions": 0.137,
    "receiving_yards": 0.216,
    "interceptions": 0.0,
}


def _lognormal_params_from_moments(mean: float, stdev: float) -> tuple[float, float] | None:
    """Method-of-moments fit: the (mu, sigma) of the log-normal
    distribution with the SAME mean and variance `player_rate` already
    computes -- no new upstream data needed. None when undefined: mean<=0
    (can only happen if a player's ENTIRE prior sample for this stat is
    0 -- e.g. a pure rusher's passing_yards -- no log-normal has that
    mean) or the moment equations degenerate."""
    if mean is None or mean <= 0 or stdev is None or stdev <= 0:
        return None
    variance = stdev * stdev
    sigma_sq = math.log(1.0 + variance / (mean * mean))
    if sigma_sq <= 0:
        return None
    mu = math.log(mean) - sigma_sq / 2.0
    return mu, math.sqrt(sigma_sq)


def _lognormal_cover_probability(mean: float, stdev: float, line: float) -> float | None:
    if line <= 0:
        return None  # no real NFL prop line is <= 0; caller falls back to the Normal-only probability
    params = _lognormal_params_from_moments(mean, stdev)
    if params is None:
        return None
    mu, sigma = params
    z = (math.log(line) - mu) / sigma
    return 1.0 - statistics.NormalDist(0.0, 1.0).cdf(z)


def _nfl_prop_model_probability(*, stat: str, mean: float | None, stdev: float | None, n: int, line: float | None) -> float | None:
    """Real season-to-date rate, converted to a probability -- a blended
    Normal/log-normal cover probability for count/yardage stats with a
    real quoted line (see `_COVER_PROBABILITY_BLEND_WEIGHT`'s comment for
    why it's a blend, not either model alone), or the player's own
    per-game hit rate directly for anytime_td (a one-sided market with no
    line -- the rate itself IS the probability of scoring, no distribution
    needed). For anytime_td, `mean` is expected to already be the SHRUNK
    rate (`player_stats.anytime_td_rate`, not the raw `player_rate`) --
    see `#471`: the raw MLE rate reads 0% for a player with 2-4 scoreless
    games, when the real hit rate for that exact bucket is ~13-14%. This
    function stays a thin pass-through/clamp for anytime_td either way;
    the shrinkage itself lives in player_stats.py where the
    population-level prior is computed."""
    if n < 2 or mean is None:
        return None
    if stat == "anytime_td":
        return max(0.0, min(1.0, mean))
    if line is None or stdev is None or stdev <= 0:
        return None
    normal_prob = 1.0 - statistics.NormalDist(mean, stdev).cdf(line)
    weight = _COVER_PROBABILITY_BLEND_WEIGHT.get(stat, 0.0)
    if weight <= 0.0:
        return normal_prob
    lognormal_prob = _lognormal_cover_probability(mean, stdev, line)
    if lognormal_prob is None:
        return normal_prob  # log-normal undefined for this row (e.g. mean<=0) -- fall back rather than guess
    return (1.0 - weight) * normal_prob + weight * lognormal_prob


def _nfl_prop_join_market_key(stat: str, player_name: str) -> str:
    """The DISPLAY stat ("receptions", "anytime_td") is shared by every
    player who has that prop -- every player on the board legitimately has
    their own anytime_td row simultaneously. If that shared stat were used
    directly as the join key, market_inventory.join_odds_to_sim's
    needs-resim check ("does a DIFFERENT entity have sim coverage for this
    exact market?") would misfire for every player whose own rate didn't
    resolve, as soon as ANY other player at the same game had one -- same
    real bug class MLB's _mlb_prop_join_market_key was written to fix for
    hitter RBI props (confirmed empirically there: 56 false "needs resim"
    rows from two hitters sharing a market label). Disambiguate the JOIN
    key by the player themselves (never the display label, which is
    relabeled back after the join via nfl_prop_display_stat) -- no
    reliable "slot" concept exists for NFL skill-position props the way
    MLB's starting-pitcher side does, so every player simply gets their
    own slot, same as MLB's hitter-prop case."""
    return f"{stat}::{player_name.strip().casefold()}"


def nfl_prop_display_stat(market_key: str) -> str:
    """Strips the ::player disambiguator back off a joined row's market
    field -- the inverse of _nfl_prop_join_market_key, called once after
    join_odds_to_sim runs."""
    return str(market_key or "").split("::", 1)[0]


# `#471` follow-up: per-market game-context coefficients, FITTED on 2023-2024
# and reported on a 2025 holdout by `scripts/fit_nfl_props_game_context.py`.
# (alpha, beta) in `mean * ratio**alpha * exp(beta * spread_delta)`, where both
# ratio and delta are normalised against the PLAYER'S OWN history -- see
# game_context.py for why that self-normalisation is what stops this
# double-counting an effect the rolling mean already absorbed
# (model_engine_standard.md 4.4).
#
# Measured, paired on the 16,906 bets both variants graded:
#   baseline      hit 49.39%  brier 0.30273  ROI -7.44%
#   game context  hit 50.05%  brier 0.30054  ROI -6.26%
#
# TWO MARKETS SHIP UNCHANGED AT (0.0, 0.0), each for a stated reason -- the same
# discipline `#471`'s blend fix used when a market showed no real OOS benefit:
#
#   rushing_attempts  the ONE market whose holdout MAE got WORSE (+0.0030), and
#                     its fitted alpha was ~0.00 anyway. Carries are driven by
#                     game script, not scoring environment.
#   anytime_td        THE FIT AND PRODUCTION USE DIFFERENT ESTIMATORS. The fit
#                     ran on the raw per-player rate; this module uses `#471`'s
#                     Gamma-Poisson SHRUNK `anytime_td_rate`. An alpha of 1.20
#                     fitted against the raw rate is not a coefficient for the
#                     shrunk one, and shipping it would apply a number nothing
#                     measured. Needs a re-fit against the shrunk estimator.
_NFL_GAME_CONTEXT_PARAMS: dict[str, tuple[float, float]] = {
    "passing_yards": (0.40, -0.005),
    "passing_attempts": (0.20, -0.010),
    "passing_tds": (0.80, -0.005),
    "interceptions": (0.60, -0.020),
    "rushing_yards": (0.20, 0.010),
    "rushing_attempts": (0.0, 0.0),
    "receptions": (0.30, -0.005),
    "receiving_yards": (0.60, -0.010),
    "anytime_td": (0.0, 0.0),
}


def _nfl_game_context_enabled() -> bool:
    raw = os.environ.get("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "on")
    return str(raw).strip().lower() not in {"0", "off", "false", "no"}


def nfl_game_context_multiplier(season: int, week: int, player_id: str, stat: str) -> float:
    """Multiplier on a player's projected mean for THIS week's game context.

    Returns exactly 1.0 -- a real no-op -- when the feature is off, when the
    market ships unchanged, or when the context cannot be resolved. That last
    case is a deliberate choice and not a neutral default in the sense
    model_engine_standard.md 4.2 warns about: `implied_total_ratio` returns None
    rather than 1.0 for an unknown lookup, so "unfed" is distinguishable HERE at
    the one place that can decide what to do about it, instead of being smeared
    into every downstream number.
    """
    if not _nfl_game_context_enabled():
        return 1.0
    alpha, beta = _NFL_GAME_CONTEXT_PARAMS.get(stat, (0.0, 0.0))
    if alpha == 0.0 and beta == 0.0:
        return 1.0
    by_week = player_team_by_week(season).get(player_id) or {}
    prior_weeks = [w for w in by_week if w < int(week)]
    if len(prior_weeks) < 2:
        return 1.0
    ratio = implied_total_ratio(season, week, by_week, prior_weeks=prior_weeks)
    delta = favoured_by_delta(season, week, by_week, prior_weeks=prior_weeks)
    if ratio is None or delta is None:
        return 1.0
    return float(ratio ** alpha) * math.exp(beta * float(delta))


def nfl_props_rows_for_week(season: int, week: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Real odds + real-rate-based sim rows for every quoted player prop
    this week. Entity = player's real full name (as quoted by the odds
    feed); market = the stat key disambiguated by player (see
    _nfl_prop_join_market_key). A real quoted line is always included
    even when the player's rate can't be resolved yet (too few games,
    or a name the pbp data has no record of) -- never silently dropped."""
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []
    for row in _best_price_player_props(season, week):
        stat = _NFL_PROP_MARKET_TO_STAT.get(str(row.get("market") or "").strip())
        if stat is None:
            continue
        player_name = str(row.get("player") or "").strip()
        join_market = _nfl_prop_join_market_key(stat, player_name)
        # Keyed by real team full names (not a game_pk) -- this feed carries
        # no game id of its own, and callers that need to attach these rows
        # to a specific game-board entry (build_nfl_market_board) match on
        # this same away/home pair, then remap to that game's real game_id
        # before joining -- see nfl_props_key().
        game_id = nfl_props_key(str(row.get("away_team") or ""), str(row.get("home_team") or ""))
        line = _safe_float(row.get("line"))
        over_odds = _safe_float(row.get("over_price"))
        under_odds = _safe_float(row.get("under_price"))

        if stat == "anytime_td":
            if over_odds is not None:
                odds_rows.append({"game_id": game_id, "market": join_market, "period": "full_game", "entity": player_name, "side": "over", "odds": over_odds, "market_type": "prop"})
        else:
            if over_odds is not None:
                odds_rows.append({"game_id": game_id, "market": join_market, "period": "full_game", "entity": player_name, "side": "over", "line": line, "odds": over_odds, "market_type": "prop"})
            if under_odds is not None:
                odds_rows.append({"game_id": game_id, "market": join_market, "period": "full_game", "entity": player_name, "side": "under", "line": line, "odds": under_odds, "market_type": "prop"})

        player_id = resolve_player_id(season, player_name)
        if player_id is None:
            continue
        if stat == "anytime_td":
            # `#471` shrinkage -- see player_stats.anytime_td_rate's
            # docstring. stdev is meaningless for this market
            # (_nfl_prop_model_probability's anytime_td branch never reads
            # it), so it is not computed here.
            mean, n = anytime_td_rate(season, week, player_id)
            stdev = None
        else:
            mean, stdev, n = player_rate(season, week, player_id, stat)
        # Game context. Applied to the MEAN only: the rolling stdev describes
        # this player's own game-to-game spread and a scoring-environment shift
        # is not evidence about that dispersion.
        if mean is not None:
            mean = float(mean) * nfl_game_context_multiplier(season, week, player_id, stat)
        model_prob = _nfl_prop_model_probability(stat=stat, mean=mean, stdev=stdev, n=n, line=line)
        if model_prob is None:
            continue
        sim_rows.append({
            "game_id": game_id, "market": join_market, "period": "full_game", "entity": player_name,
            "sim_projection": model_prob, "projected_value": mean, "sim_source": "nfl_season_rate",
        })
    return odds_rows, sim_rows


def _format_stat_label(stat: str) -> str:
    return {value: key for key, value in _NFL_PROP_MARKET_TO_STAT.items()}.get(stat, stat.replace("_", " ").title())


def build_nfl_props_page_context(season: int, week: int) -> dict[str, Any]:
    """Ranked props ladder -- one card per real quoted prop with a
    resolved real-rate model probability, sorted by edge (model
    probability minus the odds' own single-sided implied probability --
    labeled as market-implied, not no-vig, same honesty
    syndicate.features.mlb.hr_targets.py already uses for the same
    reason)."""
    odds_rows, sim_rows = nfl_props_rows_for_week(season, week)
    inventory = join_odds_to_sim(odds_rows, sim_rows)

    cards: list[dict[str, Any]] = []
    for row in inventory:
        sim_projection = row.get("sim_projection")
        odds = row.get("odds")
        if sim_projection is None or odds is None:
            continue
        implied_prob = (100.0 / (odds + 100.0)) if odds > 0 else ((-odds) / ((-odds) + 100.0))
        edge = sim_projection - implied_prob
        stat_label = _format_stat_label(nfl_prop_display_stat(row.get("market")))
        side = str(row.get("side") or "").title()
        line = row.get("line")
        line_text = f"{line:g}" if isinstance(line, (int, float)) else "-"
        cards.append({
            "title": f"{row.get('entity')} — {stat_label}",
            "eyebrow": "NFL Props",
            "badge": f"{edge:+.1%} edge",
            "meta": f"{side} {line_text}" if line is not None else side,
            "metrics": [
                {"label": "Real rate model", "value": f"{sim_projection:.1%}"},
                {"label": "Market implied", "value": f"{implied_prob:.1%}"},
                {"label": "Real odds", "value": f"{odds:+.0f}" if odds is not None else "-"},
                {"label": "Season-to-date value", "value": f"{row.get('projected_value'):.1f}" if row.get("projected_value") is not None else "-"},
            ],
            "summary": f"{row.get('entity')}'s real season-to-date rate implies {sim_projection:.1%} on this {stat_label.lower()} line, vs. a market-implied {implied_prob:.1%}.",
            "list_items": [],
            "_edge": edge,
        })
    cards.sort(key=lambda card: card.pop("_edge"), reverse=True)

    return build_rank_page_context(
        selected_date=f"{season}-01-{week:02d}",
        route_path="/nfl/props",
        intro_title="NFL Props",
        intro_body="Real quoted player-prop lines ranked by edge against a real season-to-date rate baseline (not a trained model) -- see the module docstring for why, and note most weeks have no real prop odds populated yet.",
        aria_label="NFL props ladder",
        source_path=str(_props_path(season, week)),
        source_title="Real OddsAPI player-prop snapshot",
        source_date_display=f"{season} Week {week}",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(week)},
        ],
        module_links=[{"label": "Market Board", "href": f"/nfl/market-board?season={season}&week={week}", "active": False}],
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(week),
        hidden_fields=[{"name": "season", "value": str(season)}],
        empty_state=None if cards else {
            "eyebrow": "NFL props",
            "title": "No real player-prop lines available for this week",
            "body": "The real OddsAPI player-props snapshot has no rows for this season/week -- this feed only ever captures whatever is live/upcoming when it's refreshed, so most historical weeks have none.",
            "list_items": [f"Season: {season}", f"Week: {week}"],
        },
    )


# --------------------------------------------------------------------------
# Player -> team side attribution for the game cards.
#
# `nfl/cards.py` left `prop_recommendations` unset for as long as NFL cards
# have existed, and its comment gave an honest reason: the prop feed carries a
# player's NAME but not which of the two teams he plays for, while
# `_build_prop_rows` needs rows already split into "away"/"home" lists. That
# reason was true when written and is no longer true -- not because the feed
# improved (measured 2026-08-27: `team` is empty in 0 of 294 real week-1 rows,
# exactly as documented) but because a real per-player team artifact is now
# built, published and present on the web service's disk.
#
# THE RULE THIS CODE IS BUILT AROUND, taken from `player_name_index`'s
# docstring in player_stats.py: "An unresolvable name costs us one bet. A
# wrongly resolved name prices a projection against a different human being,
# which is worse than no bet at any stake." Every branch below refuses rather
# than guesses, and the refusals are counted so a caller can report the
# coverage it is losing instead of silently dropping rows.
# --------------------------------------------------------------------------


def _normalized_player_name(value: Any) -> str:
    """Lowercased, punctuation-free player name for joining two real feeds.

    OddsAPI writes "A.J. Brown" and the nflverse roster writes "A.J. Brown" but
    also "Marquise Brown"/"Hollywood Brown" style variants elsewhere, and
    suffixes drift ("Michael Pittman Jr." vs "Michael Pittman"). Periods and
    the common generational suffixes are removed so the join does not fail on
    typography alone -- but nothing FUZZY happens here: two different humans
    never normalize together unless they genuinely share a name, and that case
    is handled by dropping the name entirely (see `nfl_player_team_index`).
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    for char in (".", ",", "'", "`", "-"):
        text = text.replace(char, " " if char == "-" else "")
    parts = [part for part in text.split() if part]
    while parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        parts.pop()
    return " ".join(parts)


@lru_cache(maxsize=4)
def nfl_player_team_index(season: int) -> dict[str, str]:
    """{normalized player name: canonical team abbr} from the roster snapshot.

    AMBIGUOUS NAMES ARE OMITTED, not resolved by preference. If two players on
    two different teams normalize to the same name, there is no evidence here
    for choosing between them, and choosing wrong puts a real prop on the wrong
    team's card. Omitting costs those rows; guessing corrupts them.

    Returns {} when the artifact is absent -- an empty index makes every lookup
    refuse, which degrades the card to the same honest "no props" state it has
    shown all along, rather than failing the whole card build.
    """
    path = nfl_roster_snapshot_path(season)
    try:
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError):
        return {}

    teams_by_name: dict[str, set[str]] = {}
    for row in rows:
        name = _normalized_player_name(row.get("player_name") or row.get("player_display_name"))
        if not name:
            continue
        team = canonical_team_abbr(row.get("team_abbr") or row.get("team") or row.get("team_name") or "")
        if not team:
            continue
        teams_by_name.setdefault(name, set()).add(team)
    return {name: next(iter(teams)) for name, teams in teams_by_name.items() if len(teams) == 1}


def nfl_player_team_collisions(season: int) -> dict[str, frozenset[str]]:
    """Names the index above had to drop, so coverage loss can be REPORTED
    rather than inferred from a smaller number than expected."""
    path = nfl_roster_snapshot_path(season)
    try:
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError):
        return {}
    teams_by_name: dict[str, set[str]] = {}
    for row in rows:
        name = _normalized_player_name(row.get("player_name") or row.get("player_display_name"))
        team = canonical_team_abbr(row.get("team_abbr") or row.get("team") or row.get("team_name") or "")
        if name and team:
            teams_by_name.setdefault(name, set()).add(team)
    return {name: frozenset(teams) for name, teams in teams_by_name.items() if len(teams) > 1}


# Only markets a card can render as a one-line pick. `is_ladder` alternate
# lines are excluded upstream by the capture; this is the display filter.
_NFL_CARD_PROP_PRIORITY = (
    "Anytime TD",
    "Passing Yards",
    "Passing TDs",
    "Rushing Yards",
    "Receiving Yards",
    "Receptions",
)


def nfl_prop_recommendations_for_matchup(
    season: int,
    week: int,
    *,
    away_full_name: str,
    home_full_name: str,
) -> dict[str, list[dict[str, Any]]]:
    """`prop_recommendations` for ONE game, split into away/home lists.

    The shape `game_board_contract._build_prop_rows` consumes: a dict with
    "away" and "home" keys, each a list of row dicts. It reads at most 8 rows
    total across both sides, so this returns a bounded, priced, best-price
    selection rather than every quote.

    THE SIDE SPLIT IS A JOIN, NEVER A GUESS. Three independent refusals, each
    of which drops the row instead of placing it somewhere plausible:

      1. the player's name does not resolve to exactly one team in the roster
         snapshot (unknown, or a genuine name collision), or
      2. the player's team is neither of THIS game's two teams -- a stale
         roster row, or a name that collided with a player elsewhere in the
         league. Placing him would put a real prop on a card he has nothing to
         do with, which is the failure the old comment refused to risk, and
      3. the row carries no usable price.

    Refusal 2 is what makes mis-attribution structurally impossible rather than
    merely unlikely: a player can only ever land on a card whose own two teams
    include the team the roster says he plays for.
    """
    away_abbr = canonical_team_abbr(away_full_name)
    home_abbr = canonical_team_abbr(home_full_name)
    if not away_abbr or not home_abbr or away_abbr == home_abbr:
        return {"away": [], "home": []}

    team_index = nfl_player_team_index(season)
    game_key = nfl_props_key(away_full_name, home_full_name)

    # Best price per (player, market, line, side): the capture may now carry
    # several books for the same selection, and a card must show one row --
    # the BEST one, which is the whole point of keeping every book.
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _nfl_raw_player_props(season, week):
        if str(row.get("is_ladder") or "").strip().lower() == "true":
            continue
        market = str(row.get("market") or "").strip()
        if market not in _NFL_CARD_PROP_PRIORITY:
            continue
        if nfl_props_key(str(row.get("away_team") or ""), str(row.get("home_team") or "")) != game_key:
            continue
        player = str(row.get("player") or "").strip()
        if not player:
            continue
        team = team_index.get(_normalized_player_name(player))
        if team not in (away_abbr, home_abbr):
            continue
        price = _safe_float(row.get("over_price"))
        if price is None:
            continue
        line = _safe_float(row.get("line"))
        key = (player, market, "" if line is None else f"{line:g}")
        current = best.get(key)
        if current is None or _american_is_better(price, current["_price"]):
            best[key] = {
                "_price": price,
                "_team": team,
                "player": player,
                "market": market,
                "line": line,
                "price": int(price),
                "book": str(row.get("book") or "").strip(),
                "selection": "over",
                "display_pick": _nfl_card_prop_display_pick(market, line),
            }

    rows_by_side: dict[str, list[dict[str, Any]]] = {"away": [], "home": []}
    priority = {market: index for index, market in enumerate(_NFL_CARD_PROP_PRIORITY)}
    for entry in sorted(
        best.values(),
        key=lambda item: (priority.get(item["market"], 99), -item["_price"] if item["_price"] < 0 else item["_price"]),
    ):
        side = "away" if entry["_team"] == away_abbr else "home"
        rows_by_side[side].append({key: value for key, value in entry.items() if not key.startswith("_")})
    return rows_by_side


def _american_is_better(candidate: float, incumbent: float) -> bool:
    """Higher american odds pay more on the same stake, on both sides of zero
    (+240 beats +180; -105 beats -130). A single `>` is correct here precisely
    because american odds are already monotonic in payout -- no conversion to
    decimal is needed, and adding one would be a place to introduce a bug."""
    return candidate > incumbent


def _nfl_card_prop_display_pick(market: str, line: float | None) -> str:
    if market == "Anytime TD":
        return "Anytime TD"
    if line is None:
        return market
    return f"Over {line:g} {market}"
