"""Soccer projections for the Layer 1 board (S3, third sport after MLB/WNBA).

Audited 2026-08-07: soccer rendered **0.0% projections on all 7 markets** while
identity/line/odds were 100%.

WHAT THE SOURCE ACTUALLY CARRIES, checked field by field rather than assumed --
`recommendations_<date>.json`, per league:

    win_probability      {home, draw, away}   REAL probability
    anytime_scorer_probability                REAL probability (per player)
    total_distribution   {mean, over_2_5_probability, both_teams_scored_...}
    spread_distribution  {home: margin, away: -margin}
    expected_shots / expected_shots_on_target REAL means (per player)

The two `*_distribution` keys are **summary statistics, not distributions**, and
the naming invites exactly the wrong assumption. `total_distribution` can answer
P(over) at **2.5 and nowhere else**; at any other line it has a mean and nothing
more -- but `scoreline_probabilities` is published beside it and IS a real
distribution, so totals at any line are summed from that rather than inferred
from a mean (see `_total_prob_from_scorelines`). `spread_distribution` is a
single margin number and still has no such companion.

So this emits a probability ONLY where one genuinely exists, and a mean
otherwise -- never a probability derived from a mean. Where a real probability
is present the row gets `model_prob_over` and can carry a true
`edge_vs_market_pct`; where only a mean is present it gets `projected` +
`edge_vs_line`, the same contract WNBA uses. Every row states its `basis` so a
reader can tell the two apart, because "0.65" from a simulation and "0.65"
inferred from a mean are not the same claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.prop_projections import _norm_name
from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.book_margin_model import (
    EDGE_FIELD as MODELLED_EDGE_FIELD,
    modelled_fair_edge,
)

# Player-prop market -> field on the player_props entry, and whether that field
# is a PROBABILITY or a MEAN. Getting this wrong in either direction is the
# whole risk: a mean presented as a probability is a fabricated edge.
_PLAYER_FIELDS: dict[str, tuple[str, str]] = {
    "player_goal_scorer_anytime": ("anytime_scorer_probability", "probability"),
    "player_shots": ("expected_shots", "mean"),
    "player_shots_on_target": ("expected_shots_on_target", "mean"),
}

# PER-LINE PROBABILITY DICTS, PREFERRED OVER THE MEAN ABOVE WHERE PRESENT.
#
# The sim publishes `{line: P(over line)}` for shots, shots on target and
# assists -- real probabilities from the same allocation the means come from,
# not an inference off them. Priced from the mean, these markets could only
# ever carry `edge_vs_line` in SHOT units, which `_model_edge_for` correctly
# refuses to add to an EV percentage; so they ranked on EV alone and the sim
# had no say. `player_assists` had no projection at all.
#
# Falls back to `_PLAYER_FIELDS` when the dict is absent -- an artifact built
# before these were allowlisted degrades to exactly the previous behaviour
# rather than to a wrong number, and `#170`-style rebuild lag is the norm here.
#: Corners totals, priced from `volume_projection` and NEVER from the goals
#: model -- see the branch in `attach_soccer_projections` for the recorded
#: near-miss that separation exists to prevent. Both spellings are listed
#: because the board carries `alternate_totals_corners` today and a plain
#: `totals_corners` is the obvious sibling; an absent key simply never matches.
_CORNERS_MARKETS: frozenset[str] = frozenset({
    "alternate_totals_corners",
    "totals_corners",
})

_PLAYER_PROB_BY_LINE: dict[str, str] = {
    "player_shots": "shots_over_probabilities",
    "player_shots_on_target": "shots_on_target_over_probabilities",
    "player_assists": "assists_over_probabilities",
}


def _prob_at_line(entry: Mapping[str, Any], field: str, line: Any) -> float | None:
    """P(over `line`) from a `{line: prob}` dict, EXACT MATCH ONLY.

    Deliberately no nearest-line fallback: 0.5 and 1.5 assists are different
    questions, and answering one with the other's number is the substitution
    this module exists to refuse. A line the sim did not price returns None and
    the caller falls back to the mean.
    """
    table = entry.get(field)
    if not isinstance(table, Mapping) or not table:
        return None
    target = _as_float(line)
    if target is None:
        return None
    for key, value in table.items():
        if _as_float(key) == target:
            prob = _as_float(value)
            if prob is not None and 0.0 <= prob <= 1.0:
                return prob
    return None

# `player_first_goal_scorer` / `player_last_goal_scorer` are NOT in the table
# above because they are not a field lookup -- they are DERIVED, per match, by
# `soccer_scorer_markets.scorer_race` (`#368`). The note that stood here said
# reusing the anytime probability would overstate every row, which was true; a
# Poisson race is a transformation rather than a reuse, and it is anchored on the
# match's own expected goals so incomplete player lists leave probability
# unallocated instead of inflating whoever happens to be listed.
_DERIVED_SCORER_MARKETS = {"player_first_goal_scorer", "player_last_goal_scorer"}

_TOTALS_EXACT_PROB_LINE = 2.5

# Game markets whose third leg is a KNOWN, enumerable outcome (the draw), so a
# three-leg de-vig spans the whole outcome space. `_no_vig_over_probability`
# handles exactly these: it finds `draw`/`tie`/`x`, includes it in the
# denominator, and returns None if the leg is quoted-but-priceless rather than
# de-vigging across two of three. Anything NOT on this list keeps the old
# refusal -- see `_price_against_market` for why "three sides" alone is not a
# licence to de-vig.
_THREE_WAY_GAME_MARKETS = {"h2h", "h2h_3_way", "totals_3_way", "spreads_3_way"}


from syndicate.features.shared.team_aliases import teams_match  # noqa: E402
from syndicate.features.shared.probability_refusal import refuse_published_certainty


def _norm_team(value: Any) -> str:
    return _norm_name(value)


@dataclass
class SoccerProjectionIndex:
    by_event: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_teams: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    players_by_match: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    leagues: list[str] = field(default_factory=list)
    matches: int = 0
    source_paths: list[str] = field(default_factory=list)
    # `#350`: when each league's simulation was produced. A projection has an
    # age and the board never showed it -- measured 2026-08-11, la_liga's
    # 2026-08-15 recommendations carried `generated_at: 2026-07-20`, so the
    # board was pairing a 22-DAY-OLD sim with odds quoted minutes earlier and
    # rendering it identically to a fresh one. Prices carry `age_seconds`;
    # projections carried nothing.
    generated_at_by_league: dict[str, str] = field(default_factory=dict)
    # Which dates were actually read, so a zero is attributable to the slate
    # rather than to a one-date read. Same reason `per_sport_ingest` carries
    # `window_dates` for the quote side (`#379`).
    dates: list[str] = field(default_factory=list)
    # TEAM KEYS THAT NOW REFER TO MORE THAN ONE FIXTURE, and therefore to none.
    #
    # Load-bearing only since the index went multi-date. `match_for` documents
    # that the two feeds use different id schemes (ESPN in the sim, OddsAPI on
    # the board), so `by_event` "can never hit across these two feeds" and the
    # join is in practice keyed on TEAM NAMES. Within one date that is safe: a
    # club plays once. Across a 7-day window it is not -- a midweek cup tie and
    # a weekend league game share (home, away), `by_teams` is a plain write, so
    # the later file would silently overwrite the earlier and hand a row for one
    # fixture the projection for the other.
    #
    # A wrong projection is far worse than a blank one (this module's own words,
    # about the alias fallback). So a colliding key is REMOVED and recorded
    # rather than resolved by guessing which fixture the row meant.
    ambiguous_team_keys: set[tuple[str, str]] = field(default_factory=set)

    def match_for(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """Find this row's projection: event id, exact names, then aliases.

        `#346`: THE EVENT IDS CANNOT JOIN AND THE NAMES OFTEN DO NOT MATCH
        EXACTLY. Measured on production 2026-08-11, primeira_liga:

            source  event_id '401885486'   (ESPN)     home 'Santa Clara'  away 'C.D. Nacional'
            board   event_id 'abbf3c5f…'   (OddsAPI)  home 'Santa Clara'  away 'Nacional'

        Two different id schemes, so the `by_event` lookup can never hit across
        these two feeds; and the exact tuple lookup missed on `nacional` vs
        `c d nacional`. Result: `unmatched_match_rows: 9` of 9 -- the sim had a
        projection for the only fixture on the board and none of it was shown.

        The alias fallback uses `teams_match`, which already resolves the club
        prefixes soccer feeds disagree on (`C.D.`, `FC`, `S.L.`). Verified on
        the real variants: nacional/c.d. nacional, porto/fc porto,
        benfica/s.l. benfica all match; `sporting cp`/`sporting` does NOT, and
        that is correct -- several clubs are called Sporting and guessing would
        attach one club's projection to another's price.

        BOTH SIDES MUST MATCH, AND AMBIGUITY RETURNS NOTHING. If two indexed
        fixtures both alias-match this row, the join cannot know which, and a
        wrong projection is far worse than a blank one -- it puts a real number
        next to the wrong bet.

        THE ALIAS FALLBACK MUST SEE RAW NAMES, NOT NORMALISED ONES. `_norm_team`
        is `prop_projections._norm_name`, which replaces a non-ASCII character
        with a SPACE rather than folding it:

            'Vitória SC'           -> 'vit ria sc'
            'Vitória de Guimaraes' -> 'vit ria de guimaraes'

        `teams_match` then normalises again internally, but its alias map is
        keyed on `normalize` ('vitória sc') and `fold_accents` ('vitoria sc') --
        neither of which is 'vit ria sc'. So `canonical_team` returned None for
        BOTH sides, the authoritative map could not answer, and the heuristics
        could not rescue it. Feeding it pre-normalised text destroyed the only
        thing it needed.

        Measured 2026-08-15 by reproducing the real join against the served
        board and the four production recommendation files:
        `teams_match(raw, raw)` is **True** and `teams_match(normed, normed)` is
        **False** for exactly this pair -- primeira_liga was the one league of
        four serving 0 projections, on a fixture whose sim payload was complete
        (`win_probability {home 0.28, draw 0.2625, away 0.4575}`).

        NOT A ONE-FIXTURE FIX. 9 of 204 configured clubs across 5 leagues carry
        a non-ASCII name and had a dead alias fallback: Atlético Madrid, Alavés,
        Málaga, Deportivo La Coruña (la_liga), Borussia Mönchengladbach,
        CF Montréal, Académico de Viseu, Vitória de Guimaraes, RAAL La Louvière.
        They still joined whenever both feeds happened to spell the club
        IDENTICALLY -- both sides get mangled the same way, so the exact tuple
        lookup above survives -- which is why this stayed invisible: the safety
        net for a name DISAGREEMENT was the only part broken, and only for
        accented clubs. la_liga opens 08-21/08-22, so four more of these were
        about to enter the sim horizon.

        The index side is read back from the match's own `matchup`, because
        `by_teams` is keyed on the same mangled form and comparing mangled to
        raw would fail in the other direction.
        """
        event_id = str(row.get("event_id") or "").strip()
        if event_id and event_id in self.by_event:
            return self.by_event[event_id]
        home = _norm_team(row.get("home_team"))
        away = _norm_team(row.get("away_team"))
        if not (home and away):
            return None
        # Checked BEFORE the exact lookup, not only in the alias fallback below.
        # `_load_one` removes a colliding key from `by_teams`, so this is belt
        # and braces -- but the exact path is the one that would return a wrong
        # fixture silently, and it costs a set membership test.
        if (home, away) in self.ambiguous_team_keys:
            return None
        exact = self.by_teams.get((home, away))
        if exact is not None:
            return exact
        raw_home = row.get("home_team")
        raw_away = row.get("away_team")
        hits = []
        for (index_home, index_away), match in self.by_teams.items():
            if (index_home, index_away) in self.ambiguous_team_keys:
                continue
            matchup = match.get("matchup") or {}
            source_home = matchup.get("home_team") or index_home
            source_away = matchup.get("away_team") or index_away
            if teams_match("soccer", raw_home, source_home) and teams_match(
                "soccer", raw_away, source_away
            ):
                hits.append(match)
        return hits[0] if len(hits) == 1 else None


def _same_fixture(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Whether two indexed matches are the same fixture, not merely the same clubs.

    Same league-date loaded twice (two roots, or a re-read) is NOT a collision
    and must not blank a good key. A genuine repeat of the same clubs on two
    dates inside the window IS. `event_id` decides it where both carry one --
    ids are consistent WITHIN the sim feed even though they do not cross to the
    board's feed -- and the fixture date is the fallback when one side has none.
    """
    left_id = str(left.get("event_id") or "").strip()
    right_id = str(right.get("event_id") or "").strip()
    if left_id and right_id:
        return left_id == right_id
    left_date = str(left.get("date") or left.get("kickoff") or "")[:10]
    right_date = str(right.get("date") or right.get("kickoff") or "")[:10]
    if left_date and right_date:
        return left_date == right_date
    # Neither identifiable. Treat as the same rather than poisoning the key:
    # the pre-existing single-date behaviour was a plain overwrite, and an
    # undated payload is the one case this widening did not change.
    return True


def _load_one(path: Path, index: SoccerProjectionIndex) -> bool:
    """Merge one league-date file. Returns whether a payload was actually read.

    The return value is what lets `load_soccer_projections` implement
    first-root-wins: a file that could not be parsed must NOT count as having
    supplied its league, or an unreadable copy on the runtime disk would
    suppress a perfectly good one in the repo mirror.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    league = str(payload.get("league") or "")
    if league:
        index.leagues.append(league)
        generated_at = str(payload.get("generated_at") or "").strip()
        if generated_at:
            index.generated_at_by_league[league] = generated_at
    index.source_paths.append(str(path))

    for match in payload.get("matches") or []:
        if not isinstance(match, Mapping):
            continue
        matchup = match.get("matchup") or {}
        home = _norm_team(matchup.get("home_team"))
        away = _norm_team(matchup.get("away_team"))
        event_id = str(match.get("event_id") or "").strip()
        if event_id:
            index.by_event[event_id] = dict(match)
        if home and away:
            key = (home, away)
            existing = index.by_teams.get(key)
            if existing is not None and not _same_fixture(existing, match):
                # Two DIFFERENT fixtures now answer to one team key. Drop it --
                # see SoccerProjectionIndex.ambiguous_team_keys. Deliberately
                # not "keep the earlier" or "keep the nearer date": the row
                # being joined carries no date this index can compare against,
                # so any tie-break here would be a guess dressed as a rule.
                index.ambiguous_team_keys.add(key)
                index.by_teams.pop(key, None)
            elif key not in index.ambiguous_team_keys:
                index.by_teams[key] = dict(match)
        index.matches += 1

    # Player props are keyed by match_id, so a name collision across two matches
    # on the same slate cannot cross-contaminate.
    for entry in payload.get("player_props") or []:
        if not isinstance(entry, Mapping):
            continue
        match_id = str(entry.get("match_id") or "").strip()
        name = _norm_name(entry.get("player_name"))
        if not name:
            continue
        index.players_by_match.setdefault(match_id, {})[name] = dict(entry)

    # A payload was read. Without this the function falls off the end returning
    # None, no league is ever claimed, and precedence silently degrades to the
    # last-root-wins behaviour this change exists to remove.
    return True


def load_soccer_projections(
    roots: Iterable[Path],
    selected_date: str,
    *,
    window_dates: Iterable[str] | None = None,
) -> SoccerProjectionIndex:
    """Merge each league's recommendations files, taking the FIRST root that has each.

    THE PROJECTION READ IS THE WINDOW, NOT ONE DATE -- and this is the second
    half of `#379`.

    That fix widened Layer 2's QUOTE read from `selected_date` to the sport's
    whole slate window, because soccer shards by KICKOFF date and almost nothing
    kicks off "today". It did not widen the projection read beside it, so the
    board went on asking for `recommendations_<today>.json` alone while holding
    quotes for seven days. Every row outside today was then structurally unable
    to carry a model view, no matter how well the sim ran.

    MEASURED ON PRODUCTION 2026-08-17 19:5xZ, soccer's `per_sport_ingest`:

        window_dates    7   (08-17 .. 08-23)
        dates_with_rows 6   (08-17, 08-19, 08-20, 08-21, 08-22, 08-23)
        grid_rows           8,759
        rows_with_projection    4      (pct_projected 0.0)
        matches_in_source       3
        unmatched_match_rows    8,755

    and downstream: `rows_with_model_edge: 0`, soccer absent from `per_sport`,
    0 rows on the board out of 5,527 opportunities. The A3 filter drops a row
    whose `ev_pct` is a restatement of the book's hold UNLESS it has a
    projection -- so a missing projection is not a cosmetic gap here, it is the
    thing keeping soccer off the board entirely.

    The three matches that DID load were today's, and all three were in play, so
    their pregame projections were correctly withheld (`live_edge_enforced_rows:
    1`). Today was never the problem. The other six dates were.

    `window_dates` is passed in rather than resolved here, so this module keeps
    knowing nothing about slate windows and the caller reuses
    `resolve_window_dates` -- the same resolver Layer 2's quote read uses. Two
    independent notions of "which dates is this sport's board" would drift, and
    the drift is exactly what produced this defect.

    COST, measured before shipping because `#241` is the standing reason to
    check rather than assume: every tracked soccer recommendations file in the
    repo is 22 files totalling **1.5 MB** (2 KB - 40 KB each). A full 10-league
    x 7-date read is ~2.8 MB worst case, against the 8.8 MB soccer quote window
    already being read beside it. The widened read is a fraction of the read it
    accompanies.

    Defaults to `[selected_date]` when no window is given, so every existing
    caller behaves exactly as before.

    ---

    Note the first-root-wins claim key below is now (league, DATE), not league:
    keying on league alone would let the first date read claim the league and
    suppress every other date, quietly turning the widening above into a no-op
    that still reported seven dates.

    `#360`. This used to load every matching file from every root, and `_load_one`
    assigns rather than merges -- `generated_at_by_league[league]`, `by_event[id]`
    and `by_teams[(home, away)]` are all plain writes. So when two roots carried the
    same league-date, the LAST root silently won.

    `preferred_source_roots` orders the runtime disk first and the git repo mirror
    second, and the mirror is a cold-start safety net of unknown vintage. The result
    was that a freshly simulated league was overwritten by a git artifact:

        board built 2026-08-11T22:01:15Z, seven minutes AFTER the sim wrote
          la_liga   projections stamped 2026-07-20T21:32:50   (528.5h stale)
          mls       projections stamped 2026-08-11T21:27:18   (0.6h)

    and the split is the proof. The checkout tracks
    `la_liga/api/recommendations/recommendations_2026-08-15.json` -- exactly the
    simulated date -- so la_liga was overwritten; the checkout's newest mls file is
    from July, so nothing overwrote mls and it rendered fresh. Same code path, same
    board, opposite outcome, decided entirely by which stale files git happens to
    carry.

    First-root-wins matches what `sources._api_read_path` already documents ("the
    first root that actually HAS it"), so the two readers now agree. The mirror
    still serves any league the runtime disk lacks, which is the fallback's whole
    purpose -- it just can no longer overwrite live data.
    """
    index = SoccerProjectionIndex()
    dates = [str(d).strip() for d in (window_dates or [selected_date]) if str(d).strip()]
    if not dates:
        dates = [str(selected_date)]
    index.dates = list(dates)
    seen: set[str] = set()
    # Keyed on (league, DATE), not league. Keying on league alone would let the
    # first date read claim the league and suppress every other date's file --
    # which would turn this widening into a no-op that still reports seven dates.
    loaded_league_dates: set[tuple[str, str]] = set()
    for date_str in dates:
        file_name = f"recommendations_{date_str}.json"
        for root in roots:
            try:
                candidates = sorted(Path(root).glob(f"*/api/recommendations/{file_name}"))
            except OSError:
                continue
            for candidate in candidates:
                # <root>/<league>/api/recommendations/<file>. Taken from the PATH, not
                # the payload, so a league is claimed without reading the loser's file.
                try:
                    league_dir = candidate.parents[2].name
                except IndexError:
                    league_dir = ""
                if league_dir and (league_dir, date_str) in loaded_league_dates:
                    continue
                key = str(candidate.resolve()) if candidate.exists() else str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                # Only a file that actually parsed claims its league -- an unreadable
                # copy on the runtime disk must not suppress a good one in the mirror.
                if _load_one(candidate, index) and league_dir:
                    loaded_league_dates.add((league_dir, date_str))
    return index


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _total_prob_from_scorelines(scorelines: Any, line: float) -> tuple[float, float] | None:
    """(P(over), P(push)) for ANY total line, from the scoreline distribution.

    `total_distribution` can answer 2.5 and nothing else, which cost real
    coverage: measured 2026-08-21, Marseille v Strasbourg was priced by the
    books at 3.0 and 3.5 ONLY, so its card and both boards carried no market
    total at all while the sim had the full distribution in hand the whole time.

    THIS IS A TRANSFORMATION, NOT AN INFERENCE. `scoreline_probabilities` is a
    real distribution over final scores published alongside `total_distribution`
    by `adapters.py`, so summing the arm above the line is exact, not a
    probability reverse-engineered from a mean -- the thing this module's
    docstring refuses to do and still refuses to do. Verified against the real
    2026-08-21 ligue_1 artifact: summing above 2.5 reproduces the published
    `over_2_5_probability` of 0.5775 EXACTLY.

    INTEGER LINES PUSH. At 3.0 a match landing on exactly 3 goals is void, not a
    loss, so P(over) and P(under) do not sum to 1 and the caller must
    renormalise. Returning the push mass rather than swallowing it keeps that
    the caller's decision.
    """
    if not isinstance(scorelines, dict) or not scorelines:
        return None
    over = 0.0
    push = 0.0
    total_mass = 0.0
    max_total = 0
    for key, raw in scorelines.items():
        prob = _as_float(raw)
        if prob is None:
            continue
        parts = str(key).replace(":", "-").split("-")
        if len(parts) != 2:
            continue
        try:
            goals = int(parts[0]) + int(parts[1])
        except (TypeError, ValueError):
            continue
        total_mass += prob
        max_total = max(max_total, goals)
        if goals > line:
            over += prob
        elif abs(goals - line) < 1e-9:
            push += prob
    # A distribution that does not sum to ~1 is not one this can price against.
    if total_mass < 0.99 or total_mass > 1.01:
        return None
    # Beyond the simulated support the answer would be a hard 0.0, which reads
    # as certainty the sim never expressed -- it is the granularity of a finite
    # sim, not knowledge. Refuse and let the caller fall back to the mean.
    if line > max_total:
        return None
    return over, push


def _probability_projection(prob: float, *, basis: str, side: str = "over") -> dict[str, Any]:
    return {
        "model_prob_over": round(prob, 4),
        "side": side,
        "basis": basis,
        "source": "soccer_recommendations",
    }


def _mean_projection(mean: float, line: Any, *, basis: str) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "projected": round(mean, 3),
        "basis": basis,
        "source": "soccer_recommendations",
        "model_prob_over": None,
        "edge_vs_market_pct": None,
        "probability_unavailable_reason": "source carries a mean, not a distribution",
    }
    line_value = _as_float(line)
    if line_value is not None:
        edge = round(mean - line_value, 3)
        projection["edge_vs_line"] = edge
        projection["side"] = "over" if edge > 0 else "under"
    return projection


_LIVE_OR_DONE = {"live", "in_progress", "final", "completed"}


def _price_against_market(row: Mapping[str, Any], projection: dict[str, Any]) -> None:
    """Turn a model probability into an EDGE, or say why it cannot be one.

    #263. This module emitted `model_prob_over` and nothing priced it, so every
    soccer row reached Layer 2 with `model_edge_pct` null -- and with no model
    edge `blended_score` falls back to EV alone, which under proportional devig
    is `1/overround - 1`: IDENTICAL for every side of a market. Measured on the
    live board, all three sides of Famalicao@Estoril carried ev=8.6383, so a
    -750 draw and a +6000 longshot ranked as equally good bets.

    THREE REFUSALS, each deliberate:

    - a mean is not a probability, so mean-based rows never get an edge here;
    - a market with more than two sides that is NOT a known three-way game
      market is not de-vigged, because nothing here knows what its legs span;
    - a pregame projection cannot be priced against a LIVE market. Same rule
      prop_projections applies, for the same measured reason (a +23-point "edge"
      on a coin-flip game once the score, not the model, moved the line).

    THE BLANKET THREE-WAY REFUSAL THAT USED TO STAND HERE WAS STALE ON THE DAY
    IT WAS WRITTEN, and it was suppressing every h2h edge soccer has.

    It read "`_no_vig_over_probability` pairs home against away and would
    silently drop the draw". That was true of an older version of that function.
    `95305cab` (2026-08-07 13:13 CDT) taught it the draw leg explicitly -- it
    now finds `draw`/`tie`/`x`, adds it to the denominator, and returns None if
    a three-way market is missing its draw price rather than de-vigging across
    two of three legs. `#263`'s refusal was written at 23:43 the SAME DAY,
    describing behaviour the function had already stopped having ten hours
    earlier. `git merge-base --is-ancestor` confirms the ordering.

    Verified against production rather than read off the source, 2026-08-15, by
    calling the real `_no_vig_over_probability` on the live board's four h2h
    rows. Telstar vs Sparta Rotterdam, consensus home 133 / draw 255 / away 183:
    implied 0.4292 / 0.2817 / 0.3534 summing to 1.0643 (a 6.4% hold, matching
    soccer's ~6.5% modelled hold), fair home = 0.4292/1.0643 = **0.4033**. A
    correct three-leg de-vig. Three of the four rows produced a real edge
    (+11.17, +0.03, -27.98 points); the fourth had no model probability for an
    unrelated reason (a primeira_liga name-join miss).

    BOTH SIDES OF THE COMPARISON LIVE IN THE SAME SPACE, which is what makes it
    valid: the h2h branch above emits `win_probability.home`, an UNCONDITIONAL
    P(home) over the three-way outcome space, and the fair above is
    home/(home+draw+away) over that same space. Neither is renormalised into a
    decided-only space, so they are directly comparable. If a future branch ever
    emits a conditional P(home | decided) it must NOT reach this comparison
    without renormalising -- that is the mistake `prop_projections` documents at
    its `win_prob_decided` basis.

    Scoped to a known list rather than "anything with three sides": a market
    with many legs (a scorer market quoting a price per player, say) is still
    refused, because de-vigging it would need to span every leg and nothing here
    can confirm the quoted set is complete.
    """
    model_prob = projection.get("model_prob_over")
    if model_prob is None:
        return

    market = str(row.get("market") or "").strip().lower()
    sides = [str(side).strip().lower() for side in (row.get("sides") or [])]
    if len(sides) > 2 and market not in _THREE_WAY_GAME_MARKETS:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = (
            f"{len(sides)}-side market '{market}': no de-vig spans an unknown leg set"
        )
        return

    # THE FAIR VALUE IS COMPUTED BEFORE THE LIVE REFUSAL, AND THE ORDER IS THE
    # WHOLE FIX (`#530`).
    #
    # It used to sit below the `live_reason` early-return, so on a LIVE game
    # `market_fair_prob_over` was never written at all. That is a different
    # claim from the one the refusal is making. The refusal says a PREGAME MODEL
    # must not be priced against a re-priced market -- true, and it suppresses
    # the edge. The fair value is not the model: it is a de-vig of the quote
    # sitting in front of us right now, a property of the MARKET. Withholding it
    # threw away the one input that was still valid.
    #
    # What that cost, measured 2026-08-23 16:41-16:49Z, three consecutive builds:
    #
    #     LIVE_PROJECTION_JOIN sport=soccer considered=1585 projected=188 edged=0
    #                          edge_why={'no_fair_value_devig_failed': 188}
    #
    # 188 of 188. `live_projection_join` had a genuine LIVE probability from the
    # re-sim -- exactly the signal `live_edge_policy`'s own docstring says is
    # "precisely the thing worth ranking" -- and nothing to price it against,
    # because this function had returned before stamping it.
    #
    # 100% ON ONE NAMED REASON IS A BUG, NOT A DISTRIBUTION. The reason string
    # said "the market is one-sided, so de-vig has no answer", which is a real
    # thing that happens to SOME soccer props; it cannot happen to all 188, and
    # reading the rate rather than the reason is what turned a nine-hour
    # "pricing decision" into a misplaced `return`.
    #
    # `prop_projections.py:951` has always done it in this order, which is why
    # MLB's live tier works (`live_proj=252` on the same board) and soccer's did
    # not. Two implementations of one rule, and only one of them was right.
    #
    # Deliberately AFTER the unknown-leg-set refusal above: that one returns
    # without a fair value on purpose, because nothing here can confirm the
    # quoted set is complete.
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    fair = _no_vig_over_probability(row)
    projection["market_fair_prob_over"] = fair
    # WHY THE DE-VIG CAME BACK EMPTY, STAMPED HERE SO IT SURVIVES THE LIVE
    # EARLY-RETURN BELOW (`#536`).
    #
    # `#530` fixed the ORDER and `edged` stayed 0, with
    # `edge_why={'no_fair_value_devig_failed': 45}`. That name is once again one
    # label over two states, and the ambiguity has now cost this lane twice in a
    # day:
    #
    #   the row was quoted ONE-SIDED, so no de-vig is possible and nothing
    #     downstream can fix it -- a producer/coverage question;
    #   the row HAS both sides and `_no_vig_over_probability` still returned
    #     None -- an unparseable or missing consensus price, which is ours.
    #
    # The pregame branch below already distinguishes these; the live path returns
    # before reaching it, so the live reader saw one flat name. Stamping it on
    # the projection is what carries the distinction across the return.
    if fair is None:
        _consensus = row.get("consensus") if isinstance(row.get("consensus"), Mapping) else {}
        _sides = [str(side).strip().lower() for side in (row.get("sides") or [])]
        _priced = [side for side in _sides if _consensus.get(side) is not None]
        projection["market_fair_unavailable_reason"] = (
            "one_sided_quote" if len(_priced) < 2 else "consensus_present_devig_returned_none"
        )
    else:
        projection.pop("market_fair_unavailable_reason", None)

    # `#340`: shared with MLB and WNBA via `live_edge_policy` rather than kept
    # per-sport. This file and `prop_projections` had matching copies; WNBA had
    # none and shipped 128 live edges on 2026-08-10 as a result.
    live_reason = live_edge_unavailable_reason(row)
    if live_reason:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = live_reason
        # BOTH edge contracts, not just the probability one. `_mean_projection`
        # sets `edge_vs_line` unconditionally, so suppressing only
        # `edge_vs_market_pct` here left every mean-based soccer row carrying a
        # live edge -- the identical defect WNBA had, in the same file that
        # already knew the rule. Checked rather than assumed: this runs for
        # every row, mean-based and probability-based alike.
        if projection.get("edge_vs_line") is not None:
            projection["edge_vs_line"] = None
        return

    if fair is None:
        projection["edge_vs_market_pct"] = None
        # Say WHICH leg is missing. Now that three-way markets reach this
        # point, "one-sided market" would be an actively wrong description of
        # an h2h row whose draw price simply failed to arrive -- and a wrong
        # reason is worse than a blank one, because it sends the next reader to
        # the wrong subsystem.
        reason = (
            "3-way market: incomplete price set, no fair to price against"
            if market in _THREE_WAY_GAME_MARKETS
            else "one-sided market: no two-sided fair to price against"
        )
        # USER DECISION 2026-08-17, audit recommendation 4. 1,131 soccer rows
        # land here carrying a `model_prob_over` AND a modelled fair, and served
        # no edge of any kind. They may now be priced against the MODELLED fair,
        # in its own column.
        #
        # `edge_vs_market_pct` stays None above and is never written here: this
        # is a separate, weaker claim (one book's measured hold, not a two-sided
        # de-vig), and `book_margin_model` forbids the two being mixed.
        #
        # DELIBERATELY NOT wired into the `live_reason` branch above. That
        # refusal is about the row being LIVE, and it holds whichever fair is
        # used -- a modelled fair does not make a live pregame projection
        # priceable. Adding it there would reintroduce exactly the live-edge
        # leak `#340` fixed across three sports.
        modelled_edge = modelled_fair_edge(
            row, model_prob=model_prob, side=projection.get("side")
        )
        if modelled_edge:
            projection.update(modelled_edge)
            reason = (
                f"{reason}; priced against the modelled fair instead "
                f"(see {MODELLED_EDGE_FIELD})"
            )
        projection["edge_unavailable_reason"] = reason
        return
    projection["edge_vs_market_pct"] = round((float(model_prob) - float(fair)) * 100.0, 2)


def _age_hours(generated_at: str) -> float | None:
    """Hours since a simulation was produced, or None if unparseable.

    None rather than 0 on a parse failure: an unknown age must not read as a
    fresh one, which is the same rule this whole field exists to enforce.
    """
    from datetime import datetime, timezone

    raw = str(generated_at or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0, 1)


def _scorer_race_for(index: "SoccerProjectionIndex", match_id: str, match: Mapping[str, Any]) -> dict[str, Any]:
    """Per-match scorer race, computed once. Cached because a single match can
    carry 40+ first-scorer rows and the race is O(players) each time."""
    cache = getattr(index, "_scorer_race_cache", None)
    if cache is None:
        cache = {}
        setattr(index, "_scorer_race_cache", cache)
    if match_id in cache:
        return cache[match_id]
    from syndicate.features.shared.soccer_scorer_markets import scorer_race

    players = (index.players_by_match.get(match_id) or {}).values()
    mean = (match.get("total_distribution") or {}).get("mean")
    result = scorer_race(players, match_expected_goals=mean)
    #  keys by the RAW player name; every lookup in this module goes
    # through . Normalising here rather than inside the race keeps the
    # race sport-agnostic -- and an un-normalised key silently matched NOTHING,
    # which reads exactly like "no projection available".
    result = {
        **result,
        "by_player": {_norm_name(k): v for k, v in (result.get("by_player") or {}).items()},
    }
    cache[match_id] = result
    return result


# How many SIM-side fixtures to show per league that has unmatched rows. Enough
# to spot the club under a different spelling (a league's slate is ~10 fixtures
# and a missed one is usually adjacent to its match in sorted order), small
# enough that ten leagues cannot push the log line past what a collector will
# keep on one row.
_SIM_FIXTURES_PER_LEAGUE = 12

# Player samples are capped harder than fixture ones: a soccer slate has ~10
# fixtures and ~500 players, so an uncapped list would not fit on a log line the
# collector keeps intact.
_PLAYER_SAMPLE_CAP = 10
_ROSTER_SAMPLE_PER_MATCH = 8


def attach_soccer_projections(
    grid: Iterable[Mapping[str, Any]], index: SoccerProjectionIndex
) -> dict[str, Any]:
    considered = 0
    projected = 0
    with_probability = 0
    unmatched_match = 0
    unmatched_player = 0
    unsupported_market = 0
    # ATTRIBUTION FOR `unmatched_match_rows`, which until now was a bare total.
    #
    # It has read ~99.6% of the grid for days (`state.md`: 1,138 of 1,142) and
    # that one number cannot distinguish the three things it can mean, which
    # have three unrelated fixes:
    #
    #   the league is not in the index at all  -> the SIM did not run it, or its
    #                                             file is outside the window
    #   the league IS indexed, rows still miss -> the NAME join failed
    #   the league is indexed and matches      -> nothing to fix here
    #
    # Per-league counts separate the first two by themselves; the paired name
    # samples (board side and index side, same league) settle the third. Same
    # contract `#296` set and `LIVE_PROJECTION_JOIN` already follows for the
    # live tier: a zero must be attributable, never bare.
    rows_by_league: dict[str, int] = {}
    unmatched_by_league: dict[str, int] = {}
    unmatched_fixtures: dict[str, str] = {}
    # SAME SPLIT AS `unmatched_by_league`, one level down. `unmatched_player` is
    # now the LARGEST bucket (6,057 rows, measured 18:31:07Z, and it grew when
    # the team-name join was fixed because more rows reach this stage) and it
    # covers two states with different owners:
    #
    #   the sim published NO players for this match  -> producer gap
    #   it published players and this name is absent -> a name join problem,
    #                                                   the player-level twin of
    #                                                   what 13 aliases just fixed
    #
    # Paired samples for the same reason as the fixture ones: an alias cannot be
    # written from the board's spelling alone.
    player_miss_no_roster = 0
    player_miss_name = 0
    # `#263` follow-up. TWO counters that did not exist, and the second is the
    # larger finding by an order of magnitude.
    #
    # `player_alias_*` measure the token-subset fallback below.
    # `unprojected_by_market` attributes the SILENT DROP at the end of this
    # loop: measured 2026-09-03, `considered=140924 projected=25145` while the
    # three named miss buckets summed to only 9,329 -- so **106,450 rows
    # (75.5%) fell through `if projection is None: continue` with NO counter at
    # all**, which is 92% of everything unprojected. The player-name join this
    # was opened to fix is 6.1% of it. A bucket that large has to be
    # attributable before anyone chooses what to fix next.
    player_alias_hits = 0
    player_alias_ambiguous = 0
    unprojected_no_field = 0
    unprojected_by_market: dict[str, int] = {}
    unmatched_players: dict[str, str] = {}
    roster_sample_by_match: dict[str, list[str]] = {}

    def _lookup_player(pool: Mapping[str, Any], board_name: Any) -> tuple[Any, str]:
        """`(value, state)` for a board player name against a per-match pool.

        EXACT NORMALISED MATCH FIRST; the fallback is a UNIQUE TOKEN-SUBSET
        match and nothing looser. `_norm_name` already folds accents (fixed for
        MLB 2026-08-16), so the residue here is not diacritics -- it is the
        short-vs-full-name convention this sport is full of: the sim publishes
        `Alisson` where the board says `Alisson Ramses Becker`, and the board
        says `Emersonn Correia da Silva` where the sim says `Emersonn`.

        THREE THINGS KEEP THIS FROM INVENTING A MATCH, and each is a real risk
        rather than a hypothetical:

        1. The pool is ONE MATCH'S roster, not a league or a season. Two
           players sharing a surname across different fixtures can never meet.
        2. AMBIGUITY REFUSES. More than one candidate returns `ambiguous` and
           is COUNTED, never resolved by picking the first -- a silently wrong
           player is worse than an unmatched row, because the row still prices
           and nothing downstream can tell.
        3. A ONE-TOKEN subset must be at least four characters, so `da`, `de`
           and initials cannot swallow a roster.
        """
        key = _norm_name(board_name)
        if not key or not pool:
            return None, "empty"
        hit = pool.get(key)
        if hit is not None:
            return hit, "exact"
        tokens = set(key.split())
        if not tokens:
            return None, "empty"
        candidates: list[Any] = []
        for pool_key, pool_value in pool.items():
            pool_tokens = set(str(pool_key or "").split())
            if not pool_tokens:
                continue
            shorter, longer = (
                (pool_tokens, tokens) if len(pool_tokens) <= len(tokens) else (tokens, pool_tokens)
            )
            if not shorter <= longer:
                continue
            if len(shorter) == 1 and len(next(iter(shorter))) < 4:
                continue
            candidates.append(pool_value)
        if len(candidates) == 1:
            return candidates[0], "alias"
        if len(candidates) > 1:
            return None, "ambiguous"
        return None, "miss"

    def _note_player_miss(match: Mapping[str, Any], row: Mapping[str, Any], roster: Mapping[str, Any]) -> None:
        nonlocal player_miss_no_roster, player_miss_name
        league = str(match.get("league") or "").strip() or "?"
        board_name = str(row.get("player_name") or "").strip() or "?"
        if not roster:
            player_miss_no_roster += 1
            return
        player_miss_name += 1
        # Keyed by (league, player) so one player's twelve prop rows contribute
        # one sample, not twelve -- the fixture samples learned this already.
        key = f"{league}|{board_name}"
        if key not in unmatched_players and len(unmatched_players) < _PLAYER_SAMPLE_CAP:
            unmatched_players[key] = board_name
            match_id = str(match.get("match_id") or "").strip()
            if match_id and match_id not in roster_sample_by_match:
                roster_sample_by_match[match_id] = sorted(
                    str((entry or {}).get("player_name") or name)
                    for name, entry in list(roster.items())
                )[:_ROSTER_SAMPLE_PER_MATCH]

    for row in grid:
        market = str(row.get("market") or "").strip().lower()
        considered += 1
        row_league = str(row.get("league") or "").strip() or "?"
        rows_by_league[row_league] = rows_by_league.get(row_league, 0) + 1
        match = index.match_for(row)
        if match is None:
            unmatched_match += 1
            unmatched_by_league[row_league] = unmatched_by_league.get(row_league, 0) + 1
            # Keyed by fixture so a 900-row league contributes ONE sample --
            # every row of a missed fixture misses identically, and a sample
            # list of the same pair nine hundred times names nothing.
            fixture = f"{row.get('home_team')} v {row.get('away_team')}"
            unmatched_fixtures.setdefault(f"{row_league}|{fixture}", fixture)
            continue

        projection: dict[str, Any] | None = None

        if market in {"h2h", "h2h_3_way"}:
            win = match.get("win_probability") or {}
            prob = _as_float(win.get("home"))
            if prob is not None:
                # Expressed from the HOME side, matching how the board's other
                # sports state a game-line projection.
                projection = _probability_projection(prob, basis="win_probability", side="home")
                projection["draw_probability"] = _as_float(win.get("draw"))
                projection["away_probability"] = _as_float(win.get("away"))
        elif market in {"totals", "totals_alt"}:
            totals = match.get("total_distribution") or {}
            line_value = _as_float(row.get("line"))
            over_25 = _as_float(totals.get("over_2_5_probability"))
            derived = (
                _total_prob_from_scorelines(match.get("scoreline_probabilities"), line_value)
                if line_value is not None
                else None
            )
            if line_value is not None and over_25 is not None and abs(line_value - _TOTALS_EXACT_PROB_LINE) < 1e-9:
                # The ONE line the SUMMARY can answer directly. Kept ahead of the
                # derivation so 2.5 kicks out the byte-identical number it always
                # has -- a fix that silently restates every existing row is a
                # fix whose blast radius nobody can bound.
                projection = _probability_projection(over_25, basis="over_2_5_probability")
            elif derived is not None:
                p_over, p_push = derived
                live_mass = 1.0 - p_push
                # An all-push line prices nothing. Refuse rather than divide by
                # ~0 and publish a probability built from rounding error.
                if live_mass > 1e-6:
                    projection = _probability_projection(
                        p_over / live_mass, basis="scoreline_distribution"
                    )
                    if p_push > 0:
                        # Named, because a 0.62 that excludes a 12% push is a
                        # different claim from a 0.62 that has no push at all.
                        projection["push_probability"] = round(p_push, 4)
                else:
                    projection = _mean_projection(
                        _as_float(totals.get("mean")) or 0.0, row.get("line"), basis="total_mean"
                    )
            else:
                mean = _as_float(totals.get("mean")) or _as_float(
                    (match.get("team_projection") or {}).get("total_mean")
                )
                if mean is not None:
                    projection = _mean_projection(mean, row.get("line"), basis="total_mean")
        elif market in _CORNERS_MARKETS:
            # CORNERS, PRICED FROM THE CORNERS MEAN -- never from the goals model.
            #
            # `market_keys.py` records the near-miss this pairing exists to avoid:
            # Kalshi words a corners market "Over 4.5 corners?", soccer boards
            # carry a GOALS total at 4.5, and a grammar that threw the unit away
            # "would have priced a corners market [with] our goals model and the
            # join would have looked clean". `_TOTAL_UNIT["soccer"]` keeps that
            # separation upstream; this branch keeps it here by reading
            # `volume_projection`, the block the sim fills with corners, and
            # nothing else.
            #
            # WHY IT WAS UNMODELLED AND WHY THAT WAS A DEFECT. Measured on the
            # served board 2026-09-04: `alternate_totals_corners` was **186 rows,
            # 0 with a model, 0 with an edge** -- the single largest unmodelled
            # market in soccer's candidate pool -- while `soccer/cards.py` has
            # rendered `Proj {total:.1f} | Line {market:g}` for corners all along.
            # The sim had the number and the board was the surface that could not
            # see it.
            #
            # A MEAN, AND ONLY A MEAN. `distribution.py` accumulates
            # `mean_home_corners` / `mean_away_corners` across simulations and
            # divides; there is no corners DISTRIBUTION, no SD, no per-line
            # over-probability -- unlike goals, which has `scoreline_probabilities`
            # and `over_2_5_probability`. So this publishes `edge_vs_line` in
            # CORNER UNITS and nothing else, exactly the contract WNBA uses and
            # `_PLAYER_PROB_BY_LINE`'s comment states: "a mean presented as a
            # probability is a fabricated edge".
            #
            # **THESE ROWS THEREFORE REMAIN UNBUYABLE, AND THAT IS THE POINT.**
            # `_model_edge_for` refuses to add a stat-unit edge to an EV
            # percentage, so they will read `sim_view: unpriced` rather than
            # `none` -- the sim has a view, it cannot be priced against this
            # market, and the board now says which. Making them buyable needs a
            # corners distribution the engine does not produce; inventing a
            # variance here would be the fabricated edge the file forbids.
            volume = match.get("volume_projection") or {}
            home_c = _as_float(volume.get("home_corners"))
            away_c = _as_float(volume.get("away_corners"))
            if home_c is not None and away_c is not None:
                projection = _mean_projection(
                    home_c + away_c, row.get("line"), basis="corners_mean"
                )
        elif market in {"spreads", "spreads_alt"}:
            margin = _as_float((match.get("spread_distribution") or {}).get("home"))
            if margin is None:
                margin = _as_float((match.get("team_projection") or {}).get("margin_mean"))
            if margin is not None:
                projection = _mean_projection(margin, row.get("line"), basis="margin_mean")
        elif market in _DERIVED_SCORER_MARKETS:
            match_id = str(match.get("match_id") or "").strip()
            race = _scorer_race_for(index, match_id, match)
            prob, race_state = _lookup_player(
                (race.get("by_player") or {}) if race else {}, row.get("player_name")
            )
            if race_state == "alias":
                player_alias_hits += 1
            elif race_state == "ambiguous":
                player_alias_ambiguous += 1
            if prob is None:
                unmatched_player += 1
                # The scorer race is DERIVED from the same per-match player
                # entries, so its absence is the same two states.
                _note_player_miss(
                    match, row, index.players_by_match.get(match_id) or {}
                )
                continue
            projection = _probability_projection(
                float(prob),
                basis="poisson_scorer_race",
                side=str(row.get("player_name") or "").strip() or "yes",
            )
            # Both halves of the honesty: how much of the match's goal rate the
            # listed players actually cover, and the time-reversal assumption the
            # LAST-scorer number rests on.
            projection["attributable_share"] = race.get("attributable_share")
            if not race.get("usable"):
                projection["low_coverage"] = True
            if market == "player_last_goal_scorer":
                projection["assumption"] = "last scorer equals first scorer under time-reversal symmetry"
        elif market in _PLAYER_FIELDS or market in _PLAYER_PROB_BY_LINE:
            players = index.players_by_match.get(str(match.get("match_id") or "").strip()) or {}
            entry, player_state = _lookup_player(players, row.get("player_name"))
            if player_state == "alias":
                player_alias_hits += 1
            elif player_state == "ambiguous":
                player_alias_ambiguous += 1
            if entry is None:
                unmatched_player += 1
                _note_player_miss(match, row, players)
                continue
            # PER-LINE PROBABILITY FIRST, mean only as a fallback. Falls
            # through to the shared tail below rather than pricing here, so
            # `_price_against_market`, the `#350` age stamp and the coverage
            # counters cannot drift between the two paths -- a second copy of
            # that tail is exactly how this file's rules have rotted before.
            prob_field = _PLAYER_PROB_BY_LINE.get(market)
            exact = _prob_at_line(entry, prob_field, row.get("line")) if prob_field else None
            if exact is not None:
                projection = _probability_projection(exact, basis=prob_field)
            elif market not in _PLAYER_FIELDS:
                # An assists row whose exact line the sim did not price. Named
                # rather than counted as a player miss: the player matched, the
                # LINE did not.
                unsupported_market += 1
                continue
            else:
                field_name, kind = _PLAYER_FIELDS[market]
                value = _as_float(entry.get(field_name))
                if value is not None:
                    projection = (
                        _probability_projection(value, basis=field_name)
                        if kind == "probability"
                        else _mean_projection(value, row.get("line"), basis=field_name)
                    )
        else:
            unsupported_market += 1
            continue

        if projection is None:
            # THE BUCKET THAT WAS INVISIBLE. The row matched its fixture, its
            # market is supported and its player was found -- the sim simply
            # published no value for the field this market needs. Counted BY
            # MARKET because that is the only cut that says what to fix.
            unprojected_no_field += 1
            unprojected_by_market[market] = unprojected_by_market.get(market, 0) + 1
            continue
        # #263: a model probability that is never priced against the market
        # cannot rank anything.
        _price_against_market(row, projection)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        # `#350`: STAMP THE SIM'S AGE ONTO THE ROW.
        #
        # A projection is a claim about a fixture made at a moment, and the
        # board rendered a 22-day-old one exactly like a fresh one -- measured
        # 2026-08-11, la_liga's 2026-08-15 file carried
        # `generated_at: 2026-07-20`. Prices already show `age_seconds`; the
        # model behind them showed nothing, so "the sim likes this" could mean
        # "as of three weeks ago" with no way to tell.
        #
        # Taken from the LEAGUE that produced this match, not a global value:
        # leagues simulate on their own units, so one stale league must not make
        # the others look stale, or the reverse.
        source_league = str(match.get("league") or "").strip()
        generated_at = index.generated_at_by_league.get(source_league)
        if generated_at:
            projection["generated_at"] = generated_at
            age = _age_hours(generated_at)
            if age is not None:
                projection["age_hours"] = age
        projected += 1
        if projection.get("model_prob_over") is not None:
            with_probability += 1

    # THE INDEX SIDE OF THE SAME PAIRING. Without it the unmatched samples say
    # what the BOARD calls a fixture and nothing about what the SIM calls it,
    # which is exactly half of a name-join question.
    #
    # SCOPED TO THE LEAGUES THAT ACTUALLY MISS, and that is a CORRECTION rather
    # than a refinement. The first cut sorted every indexed fixture
    # alphabetically and took the first 12 -- so the production reading at
    # 17:30:32Z returned belgian_pro_league, bundesliga and championship, while
    # every league with real misses (epl 510, la_liga 972, serie_a 606,
    # ligue_1 240, mls 247) fell off the end. The board side named 12 fixtures
    # and the sim side answered about none of them. An instrument that reliably
    # samples the leagues with nothing to report is worse than no sample: it
    # looks like an answer.
    #
    # Per-league quota rather than one global cap, for the same reason -- one
    # busy league would otherwise crowd out the rest.
    # NOTHING UNMATCHED MEANS NO SAMPLE. The first guard here read
    # `if missing_leagues and league not in missing_leagues`, which on a clean
    # join short-circuits to false and dumps EVERY indexed fixture onto the log
    # line -- the largest output in the case with nothing to investigate.
    missing_leagues = set(unmatched_by_league)
    by_league_fixtures: dict[str, list[str]] = {}
    for (index_home, index_away), match in index.by_teams.items():
        league = str(match.get("league") or "").strip() or "?"
        if league not in missing_leagues:
            continue
        matchup = match.get("matchup") or {}
        by_league_fixtures.setdefault(league, []).append(
            f"{league}|{matchup.get('home_team') or index_home} v "
            f"{matchup.get('away_team') or index_away}"
        )
    indexed_fixtures: list[str] = []
    for league in sorted(by_league_fixtures):
        indexed_fixtures.extend(sorted(by_league_fixtures[league])[:_SIM_FIXTURES_PER_LEAGUE])

    return {
        "supported": True,
        "leagues": sorted(set(index.leagues)),
        "matches_in_source": index.matches,
        # Which dates were actually read, so "the sim never ran that day" is
        # distinguishable from "it ran and the names missed".
        "dates_read": list(index.dates),
        "leagues_indexed": sorted({str(m.get("league") or "").strip() for m in index.by_teams.values() if m.get("league")}),
        "rows_by_league": dict(sorted(rows_by_league.items())),
        "unmatched_by_league": dict(sorted(unmatched_by_league.items())),
        "unmatched_fixtures_count": len(unmatched_fixtures),
        # The player-level split, same contract as the league one above.
        "player_miss_no_roster": player_miss_no_roster,
        "player_miss_name": player_miss_name,
        "player_alias_hits": player_alias_hits,
        "player_alias_ambiguous": player_alias_ambiguous,
        "unprojected_no_field": unprojected_no_field,
        # Top markets only: the whole dict on one log line is unreadable, and
        # the tail is never the thing anyone acts on.
        "unprojected_by_market": dict(
            sorted(unprojected_by_market.items(), key=lambda kv: -kv[1])[:12]
        ),
        "unmatched_player_sample": sorted(unmatched_players),
        "sim_roster_sample": sorted(
            name for names in roster_sample_by_match.values() for name in names
        )[: _PLAYER_SAMPLE_CAP * 2],
        "matches_with_players": len(index.players_by_match),
        "unmatched_fixture_sample": sorted(unmatched_fixtures)[:12],
        "indexed_fixture_sample": indexed_fixtures,
        # `match_for` returns None for these BY DESIGN (a wrong projection is
        # worse than a blank one), so they are unmatched rows with a cause that
        # is not a name failure and must not be read as one.
        "ambiguous_team_keys": len(index.ambiguous_team_keys),
        "rows_considered": considered,
        "rows_with_projection": projected,
        "rows_with_true_probability": with_probability,
        "unmatched_match_rows": unmatched_match,
        "unmatched_player_rows": unmatched_player,
        "unsupported_market_rows": unsupported_market,
        "pct_projected": round(100.0 * projected / considered, 1) if considered else 0.0,
        "note": "probability only where the source has one; totals price any line from the scoreline distribution (2.5 still from the published summary)",
        "source_artifacts": index.source_paths,
        # The coverage report is what an operator reads first, so the staleness
        # belongs here too -- not only on individual rows.
        "generated_at_by_league": dict(index.generated_at_by_league),
        "oldest_sim_age_hours": max(
            (a for a in (_age_hours(v) for v in index.generated_at_by_league.values()) if a is not None),
            default=None,
        ),
    }
