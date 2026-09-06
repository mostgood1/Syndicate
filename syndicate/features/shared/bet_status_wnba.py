"""Resolve a WNBA bet's CURRENT value from the live player box score.

The sibling of `bet_status_mlb`, and deliberately the same shape: it answers
"what is the thing this bet is on worth right now" and leaves every judgement
about winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
KEYED ON `event_id`, WHICH SIDESTEPS MLB'S WHOLE PROBLEM
--------------------------------------------------------------------------

MLB cost a day because the board stamps `game_pk` from `row["event_id"]` -- the
OddsAPI hash -- while StatsAPI wants a numeric gamePk, and `int()` cannot parse
a hash. Every MLB order resolved to `no_game_pk`.

WNBA WAS BELIEVED TO HAVE NO SUCH GAP. IT HAS THE IDENTICAL ONE, AND THIS
PARAGRAPH USED TO SAY OTHERWISE: "the id on the record is the id in the
artifact". MEASURED IN PRODUCTION 2026-08-26 -- WNBA had settled ZERO orders
all-time while MLB had settled 157, and the refusal was `game_not_in_live_box`
on every one:

    order   event_id "1fb615886a5e9855f01b8c3824e8d937"  (the OddsAPI board hash)
    box     event_id "WSH@PHX"                           (2026-08-25)
    box     event_id "401857177"                         (2026-08-26, ESPN)

`_public_live_player_boxscore_payload` echoes back whatever event id its CALLER
passed, and that caller works in ESPN ids. The board hash is never among them,
so the two namespaces cannot meet and the lookup could never hit. The old claim
was an assumption written as a fact and never measured; the fixture that
'proved' it set both ids to the same string.

So this now does what `bet_status_mlb` does: try the id, then RECOVER FROM THE
MATCHUP. The recovery key is the WNBA tri-code pair, because the players in the
box already carry a canonical `team_tri` and `team_aliases.canonical_team`
deliberately refuses the tri-codes WNBA shares with the NBA (PHX, CHI and DAL
all return None) -- which is precisely the game this was failing on.

--------------------------------------------------------------------------
NO FINAL FLAG IN THIS ARTIFACT, AND THAT IS STATED RATHER THAN GUESSED
--------------------------------------------------------------------------

The capture stores what `/wnba/api/live_player_boxscore` returns: minutes,
points, rebounds, assists, threes. **There is no game-status field.** So this
resolver reports `is_final=False` ALWAYS, and never claims a game has ended.

That is not a shrug -- it is exactly right for the bets in question, because it
loses nothing on the OVER side. Points, rebounds, assists and threes are
counting stats, so `bet_status.is_monotone_market` returns True for all of them
and an over DECIDES the instant it crosses its line, final flag or not. What it
costs is the under side: an under cannot be settled until the game is known to
be over, so it stays `live_ahead` rather than grading.

Claiming a game was final on a guess would be the opposite trade: it would
settle unders early, and an under graded at halftime is a confident wrong
answer on a bet that was still live. Waiting is recoverable; that is not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.bet_status import segment_refusal

__all__ = ["wnba_status_resolver"]

REASON_NO_EVENT_ID = "no_event_id"
REASON_NO_BOX = "no_live_box_for_date"
REASON_GAME_NOT_IN_BOX = "game_not_in_live_box"
# The LIVE player box carries no team scores, and never will -- it is a player
# capture. Kept as the reason for a game line that can only be read from the
# live box, i.e. one whose game is not in the FINAL box yet.
#
# THIS COMMENT USED TO SAY "the fix is upstream in the capture". That was wrong,
# and the correction is kept here because the sentence is what stopped anyone
# looking: the fix was neither upstream nor a missing table entry, it was that
# nothing ever tried the artifact that already had the answer.
# `boxscores_<date>.csv` carries `TEAM_ABBREVIATION` and `PTS` per player, and
# in basketball a team's score IS the sum of its players' points -- no team-level
# scoring exists, unlike an own goal or a defensive touchdown.
#
# MEASURED against ESPN's official scoreboard before this was relied on,
# 2026-08-28. Derived (sum of player PTS from the CSV) vs official, 2026-08-25:
#
#     401857173  CHI 81 / CON 87     ESPN  CHI 81 / CON 87
#     401857174  DAL 96 / POR 78     ESPN  DAL 96 / POR 78
#     401857175  PHX 84 / WSH 94     ESPN  PHX 84 / WSH 94
#
# Six of six exact, both sides of every game. The derivation is not an estimate.
REASON_NO_TEAM_SCORES = "no_team_scores_in_player_box"
# The game line reached the final box and could not be scored from it. SPLIT
# INTO CAUSES, because "no final box yet" (wait) and "the box has the game but
# the roster looks truncated" (a capture bug) are different jobs, and
# `REASON_NO_TEAM_SCORES` used to be the single answer for all of them.
REASON_NO_FINAL_BOX = "no_final_box_for_date"
REASON_GAME_NOT_IN_FINAL_BOX = "game_not_in_final_box"
REASON_FINAL_BOX_ROSTER_THIN = "final_box_roster_too_thin_to_total"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_PLAYER_NOT_FOUND = "player_not_in_box"
REASON_NO_STAT = "stat_not_in_box"
# The box has no row under the order's event id AND the order carries no teams
# to recover from. Distinct from `game_not_in_live_box`, which now means "we
# tried the matchup too and the game genuinely is not in the capture" -- the
# same split `bet_status_mlb` draws between `no_matchup_on_order` and
# `matchup_not_on_schedule`.
REASON_NO_MATCHUP_ON_ORDER = "no_matchup_on_order"

# Canonical board market -> the key the live box row carries.
# Canonical because `market_keys` owns that vocabulary (`#224`); the RAW board
# name is canonicalised on the way in, so both spellings resolve. Four separate
# market tables drifted apart in this codebase on 2026-08-23 and every one of
# them was a private list exactly like this one would have been.
_MARKET_TO_BOX_KEY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes_made",
}

# Combination markets the box does not carry directly but can SUM. Listed
# explicitly rather than parsed out of the market name: `player_points_rebounds`
# and `player_points_rebounds_assists` differ by one token and a prefix rule
# would price one as the other.
# THE SAME STATS IN THE FINAL BOXSCORE'S SPELLING. `boxscores_<date>.csv` is
# written by `scripts/build_wnba_boxscores.py` from ESPN's official box AFTER a
# game is complete, so unlike the live capture it carries a value that will not
# change again -- which is the whole reason settlement can trust it as final.
#
# A SEPARATE TABLE RATHER THAN A RENAME, because the two artifacts genuinely
# spell these differently (`threes_made` vs `FG3M`) and folding them would make
# a future divergence silent.
_BOX_KEY_TO_CSV: dict[str, str] = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "threes_made": "FG3M",
    "mp": "MIN",
}


_MARKET_TO_BOX_SUM: dict[str, tuple[str, ...]] = {
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
}


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _canonical(market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    return canonical_market_key("wnba", raw) or raw


def wnba_status_resolver(selected_date: str):
    """A resolver `bet_status`/`paper_settlement` can inject, for WNBA orders.

    The box is read ONCE per resolver, not once per order: a slate of forty
    orders must not mean forty reads of one unchanging artifact.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    cache: dict[str, Any] = {}

    def box_index() -> dict[str, dict[str, Mapping[str, Any]]] | None:
        if "index" in cache:
            return cache["index"]
        cache["index"] = _load_box_index(selected_date, normalize_name)
        return cache["index"]

    def final_rows():
        # THE ARTIFACT, READ ONCE. Both the player index and the team-score
        # index are derived from this, so adding game lines costs no extra read.
        if "final_rows" not in cache:
            cache["final_rows"] = _final_csv_rows(selected_date)
        return cache["final_rows"]

    def final_box():
        # Read ONCE per resolver, same rule as the live box: a slate of forty
        # orders must not mean forty reads of one unchanging artifact.
        if "final" in cache:
            return cache["final"]
        cache["final"] = _load_final_box(final_rows(), normalize_name)
        return cache["final"]

    def final_team_scores():
        if "final_teams" not in cache:
            cache["final_teams"] = _load_final_team_scores(final_rows())
        return cache["final_teams"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if str(order.get("sport") or "").strip().lower() != "wnba":
            # This resolver is handed every order; a non-WNBA one is not a
            # defect in anything and must not be reported as a WNBA failure.
            return {"unavailable_reason": f"not_a_wnba_order"}

        # SEGMENT BEFORE MARKET, AND IT MOVED UP HERE FROM
        # `_game_line_from_final_box` -- where it was correct but reachable only
        # by GAME LINES. A `segment="h1"` PLAYER PROP walked straight past it,
        # matched `_MARKET_TO_BOX_KEY["player_points"]`, and got graded off the
        # whole-game box. Same defect, one market family over.
        #
        # The wording is WNBA's own, not the shared default: this string is a
        # recorded reading in `state_basketball.md` and renaming it would orphan
        # that for nothing. Everything else about the check is now shared with
        # mlb / ncaaf / nfl / soccer, which had no such check at all.
        refusal = segment_refusal(order, reason_prefix="final_box_is_full_game_not_")
        if refusal is not None:
            return refusal

        # THE MARKET CHECK COMES FIRST, before the artifact read. "We have no
        # box key for this market" is permanent; "the box is not captured yet"
        # is temporary, and checking the transient one first hides the
        # structural one -- measured on the MLB grader this morning, where
        # `no_live_feed: 50` concealed 40 orders that could never grade.
        market = _canonical(order.get("market"))
        box_key = _MARKET_TO_BOX_KEY.get(market)
        sum_keys = _MARKET_TO_BOX_SUM.get(market)
        if box_key is None and sum_keys is None:
            # A GAME LINE IS NOT AN UNMAPPED PROP, and lumping the two together
            # is what made this invisible for months.
            #
            # IT USED TO REFUSE HERE, on the grounds that "this artifact is a
            # PLAYER box and carries none [no team scores], so the blocker is
            # the capture, not the vocabulary." The first half was true and the
            # conclusion was wrong: the FINAL box carries `TEAM_ABBREVIATION`
            # and `PTS` per player, and in basketball the team's score IS the
            # sum of its players' points. Nothing upstream had to change.
            #
            # WHAT THAT COST, measured 2026-08-28: two filled Kalshi totals on
            # `GSV @ CON` 2026-08-26 (over and under 151.5) sat ungraded for two
            # days. Every OTHER WNBA row on that slate had been settled by the
            # VENUE -- so WNBA game lines only ever settled when Kalshi settled
            # them for us, and the pair Kalshi missed could never be recovered.
            # The real total was 153 (GS 89, CON 64), confirmed against ESPN.
            #
            # A TOTAL IS NOT A "GAME LINE" HERE, and that distinction cost me a
            # wrong attribution before I checked it. `is_game_line_market`
            # covers moneylines and spreads ONLY -- `game_line_view`'s job is
            # translating a TEAM side into a value/direction/number, and a
            # total needs none of that: `over`/`under` is already the grader's
            # vocabulary and the value is just the combined score.
            #
            # So `totals` fell to `REASON_UNMAPPED_MARKET`, NOT to
            # `REASON_NO_TEAM_SCORES`. Both were refusals and both were wrong
            # for the same underlying reason, but they sat in different buckets
            # -- which is why the 2026-08-26 counter read `unmapped_market: 6`
            # while the two stuck totals looked like they belonged to
            # `no_team_scores_in_player_box: 2`. They did not.
            if is_game_line_market("wnba", market) or _is_total_market(market):
                return _game_line_from_final_box(order, market, final_team_scores())
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        event_id = str(order.get("event_id") or "").strip()
        if not event_id:
            return {"unavailable_reason": REASON_NO_EVENT_ID}

        # THE FINAL BOXSCORE FIRST, because it is the only reading that can be
        # DECIDED. It exists only for completed games, so a hit here means the
        # game is over and the value will not change again -- which is what lets
        # a losing over settle instead of waiting forever.
        finals = final_box()
        if finals is not None:
            row = finals.get(normalize_name(order.get("player_name")))
            if row is not None:
                if sum_keys is not None:
                    parts = [row.get(key) for key in sum_keys]
                    if any(part is None for part in parts):
                        # A partial sum is a smaller number that looks real.
                        return {"unavailable_reason": REASON_NO_STAT}
                    value = sum(parts)
                else:
                    value = row.get(box_key)
                    if value is None:
                        return {"unavailable_reason": REASON_NO_STAT}
                return {
                    "matched_by": "final_boxscore",
                    "current_value": value,
                    # THE POINT OF ALL OF THIS.
                    "is_final": True,
                    "started": True,
                }
            # The player is not in the final box. FALLS THROUGH to the live box
            # rather than refusing: a box for the date can exist while an
            # earlier game of a doubleheader is still being written, and a DNP
            # is deliberately absent rather than zeroed.

        index = box_index()
        if index is None:
            return {"unavailable_reason": REASON_NO_BOX}
        players = index["by_event"].get(event_id)
        recovered = False
        if players is None:
            # THE ID MISSING IS THE NORMAL CASE, NOT AN ERROR: the order carries
            # the board's OddsAPI hash and the box carries an ESPN id. Recover
            # from the matchup, exactly as MLB does.
            key_pair = _matchup_key(order.get("away_team"), order.get("home_team"))
            if key_pair is None:
                # The ledger row is too thin to recover from -- a different fact
                # from "the game is not in the capture", and the two must not
                # share a counter or the work list points at the wrong job.
                return {"unavailable_reason": REASON_NO_MATCHUP_ON_ORDER}
            players = index["by_matchup"].get(key_pair)
            if players is None:
                return {"unavailable_reason": REASON_GAME_NOT_IN_BOX}
            recovered = True

        row = players.get(normalize_name(order.get("player_name")))
        if row is None:
            # The player is not in this game's box, OR the name did not match.
            # Named rather than defaulted to 0: a bet reported as "0 points,
            # Under is fine" when we simply failed to find her is the worst
            # possible wrong answer, and it is the one `bet_status_mlb` calls
            # out for the same reason.
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}

        if sum_keys is not None:
            parts = [_as_float(row.get(key)) for key in sum_keys]
            if any(part is None for part in parts):
                # A partial sum is a smaller number that looks like a real one.
                return {"unavailable_reason": REASON_NO_STAT}
            value = sum(parts)
        else:
            value = _as_float(row.get(box_key))
            if value is None:
                return {"unavailable_reason": REASON_NO_STAT}

        return {
            # How the game was found. A recovery that is invisible is a recovery
            # nobody can audit on the day it joins the wrong game.
            "matched_by": "matchup" if recovered else "event_id",
            "current_value": value,
            # ALWAYS False -- this artifact carries no game status. See the
            # module docstring: overs still decide on crossing because these are
            # counting stats, and unders wait rather than being settled on a
            # guess about whether the game ended.
            "is_final": False,
            "started": True,
        }

    return resolve




# Fewest players a real WNBA box can list for one team. FIVE, because five are
# on the floor -- a team cannot record a game with fewer, so anything under it
# is a TRUNCATED CAPTURE rather than a short bench.
#
# This is the guard the summing rule needs and the one `_MARKET_TO_BOX_SUM`
# already states the principle for: "a partial sum is a smaller number that
# looks real". A team score summed from half a roster is exactly that, and it
# would settle a total UNDER on a number that was never the score. Measured
# rosters on 2026-08-25/26 ran 9-14 players per team, so this floor is well
# clear of the real distribution and only fires on a broken capture.
_MIN_PLAYERS_FOR_TEAM_TOTAL = 5


def _final_csv_rows(selected_date: str) -> list[dict[str, Any]] | None:
    """The final boxscore CSV as rows, or None if it is unreadable/absent.

    Split out of `_load_final_box` so the player index and the team-score index
    are two derivations of ONE read -- a resolver that read this artifact twice
    per slate would be the same waste the `box_index` cache exists to avoid.
    """
    import csv as _csv
    import io as _io

    from syndicate.features.shared.refresh_state_store import data_root, read_text_file

    try:
        raw = read_text_file(
            data_root() / f"wnba_source/data/processed/boxscores_{selected_date}.csv"
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        return list(_csv.DictReader(_io.StringIO(str(raw))))
    except Exception:
        return None


def _load_final_team_scores(rows) -> dict[Any, dict[str, Any]] | None:
    """`frozenset(tri, tri) -> {"scores": {tri: points}, "players": {tri: n}}`.

    ----------------------------------------------------------------------
    THE TEAM SCORE A PLAYER BOX WAS ALWAYS ABLE TO GIVE
    ----------------------------------------------------------------------

    `REASON_NO_TEAM_SCORES` has been the answer for every WNBA game line since
    the resolver was written, on the stated grounds that "this capture is a
    PLAYER box and has none, so the fix is upstream in the capture". The
    upstream fix was never needed: in basketball a team's score IS the sum of
    its players' points. There is no team-level scoring -- no own goal, no
    defensive touchdown, no wild pitch -- so the sum is not an estimate of the
    score, it is the score.

    VERIFIED AGAINST ESPN BEFORE USE, 2026-08-25, six of six exact on both
    sides of all three games (see `REASON_NO_TEAM_SCORES`). Repeated on
    2026-08-26: `401857176` GS 89 / CON 64 against ESPN's `GS 89, CON 64`.

    KEYED ON THE MATCHUP, NOT THE EVENT ID, for the reason this module already
    documents at length: the order carries the board's OddsAPI hash and this
    artifact carries an ESPN id, and the two namespaces never meet. The
    tri-codes do -- `_canonical_wnba_tri` maps the CSV's `TEAM_ABBREVIATION`
    and the order's full club name onto the same code, checked both directions
    on all nine clubs before this was written (`GS`/`Golden State Valkyries`
    both -> `GSV`, `CON`/`Connecticut Sun` both -> `CON`, and so on).

    A GAME WITH ANYTHING OTHER THAN EXACTLY TWO TEAMS IS DROPPED. Not repaired
    and not partially reported: three teams under one `game_id` means the CSV
    is not what this function thinks it is, and a "score" read out of it would
    be a confident wrong number.
    """
    if rows is None:
        # NO ARTIFACT. Distinct from an artifact with no usable game in it --
        # see the return below. The caller turns the first into
        # `no_final_box_for_date` (wait for the capture) and the second into
        # `game_not_in_final_box` (the capture ran and this game is not in it),
        # and collapsing them would send the reader to the wrong job.
        return None

    by_game: dict[str, dict[str, dict[str, float]]] = {}
    poisoned: set[str] = set()
    for row in rows:
        game_id = str(row.get("game_id") or row.get("gameId") or "").strip()
        tri = _wnba_tri(row.get("TEAM_ABBREVIATION"))
        if not game_id or not tri:
            continue
        points = _as_float(row.get("PTS"))
        if points is None:
            # AN UNREADABLE POINTS CELL POISONS THE WHOLE GAME rather than
            # being skipped. Skipping it would silently subtract that player's
            # points from their team's score -- the "partial sum is a smaller
            # number that looks real" failure, applied to a game total.
            #
            # Recorded in a SET rather than by clearing the game's dict: a
            # later row would simply repopulate a cleared dict, so the poison
            # has to outlive the rows it came from.
            poisoned.add(game_id)
            continue
        teams = by_game.setdefault(game_id, {})
        entry = teams.setdefault(tri, {"points": 0.0, "players": 0.0})
        entry["points"] += points
        entry["players"] += 1

    index: dict[Any, dict[str, Any]] = {}
    for game_id, teams in by_game.items():
        if game_id in poisoned or len(teams) != 2:
            continue
        tris = sorted(teams)
        key = frozenset(tris)
        if key in index:
            # The same two clubs twice on one date. A doubleheader does not
            # happen in this league, so this is an artifact defect; refusing
            # both is the only safe reading, and it is why the key is removed
            # rather than overwritten.
            index[key] = {"ambiguous": True}
            continue
        index[key] = {
            "game_id": game_id,
            "scores": {tri: teams[tri]["points"] for tri in tris},
            "players": {tri: int(teams[tri]["players"]) for tri in tris},
        }
    # AN EMPTY DICT, NOT None. Rows existed; no game survived them (every game
    # poisoned, or none with exactly two teams). `no_final_box_for_date` would
    # be a false statement about a file that is right there.
    return index


# Canonical market names whose value is the COMBINED score. Listed rather than
# prefix-matched: `totals` and `player_points` both contain "points" under some
# spellings, and a prefix rule over market names is how one market gets graded
# as another.
_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})

# The only segment a FINAL score can grade. A first-half or quarter total is a
# real market this artifact cannot answer -- the boxscore carries the whole
# game and nothing else -- and grading one off the final score would be a
# confident wrong answer rather than a missing one.
_FULL_GAME_SEGMENT = "full"


def _is_total_market(market: Any) -> bool:
    return str(market or "").strip().lower() in _TOTAL_MARKETS


def _game_line_from_final_box(order, market, team_scores) -> dict[str, Any]:
    """Grade a WNBA spread/total/moneyline off the FINAL boxscore, or refuse.

    `is_final=True` is asserted rather than assumed: `build_wnba_boxscores`
    writes ONLY completed games, so a game's presence in this artifact IS the
    statement that it is over. That is the same reasoning the player path uses
    one function down, and it is what lets an UNDER settle -- the side that,
    with `is_final` hardcoded False, could never decide at all.

    REFUSES BY CAUSE, because the causes need different work: no artifact yet
    (wait), the game not in it (wait, or a join to check), a roster too thin to
    sum (a capture bug), a matchup we cannot key (a thin ledger row).
    """
    from syndicate.features.shared.game_line_bet import game_line_view

    # THE SEGMENT CHECK THAT STOOD HERE NOW RUNS AT THE RESOLVER ENTRY, and is
    # deleted rather than left as a second line of defence. `resolve` (~:205) is
    # this function's ONLY caller -- verified, not assumed -- so a copy here is
    # unreachable code that reads as protection, and the next person to change
    # one of the two would have no way to know which one fires. The refusal
    # string is unchanged; only the place it is decided moved, so that PLAYER
    # PROPS are covered too. They never reached this function.
    if team_scores is None:
        # No final box for the date. NOT the same as "this game is unfinished",
        # and the live box genuinely has no team scores to fall back on -- so
        # the old reason is still the right one for exactly this case.
        return {"unavailable_reason": REASON_NO_FINAL_BOX}

    key = _matchup_key(order.get("away_team"), order.get("home_team"))
    if key is None:
        return {"unavailable_reason": REASON_NO_MATCHUP_ON_ORDER}

    game = team_scores.get(key)
    if not game or game.get("ambiguous"):
        return {"unavailable_reason": REASON_GAME_NOT_IN_FINAL_BOX}

    home_tri = _wnba_tri(order.get("home_team"))
    away_tri = _wnba_tri(order.get("away_team"))
    scores = game.get("scores") or {}
    players = game.get("players") or {}
    if home_tri not in scores or away_tri not in scores:
        # The matchup key matched but a side did not. `_matchup_key` is a
        # frozenset, so it cannot tell home from away -- this is the check that
        # does, and without it a swapped pair would score the wrong side.
        return {"unavailable_reason": REASON_GAME_NOT_IN_FINAL_BOX}

    if min(players.get(home_tri, 0), players.get(away_tri, 0)) < _MIN_PLAYERS_FOR_TEAM_TOTAL:
        # A TRUNCATED CAPTURE, not a short bench. See the constant: a summed
        # score off half a roster is a smaller number that looks real, and on a
        # total it would settle the UNDER on a score that never happened.
        return {"unavailable_reason": REASON_FINAL_BOX_ROSTER_THIN}

    home_score = scores[home_tri]
    away_score = scores[away_tri]

    if _is_total_market(market):
        # NO `game_line_view` CALL. It exists to turn a TEAM side into a value
        # and a direction; a total's side is already `over`/`under` and its
        # value is the combined score, so routing it through would ask a
        # translator to translate something already in the target language --
        # and `game_line_view` correctly refuses it as an unknown game market.
        return {
            "matched_by": "final_boxscore_team_totals",
            "current_value": home_score + away_score,
            "is_final": True,
            "started": True,
            "home_score": home_score,
            "away_score": away_score,
            "home_name": order.get("home_team"),
            "away_name": order.get("away_team"),
        }

    view = game_line_view(
        sport="wnba",
        market=market,
        side=order.get("side"),
        line=order.get("line"),
        home_team=order.get("home_team"),
        away_team=order.get("away_team"),
        home_score=home_score,
        away_score=away_score,
        # BASKETBALL CANNOT TIE. Overtime is played until it does not, so a
        # moneyline is a two-way market and `game_line_view` must not hold a
        # push open for a draw that the sport does not have.
        draw_possible=False,
    )
    if view.get("unavailable_reason"):
        return view
    return {
        **view,
        "matched_by": "final_boxscore_team_totals",
        "is_final": True,
        "started": True,
        "home_score": home_score,
        "away_score": away_score,
        "home_name": order.get("home_team"),
        "away_name": order.get("away_team"),
    }


def _load_final_box(rows, normalize_name):
    """`normalized player name -> {stat -> float}` from the FINAL boxscore, or None.

    THE FINAL FLAG THIS MODULE NEVER HAD. The live player box carries no game
    status, so `is_final` was hardcoded False and `resolve_bet_status` decides
    only on `is_final` OR the value crossing its line. An over that falls short
    therefore NEVER decided, and ONLY WINNING OVERS SETTLED.

    MEASURED 2026-08-25 against ESPN: Sonia Citron 1 rebound against over 3.5
    and Georgia Amoore 3 assists against over 3.5 are losses that could never be
    recorded, while Natasha Mack's over 7.5 (8 rebounds) graded within minutes.
    A win rate computed over that is 100% by construction.

    `build_wnba_boxscores` writes ONLY completed games, so a player's presence
    here IS the assertion that their game is over. None means no final box for
    the date -- NOT that the game is unfinished, which is why the caller falls
    back to the live box rather than refusing.
    """
    if rows is None:
        return None

    index: dict[str, dict[str, float]] = {}
    for row in rows:
        key = normalize_name(row.get("PLAYER_NAME"))
        if not key:
            continue
        stats: dict[str, float] = {}
        for box_key, column in _BOX_KEY_TO_CSV.items():
            value = _as_float(row.get(column))
            if value is not None:
                stats[box_key] = value
        if stats:
            index[key] = stats
    return index or None


def _wnba_tri(value):
    """A WNBA tri-code for a team name, or None.

    `wnba/cards.py` owns this vocabulary and already maps full names onto the
    same codes the box's `team_tri` carries. Imported rather than restated: a
    second table here is how two spellings drift, and `bet_status_mlb` reaches
    into `mlb/cards.py` for `_schedule_raw_games` for exactly the same reason.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from syndicate.features.wnba.cards import _canonical_wnba_tri
    except Exception:
        return None
    try:
        tri = _canonical_wnba_tri(text)
    except Exception:
        return None
    tri = str(tri or "").strip().upper()
    return tri or None


def _matchup_key(one, two):
    """An order-independent key for the two clubs in a game.

    A frozenset, not a tuple: home/away is exactly the convention most likely to
    be written the other way round on one of the two sides, and a swapped pair
    that silently fails to join is indistinguishable from an absent game.
    """
    left, right = _wnba_tri(one), _wnba_tri(two)
    if not left or not right or left == right:
        return None
    return frozenset((left, right))

def _load_box_index(selected_date: str, normalize_name) -> dict[str, dict[str, Mapping[str, Any]]] | None:
    """Both indexes over the box, or None if unreadable.

    `{"by_event": {event_id: {player -> row}},
      "by_matchup": {frozenset(tri, tri): {player -> row}}}`

    None means "we could not read the box", which is NOT the same as a box with
    no games in it -- the caller reports them as different reasons.
    """
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    try:
        record = read_json_file(
            data_root() / f"wnba_source/data/live/live_player_box_{selected_date}.json"
        )
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else record

    index: dict[str, dict[str, Mapping[str, Any]]] = {}
    by_matchup: dict[Any, dict[str, Mapping[str, Any]]] = {}
    for game in payload.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        players: dict[str, Mapping[str, Any]] = {}
        tris: set[str] = set()
        for player in game.get("players") or []:
            if not isinstance(player, Mapping):
                continue
            key = normalize_name(player.get("player") or player.get("player_name"))
            if key:
                players[key] = player
            tri = str(player.get("team_tri") or "").strip().upper()
            if tri:
                tris.add(tri)
        index[event_id] = players

        # THE MATCHUP, from the two clubs actually present in the box. Taken
        # from the PLAYERS because that is the only place this artifact records
        # a team at all -- the game object carries an id and a player list and
        # nothing else. An `AAA@BBB` event id is a second source, since the
        # live-lens path emits that shape on some dates and bare ESPN ids on
        # others.
        if len(tris) != 2 and "@" in event_id:
            parts = [part.strip() for part in event_id.split("@", 1)]
            if len(parts) == 2 and all(parts):
                tris = {t for t in (_wnba_tri(parts[0]), _wnba_tri(parts[1])) if t}
        if len(tris) == 2:
            # A DOUBLEHEADER WOULD COLLIDE HERE, so the first game wins and the
            # second keeps only its event id rather than overwriting. Recovering
            # the WRONG game of a pair grades a bet against the wrong score,
            # which is worse than not grading it.
            by_matchup.setdefault(frozenset(tris), players)
    return {"by_event": index, "by_matchup": by_matchup}
