"""Resolve an NCAAF bet's CURRENT value from the captured live-state artifact.

The fifth sibling of `bet_status_mlb`, `_wnba`, `_soccer` and `_nfl`, and the
same shape as all of them: it answers "what is the thing this bet is on worth
right now" and leaves winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
ONE THING IS DIFFERENT FROM NFL, AND IT IS THE WHOLE FILE: THE JOIN
--------------------------------------------------------------------------

`bet_status_nfl` joins on the team pair through `team_aliases.teams_match`,
which is safe there because the NFL map carries all 32 clubs and a resolved
pair is authoritative.

**`team_aliases` has no NCAAF map at all.** `_alias_map("ncaaf")` returns `{}`,
so `teams_match` falls through to heuristics ending in
`len(token) >= 3 and any(word.startswith(token))`. Over ~130 FBS teams that
matches "Michigan" to "Michigan State", "Ohio" to "Ohio State", and each Miami
to the other. On a settlement path that is not a near miss -- it grades the bet
against the WRONG GAME and writes a confident won/lost verdict that nothing
downstream can question.

So the join goes through `ncaaf_team_registry.resolve_ncaaf_team_id`, which
reads the 684-team registry and REFUSES ambiguous names rather than picking the
first row (`ncaaf/cards.py`'s index would resolve "Wildcats" to Abilene
Christian, and "Tigers" to one of 25). Measured before this was written: on the
live 2026-08-29 ESPN slate, 16/16 teams resolved unambiguously, so the refusal
costs nothing real.

**BOTH SIDES MUST RESOLVE, AND TO DIFFERENT TEAMS.** A pair where one side is
unresolvable cannot be confirmed as this fixture, and a pair that resolves to
the SAME id means the vocabulary collapsed two teams together -- which would be
a registry bug, and is refused rather than graded.

--------------------------------------------------------------------------
PROPS REFUSE, BY NAME
--------------------------------------------------------------------------

The scoreboard capture carries team scores and nothing per-player. Permanent
refusal, reported separately from "the capture is not there yet", which is
transient -- so the market check runs BEFORE the artifact read.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["ncaaf_status_resolver"]

REASON_NOT_NCAAF = "not_an_ncaaf_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_ncaaf_live_state_for_date"
REASON_GAME_NOT_FOUND = "game_not_in_ncaaf_live_state"
REASON_PROPS = "ncaaf_props_not_gradeable_from_scoreboard"
REASON_UNKNOWN_MARKET = "unmapped_market"
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
# PREFIXED, unlike `bet_status_nfl`'s otherwise-identical constant, and that
# asymmetry is deliberate. Both files defined the SAME string, so the first
# production read after this shipped showed `game_carries_no_scores: 18` with
# no way to say whether the NFL or the NCAAF resolver produced it -- the exact
# collapse this module refuses one field below, where `REASON_TEAM_UNRESOLVED`
# is kept distinct because "they point at different jobs". NFL keeps the
# unprefixed string because it is already deployed and its verification
# (2026-08-28T03:59:18Z) is recorded against it; renaming it would orphan that
# reading for a cosmetic gain.
REASON_NO_SCORES = "ncaaf_game_carries_no_scores"
# DISTINCT FROM `game_not_in_ncaaf_live_state` ON PURPOSE. That one says the
# fixture is not in a capture we DID read; this one says the ORDER's own team
# names could not be pinned to a team at all, so no capture could ever match
# them. They point at different jobs -- a poller gap versus a registry gap --
# and collapsing them is how the registry gap would stay invisible.
REASON_TEAM_UNRESOLVED = "ncaaf_team_not_in_registry_or_ambiguous"

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
    """Every NCAAF game captured for this date, in play or finished.

    Same contract and same lazy-capture reasoning as `bet_status_nfl._load_games`
    -- read through `refresh_state_store` (the matching half of the poller's
    write, because settlement runs on refresh-worker and Render cannot share a
    disk), and at most ONE scoreboard fetch per resolver construction on a miss
    rather than a new periodic task on a worker with 110 OOM kills on record.

    None means "could not read any live state", which is NOT "no games today".
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        from scripts.poll_ncaaf_live_state import live_state_path, poll_ncaaf_live_state
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None

    record = None
    try:
        record = read_json_file(live_state_path(selected_date))
    except Exception:
        record = None

    if not isinstance(record, Mapping) or not record.get("games"):
        try:
            fetched = poll_ncaaf_live_state(selected_date)
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


def ncaaf_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for NCAAF orders."""
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.ncaaf_team_registry import resolve_ncaaf_team_id

    cache: dict[str, Any] = {}

    def games() -> list[dict[str, Any]] | None:
        if "games" not in cache:
            cache["games"] = _load_games(selected_date)
        return cache["games"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "ncaaf":
            return {"unavailable_reason": REASON_NOT_NCAAF}

        # Market check FIRST: permanent before transient, so a structural gap is
        # not hidden behind a reason that looks like it will fix itself.
        market = order.get("market")
        canonical = _norm(market)
        if canonical in _TEAM_TOTAL_MARKETS:
            return {"unavailable_reason": REASON_TEAM_TOTAL}
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_line = is_game_line_market("ncaaf", market)
        if not (is_total or is_line):
            return {"unavailable_reason": REASON_PROPS if order.get("player_name") else REASON_UNKNOWN_MARKET}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        if not home_team or not away_team:
            return {"unavailable_reason": REASON_NO_MATCHUP}

        # RESOLVED TO IDS BEFORE ANYTHING IS COMPARED. A name that the registry
        # cannot pin -- unknown OR ambiguous -- ends the attempt here, so no
        # code below ever compares raw strings and no prefix rule can promote
        # "Michigan" into "Michigan State".
        home_id = resolve_ncaaf_team_id(home_team)
        away_id = resolve_ncaaf_team_id(away_team)
        if not home_id or not away_id or home_id == away_id:
            return {"unavailable_reason": REASON_TEAM_UNRESOLVED}

        found = games()
        if found is None:
            return {"unavailable_reason": REASON_NO_LIVE_STATE}

        record = None
        for candidate in found:
            # The capture stores several name forms; ANY of them resolving to
            # the right id is a match, and each is resolved through the same
            # unambiguous index, so a mascot cannot stand in for a school.
            cand_home = next(
                (r for r in (resolve_ncaaf_team_id(candidate.get(f))
                             for f in ("home_team", "home_abbr")) if r), None)
            cand_away = next(
                (r for r in (resolve_ncaaf_team_id(candidate.get(f))
                             for f in ("away_team", "away_abbr")) if r), None)
            if cand_home == home_id and cand_away == away_id:
                record = candidate
                break
        if record is None:
            return {"unavailable_reason": REASON_GAME_NOT_FOUND}

        home = _as_float(record.get("home_score"))
        away = _as_float(record.get("away_score"))

        if is_total:
            if home is None or away is None:
                return {"unavailable_reason": REASON_NO_SCORES}
            return {
                "current_value": home + away,
                "is_final": bool(record.get("final")),
                "started": True,
            }

        view = game_line_view(
            sport="ncaaf",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=record.get("home_score"),
            away_score=record.get("away_score"),
            # College football cannot tie -- overtime runs until someone wins --
            # so a level score is not a terminal state and `False` (two-way,
            # level is a push) is the honest encoding of a game that has not
            # finished. `h2h_3_way` is still three-way off the market name.
            draw_possible=False,
        )
        if "unavailable_reason" in view:
            return view
        view["is_final"] = bool(record.get("final"))
        view["started"] = bool(record.get("in_progress")) or bool(record.get("final"))
        return view

    return resolve
