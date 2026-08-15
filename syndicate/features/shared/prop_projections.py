"""S3 / L1-B: the sim's prop projections, joined to market lines.

This is the differentiator. OddsJam shows what the books think; this shows what
the model thinks next to it, per line. The reference surface is
player-props.com's `Line | Over | Under | Projected | Edge Proj | Edge Eff%`.

READS THE DAILY SUMMARY ARTIFACT DIRECTLY, and that is the whole point.
`build_mlb_market_board` would also produce projections, but it calls
`build_cards_page_context` -- the call whose own docstring records that it
OOM-killed the 2GB refresh-worker, and the call `#253` had to bound. This reads
one ~2.3MB JSON the sim already wrote. S3 stays a serve-time join, like S1.

WHAT THE SIM ACTUALLY GIVES US, which is better than a point estimate
---------------------------------------------------------------------
Pitchers carry full DISTRIBUTIONS (`so_dist`, `outs_dist`, ...), so P(over any
line) is exact rather than assumed-normal. Hitters carry cumulative
threshold probabilities (`hits_1plus`, `total_bases_2plus`, ...), which map
onto half-point lines exactly: a 0.5 line *is* "1 or more".

So `model_prob` is a real modelled probability, not a projection run through a
distributional guess. That distinction is why `edge_pct` here can be compared
against a no-vig market probability honestly.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason

# market (as it appears in book_quotes) -> the pitcher distribution that scores it
_PITCHER_DISTS: dict[str, tuple[str, str]] = {
    "strikeouts": ("so_dist", "so_mean"),
    "outs": ("outs_dist", "outs_mean"),
    "hits_allowed": ("hits_dist", "hits_mean"),
    "earned_runs": ("earned_runs_dist", "er_mean"),
    "walks_allowed": ("walks_dist", "walks_mean"),
    "batters_faced": ("batters_faced_dist", "batters_faced_mean"),
    "pitches": ("pitches_dist", "pitches_mean"),
}

# market -> (likelihood bucket prefix, mean field). The bucket for a line is
# derived: line 0.5 -> "<prefix>_1plus", 1.5 -> "_2plus", and so on.
_HITTER_BUCKETS: dict[str, tuple[str, str]] = {
    "batter_hits": ("hits", "h_mean"),
    "batter_total_bases": ("total_bases", "tb_mean"),
    "batter_rbis": ("rbi", "rbi_mean"),
    "batter_runs_scored": ("runs", "runs_mean"),
    "batter_hits_runs_rbis": ("hits_runs_rbis", "hrr_mean"),
    "batter_doubles": ("doubles", "doubles_mean"),
    "batter_triples": ("triples", "triples_mean"),
    "batter_stolen_bases": ("sb", "sb_mean"),
}

_HR_MARKET = "batter_home_runs"
_HRR_MARKET = "batter_hits_runs_rbis"

# `#429`. HRR is not an independently simulated stat -- it is Hits + Runs +
# RBIs, a SUMMATION of three primitives the sim already models separately.
# These are the component mean fields, in the spelling the daily summary uses.
_HRR_COMPONENT_MEANS: tuple[str, ...] = ("h_mean", "r_mean", "rbi_mean")


def _norm_name(value: Any) -> str:
    """Normalised player name for joining sim output to quote rows.

    Accents and punctuation differ between feeds -- the same fold `#218`'s team
    matching needed. Kept deliberately simple: lowercase, strip non-letters, and
    collapse whitespace.
    """
    text = str(value or "").strip().lower()
    text = text.replace(".", " ").replace("'", "").replace("-", " ")
    text = re.sub(r"[^a-z ]", " ", text)
    return " ".join(text.split())


def _attach_measured_skill(payload: dict[str, Any], market_key: str) -> None:
    """`#428`. Carry the backtest's verdict on the row that shows the number.

    THE PRODUCER ATTACHES ITS OWN SKILL, which is the contract
    `projection_skill` is built around: it fills only where `model_skill` is
    ABSENT, so a measured market takes this note and an unmeasured one is
    stamped `unmeasured` rather than inheriting a neighbour's number.

    Deliberately silent for a market with no measurement --
    `mlb_prop_calibration.skill_note` returns None, and None is the honest
    answer. `batter_hits_runs_rbis` is exactly that case today: it was the
    degenerate `0.0` throughout the backtest window (`#429`), so it has no
    number and must not borrow one.

    Never raises. A missing calibration module must not take down the join it
    annotates.
    """
    try:
        from syndicate.features.shared.mlb_prop_calibration import skill_note

        note = skill_note(market_key)
    except Exception:
        return
    if note:
        payload["model_skill"] = note


def _dist_mean(dist: Mapping[str, Any]) -> float | None:
    total = 0.0
    weighted = 0.0
    for raw_value, raw_count in (dist or {}).items():
        try:
            value = float(raw_value)
            count = float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total += count
        weighted += value * count
    return round(weighted / total, 3) if total > 0 else None


def _dist_prob_over(dist: Mapping[str, Any], line: float) -> float | None:
    """P(outcome > line) straight off the simulated distribution.

    Exact, not a normal approximation. A whole-number line is a push on the
    line itself, so strictly-greater is the right comparison and the push mass
    is deliberately excluded from BOTH sides rather than split.
    """
    total = 0.0
    over = 0.0
    for raw_value, raw_count in (dist or {}).items():
        try:
            value = float(raw_value)
            count = float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total += count
        if value > line:
            over += count
    return round(over / total, 4) if total > 0 else None


def _bucket_for_line(prefix: str, line: float) -> str | None:
    """`total_bases` + line 1.5 -> `total_bases_2plus`.

    Only half-point lines map cleanly: "over 1.5" is exactly "2 or more". A
    whole-number line carries push mass that a `Nplus` bucket cannot express, so
    it returns None rather than silently answering the wrong question.
    """
    if abs(line - round(line)) < 0.01:
        return None
    threshold = int(math.floor(line)) + 1
    if threshold < 1:
        return None
    return f"{prefix}_{threshold}plus"


# Quote `segment` -> the sim payload that covers it. The sim simulates the same
# game four ways and the board quotes all four, so a projection joined to the
# wrong segment would be confidently wrong rather than absent.
_SEGMENT_PAYLOADS: dict[str, str] = {
    "full_game": "full",
    "full": "full",
    "": "full",
    "1st_5_innings": "first5",
    "first5": "first5",
    "1st_3_innings": "first3",
    "first3": "first3",
    "1st_1_innings": "first1",
    "1st_inning": "first1",
    "first1": "first1",
}


class PropProjectionIndex:
    """Lookup from (player, market, line) to what the sim projected.

    Also carries GAME-level projections (h2h / spreads / totals), which come
    from a different part of the same artifact and join on the team pair rather
    than a player name.
    """

    def __init__(self) -> None:
        self._pitchers: dict[str, dict[str, Any]] = {}
        self._hitters: dict[tuple[str, str], dict[str, Any]] = {}
        self._hitter_means: dict[str, dict[str, float]] = {}
        # (away_tri, home_tri) -> {segment_payload_name: payload}
        self._games: dict[tuple[str, str], dict[str, Any]] = {}
        self.games = 0

    # -- build ----------------------------------------------------------
    def ingest_game(self, game: Mapping[str, Any], *, pitcher_names: Mapping[str, str] | None = None) -> None:
        self.games += 1

        # Game-level payloads, one per simulated segment.
        away = str(game.get("away") or "").strip().upper()
        home = str(game.get("home") or "").strip().upper()
        if away and home:
            segments = {
                name: game.get(name)
                for name in ("full", "first5", "first3", "first1")
                if isinstance(game.get(name), Mapping)
            }
            if segments:
                self._games[(away, home)] = segments

        # `starter_names` is keyed by SIDE ({"away": "...", "home": "..."})
        # while `pitcher_props` is keyed by PITCHER ID, and nothing in the
        # daily summary links the two -- verified by walking the whole game
        # payload for either id. Guessing from dict order would silently give
        # one starter the other's distribution, which is worse than a blank
        # cell: it is a confident wrong number next to a real price.
        #
        # So the id->name map is supplied by the caller from the roster
        # snapshot (`.away.starter` / `.home.starter` carry {id, name}). When
        # no snapshot exists for the date, pitcher props simply do not project
        # and `coverage` says so.
        id_to_name = {str(k): str(v) for k, v in (pitcher_names or {}).items()}

        for pitcher_id, payload in (game.get("pitcher_props") or {}).items():
            if not isinstance(payload, Mapping):
                continue
            name = _norm_name(id_to_name.get(str(pitcher_id)))
            if not name:
                continue
            self._pitchers[name] = dict(payload)

        for bucket_name, rows in (game.get("hitter_props_likelihood_topn") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                name = _norm_name(row.get("name"))
                if not name:
                    continue
                self._hitters[(name, str(bucket_name))] = dict(row)
                means = self._hitter_means.setdefault(name, {})
                for key, value in row.items():
                    if isinstance(key, str) and key.endswith("_mean"):
                        try:
                            means[key] = float(value)
                        except (TypeError, ValueError):
                            continue

        hr_payload = game.get("hitter_hr_likelihood_all") or {}
        for row in (hr_payload.get("overall") or []) if isinstance(hr_payload, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            name = _norm_name(row.get("name"))
            if name:
                self._hitters[(name, "hr_1plus")] = dict(row)

    def _derived_hrr_mean(self, name: str) -> float | None:
        """Hits + Runs + RBIs, summed from the components the sim DOES write.

        `#429`. The sim writes `hrr_mean: 0.0` for every hitter while writing
        genuine per-player probabilities (`p_hrr_2plus`, 75 distinct values on
        a live board) and genuine `pa_mean`/`ab_mean`. Measured on
        `daily_summary_2026_07_09.json`: `hrr_mean` present on 936 of 936 rows,
        **nonzero on 0 of them**. The producer of that field was not located;
        this reconstructs the value from data already in hand rather than
        serving a fabricated 0.0.

        WHY THIS IS EXACT AND NOT AN APPROXIMATION. Expectation is linear:

            E[H + R + RBI] = E[H] + E[R] + E[RBI]

        That holds no matter how strongly the three are correlated -- and they
        are heavily correlated, since a home run is 1 hit + 1 run + 1 RBI. That
        correlation would wreck a variance or a probability derived this way;
        it leaves the MEAN untouched. So this composes means and deliberately
        never composes probabilities: `model_prob_over` still comes from the
        sim's own `p_hrr_*` field.

        WHY THE COMPONENTS ARE AVAILABLE HERE. They arrive on DIFFERENT bucket
        rows (`h_mean` on hits_*, `r_mean` on runs_*, `rbi_mean` on rbi_*),
        which is why an hits_runs_rbis row looks bare. `ingest_game` already
        folds every `*_mean` it sees into `_hitter_means[name]` regardless of
        which bucket carried it, so by scoring time all three are in memory.
        Measured on the same artifact: all three present for **234 of 234**
        players, deriving to 1.79-2.47 against a market line of 1.5 -- the
        right magnitude, which a wrong-field or wrong-scale join would not be.

        ALL THREE OR NOTHING. A partial sum is silently too low and would be
        worse than a blank, because it looks like a real projection. Missing
        any component returns None and the cell stays empty.
        """
        means = self._hitter_means.get(name) or {}
        total = 0.0
        for key in _HRR_COMPONENT_MEANS:
            value = means.get(key)
            if not isinstance(value, (int, float)):
                return None
            total += float(value)
        # A zero sum means the components are dead too -- do not swap one
        # fabricated 0.0 for another.
        return round(total, 3) if total > 0 else None

    # -- query ----------------------------------------------------------
    def game_payloads(self, *, sport: Any, home_team: Any, away_team: Any) -> dict[str, Any] | None:
        """Segment payloads for a game, matched on the TEAM PAIR.

        The sim keys games by tri-code ("MIL", "PIT"); quote rows carry full
        club names ("Milwaukee Brewers"). Resolved through `team_aliases`, the
        same real per-sport maps `#218` established -- a string heuristic cannot
        bridge that gap, and that single failure is why 0 of 108 board
        candidates carried a quote on 2026-08-06.
        """
        if not self._games:
            return None
        try:
            from syndicate.features.shared.team_aliases import teams_match
        except Exception:
            return None
        for (away_tri, home_tri), payloads in self._games.items():
            try:
                if teams_match(sport, home_team, home_tri) and teams_match(sport, away_team, away_tri):
                    return payloads
            except Exception:
                continue
        return None

    def project(self, *, player_name: Any, market: Any, line: Any) -> dict[str, Any] | None:
        """Projection + modelled P(over) for one market line, or None.

        None is returned rather than a guess whenever the sim cannot answer:
        no such player, no such market, or a whole-number line on a
        threshold-only (hitter) market. A blank cell is honest; an invented
        projection next to a real price is not.
        """
        name = _norm_name(player_name)
        if not name:
            return None
        market_key = str(market or "").strip().lower()
        try:
            line_value = float(line)
        except (TypeError, ValueError):
            return None

        if market_key in _PITCHER_DISTS:
            payload = self._pitchers.get(name)
            if not payload:
                return None
            dist_key, mean_key = _PITCHER_DISTS[market_key]
            dist = payload.get(dist_key)
            if not isinstance(dist, Mapping):
                return None
            projected = payload.get(mean_key)
            try:
                projected = round(float(projected), 3)
            except (TypeError, ValueError):
                projected = _dist_mean(dist)
            return {
                "projected": projected,
                "model_prob_over": _dist_prob_over(dist, line_value),
                "source": "pitcher_distribution",
                "basis": dist_key,
            }

        if market_key == _HR_MARKET:
            row = self._hitters.get((name, "hr_1plus"))
            if not row or abs(line_value - 0.5) > 0.01:
                return None
            prob = row.get("p_hr_1plus_cal", row.get("p_hr_1plus"))
            return {
                "projected": row.get("hr_mean"),
                "model_prob_over": round(float(prob), 4) if prob is not None else None,
                "source": "hitter_threshold",
                "basis": "hr_1plus",
            }

        if market_key in _HITTER_BUCKETS:
            prefix, mean_key = _HITTER_BUCKETS[market_key]
            bucket = _bucket_for_line(prefix, line_value)
            if bucket is None:
                return None
            row = self._hitters.get((name, bucket))
            if not row:
                return None
            prob = None
            for key, value in row.items():
                # The probability field is named for its own threshold
                # (p_h_2plus, p_tb_3plus, ...), so pick the calibrated one if
                # present rather than hard-coding every spelling.
                if isinstance(key, str) and key.startswith("p_") and key.endswith("_cal"):
                    prob = value
                    break
            if prob is None:
                for key, value in row.items():
                    if isinstance(key, str) and key.startswith("p_"):
                        prob = value
                        break
            projected = row.get(mean_key)
            if projected is None:
                projected = (self._hitter_means.get(name) or {}).get(mean_key)
            derived_from = None
            if market_key == _HRR_MARKET and not projected:
                # The stored mean is the known-dead 0.0 (`#429`). Try to
                # reconstruct it; if that is not possible, BLANK IT rather than
                # letting the 0.0 through. A player in a "2+ HRR" bucket cannot
                # truly project 0.0, so serving it is the fabricated number this
                # whole ticket is about -- and a blank is the stated acceptable
                # outcome where a real value cannot be had.
                projected = self._derived_hrr_mean(name)
                if projected is not None:
                    derived_from = "h_mean+r_mean+rbi_mean"
            payload = {
                "projected": round(float(projected), 3) if projected is not None else None,
                "model_prob_over": round(float(prob), 4) if prob is not None else None,
                "source": "hitter_threshold",
                "basis": bucket,
            }
            if derived_from:
                # Say that the number was DERIVED rather than simulated. Same
                # rule the rest of this board follows: a value a consumer
                # cannot tell the provenance of is worse than a labelled one.
                payload["projected_derived_from"] = derived_from
            _attach_measured_skill(payload, market_key)
            return payload

        return None


def starter_ids_from_roster_snapshots(snapshot_dir: Path | str) -> dict[str, str]:
    """pitcher_id -> name, from a date's roster snapshots.

    The daily summary cannot supply this (see `ingest_game`). Roster snapshots
    can: each carries `.away.starter` and `.home.starter` as {id, name}. One
    small read per game, ~53KB each, and entirely optional -- a missing
    directory yields an empty map and pitcher props go unprojected rather than
    mis-projected.
    """
    mapping: dict[str, str] = {}
    directory = Path(snapshot_dir)
    if not directory.is_dir():
        return mapping
    for path in sorted(directory.glob("roster_*_pk*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for side in ("away", "home"):
            starter = ((payload.get(side) or {}) if isinstance(payload, Mapping) else {}).get("starter")
            if not isinstance(starter, Mapping):
                continue
            pitcher_id = starter.get("id")
            name = starter.get("name")
            if pitcher_id is not None and name:
                mapping[str(pitcher_id)] = str(name)
    return mapping


def load_prop_projections(
    summary_path: Path | str, *, roster_snapshot_dir: Path | str | None = None
) -> PropProjectionIndex:
    """Build the index from one daily-summary artifact.

    `roster_snapshot_dir` is optional and only unlocks PITCHER props. Without
    it hitter props still project; the coverage report distinguishes the two so
    a thin result is attributable rather than mysterious.
    """
    index = PropProjectionIndex()
    path = Path(summary_path)
    if not path.is_file():
        return index
    try:
        # Streaming would not help here: this is a single JSON object, not a
        # JSONL shard, so it must be parsed whole. It is ~2.3MB -- three orders
        # of magnitude under the ledger chunks `#254` had to stream.
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return index
    pitcher_names = (
        starter_ids_from_roster_snapshots(roster_snapshot_dir) if roster_snapshot_dir else {}
    )
    index.pitcher_name_map_size = len(pitcher_names)
    for game in (payload.get("outputs") or []) if isinstance(payload, Mapping) else []:
        if isinstance(game, Mapping):
            index.ingest_game(game, pitcher_names=pitcher_names)
    return index


def _dist_prob_below(dist: Mapping[str, Any], line: float) -> float | None:
    """P(outcome < line), the complement side. Push mass excluded from both."""
    total = 0.0
    below = 0.0
    for raw_value, raw_count in (dist or {}).items():
        try:
            value = float(raw_value)
            count = float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total += count
        if value < line:
            below += count
    return round(below / total, 4) if total > 0 else None


def project_game_market(
    index: "PropProjectionIndex",
    *,
    sport: Any,
    home_team: Any,
    away_team: Any,
    market: Any,
    selection: Any,
    line: Any,
    segment: Any,
) -> dict[str, Any] | None:
    """The sim's view of a GAME market -- h2h, spreads, totals -- or None.

    The sign convention is measured, not assumed. `run_margin_dist` is
    **home minus away**: verified against six games on 2026-07-12 where
    P(margin > 0) equalled `home_win_prob` to three decimals in every one
    (0.495/0.495, 0.475/0.475, 0.457/0.457, 0.428/0.428, 0.585/0.585). Getting
    that backwards would have inverted every spread projection while looking
    entirely plausible.
    """
    payloads = index.game_payloads(sport=sport, home_team=home_team, away_team=away_team)
    if not payloads:
        return None
    segment_key = _SEGMENT_PAYLOADS.get(str(segment or "").strip().lower())
    if segment_key is None:
        return None
    payload = payloads.get(segment_key)
    if not isinstance(payload, Mapping):
        return None

    market_key = str(market or "").strip().lower()
    side = str(selection or "").strip().lower()
    basis = f"{segment_key}"

    if market_key in {"h2h", "moneyline", "h2h_3_way"}:
        # Straight from the simulation -- no line, no distribution walk.
        home_prob = payload.get("home_win_prob")
        away_prob = payload.get("away_win_prob")
        if side in {"home", "1"}:
            prob = home_prob
        elif side in {"away", "2"}:
            prob = away_prob
        elif side in {"draw", "tie", "x"}:
            prob = payload.get("tie_prob")
        else:
            return None
        if prob is None:
            return None

        # A SEGMENT WIN AND A SEGMENT MONEYLINE ARE DIFFERENT OUTCOME SPACES.
        #
        # The sim answers "does the home team lead at the end of this segment",
        # which for a short segment is mostly NO because the segment is TIED.
        # The book's `h2h` lists two sides only, so a tie voids -- its price
        # describes P(home wins | someone wins). Comparing the two directly
        # subtracts a 3-outcome probability from a 2-outcome one.
        #
        # MEASURED on production 2026-08-08, MLB h2h, 15 games x 4 segments:
        #
        #     segment   model home_p   market fair   median edge
        #     full        0.463          0.526        -3.92
        #     first5      0.420          0.524       -11.62
        #     first3      0.369          0.522       -13.78
        #     first1      0.241          0.509       -31.83
        #
        # The model falls monotonically as the segment shortens -- CORRECT,
        # ties get likelier. The market fair stays pinned near 0.52 at every
        # segment -- because `_no_vig_over_probability` devigs the two listed
        # sides and there is no third to devig. So the "edge" is an artifact
        # that scales with how likely a tie is, and it is what put 29 of 60
        # h2h rows over 15 points and made the board look systematically
        # bearish on home.
        #
        # Renormalising into the decided space is the correct comparison, not a
        # fudge: if the tie voids the bet, P(home | decided) is exactly what the
        # price is offering. On `full` this is a no-op -- an MLB game cannot end
        # tied, so home+away already sums to 1.
        #
        # NOT applied to `h2h_3_way`, where the draw is a listed side and the
        # market's own three prices span the same space the sim does.
        renormalised = False
        if market_key in {"h2h", "moneyline"} and side not in {"draw", "tie", "x"}:
            try:
                decided = float(home_prob) + float(away_prob)
            except (TypeError, ValueError):
                decided = None
            # Guard the degenerate case rather than dividing by ~0: a segment
            # the sim thinks is almost never decided carries no usable signal,
            # and scaling by 1/0.01 would manufacture a confident number out of
            # simulation noise.
            if decided is not None and decided >= 0.2 and abs(1.0 - decided) > 1e-6:
                prob = float(prob) / decided
                renormalised = True

        return {
            "projected": None,  # a win probability has no "projected value"
            "model_prob_over": round(float(prob), 4),
            "source": "game_simulation",
            # The basis says WHICH space this probability lives in, so a reader
            # can tell a conditional number from a raw one without re-deriving
            # it -- the `basis` discipline #263 asked for, applied here.
            "basis": f"{basis}/win_prob_decided" if renormalised else f"{basis}/win_prob",
        }

    try:
        line_value = float(line)
    except (TypeError, ValueError):
        return None

    # `totals_alt` IS `totals` AT A DIFFERENT LINE, and the distribution prices
    # any line. Measured on the served board 2026-08-15 22:41Z: of 107 live
    # game-line rows, **53 carried no projection at all** -- not even a pregame
    # one -- and every one of them was `spreads_alt` (29) or `totals_alt` (24),
    # because neither key was in these sets and `project_game_market` returned
    # None. Same defect class as `batter_hits_runs_rbis` sitting in the prop
    # dist config while absent from the emitter's key table: the model could
    # price it and no one asked.
    if market_key in {"totals", "total", "totals_3_way", "totals_alt", "alternate_totals"}:
        dist = payload.get("total_runs_dist")
        if not isinstance(dist, Mapping):
            return None
        mean = _dist_mean(dist)
        if side in {"over", "o"}:
            prob = _dist_prob_over(dist, line_value)
        elif side in {"under", "u"}:
            prob = _dist_prob_below(dist, line_value)
        else:
            return None
        return {
            "projected": mean,
            "model_prob_over": prob,
            "source": "game_simulation",
            "basis": f"{basis}/total_runs_dist",
        }

    # `spreads_alt` likewise -- same `run_margin_dist`, different line. The
    # away/over frame note below applies to it unchanged.
    if market_key in {"spreads", "spreads_3_way", "run_line", "ats", "spreads_alt", "alternate_spreads"}:
        dist = payload.get("run_margin_dist")
        if not isinstance(dist, Mapping):
            return None
        # THE LINE ARRIVES IN THE AWAY/OVER FRAME. `#262` made the grid row's
        # `line` canonical (`book_grid._canonical_line`) so a row's line always
        # agrees with its own cells; before that it was whichever side happened
        # to anchor, so this code was ambiguous and sometimes right by accident.
        #
        # With L = the away-frame line, home's own line is H = -L, and home
        # covers when margin > -H, i.e. margin > +L. So the home branch must NOT
        # negate: negating computes P(margin > -L), which is the home +L
        # probability reported against the home -L market.
        #
        # MEASURED on production 2026-08-08 before the fix, same distribution at
        # +/-1.5 on two rows:
        #     line=+1.5 side=home -> 0.7386   (P(margin > -1.5), should be ~0.26)
        #     line=-1.5 side=home -> 0.2296   (P(margin > +1.5), should be ~0.74)
        # Inflated home probabilities of 0.67-0.74 on underdogs, which is where
        # the board's 86-89% implied model views and 19-28 point "edges" came
        # from -- confidently recommending bets the market prices at -4% to -8%.
        #
        # The away branch needs no change: it wants P(margin < away's line), and
        # the away frame is exactly what it now receives.
        if side in {"home", "1"}:
            prob = _dist_prob_over(dist, line_value)
        elif side in {"away", "2"}:
            prob = _dist_prob_below(dist, line_value)
        else:
            return None
        return {
            "projected": _dist_mean(dist),
            "model_prob_over": prob,
            "source": "game_simulation",
            "basis": f"{basis}/run_margin_dist",
        }

    return None


def _implied(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def _no_vig_over_probability(row: Mapping[str, Any]) -> float | None:
    """The market's TRUE probability of the over, vig removed.

    Comparing a model probability against a raw book price overstates the edge
    by roughly half the hold -- that is #238's whole finding (median hold 6.25%,
    so every EV was ~3.1 points optimistic). The correction needs BOTH sides, so
    this returns None on a one-sided market rather than pretending.

    Uses the CONSENSUS price per side, not the best: the best price is the most
    generous book, and de-vigging against it would understate the market's real
    view and manufacture edge.
    """
    consensus = row.get("consensus") or {}
    sides = [str(side) for side in (row.get("sides") or [])]
    # Two vocabularies, one shape: props quote over/under, game markets quote
    # home/away. Both are two-sided markets whose implied probabilities sum to
    # more than 1 by exactly the book's margin, so both de-vig identically --
    # only the labels differ. Handling just over/under is why every game market
    # came back with a projection and no edge.
    over_side = next((s for s in sides if s.lower() in {"over", "yes", "home", "1"}), None)
    under_side = next((s for s in sides if s.lower() in {"under", "no", "away", "2"}), None)
    if not over_side or not under_side:
        return None
    # A 3-way market (h2h_3_way) has a draw leg that must be included or the
    # sides sum to less than a market and the "fair" price errs in the bettor's
    # favour -- the most dangerous direction, and the same rule
    # `market_sides_for_quote` already enforces.
    draw_side = next((s for s in sides if s.lower() in {"draw", "tie", "x"}), None)
    over_implied = _implied(consensus.get(over_side))
    under_implied = _implied(consensus.get(under_side))
    if over_implied is None or under_implied is None:
        return None
    total = over_implied + under_implied
    if draw_side is not None:
        draw_implied = _implied(consensus.get(draw_side))
        if draw_implied is None:
            # A 3-way market missing its draw price cannot be de-vigged; saying
            # so is better than de-vigging across two of three legs.
            return None
        total += draw_implied
    if total <= 0:
        return None
    return round(over_implied / total, 4)


def attach_projections(grid_rows: list[dict[str, Any]], index: PropProjectionIndex) -> dict[str, Any]:
    """Stamp `projection` onto each grid row that the sim can answer for.

    Returns coverage, because "we joined projections" and "the projections
    joined to anything" are different claims -- and the second is the one that
    matters. A surface reporting zero coverage is a working surface over broken
    inputs, which is exactly the distinction the settlement work needed and did
    not have.
    """
    attached = 0
    considered = 0
    with_edge = 0
    for row in grid_rows:
        player = row.get("player_name")
        sides = list(row.get("sides") or ())
        considered += 1
        projected_side = None
        if player:
            projection = index.project(
                player_name=player, market=row.get("market"), line=row.get("line")
            )
            # Props: `model_prob_over` is the OVER, so it belongs on that row.
            projected_side = next((s for s in sides if str(s).lower() in {"over", "yes"}), None)
        else:
            # GAME markets -- h2h, spreads, totals -- join on the team pair and
            # the segment rather than a player name. Projected per SIDE, because
            # unlike a prop the two sides are different questions ("does home
            # win" vs "does away win") rather than over/under one number.
            projection = None
            over_side = next(
                (s for s in sides if str(s).lower() in {"over", "home", "yes", "1"}), None
            )
            projected_side = over_side
            if over_side is not None:
                projection = project_game_market(
                    index,
                    sport=row.get("sport"),
                    home_team=row.get("home_team"),
                    away_team=row.get("away_team"),
                    market=row.get("market"),
                    selection=over_side,
                    line=row.get("line"),
                    segment=row.get("segment"),
                )
        if projection is None:
            continue
        # Which SIDE this projection describes. A prop's `model_prob_over` is
        # the over; a game market's is home (or the over). Rendering it against
        # the wrong side would put home's edge on the away row -- a number that
        # is right and labelled wrong, which reads as a real signal.
        projection["side"] = projected_side
        model_prob = projection.get("model_prob_over")
        fair = _no_vig_over_probability(row)
        projection["market_fair_prob_over"] = fair

        # A PREGAME projection cannot be priced against a LIVE market.
        #
        # The sim's payloads are generated before first pitch. Once a game
        # starts the market re-prices on the actual state and the model does
        # not, so the difference is not an edge -- it is the score. Found on
        # 2026-07-12: an event with commence 16:07 carried betmgm quotes at
        # 17:35 (away -500) while the sim still said 0.495, producing a
        # +23-point "edge" on a coin-flip game. Game-market edges spread
        # -55 to +54 as a result, on moneylines, where books are sharpest.
        #
        # The projection itself is still shown -- a researcher comparing a
        # pregame model against a live line is a legitimate thing to want --
        # but it is not given an edge number, because that number would be
        # meaningless and would rank.
        # `#340`: the rule now lives in `live_edge_policy` because it was
        # duplicated here and in `soccer_projections`, and WNBA -- which never
        # got a copy -- shipped 128 live edges on 2026-08-10 while this suppressed
        # 862. A rule that has to be remembered in each sport's join will be
        # missed by the next sport added.
        live_reason = live_edge_unavailable_reason(row)
        if live_reason:
            projection["edge_vs_market_pct"] = None
            projection["edge_unavailable_reason"] = live_reason
        else:
            projection["edge_vs_market_pct"] = (
                round((float(model_prob) - float(fair)) * 100.0, 2)
                if model_prob is not None and fair is not None
                else None
            )
        row["projection"] = projection
        attached += 1
        if projection["edge_vs_market_pct"] is not None:
            with_edge += 1
    return {
        # Renamed from `player_rows`: this now counts EVERY row, because game
        # markets are projected too. Keeping the old name would have made the
        # denominator silently mean something different.
        "rows_considered": considered,
        "player_rows": considered,
        "rows_with_projection": attached,
        "rows_with_edge": with_edge,
        "pct_projected": round(100.0 * attached / considered, 1) if considered else 0.0,
        # Projected-but-no-edge means the market was one-sided, so no-vig could
        # not be computed. Reported separately because "the sim has a view" and
        # "we can price that view honestly" are different claims.
        "pct_with_edge": round(100.0 * with_edge / considered, 1) if considered else 0.0,
        "pitcher_names_resolved": getattr(index, "pitcher_name_map_size", 0),
    }
