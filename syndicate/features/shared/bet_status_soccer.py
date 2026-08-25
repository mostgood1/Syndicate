"""Resolve a soccer bet's CURRENT value from the live-state artifact.

The third sibling of `bet_status_mlb` and `bet_status_wnba`, and deliberately
the same shape: it answers "what is the thing this bet is on worth right now"
and leaves every judgement about winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
WHY THIS EXISTS: SOCCER BETS COULD NEVER SETTLE
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had builders for `mlb` and `wnba` only, so
every soccer order returned `no_resolver_for_soccer` -- forever. Measured
2026-08-25 14:03:02Z:

    SETTLED date=2026-08-25 orders=2 graded=0 ungraded={'no_resolver_for_soccer': 2}
    PNL_CUT all_time by_sport=[('mlb', 181, ...), ('soccer', 0, ...), ('wnba', 0, ...)]

Zero soccer bets settled, ever, while the board that produces them was ~97%
soccer by row count (9,041 candidates, 1,277 opportunities on the 08-24 slate).
A bet that is taken and can never be graded is worse than one never taken: it
consumes bankroll and is invisible to every performance number.

--------------------------------------------------------------------------
JOINED ON THE TEAM PAIR, NOT ON `event_id` -- THIS IS THE MLB TRAP
--------------------------------------------------------------------------

`bet_status_wnba` records that MLB "cost a day" because the board stamps ids
from OddsAPI while the resolving artifact wants the provider's own. Soccer has
exactly that gap and it is worse, not better: the order's `event_id` is the
OddsAPI event hash, while `poll_soccer_live_state.py` keys its matches by
ESPN's event id. They are different namespaces and no amount of parsing bridges
them.

WNBA got to key on `event_id` because its box and its board share one id. Soccer
does not, so this joins on `home_team`/`away_team` through `team_aliases`, the
same resolver `attach_game_state` and `_soccer_live_state_games` already use for
this sport. Those fields are on `OrderRequest` and every order placed since they
were added carries them; an order without them refuses BY NAME rather than
falling back to an id that cannot match.

--------------------------------------------------------------------------
GAME LINES ONLY, AND THE PROP REFUSAL IS SPECIFIC
--------------------------------------------------------------------------

`game_line_view` is sport-agnostic and already handles a draw leg, so moneyline
(2-way and 3-way) and spreads grade the moment two scores exist. Soccer player
props do NOT grade here: the live-state artifact carries `live_player_props`
capped at twelve players per match (`poll_soccer_live_state.py`:
`sorted(...)[:12]`), so a player outside the cap is ABSENT rather than at zero.

Reporting a capped-out player as "0 shots, the under is fine" would be the
exact failure `bet_status_wnba` names for a missing player -- "the worst
possible wrong answer" -- with the added trap that the cap makes it systematic
rather than occasional. So props refuse as `soccer_props_not_gradeable_from_
capped_live_state` and the fix is upstream in the capture, not a table here.

--------------------------------------------------------------------------
FINAL IS ASSERTED, NEVER INFERRED FROM THE CLOCK
--------------------------------------------------------------------------

`is_final` comes from the artifact's own `status_state == "post"` / `final`
boolean, which the poller carries through from ESPN verbatim and preserves once
set. A 90th-minute clock is not a finished match -- stoppage time is real and
routinely decides totals -- so nothing here reads the clock.

**A `final` that never arrives costs a delay; a `final` invented from a clock
settles a live bet wrongly.** Same trade `bet_status_wnba` makes and for the
same reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["soccer_status_resolver"]

REASON_NOT_SOCCER = "not_a_soccer_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_soccer_live_state_for_date"
REASON_MATCH_NOT_FOUND = "match_not_in_soccer_live_state"
REASON_PROPS = "soccer_props_not_gradeable_from_capped_live_state"
REASON_UNKNOWN_MARKET = "unmapped_market"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def soccer_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for soccer orders.

    The live-state read happens ONCE per resolver, not once per order: a slate
    of forty soccer orders must not mean forty reads of one artifact that does
    not change between them.
    """
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.team_aliases import teams_match

    cache: dict[str, Any] = {}

    def matches() -> list[dict[str, Any]] | None:
        if "matches" in cache:
            return cache["matches"]
        cache["matches"] = _load_matches(selected_date)
        return cache["matches"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "soccer":
            # This resolver is handed every order; a non-soccer one is not a
            # defect in anything and must not be reported as a soccer failure.
            return {"unavailable_reason": REASON_NOT_SOCCER}

        # THE MARKET CHECK COMES FIRST, before the artifact read -- the rule
        # `bet_status_wnba` states and paid for: "we cannot grade this market"
        # is permanent, "the artifact is not captured yet" is transient, and
        # checking the transient one first hides the structural one.
        market = order.get("market")
        if not is_game_line_market("soccer", market):
            return {"unavailable_reason": REASON_PROPS if order.get("player_name") else REASON_UNKNOWN_MARKET}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        if not home_team or not away_team:
            # See the module docstring: `event_id` is the OddsAPI hash and
            # cannot address an ESPN-keyed artifact, so there is no fallback
            # here that would be anything but a guess.
            return {"unavailable_reason": REASON_NO_MATCHUP}

        found = matches()
        if found is None:
            return {"unavailable_reason": REASON_NO_LIVE_STATE}

        record = None
        for candidate in found:
            if teams_match("soccer", home_team, candidate.get("home_team")) and teams_match(
                "soccer", away_team, candidate.get("away_team")
            ):
                record = candidate
                break
        if record is None:
            return {"unavailable_reason": REASON_MATCH_NOT_FOUND}

        view = game_line_view(
            sport="soccer",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=record.get("home_score"),
            away_score=record.get("away_score"),
            # SOCCER DRAWS. A level 2-way moneyline is a PUSH and a level
            # three-way is a LOSS; `game_line_view` encodes both off this flag
            # and the market name, so neither is decided here.
            draw_possible=True,
        )
        if "unavailable_reason" in view:
            return view

        return {
            "current_value": view.get("current_value"),
            "side": view.get("side"),
            "line": view.get("line"),
            # ASSERTED BY THE ARTIFACT, never read off the clock. Stoppage time
            # is real and decides totals.
            "is_final": bool(record.get("final")),
            "started": True,
        }

    return resolve


def _load_matches(selected_date: str) -> list[dict[str, Any]] | None:
    """Every soccer match this service can see, in play OR finished.

    Delegates to `board_enrichment._soccer_live_state_games`, which is the ONE
    place that knows soccer's two-source asymmetry and is already relied on by
    the chip-state correction:

      `live/soccer_live_lens.json`  cross-service (keyvalue), IN-PLAY ONLY
      per-league `match_box`        local filesystem, spans `in` AND `post`

    A second copy of that logic is how the two would drift, and this module's
    siblings both record what a drifting duplicate costs. **Settlement runs on
    refresh-worker** (`pipeline/intelligence_state.py` calls `settle_orders`),
    where only the aggregate is readable -- so finished matches reach this
    resolver only because `poll_active_leagues_for_tick` now publishes them into
    that aggregate. Without that, this would grade nothing in production while
    passing every test on a dev box, which is precisely the inert-feature shape
    `model_engine_standard.md` exists to prevent.

    None means "we could not read any live state", which is NOT the same as "no
    matches today" -- the caller reports them as different reasons.
    """
    try:
        from syndicate.features.shared.board_enrichment import _soccer_live_state_games
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None

    try:
        resolved = _soccer_live_state_games(selected_date)
    except Exception:
        return None
    if resolved is None:
        return None

    games, _age = resolved
    out: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, Mapping):
            continue
        home = game.get("home") if isinstance(game.get("home"), Mapping) else {}
        away = game.get("away") if isinstance(game.get("away"), Mapping) else {}
        out.append(
            {
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_score": game.get("home_score"),
                "away_score": game.get("away_score"),
                # `_soccer_live_state_games` has already collapsed both of the
                # artifact's finished signals (`status_state == "post"` and the
                # `final` boolean) into one state token.
                "final": str(game.get("state") or "").strip().lower() == "final",
            }
        )
    return out
