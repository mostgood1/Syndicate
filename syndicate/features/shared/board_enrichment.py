"""Board enrichment: the three steps that turn a raw grid into a usable board.

MOVED HERE FROM `blueprints/intelligence.py`, where they were private helpers on
the SERVE-TIME path only. That placement was the defect: `pipeline/layer2_shortlist.py`
built its grid with `read_book_quotes` -> `build_book_grid` and called none of
them, so every row the worker persisted for Layer 2 was missing all three.

Measured consequences on the L2-A artifact (2026-08-08):

  no projections  -> `model_edge_pct` NULL on every row. This is #263. It was
                     filed as "projections don't exist"; they DO exist for MLB
                     (100% of h2h/spreads/totals carried `edge_vs_market_pct`
                     on 2026-08-07) -- they were simply never attached on the
                     worker path. With no model edge, `blended_score` falls back
                     to EV alone, and under proportional devig EV against fair
                     is `1/overround - 1`, IDENTICAL for every side of a market.
                     So the board ranked markets by hold and picked a side by
                     tie-break.
  no game state   -> `opportunity_gate` reads `game_state`/`is_live`; absent,
                     every row looks pregame and a SETTLED MARKET CAN RANK.
  no margin model -> one-sided rows carry no fair value at all.

One rule, one place: both the endpoint and the worker now call these, so the
board a user reads and the board that gets persisted cannot drift apart.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# How many EXTRA dates beyond the artifact's own to ask the scoreboard about.
# 7 covers NFL's Thu-Mon slate and soccer's week with room to spare, while
# keeping the worst case at 8 scoreboard calls per sport per build rather than
# one per distinct fixture date in a shard that may hold a month of futures.
_MAX_GAME_STATE_DATES = 7


def attach_game_state(grid: list, *, sport: str, selected_date: str) -> dict:
    """Stamp start time (pregame) or live status (in-progress) onto grid rows.

    Joined on the TEAM PAIR through `team_aliases`, not on string equality:
    quote rows carry full club names ("Baltimore Orioles") while the scoreboard
    carries tri-codes ("BAL"). `#218` established that a pure string heuristic
    cannot do this -- "chc" is neither a prefix of "chicago" nor the initials of
    "chicago cubs" -- and that single gap is why 0 of 108 board candidates
    carried a quote on 2026-08-06.

    Each side is tried against the chip's full club NAME and its abbr, first
    hit wins. Name first because it is the unambiguous key: soccer tri-codes
    collide across leagues, so `team_aliases` deliberately refuses to resolve
    them and an abbr-only join cannot match those rows at all. Abbr is kept as
    the fallback for providers that carry no name.

    `unmatched_teams` is returned on purpose. The failure mode this join has is
    a club whose two feeds spell it differently, and with no sample the symptom
    is an empty column with nothing to act on -- which is how soccer sat at 0
    matched rows through nine hypotheses.
    """
    matched = 0
    unmatched: dict[str, int] = {}
    try:
        from syndicate.features.shared.game_chip_scoreboard import build_game_chips
        from syndicate.features.shared.team_aliases import teams_match

        # CHIPS FOR THE DATES THE ROWS ACTUALLY SPAN, not just this artifact's
        # date (`#348`).
        #
        # The shard is keyed by CAPTURE date, so a Thursday fixture quoted on
        # Tuesday lands in Tuesday's artifact -- and asking the scoreboard for
        # Tuesday can never resolve it. Measured 2026-08-11: all 16 NFL preseason
        # fixtures (kickoffs 08-13/08-14, quoted on 08-11) reported
        # `chips: 0, reason: no_chips_for_date` and every one rendered `unknown`.
        #
        # `#329` made the BOARD span multiple days and left this join
        # single-date, so the two disagreed by construction. It bites hardest on
        # NFL and NCAAF, whose slates always span days, and never on MLB, whose
        # fixtures are quoted and played the same day -- which is why it went
        # unnoticed on the reference sport.
        #
        # Dates come from the rows themselves rather than a window parameter, so
        # this cannot drift from whatever scope the caller actually holds.
        row_dates: set[str] = set()
        for row in grid:
            raw = str((row.get("commence_time") or "")).strip()
            if len(raw) >= 10:
                row_dates.add(raw[:10])
        # BOUNDED, and the bound is stated rather than implicit: each date is a
        # scoreboard call, and an artifact can carry weeks of forward fixtures
        # (1,246 NFL rows across many dates, measured the same day). Nearest
        # dates first -- a board is read forward from today, and the far ones are
        # the least likely to be looked at.
        ordered = sorted(row_dates)
        if selected_date in ordered:
            ordered.remove(selected_date)
        query_dates = [selected_date] + ordered[:_MAX_GAME_STATE_DATES]

        chips = []
        for query_date in query_dates:
            try:
                chips.extend(build_game_chips(query_date, [sport]) or [])
            except Exception:
                # One bad date must not cost the others their state.
                _LOGGER.exception("BOOK_GRID_GAME_STATE_DATE_FAILURE sport=%s date=%s", sport, query_date)
    except Exception:
        _LOGGER.exception("BOOK_GRID_GAME_STATE_FAILURE sport=%s date=%s", sport, selected_date)
        return {"chips": 0, "rows_matched": 0}

    def _side_matches(row_team: str, chip_side: dict) -> bool:
        for key in ("name", "abbr"):
            token = (chip_side or {}).get(key)
            if token and teams_match(sport, row_team, token):
                return True
        return False

    for row in grid:
        home = row.get("home_team")
        away = row.get("away_team")
        if not home or not away:
            continue
        for chip in chips:
            chip_home = (chip.get("home") or {}) if isinstance(chip.get("home"), dict) else {}
            chip_away = (chip.get("away") or {}) if isinstance(chip.get("away"), dict) else {}
            try:
                if _side_matches(home, chip_home) and _side_matches(away, chip_away):
                    row["game"] = {
                        "state": chip.get("state"),
                        "start_time_utc": chip.get("start_time_utc"),
                        "status_token": chip.get("status_token"),
                        "matchup": chip.get("matchup"),
                        "home_score": (chip.get("home") or {}).get("score"),
                        "away_score": (chip.get("away") or {}).get("score"),
                    }
                    matched += 1
                    break
            except Exception:
                continue
        else:
            for team in (home, away):
                unmatched[str(team)] = unmatched.get(str(team), 0) + 1

    coverage = {"chips": len(chips), "rows_matched": matched}
    # NO CHIPS IS NOT A JOIN FAILURE, and reporting it as one is the exact
    # confusion this field was added to remove. Measured 2026-08-08: NFL
    # returned `chips: 0, unmatched_teams: [20 clubs]`, which reads as a broken
    # alias map -- but NFL's earliest board row was 2026-08-13, so there was
    # simply no slate to match against. A sport out of season would report the
    # same shape, every hour, forever.
    #
    # `unmatched_teams` answers "which clubs did the join fail to resolve",
    # which is only a meaningful question when there was something to resolve
    # against. With zero chips the honest answer is `no_chips_for_date`, and
    # the two states must not be spelled the same way -- that is the
    # degraded-looks-legitimate trap in miniature.
    if not chips:
        coverage["reason"] = "no_chips_for_date"
    elif unmatched:
        # Club names, not row counts, are the actionable unit: one unresolved
        # club fails every market on its game.
        coverage["unmatched_teams"] = sorted(unmatched, key=lambda name: (-unmatched[name], name))[:20]
    return coverage


def attach_projections(grid: list, *, sport: str, selected_date: str) -> dict:
    """Stamp the sim's projection and edge onto player-prop rows (S3).

    Per-sport, because each sim ships a different shape. An unwired sport
    returns a coverage payload saying so, so a blank column is attributable
    instead of mysterious -- a 2026-08-07 audit found WNBA, NFL and soccer at
    **0.0% projections on every market** while identity/line/odds were 100%,
    and only this reason string made that legible rather than a mystery.

    WNBA is wired to a DIFFERENT contract than MLB on purpose: it emits
    `projected` + `edge_vs_line` and leaves the probability fields null,
    because its model ships means and not a distribution. See
    `wnba_projections` -- inventing P(over) from a mean would put a fabricated
    number into EV and the blended score.
    """
    if sport == "wnba":
        try:
            from syndicate.features.shared.wnba_projections import (
                attach_wnba_projections,
                load_wnba_projections,
            )
            from syndicate.features.wnba.sources import processed_root
            from syndicate.features.shared.source_roots import preferred_artifact_roots

            file_name = f"props_recommendations_{selected_date}.csv"
            # Same resolution the WNBA props board uses: processed_root() prefers
            # a source_artifacts candidate whether or not anything was written
            # there, so fall back to whichever candidate root actually holds the
            # file rather than reporting an empty board.
            source_path = processed_root() / file_name
            if not source_path.exists():
                for root in preferred_artifact_roots(
                    __file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source"
                ):
                    candidate = root / "data" / "processed" / file_name
                    if candidate.exists():
                        source_path = candidate
                        break
            # GAME LINES FIRST, and independently of the prop join (`#364`).
            # Measured 2026-08-11: WNBA ran at 36.4% coverage with 0.0% of it on
            # game rows -- every projection was a prop, because
            # `attach_wnba_projections` skips anything whose `kind` is not
            # "prop". These are two different artifacts (game_cards vs
            # props_recommendations) and either can be present without the
            # other, so a missing props file must not suppress game lines.
            game_coverage: dict[str, Any] = {"supported": True, "rows_with_projection": 0}
            try:
                from syndicate.features.shared.wnba_game_projections import (
                    attach_wnba_game_projections,
                    load_wnba_game_projections,
                )

                game_index = load_wnba_game_projections(selected_date)
                if game_index.games:
                    game_coverage = attach_wnba_game_projections(grid, game_index)
                else:
                    game_coverage = {
                        "supported": True,
                        "rows_with_projection": 0,
                        "reason": "no WNBA game_cards rows for this date",
                    }
            except Exception:
                _LOGGER.exception("BOOK_GRID_GAME_PROJECTION_FAILURE sport=wnba date=%s", selected_date)
                game_coverage = {"supported": True, "error": "game projection join failed", "rows_with_projection": 0}

            index = load_wnba_projections(source_path)
            if not index.players:
                prop_coverage = {
                    "supported": True,
                    "rows_with_projection": 0,
                    "reason": "no WNBA model rows for this date",
                    "source_artifact": str(source_path),
                }
            else:
                prop_coverage = attach_wnba_projections(grid, index)
            return {
                **prop_coverage,
                "rows_with_projection": int(prop_coverage.get("rows_with_projection") or 0)
                + int(game_coverage.get("rows_with_projection") or 0),
                "prop_coverage": prop_coverage,
                "game_coverage": game_coverage,
            }
        except Exception:
            _LOGGER.exception("BOOK_GRID_PROJECTION_FAILURE sport=wnba date=%s", selected_date)
            return {"supported": True, "error": "projection join failed", "rows_with_projection": 0}

    if sport == "soccer":
        try:
            from syndicate.features.shared.soccer_projections import (
                attach_soccer_projections,
                load_soccer_projections,
            )
            from syndicate.features.shared.source_roots import preferred_artifact_roots

            roots = list(
                preferred_artifact_roots(
                    __file__, env_var="SYNDICATE_SOCCER_SOURCE_ROOT", local_dir_name="soccer_source"
                )
            )
            index = load_soccer_projections(roots, selected_date)
            if not index.matches:
                return {
                    "supported": True,
                    "rows_with_projection": 0,
                    "reason": "no soccer recommendations for this date",
                }
            return attach_soccer_projections(grid, index)
        except Exception:
            _LOGGER.exception("BOOK_GRID_PROJECTION_FAILURE sport=soccer date=%s", selected_date)
            return {"supported": True, "error": "projection join failed", "rows_with_projection": 0}

    if sport != "mlb":
        # NFL is unwired because there is NOTHING TO WIRE, which is a different
        # statement from "not done yet" and worth keeping distinct: production
        # holds exactly 4 NFL artifacts (two book_quotes shards and two
        # current_week.json), with no predictions/edges/recommendations of any
        # kind. Audited 2026-08-07. Fixing NFL means producing a sim, not
        # joining one.
        return {"supported": False, "reason": f"no projection source wired for {sport}"}
    try:
        from syndicate.features.mlb.sources import daily_artifact_path
        from syndicate.features.shared.prop_projections import (
            attach_projections,
            load_prop_projections,
        )

        summary_path = daily_artifact_path(selected_date)
        snapshot_dir = Path(summary_path).parent / "snapshots" / selected_date
        index = load_prop_projections(summary_path, roster_snapshot_dir=snapshot_dir)
        coverage = attach_projections(grid, index)
        coverage["supported"] = True
        coverage["summary_artifact"] = str(summary_path)
        coverage["games_in_summary"] = index.games
        return coverage
    except Exception:
        _LOGGER.exception("BOOK_GRID_PROJECTION_FAILURE sport=%s date=%s", sport, selected_date)
        return {"supported": True, "error": "projection join failed", "rows_with_projection": 0}


def attach_live_projections_for_sport(grid: list, *, sport: str, selected_date: str) -> dict:
    """Overlay the live re-sim's projections on live rows (`#350`).

    MLB ONLY, and that is a fact about which sport HAS a live re-sim rather than
    a shortcut. The 120-sim-per-live-game Monte Carlo is MLB's; WNBA ships means
    without a distribution and has no live tier at all. An unwired sport returns
    a stated reason, matching `attach_projections` above, so a blank live column
    is attributable rather than mysterious.

    Reads the PUBLISHED `live/<sport>_live_lens.json` snapshot. Never triggers
    the re-sim: that path is `refuse_if_compute_in_request_path` and belongs on
    live-odds-worker's tick.
    """
    if sport != "mlb":
        return {"supported": False, "reason": f"no live re-sim wired for {sport}", "rows_live_projected": 0}
    try:
        from syndicate.features.shared.live_projection_join import (
            attach_live_projections,
            build_live_prop_index,
        )
        from syndicate.features.shared.refresh_state_store import data_root, read_json_file

        snapshot = read_json_file(data_root() / "live" / f"{sport}_live_lens.json")
        if not isinstance(snapshot, dict):
            # An absent snapshot is the normal state outside a live slate. Say
            # which it is rather than reporting zero coverage as if the join
            # ran and found nothing -- those have different fixes.
            return {
                "supported": True,
                "reason": "no published live-lens snapshot",
                "rows_live_projected": 0,
            }
        return attach_live_projections(grid, build_live_prop_index(snapshot))
    except Exception:
        _LOGGER.exception("BOOK_GRID_LIVE_PROJECTION_FAILURE sport=%s date=%s", sport, selected_date)
        return {"supported": True, "error": "live projection join failed", "rows_live_projected": 0}


def attach_margin_model(grid: list) -> dict:
    """Fill fair value on one-sided rows from each book's measured margin (S4).

    The profile is built from THIS slate's two-sided markets rather than carried
    as a constant: holds move with the book, the sport and the day, and a stale
    constant is the defect class this codebase has paid for most often (a 900MB
    floor sized for a 2GB container; a 2.3MB payload figure describing a system
    that had changed underneath it).

    Never displaces a measured two-sided fair value -- it only fills rows that
    have none, and everything it writes is labelled
    `fair_method: "book_margin_model"`.
    """
    try:
        from syndicate.features.shared.book_margin_model import (
            apply_margin_model,
            build_margin_profile,
        )

        profile = build_margin_profile(grid)
        return apply_margin_model(grid, profile)
    except Exception:
        _LOGGER.exception("BOOK_GRID_MARGIN_MODEL_FAILURE")
        return {"rows_modelled": 0, "error": "margin model failed"}
