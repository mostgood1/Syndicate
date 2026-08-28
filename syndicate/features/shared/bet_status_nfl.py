"""Resolve an NFL bet's CURRENT value from the captured live-state artifact.

The fourth sibling of `bet_status_mlb`, `bet_status_wnba` and
`bet_status_soccer`, and deliberately the same shape: it answers "what is the
thing this bet is on worth right now" and leaves every judgement about winning
and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
WHY THIS EXISTS: NFL BETS COULD NEVER SETTLE
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had builders for `mlb`, `wnba` and
`soccer` only, so every NFL order returned `no_resolver_for_nfl` -- forever.
Measured on refresh-worker 2026-08-28T02:37-02:50Z:

    SETTLED date=2026-08-28 orders=21 graded=0
      ungraded={..., 'no_resolver_for_nfl': 6, ...}          6 of 21 = 29%
    BET_STATUS orders=158 resolved=98
      reasons={..., 'no_resolver_for_nfl': 16, ...}

NFL was the only sport producing orders with no resolver at all, and Week 1 is
where its volume starts rather than ends.

--------------------------------------------------------------------------
JOINED ON THE TEAM PAIR, NOT ON `event_id`
--------------------------------------------------------------------------

The same trap soccer documents and `bet_status_wnba` says cost MLB a day: the
order's `event_id` is the OddsAPI event hash, while the capture is keyed by
ESPN's event id. Different namespaces, and no amount of parsing bridges them.
WNBA got to key on `event_id` only because its box and its board share one id.

So this joins on `home_team`/`away_team` through `team_aliases`, whose NFL map
carries all 32 clubs; `poll_nfl_live_state` stores BOTH the display name and
the tri-code so the join does not depend on which form the board stored. An
order without the team fields refuses BY NAME rather than falling back to an id
that cannot match.

--------------------------------------------------------------------------
A TIE IS A PUSH HERE, AND THAT IS `draw_possible=False`
--------------------------------------------------------------------------

Counter-intuitive, so it is stated: NFL regular-season games CAN end level, and
a level moneyline is a PUSH -- the stake comes back. `game_line_view` encodes
exactly that under `draw_possible=False`, whose own comment names "the sports
where a tie is merely rare rather than impossible". Passing `True` -- the
soccer setting -- would make `three_way` true and grade a tie as a LOSS.

The board does emit `h2h_3_way` for NFL (measured in `VENUE_REPRICE_KEYS`
board_wanted samples, 2026-08-28T02:10Z). That market is in
`game_line_bet._ALWAYS_THREE_WAY`, so it is graded three-way off the MARKET
NAME regardless of this flag, and needs no special case here.

--------------------------------------------------------------------------
PROPS REFUSE, BY NAME
--------------------------------------------------------------------------

The scoreboard capture carries team scores and nothing per-player, so a passing
or receiving prop is not gradeable from it. That is a PERMANENT refusal and is
reported separately from "the capture is not there yet", which is transient --
the rule `bet_status_wnba` states and paid for, and the reason the market check
below runs BEFORE the artifact read.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["nfl_status_resolver"]

REASON_NOT_NFL = "not_an_nfl_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_nfl_live_state_for_date"
REASON_GAME_NOT_FOUND = "game_not_in_nfl_live_state"
REASON_PROPS = "nfl_props_not_gradeable_from_scoreboard"
REASON_UNKNOWN_MARKET = "unmapped_market"
# A team total is ONE side's points. Grading it off the combined score would
# roughly double the value and settle overs that lost, so it refuses until the
# side token is read properly. Same refusal soccer makes, same reason.
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
REASON_NO_SCORES = "game_carries_no_scores"

# The combined-points family. `team_totals` is deliberately ABSENT -- see above.
_GAME_TOTAL_MARKETS = frozenset({"totals", "total", "totals_alt", "alternate_totals"})
_TEAM_TOTAL_MARKETS = frozenset({"team_totals", "team_total", "team_totals_alt"})


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _load_games(selected_date: str) -> list[dict[str, Any]] | None:
    """Every NFL game captured for this date, in play or finished.

    None means "we could not read any live state", which is NOT the same as "no
    games today" -- the caller reports them as different reasons.

    READ THROUGH `refresh_state_store`, the matching half of the poller's
    `write_json_file`. Settlement runs on refresh-worker and Render cannot share
    a disk between services, so a filesystem read here would find nothing in
    production while passing every test on a dev box.

    ONE LAZY CAPTURE ON A MISS, and this is the deliberate part. A resolver
    whose producer runs on some other schedule is inert exactly when it is
    needed -- the failure `model_engine_standard.md` exists to prevent. Rather
    than add a periodic task to a worker with 110 OOM kills on record
    (`worker_periodic_work_never_free` is a standing rule), the capture happens
    at most ONCE per resolver construction, behind a cache, on a 6s timeout
    that already fails soft. A settlement pass over forty NFL orders is one
    scoreboard GET, not forty, and zero when the artifact is already there.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        from scripts.poll_nfl_live_state import live_state_path, poll_nfl_live_state
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None

    record = None
    try:
        record = read_json_file(live_state_path(selected_date))
    except Exception:
        record = None

    if not isinstance(record, Mapping) or not record.get("games"):
        try:
            fetched = poll_nfl_live_state(selected_date)
        except Exception:
            fetched = None
        if isinstance(fetched, Mapping) and fetched.get("status") == "ok":
            record = fetched

    if not isinstance(record, Mapping):
        return None
    games = record.get("games")
    if not isinstance(games, list):
        return None
    return [game for game in games if isinstance(game, Mapping)]


def nfl_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for NFL orders.

    The live-state read happens ONCE per resolver, not once per order: a slate
    of forty NFL orders must not mean forty reads of one artifact that does not
    change between them.
    """
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.team_aliases import teams_match

    cache: dict[str, Any] = {}

    def games() -> list[dict[str, Any]] | None:
        if "games" not in cache:
            cache["games"] = _load_games(selected_date)
        return cache["games"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "nfl":
            # This resolver is handed every order; a non-NFL one is not a
            # defect in anything and must not be reported as an NFL failure.
            return {"unavailable_reason": REASON_NOT_NFL}

        # THE MARKET CHECK COMES FIRST, before the artifact read: "we cannot
        # grade this market" is permanent, "the capture is not there yet" is
        # transient, and checking the transient one first hides the structural
        # one behind a reason that looks like it will fix itself.
        market = order.get("market")
        canonical = _norm(market)
        # ORDER MATTERS. `team_totals` must be caught BEFORE the combined-total
        # test, or a permissive match would swallow it and grade one team's
        # points against the whole scoreline.
        if canonical in _TEAM_TOTAL_MARKETS:
            return {"unavailable_reason": REASON_TEAM_TOTAL}
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_line = is_game_line_market("nfl", market)
        if not (is_total or is_line):
            return {"unavailable_reason": REASON_PROPS if order.get("player_name") else REASON_UNKNOWN_MARKET}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        if not home_team or not away_team:
            # `event_id` is the OddsAPI hash and cannot address an ESPN-keyed
            # capture, so there is no fallback here that would be anything but
            # a guess.
            return {"unavailable_reason": REASON_NO_MATCHUP}

        found = games()
        if found is None:
            return {"unavailable_reason": REASON_NO_LIVE_STATE}

        record = None
        for candidate in found:
            # BOTH FORMS TRIED. The capture stores the display name and the
            # tri-code; the board may hold either, and `canonical_team` resolves
            # both, so a miss on one is not a miss on the game.
            home_hit = teams_match("nfl", home_team, candidate.get("home_team")) or teams_match(
                "nfl", home_team, candidate.get("home_abbr")
            )
            away_hit = teams_match("nfl", away_team, candidate.get("away_team")) or teams_match(
                "nfl", away_team, candidate.get("away_abbr")
            )
            if home_hit and away_hit:
                record = candidate
                break
        if record is None:
            return {"unavailable_reason": REASON_GAME_NOT_FOUND}

        home = _as_float(record.get("home_score"))
        away = _as_float(record.get("away_score"))

        if is_total:
            # NO TRANSLATION. The order already carries `side="over"` and a
            # numeric line, so the grader needs only the combined points --
            # exactly what `bet_status_mlb._combined_score` hands it. Routing a
            # total through `game_line_view` is what produced soccer's
            # `unmapped_market` count, because `is_game_line_market` is False
            # for totals BY DESIGN: it is the spread-and-moneyline test.
            if home is None or away is None:
                # A half-known score is not a score. Refusing both together
                # stops a missing away total reading as a shutout.
                return {"unavailable_reason": REASON_NO_SCORES}
            return {
                "current_value": home + away,
                "is_final": bool(record.get("final")),
                "started": True,
            }

        view = game_line_view(
            sport="nfl",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=record.get("home_score"),
            away_score=record.get("away_score"),
            # See the module docstring. A level NFL moneyline is a PUSH, not a
            # loss, and that is what False encodes. `h2h_3_way` is graded
            # three-way off the market name regardless.
            draw_possible=False,
        )
        if "unavailable_reason" in view:
            return view
        view["is_final"] = bool(record.get("final"))
        view["started"] = bool(record.get("in_progress")) or bool(record.get("final"))
        return view

    return resolve
