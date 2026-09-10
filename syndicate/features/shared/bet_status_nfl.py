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
PROPS ARE GRADED OFF ESPN'S PER-PLAYER BOX (since 2026-09-10)
--------------------------------------------------------------------------

The scoreboard capture carries team scores and nothing per-player. Until
2026-09-10 that made every prop a PERMANENT refusal
(`nfl_props_not_gradeable_from_scoreboard`) -- which, once the board began
staking NFL props on 2026-09-09, meant real exposure with no production grade.
It was already firing on the first order the morning after.

Props now read ESPN's summary for the game (`nfl/live_player_box`), found
through the capture's own `event_id`. The rules that stay:

  * PERMANENT BEFORE TRANSIENT. An unmapped player market or a non-full segment
    refuses by name before anything is read, the order the game-line path below
    has always used -- `bet_status_wnba` states the rule and paid for it.
  * ABSENT IS NOT ZERO. A player missing from a FINAL box may have been
    inactive (books void that) or active with no touch; this box cannot tell
    them apart, so it refuses. A player who appears in ANY stat group played,
    so his zeros are real zeros and settle.
  * ONE READ PER GAME. The box is cached per resolver, like the live state.
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared.segment_actuals import (
    FULL_GAME_SEGMENT,
    REASON_UNSUPPORTED_SEGMENT_PREFIX,
    order_segment,
    segment_actuals,
    segment_periods,
)

__all__ = ["nfl_status_resolver"]

REASON_NOT_NFL = "not_an_nfl_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_nfl_live_state_for_date"
REASON_GAME_NOT_FOUND = "game_not_in_nfl_live_state"
REASON_UNKNOWN_MARKET = "unmapped_market"
# PLAYER PROPS, graded off ESPN's per-player box since 2026-09-10. Until then
# every one refused as `nfl_props_not_gradeable_from_scoreboard`, which made
# NFL props stakeable but unmeasurable. Each refusal below is named, and each is
# one of two kinds: PERMANENT (this market or segment can never be graded here)
# or TRANSIENT (the box is not there yet).
REASON_PROP_MARKET = "nfl_prop_market_not_mapped"
REASON_PROP_SEGMENT = "nfl_prop_needs_full_game"
REASON_NO_EVENT_ID = "nfl_game_has_no_espn_event_id"
REASON_NO_BOX = "nfl_player_box_unavailable"
# A player absent from a FINAL box may have been inactive -- which books VOID --
# or active with no touch in any stat group. Those settle differently and this
# box cannot tell them apart, so it refuses rather than grading a zero.
REASON_PLAYER_NOT_IN_BOX = "nfl_player_not_in_final_box"
REASON_PLAYER_NOT_IN_BOX_YET = "nfl_player_not_in_live_box_yet"
REASON_PLAYER_AMBIGUOUS = "nfl_player_ambiguous_in_box"
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


# Board market -> the box field that settles it. BOTH vocabularies, because both
# reach orders: the board writes display labels ("Receiving Yards") and a
# minority of rows still carry the raw OddsAPI key -- 28 of 1,422 served NFL
# prop rows on 2026-09-09 arrived as `player_receptions` / `player_pass_tds`.
# `interceptions` here is the QB's prop, interceptions THROWN, which is why the
# box reads it from ESPN's `passing` group only.
_PROP_FIELDS = {
    "passing yards": "pass_yards",
    "player_pass_yds": "pass_yards",
    "passing attempts": "pass_attempts",
    "player_pass_attempts": "pass_attempts",
    "passing completions": "completions",
    "player_pass_completions": "completions",
    "passing tds": "pass_td",
    "passing touchdowns": "pass_td",
    "player_pass_tds": "pass_td",
    "interceptions": "pass_int",
    "player_pass_interceptions": "pass_int",
    "rushing yards": "rush_yards",
    "player_rush_yds": "rush_yards",
    "rushing attempts": "rush_attempts",
    "player_rush_attempts": "rush_attempts",
    "receptions": "receptions",
    "player_receptions": "receptions",
    "receiving yards": "rec_yards",
    "player_reception_yds": "rec_yards",
    "anytime td": "td_scored",
    "player_anytime_td": "td_scored",
}
# Anytime TD is a yes/no market with no line on the board. "Scored at least
# once" is `td_scored > 0.5`, and `paper_settlement` honours a line the resolver
# supplies (`resolved.get("line", order.get("line"))`).
_ANYTIME_TD_FIELD = "td_scored"
_ANYTIME_TD_LINE = 0.5
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _player_key(value: Any) -> str:
    """A player name folded for joining a board order to ESPN's box.

    Built ON `prop_projections._norm_name`, which already folds accents and
    ligatures correctly, and fixes the two things it cannot: INITIALS and
    SUFFIXES. `_norm_name` turns "A.J. Brown" into "a j brown" while the board
    writes "AJ Brown" -> "aj brown", so runs of single letters are merged here;
    and ESPN and the books disagree on "Jr." / "III", so suffixes are dropped.
    Measured on the opener: ESPN's box carries "A.J. Brown", the board "AJ Brown".
    """
    from syndicate.features.shared.prop_projections import _norm_name

    tokens = [token for token in _norm_name(value).split() if token not in _NAME_SUFFIXES]
    merged: list[str] = []
    initials = ""
    for token in tokens:
        if len(token) == 1:
            initials += token
            continue
        if initials:
            merged.append(initials)
            initials = ""
        merged.append(token)
    if initials:
        merged.append(initials)
    return " ".join(merged)


def _fetch_box(event_id: str) -> list[dict[str, Any]] | None:
    """Every athlete in this game's ESPN box, every field. None means NOT READ.

    A module-level seam so tests can substitute a real captured payload without
    network access. One GET per game per resolver construction -- see the
    resolver's own cache -- and no new periodic task, for the reason
    `_load_games` gives.
    """
    try:
        from syndicate.features.nfl.live_player_box import fetch_player_stat_rows
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None
    return fetch_player_stat_rows(event_id)


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

    def box(event_id: str) -> list[dict[str, Any]] | None:
        # ONCE PER GAME PER RESOLVER, like the live-state read above: a slate of
        # forty prop orders on one game is one ESPN GET, not forty. A failed
        # read is remembered for this pass only and retried on the next.
        slot = f"box:{event_id}"
        if slot not in cache:
            cache[slot] = _fetch_box(event_id)
        return cache[slot]

    def locate(home_team: Any, away_team: Any) -> tuple[Mapping[str, Any] | None, str | None]:
        """`(record, None)` or `(None, refusal)`, in the order the refusals
        have always been made: matchup, then capture, then game."""
        if not home_team or not away_team:
            # `event_id` is the OddsAPI hash and cannot address an ESPN-keyed
            # capture, so there is no fallback here that would be anything but
            # a guess.
            return None, REASON_NO_MATCHUP
        found = games()
        if found is None:
            return None, REASON_NO_LIVE_STATE
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
                return candidate, None
        return None, REASON_GAME_NOT_FOUND

    def resolve_prop(order: Mapping[str, Any], canonical: str, segment: str) -> dict[str, Any]:
        # PERMANENT REFUSALS FIRST, before any read -- the rule the game-line
        # path below already follows, for the same reason.
        field = _PROP_FIELDS.get(canonical)
        if field is None:
            return {"unavailable_reason": REASON_PROP_MARKET}
        if segment != FULL_GAME_SEGMENT:
            # ESPN's box is whole-game. A quarter prop graded off it would be
            # graded off the wrong quantity.
            return {"unavailable_reason": REASON_PROP_SEGMENT}

        record, refusal = locate(order.get("home_team"), order.get("away_team"))
        if refusal:
            return {"unavailable_reason": refusal}
        is_final = bool(record.get("final"))
        if not (bool(record.get("in_progress")) or is_final):
            # Not unanswerable -- not yet asked.
            return {"current_value": None, "is_final": False, "started": False}
        event_id = str(record.get("event_id") or "").strip()
        if not event_id:
            return {"unavailable_reason": REASON_NO_EVENT_ID}

        rows = box(event_id)
        if rows is None:
            return {"unavailable_reason": REASON_NO_BOX}
        key = _player_key(order.get("player_name"))
        matches = [row for row in rows if _player_key(row.get("player_name")) == key]
        if len(matches) > 1:
            return {"unavailable_reason": REASON_PLAYER_AMBIGUOUS}
        if not matches:
            return {
                "unavailable_reason": REASON_PLAYER_NOT_IN_BOX if is_final else REASON_PLAYER_NOT_IN_BOX_YET
            }

        resolved: dict[str, Any] = {
            "current_value": _as_float(matches[0].get(field)),
            "is_final": is_final,
            "started": True,
        }
        if field == _ANYTIME_TD_FIELD and _as_float(order.get("line")) is None:
            resolved["line"] = _ANYTIME_TD_LINE
        return resolved

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "nfl":
            # This resolver is handed every order; a non-NFL one is not a
            # defect in anything and must not be reported as an NFL failure.
            return {"unavailable_reason": REASON_NOT_NFL}

        # SEGMENT BEFORE MARKET -- the more permanent of the two. A segment
        # this sport does not play (`first5` on an NFL order) is a join defect
        # that no capture will ever answer, so it refuses here BY NAME. A
        # segment it does play (`q1..q4`, `h1`, `h2`) is graded below off the
        # poller's per-period linescores -- and refuses by name when a record
        # lacks them, never off the whole-game score (`segment_actuals`).
        # Absent or `full` means the whole game, the one permissive default,
        # for the reason `bet_status.segment_refusal` states.
        segment = order_segment(order)
        if segment != FULL_GAME_SEGMENT and segment_periods("nfl", segment) is None:
            return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{segment}"}

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
        if order.get("player_name"):
            # A PLAYER PROP, graded off ESPN's per-player box. Routed before the
            # game-line test, so a prop is never reported as an unmapped game
            # market.
            return resolve_prop(order, canonical, segment)
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_line = is_game_line_market("nfl", market)
        if not (is_total or is_line):
            return {"unavailable_reason": REASON_UNKNOWN_MARKET}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        record, refusal = locate(home_team, away_team)
        if refusal:
            return {"unavailable_reason": refusal}

        if segment == FULL_GAME_SEGMENT:
            home = _as_float(record.get("home_score"))
            away = _as_float(record.get("away_score"))
            is_final = bool(record.get("final"))
            started = bool(record.get("in_progress")) or is_final
        else:
            # THE SEGMENT'S OWN SCORE PAIR, or a named refusal. `is_final` is
            # the SEGMENT's: a first-half total is decided at the half, not at
            # the final whistle, and `h2` (overtime included) only with the
            # game. A segment that has not begun yet reports `started=False`
            # rather than a refusal -- not unanswerable, not yet asked.
            actual = segment_actuals("nfl", segment, record)
            if actual.get("unavailable_reason"):
                return actual
            if not actual.get("started"):
                return {"current_value": None, "is_final": False, "started": False}
            home = _as_float(actual.get("home_score"))
            away = _as_float(actual.get("away_score"))
            is_final = bool(actual.get("is_final"))
            started = True

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
                "is_final": is_final,
                "started": True,
            }

        view = game_line_view(
            sport="nfl",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=home,
            away_score=away,
            # See the module docstring. A level NFL moneyline is a PUSH, not a
            # loss, and that is what False encodes -- for a quarter or a half
            # exactly as for the game. `h2h_3_way` is graded three-way off the
            # market name regardless.
            draw_possible=False,
        )
        if "unavailable_reason" in view:
            return view
        view["is_final"] = is_final
        view["started"] = started
        return view

    return resolve
