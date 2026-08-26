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
TWO SHAPES OF SCOREBOARD BET, AND ONLY ONE NEEDS TRANSLATING
--------------------------------------------------------------------------

MONEYLINES AND SPREADS go through `game_line_view`, which is sport-agnostic and
already handles a draw leg. They need it because a spread arrives as
`side="Chelsea", line=-1.5` and the grader speaks over/under.

TOTALS DO NOT, and that is the whole reason they were missing. A total already
arrives in the grader's vocabulary -- `side="over", line=2.5` -- so the only
thing needed is the combined goals. `bet_status_mlb` grades its 46 settled
totals exactly this way (`_combined_score`, no `game_line_view` call), and
routing a total through the translator instead is what produced:

    UNMAPPED_MARKETS date=2026-08-25 {'totals': 1}      (measured 14:47:23Z)

`is_game_line_market` is False for `totals` by design -- it is the SPREAD and
MONEYLINE test -- so the first cut of this resolver refused a bet it already
held both numbers for. Two of the four pending soccer orders were totals.

**`team_totals` IS REFUSED BY NAME AND IS NOT THE SAME MARKET.** It is one
team's goals, not the combined score, and grading it off `home + away` would
double the number and settle overs that lost. The side token carries which team
and nothing here reads it, so it refuses rather than guesses -- the same trade
the module makes everywhere else.

A total's line is often integral in soccer (Asian 2.0, 3.0) where MLB's rarely
is, and that needs NO special handling: `resolve_bet_status` settles equality as
a push, which is exactly right for a total landing on its line. This is the
opposite of the three-way moneyline case, where the half-point trick exists
precisely BECAUSE a push would be wrong.

Soccer player props do NOT grade here: the live-state artifact carries `live_player_props`
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
# A team total is ONE side's goals. Grading it off the combined score would
# roughly double the value and settle overs that lost, so it refuses until the
# side token is read properly.
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
REASON_NO_SCORES = "match_carries_no_scores"
# The rolling aggregate is readable but has moved on to another date, and no
# settlement record was kept for the date we are grading. Distinct from
# `no_soccer_live_state_for_date`, which means we could read nothing at all:
# this one says the window CLOSED, which is a different job for whoever reads
# the counter -- it points at retention, not at the poller being down.
REASON_FINALS_WINDOW_CLOSED = "soccer_finals_window_closed"

# The combined-goals family. `team_totals` is deliberately ABSENT -- see the
# module docstring. Mirrors `live_gameline_join._TOTALS_MARKETS`, which is the
# vocabulary the board actually emits (`totals_alt` and `alternate_totals` are
# the same market at another line, and a distribution -- or here a final score
# -- prices any line).
_GAME_TOTAL_MARKETS = frozenset({"totals", "total", "totals_alt", "alternate_totals"})
_TEAM_TOTAL_MARKETS = frozenset({"team_totals", "team_total", "team_totals_alt"})


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    """ESPN ships scores as STRINGS ("1"). A string compares wrong downstream
    without ever raising, which is the failure `board_enrichment` records for
    this same field."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


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
        canonical = _norm(market)
        # ORDER MATTERS. `team_totals` must be caught BEFORE the combined-total
        # test, because a permissive `startswith("total")` would swallow it and
        # grade one team's goals against the whole scoreline.
        if canonical in _TEAM_TOTAL_MARKETS:
            return {"unavailable_reason": REASON_TEAM_TOTAL}
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_line = is_game_line_market("soccer", market)
        if not (is_total or is_line):
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

        if is_total:
            # NO TRANSLATION. The order already carries `side="over"` and a
            # numeric line, so the grader needs only the combined goals --
            # exactly what `bet_status_mlb._combined_score` hands it. Passing
            # this through `game_line_view` is what refused it as
            # `unmapped_market` in the first place.
            home = _as_float(record.get("home_score"))
            away = _as_float(record.get("away_score"))
            if home is None or away is None:
                # A half-known score is not a score. Refusing both together
                # stops a missing away total reading as a clean sheet -- the
                # same rule `game_line_view` states for its own two scores.
                return {"unavailable_reason": REASON_NO_SCORES}
            return {
                "current_value": home + away,
                "is_final": bool(record.get("final")),
                "started": True,
            }

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



def _finals_record_path(root, selected_date: str):
    return root / "live" / f"soccer_finals_{selected_date}.json"


def _remember_finals(selected_date: str, matches) -> None:
    """Keep this date's FINISHED matches where a later tick can still find them.

    WHY SETTLEMENT HAS TO KEEP ITS OWN RECORD. `live/soccer_live_lens.json` is a
    ROLLING SINGLE-DATE snapshot, and both of its readers gate on
    `snapshot["date"] == selected_date` -- correctly, since answering for one
    date out of another date's match state would grade the wrong scoreline.
    But `settle_orders` deliberately runs for TODAY AND YESTERDAY (a slate that
    starts before midnight UTC files its orders under the previous date), and
    the moment the aggregate rolls, the yesterday pass can read NOTHING: the
    per-league `match_box` tree is a filesystem write on live-odds-worker and
    settlement runs on refresh-worker. So yesterday's pass was structurally
    impossible for soccer -- which is the sport that needs it most, since
    European matches finish within a couple of hours of the UTC date roll.

    MEASURED 2026-08-26: soccer had settled ZERO orders all-time, and at
    14:57Z the pass for 2026-08-25 reported `no_soccer_live_state_for_date: 3`
    while the aggregate had already rolled to 2026-08-26.

    UNIONED, NEVER REPLACED. A tick that can see only some of the day's finals
    must not erase the ones an earlier tick recorded, and the poller itself
    rebuilds nothing it has already marked final. Same trim the poller applies:
    a handful of scalars per finished match, so this cannot grow with squad
    size or trip the aggregate's 1MB write warning.

    NEVER RAISES. Settlement failing because a cache write failed would be a
    worse outcome than the gap this closes.
    """
    finished = [m for m in matches if m.get("final")]
    if not finished:
        return
    try:
        from syndicate.features.shared.refresh_state_store import (
            data_root,
            read_json_file,
            write_json_file,
        )

        path = _finals_record_path(data_root(), selected_date)
        merged: dict[Any, dict[str, Any]] = {}
        existing = read_json_file(path)
        if isinstance(existing, Mapping) and str(existing.get("date") or "") == str(selected_date):
            for record in existing.get("matches") or []:
                if isinstance(record, Mapping):
                    merged[(record.get("home_team"), record.get("away_team"))] = dict(record)
        added = 0
        for record in finished:
            key = (record.get("home_team"), record.get("away_team"))
            if key not in merged:
                added += 1
            merged[key] = dict(record)
        if not added:
            # Nothing new this tick. Skipping the write keeps a settled day
            # from being rewritten every three minutes for the rest of it.
            return
        write_json_file(path, {"date": str(selected_date), "matches": list(merged.values())})
    except Exception:
        return


def _recall_finals(selected_date: str):
    """This date's finished matches from settlement's own record, or None.

    None means nothing was kept -- NOT that the day had no matches. The caller
    keeps those two as different reasons, which is the same split the rest of
    this module draws and the reason `_load_matches` returns None rather than
    an empty list.
    """
    try:
        from syndicate.features.shared.refresh_state_store import data_root, read_json_file

        record = read_json_file(_finals_record_path(data_root(), selected_date))
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    if str(record.get("date") or "") != str(selected_date):
        # A record written for another date cannot answer for this one, for
        # exactly the reason the aggregate is date-gated in the first place.
        return None
    out = [dict(m) for m in (record.get("matches") or []) if isinstance(m, Mapping)]
    return out or None

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
        resolved = None
    if resolved is None:
        # THE AGGREGATE HAS ROLLED PAST THIS DATE (or could not be read at all).
        # Settlement's own kept record is the only thing that can still answer,
        # and it is what makes the yesterday pass possible for soccer.
        return _recall_finals(selected_date)

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
    # Kept BEFORE returning, so the window is recorded on every tick that can
    # still see it rather than only on the one that happens to grade.
    _remember_finals(selected_date, out)
    return out
