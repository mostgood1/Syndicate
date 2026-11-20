"""Orientation-free live game-line join for college basketball (lane college-neutral-site-live-join, 2026-11-19).

THE DEFECT. At a NEUTRAL SITE "home" is a label each vendor assigns, and ESPN and the odds feed sometimes assign it
the other way round. The board's rows carry the ODDS FEED's away/home. The NCAAB / WNCAAB live re-sim keys each game
on ESPN's `homeAway` (`ncaab/live_resim.py` `_espn_names`, read in `build_live_lens_snapshot`) and only RESPELLS the
two names from the odds feed (`board_name`, `nameSource: odds`) -- it never reorders them. `live_gameline_join` then
looks the lane up by the row's ORDERED `(away, home)` pair, so on every game the two vendors orient differently the
rows find nothing: `no_live_gameline_projection`, no model, no flag, no bet. The slate already reorients these games
to the odds feed (`ncaab/slate.orient_neutral_site_games`, since 11-02, 92d9e9193), and its `reoriented_neutral_site`
count is the visible marker of the population.

Measured 2026-11-19 (rail monitor, `.syndicate/findings_2026-11-19_layer2_rail_monitor.md` readings 6-13): WVU /
Florida (ESPN 401920517) was dark from 1:47 PM CST to the final after the odds feed's orientation flipped mid-game;
Auburn / Notre Dame (401920519) was dark from its 4:00 PM tip to the final. Both lanes were priced and indexed the
whole time -- under the other orientation.

THE FIX, AND WHY IT LIVES HERE. Every number on a lane is a fact about TEAMS, so a lane can be restated in the row's
frame exactly: P(row home wins) is P(lane away wins), the row's home margin is minus the lane's, and so on. This
module files a REVERSED VIEW of each indexed lane under the reversed pair, with every home-oriented field restated
(`reversed_view`), so the join's existing resolver (`live_gameline_join.resolve_live_gameline`, which reads the
index's `candidates` first) hands the row a projection already in its own frame. Nothing downstream changes: the
pricers, the gates, the display block and the ledger all read the hit as they always have.

- EXACT FIRST, ALWAYS. A view is filed only under a pair with NO exact candidate, so every row that joins today joins
  identically with the switch on.
- UNKNOWN MUST NOT DEFAULT PERMISSIVE. Every field of the hit is classified below as side-free or restated; a hit
  carrying a field in neither table gets NO view (counted by name in `refused`), never a copy that might still be in
  the lane's frame. The same goes for a margin histogram key that is not an integer and for an analytic per-line
  market (college lanes publish none; a spread quoted at one line has no exact restatement when a push is possible).
- THE RE-SIM'S OWN NUMBERS NEED NO CHANGE. At a neutral site the live prior carries no home edge
  (`ncaab/live_team_model.game_prior`: `edge = 0.0 if neutral`; the prior calibration's `gamma` applies only when
  `home_site`), the engine has no home-only term, and the margin anchor maps the closing market and the pregame sim
  onto the live home side by team id (`ncaab/live_resim.margin_anchor_for`). So the lane is right in ESPN's frame and
  only its LABELS disagree with the row.

THE SWITCH: `SYNDICATE_COLLEGE_LIVE_JOIN_ORIENTATION` = `off` | `shadow` | `on`. ABSENT = SHADOW, which serves exactly
what the board served before: no view is filed, nothing is priced differently, and each build counts the rows that
WOULD have joined (`COLLEGE_ORIENTATION_JOIN` line, and `orientation_reversed` in the join's `index_diagnostics`).
`on` files the views. NCAAB and WNCAAB only (`ORIENTATION_JOIN_SPORTS`); every other sport is `off` whatever the
switch says. Turning it `on` changes which live rows can carry an edge, so it is a BETTING change and loads only in a
betting-change window.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any

ORIENTATION_JOIN_ENV = "SYNDICATE_COLLEGE_LIVE_JOIN_ORIENTATION"
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
DEFAULT_MODE = MODE_SHADOW
_ON_VALUES = frozenset({"on", "1", "true", "yes"})
_OFF_VALUES = frozenset({"off", "0", "false", "no"})

# The sports whose live lanes are oriented by ESPN while their board rows are oriented by the odds feed, and whose lane
# fields are all classified below. A sport is added only after its hit fields are checked against these tables.
ORIENTATION_JOIN_SPORTS = frozenset({"ncaab", "wncaab"})

LOG_TAG = "[live_gameline_orientation] COLLEGE_ORIENTATION_JOIN"

# ---------------------------------------------------------------------------------------- the field classification
# The keys a hit carries (`live_gameline_join.live_gameline_from_lens` for a full-game lane, `_segment_hit` for a
# segment, plus what `build_live_gameline_index` stamps on each). Every key must be in exactly one table.

# Values that do not depend on which team is called home.
SIDE_FREE_FIELDS = frozenset({
    "sims_run", "total_mean", "total_runs_dist", "margin_anchored", "as_of", "score_changed_at",
    "state_period", "state_clock_seconds", "carried_forward", "lane", "game_pk", "start_epoch",
    "analytic_std_err", "sport", "segment", "segment_settled", "segment_margin_unanchored",
})
# Values `reversed_view` restates in the other frame.
RESTATED_FIELDS = frozenset({
    "home_win_prob", "home_margin", "margin_dist", "margin_dist_raw", "margin_dist_display",
    "state_home_score", "state_away_score", "pregame_home_win_prob", "analytic_markets", "progress",
})
# `progress` keys that are side-free (a share of the game). Anything else in it (MLB's `half`) refuses the view.
SIDE_FREE_PROGRESS_FIELDS = frozenset({"remainingFraction", "fraction"})
# Set on every view, so a reader can tell a restated hit from a native one.
VIEW_MARKER = "orientation_flipped"


def orientation_join_mode(sport: Any, environ: Mapping[str, str] | None = None) -> str:
    """`off` for a sport outside `ORIENTATION_JOIN_SPORTS`; else the switch, ABSENT (or unreadable) = shadow."""
    if str(sport or "").strip().lower() not in ORIENTATION_JOIN_SPORTS:
        return MODE_OFF
    env = os.environ if environ is None else environ
    raw = str(env.get(ORIENTATION_JOIN_ENV) or "").strip().lower()
    if raw in _ON_VALUES:
        return MODE_ON
    if raw in _OFF_VALUES:
        return MODE_OFF
    return DEFAULT_MODE


class ViewRefused(Exception):
    """A field this module cannot restate exactly. Its message is the counted reason."""


def _negated_hist(dist: Any, field: str) -> dict[str, Any]:
    """A home-positive integer histogram restated home-negative: key m -> -m, counts unchanged."""
    if not dist:
        return {}
    if not isinstance(dist, Mapping):
        raise ViewRefused(f"{field}_not_a_mapping")
    out: dict[str, Any] = {}
    for key, count in dist.items():
        try:
            margin = int(str(key).strip())
        except (TypeError, ValueError):
            raise ViewRefused(f"{field}_key_not_integer") from None
        out[str(-margin)] = count
    return out


def _complement(probability: Any, field: str) -> Any:
    if probability is None:
        return None
    try:
        p = float(probability)
    except (TypeError, ValueError):
        raise ViewRefused(f"{field}_not_a_number") from None
    if not 0.0 <= p <= 1.0:
        raise ViewRefused(f"{field}_out_of_range")
    return 1.0 - p


def _negated(value: Any, field: str) -> Any:
    if value is None:
        return None
    try:
        return -float(value)
    except (TypeError, ValueError):
        raise ViewRefused(f"{field}_not_a_number") from None


def _segment_home_prob(margin_dist: Mapping[str, Any]) -> float | None:
    """P(margin > 0) over every sim, ties included in the denominator: `_segment_hit`'s own three-way rule."""
    counts = [(int(k), int(v)) for k, v in margin_dist.items()]
    n = sum(c for _m, c in counts)
    return (sum(c for m, c in counts if m > 0) / n) if n > 0 else None


def reversed_view(projection: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """`(view, None)` -- the same lane restated with home and away swapped -- or `(None, reason)`.

    Full-game `home_win_prob` becomes `1 - p`, which is exact: a full-game sim cannot end level (overtime resolves it,
    `ncaab/live_resim.resim_live_game`), and the anchored histogram splits a shifted 0 half to each side
    (`anchor_result`). A SEGMENT can end level, so its three-way `P(margin > 0)` is recomputed from the restated
    histogram instead -- its complement would hand the tie mass to the other side."""
    if not isinstance(projection, Mapping):
        return None, "hit_not_a_mapping"
    unknown = sorted(set(projection) - SIDE_FREE_FIELDS - RESTATED_FIELDS - {VIEW_MARKER})
    if unknown:
        return None, f"unclassified_field:{unknown[0]}"
    try:
        view: dict[str, Any] = {k: v for k, v in projection.items() if k in SIDE_FREE_FIELDS}
        for field in ("margin_dist", "margin_dist_raw", "margin_dist_display"):
            if field in projection:
                view[field] = _negated_hist(projection.get(field), field)
        if "home_margin" in projection:
            view["home_margin"] = _negated(projection.get("home_margin"), "home_margin")
        if "home_win_prob" in projection:
            p = projection.get("home_win_prob")
            if p is None:
                view["home_win_prob"] = None
            elif "segment" in projection:
                raw = view.get("margin_dist_raw") or view.get("margin_dist")
                if not raw:
                    raise ViewRefused("segment_win_prob_without_histogram")
                view["home_win_prob"] = _segment_home_prob(raw)
            else:
                view["home_win_prob"] = _complement(p, "home_win_prob")
        if "pregame_home_win_prob" in projection:
            view["pregame_home_win_prob"] = _complement(projection.get("pregame_home_win_prob"),
                                                        "pregame_home_win_prob")
        if "state_home_score" in projection or "state_away_score" in projection:
            view["state_home_score"] = projection.get("state_away_score")
            view["state_away_score"] = projection.get("state_home_score")
        if "analytic_markets" in projection:
            if projection.get("analytic_markets"):
                raise ViewRefused("analytic_market_not_restatable")
            view["analytic_markets"] = {}
        if "progress" in projection:
            progress = projection.get("progress")
            if progress is not None and not isinstance(progress, Mapping):
                raise ViewRefused("progress_not_a_mapping")
            extra = sorted(set(progress or {}) - SIDE_FREE_PROGRESS_FIELDS)
            if extra:
                raise ViewRefused(f"progress_field_not_side_free:{extra[0]}")
            view["progress"] = dict(progress or {})
    except ViewRefused as exc:
        return None, str(exc)
    except (TypeError, ValueError):
        return None, "unparseable_value"
    view[VIEW_MARKER] = True
    return view, None


# ---------------------------------------------------------------------------------------------- filing the views

def _plan(index: Any) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, int]]:
    """Every reversed view this index would carry: `{reversed pair: [views]}`, plus the refusals by reason."""
    planned: dict[tuple[str, str], list[dict[str, Any]]] = {}
    refused: dict[str, int] = {}
    pool = getattr(index, "candidates", None)
    if not isinstance(pool, dict):
        return planned, refused
    exact = set(pool)
    for key, projections in pool.items():
        if not (isinstance(key, tuple) and len(key) == 2):
            continue
        reversed_key = (key[1], key[0])
        if reversed_key == key or reversed_key in exact:
            continue  # EXACT FIRST: a pair some lane already answers is never shadowed by a view
        views: list[dict[str, Any]] = []
        for projection in projections or ():
            view, why = reversed_view(projection)
            if view is None:
                refused[str(why)] = refused.get(str(why), 0) + 1
                continue
            views.append(view)
        if views:
            planned[reversed_key] = views
    return planned, refused


class OrientationState:
    """What one board build's orientation pass decided, carried from `prepare` to `finish`."""

    def __init__(self, sport: str, mode: str) -> None:
        self.sport = sport
        self.mode = mode
        self.keys: set[tuple[str, str]] = set()
        self.views = 0
        self.refused: dict[str, int] = {}
        self.error: str | None = None


def prepare(index: Any, segment_indexes: Mapping[str, Any] | None = None, *, sport: Any,
            environ: Mapping[str, str] | None = None) -> OrientationState:
    """Plan the reversed views of the full-game index and every segment index; FILE them only when the mode is `on`.

    Never raises: any failure leaves every index exactly as built (the old behaviour) and is named on the state."""
    slug = str(sport or "").strip().lower()
    state = OrientationState(slug, orientation_join_mode(slug, environ))
    if state.mode == MODE_OFF:
        return state
    try:
        plans = [_plan(index)]
        for seg_index in (segment_indexes or {}).values():
            plans.append(_plan(seg_index))
        full_plan = plans[0][0]
        state.views = sum(len(v) for v in full_plan.values())
        for planned, refused in plans:
            state.keys.update(planned)
            for reason, n in refused.items():
                state.refused[reason] = state.refused.get(reason, 0) + n
        if state.mode == MODE_ON:
            targets = [index] + list((segment_indexes or {}).values())
            for target, (planned, _refused) in zip(targets, plans):
                for reversed_key, views in planned.items():
                    target.candidates[reversed_key] = views
    except Exception as exc:  # noqa: BLE001 -- the join must run as it always did
        state.error = f"{type(exc).__name__}: {exc}"[:200]
        state.keys = set()
        state.views = 0
    return state


def _token(value: Any) -> str:
    return re.sub(r"\s+", "_", str(value)).strip("_") or "none"


_LIVE_STATES = frozenset({"live", "in_progress"})
_JOINED_MARKETS = frozenset({"h2h", "totals", "total", "totals_alt", "alternate_totals",
                             "spreads", "run_line", "ats", "spreads_alt", "alternate_spreads"})


def finish(state: OrientationState, grid: Any, coverage: dict[str, Any] | None,
           index_diag: dict[str, Any] | None) -> dict[str, Any] | None:
    """Count the live rows on a reversed pair, and how many of them now carry a live number; record and print it.

    `rows`: live game rows whose ordered pair is the REVERSE of an indexed lane's (shadow: rows that would have
    joined; on: rows that did), and `games` their distinct pairs. `joined`: of those rows, the ones carrying a
    `live_gameline` verdict or a Live-column number (a settled segment carries neither, as on any game). Printed only
    when there is something to say (a reversed row, a refusal or an error), so a slate with none adds no line."""
    if state.mode == MODE_OFF:
        return None
    reversed_pairs: set[tuple[str, str]] = set()
    try:
        from syndicate.features.shared.live_gameline_join import LIVE_DISPLAY_KEY, _norm_team

        rows = joined = 0
        for row in grid if isinstance(grid, (list, tuple)) else ():
            if not isinstance(row, Mapping) or str(row.get("kind") or "") != "game":
                continue
            game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
            if str(game.get("state") or "").strip().lower() not in _LIVE_STATES:
                continue
            if str(row.get("market") or "").strip().lower() not in _JOINED_MARKETS:
                continue
            key = (_norm_team(row.get("away_team")), _norm_team(row.get("home_team")))
            if key not in state.keys:
                continue
            rows += 1
            reversed_pairs.add(key)
            if isinstance(row.get("live_gameline"), Mapping) or isinstance(row.get(LIVE_DISPLAY_KEY), Mapping):
                joined += 1
        summary = {"mode": state.mode, "games": len(reversed_pairs), "rows": rows, "joined": joined}
        if state.refused:
            summary["refused"] = dict(state.refused)
        if state.error:
            summary["error"] = state.error
    except Exception as exc:  # noqa: BLE001 -- instrumentation never breaks the board
        summary = {"mode": state.mode, "error": f"count_failed:{type(exc).__name__}"}
    if isinstance(coverage, dict):
        coverage["orientation_reversed"] = summary
    worth_saying = bool(summary.get("rows") or summary.get("refused") or summary.get("error"))
    if worth_saying and isinstance(index_diag, dict):
        # Only then: `index_diagnostics` rides the LIVE_GAMELINE_BUILD line, which drops its widest dict past 1,000
        # chars, and an always-present zero would crowd out `withheld_by_reason` on every college build.
        index_diag["orientation_reversed"] = summary
    if worth_saying:
        pairs = _token(";".join(f"{a}@{h}" for a, h in sorted(reversed_pairs)))[:300]
        print(f"{LOG_TAG} sport={state.sport} mode={state.mode} "
              f"games={summary.get('games', 0)} rows={summary.get('rows', 0)} joined={summary.get('joined', 0)} "
              f"error={_token(summary.get('error') or 'none')} pairs={pairs or '-'} "
              f"refused={json.dumps(summary.get('refused') or {}, sort_keys=True, separators=(',', ':'))}",
              flush=True)
    return summary
