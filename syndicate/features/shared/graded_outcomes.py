"""One grading contract for every sport's evaluation-ledger settlement.

Context: Syndicate learning loop (docs/reports/syndicate_learning_loop_plan_2026_08_03.md), Stage 1.
See also: docs/ai_context/architecture.md

Role:
- `graded_rows_for_date(sport, date_str)` is the single entrypoint
  evaluation_settlement.settle_ledger_for_date should call. Before this
  module, settlement hardcoded a two-sport allowlist (_SUPPORTED_SPORTS =
  ("mlb", "wnba")) because grading was implemented ad hoc, once per sport,
  inline in evaluation_settlement.py -- the reason 6 of 8 sports could
  never be settled wasn't missing data, it was a missing adapter.
- Every grader below returns the SAME row shape
  match_graded_row/_pnl_for_settlement already consume (sport, market,
  selection, player, team, home, away, title, line, actual, odds, result,
  pnl, closing_price) -- this module does not change the matching
  contract, only centralizes who is allowed to answer "what happened".

Constraints:
- Read-only against each sport's own already-graded/scored artifacts;
  mirrors evaluation_settlement.py's own constraint of never recomputing a
  join a sport's own module already does.
- A sport with no real grader yet returns [] rather than raising, so an
  unmatched ledger record for that sport is correctly attributed to
  "no graded rows available" (evaluation_settlement's own diagnostic
  breakdown) instead of crashing settlement for every other sport.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping


GradedRowGrader = Callable[[str], list[dict[str, Any]]]

# Documented, not enforced: the canonical GradedOutcome shape every grader
# below produces (a superset across sports -- most rows only populate the
# fields relevant to their own market). Kept as a plain dict, not a
# dataclass/TypedDict, because match_graded_row/_pnl_for_settlement already
# consume these as Mapping[str, Any] and every existing per-sport source
# (market_accuracy payloads, performance logs) is naturally dict-shaped --
# wrapping and unwrapping a dataclass at every call site would add
# conversion cost without changing what's actually validated.
GRADED_OUTCOME_FIELDS = (
    "sport", "market", "selection", "player", "team", "home", "away",
    "title", "line", "actual", "odds", "result", "pnl", "closing_price",
)


def _unavailable_graded_rows_for_date(_date_str: str) -> list[dict[str, Any]]:
    return []


# ---------------------------------------------------------------------------
# MLB / WNBA / NBA / NHL -- all four already flow through the same
# "days -> games.rows / props.rows" shape (live_lens_local.build_local_market_accuracy_payload
# for wnba/nba/nhl; MLB has its own equivalent by-kind structure). One
# generic extractor handles all of them; only the payload-builder and the
# per-row field names differ slightly.
# ---------------------------------------------------------------------------


def _mlb_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.mlb.market_accuracy import build_market_accuracy_payload

    try:
        payload = build_market_accuracy_payload(f"date={date_str}")
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        by_kind = day.get("rows") if isinstance(day.get("rows"), dict) else {}
        # WIDEST TIER FIRST. This asks "what happened in this market", not "did
        # the locked policy pick it" -- and every caller is settlement-side
        # (`evaluation_settlement`, `emit_settlement_inputs`,
        # `settlement_cost_preflight`). The ledger's recommendations are
        # produced independently of the policy card, so grading only the
        # policy's own picks means settlement can never match anything it did
        # not also choose to bet.
        #
        # The old order short-circuited on `official` and discarded the rest,
        # because `or` takes the first NON-EMPTY tier rather than the largest.
        # Measured on restored dates:
        #
        #     2026-06-04   official 182   playable 789   all 971
        #     2026-07-04   official 272   playable 510   all 782
        #     2026-07-08   official 234   playable 392   all 626
        #     TOTAL        official 688                  all 2379   -> 3.5x
        #
        # Safe as a straight swap rather than a union, verified on both dates:
        # `official` and `playable` are each SUBSETS of `all`, and
        # `union(official, playable) == all` exactly -- zero all-only rows, so
        # nothing is invented and nothing is double-counted. Every row in `all`
        # also carries a real result (win/loss), which the filter below
        # re-checks anyway.
        kind_rows = by_kind.get("all") or by_kind.get("playable") or by_kind.get("official") or []
        for row in kind_rows:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": "mlb",
                    "market": row.get("market"),
                    "selection": row.get("selection"),
                    "player": row.get("player_name"),
                    "team": row.get("team"),
                    "title": row.get("title"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("odds"),
                    "result": result,
                    "pnl": row.get("profit_u"),
                }
            )
    return rows


def _local_market_accuracy_graded_rows_for_date(
    sport: str, date_str: str, *, build_payload: Callable[[str], dict[str, Any] | None]
) -> list[dict[str, Any]]:
    try:
        payload = build_payload(f"date={date_str}")
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        games = day.get("games") if isinstance(day.get("games"), dict) else {}
        for row in games.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": sport,
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "home": row.get("home"),
                    "away": row.get("away"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
        props = day.get("props") if isinstance(day.get("props"), dict) else {}
        for row in props.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": sport,
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "player": row.get("player"),
                    "team": row.get("team"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
    return rows


def _wnba_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.shared.live_lens_local import build_local_market_accuracy_payload
    from syndicate.features.wnba.sources import processed_roots

    # `#309`. Was `processed_root()` -- ONE root, chosen before any filename is
    # known. Measured live 2026-08-09: it returned
    # `.../wnba_source/source_artifacts/data/processed` while the refresh
    # pipeline writes `.../wnba_source/data/processed`, so this grader read an
    # unrelated directory and every WNBA date scored `{"available": False}` ->
    # zero graded rows, indistinguishable from an unplayed slate.
    #
    # `roots` is now every candidate, resolved per requested file downstream.
    # NOTE this alone does not guarantee rows: `_score_market_{games,props}_day`
    # need `recon_games_{date}.csv` / `recon_props_{date}.csv` alongside the
    # recommendations, and either side of a pair missing still yields
    # `{"available": False}`. See `#310`.
    roots = processed_roots()
    return _local_market_accuracy_graded_rows_for_date(
        "wnba", date_str, build_payload=lambda qs: build_local_market_accuracy_payload(qs, roots)
    )


def _nba_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.nba.market_accuracy import build_market_accuracy_payload

    return _local_market_accuracy_graded_rows_for_date("nba", date_str, build_payload=build_market_accuracy_payload)


def _nhl_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.nhl.market_accuracy import build_market_accuracy_payload

    return _local_market_accuracy_graded_rows_for_date("nhl", date_str, build_payload=build_market_accuracy_payload)


# ---------------------------------------------------------------------------
# NFL -- schedule_{season}.csv carries the real closing spread/total/
# moneyline numbers AND the game date AND (once played) the final score,
# all keyed by the same game_id. smartsim2_performance_tracking's own
# log (smartsim2_performance_log.jsonl) does NOT carry a date, only
# season/week, and it grades the MODEL's pick, not an arbitrary
# selection+line -- neither is directly usable as a generic "what would an
# arbitrary bet on this game have graded as" ladder the way MLB/WNBA's
# market_accuracy rows already are. Build that ladder straight from the
# schedule file instead: one graded row per side per market
# (moneyline/spread/total), which needs nothing but the closing numbers
# already on that row and the final score -- no model attribution needed,
# mirroring how MLB/WNBA's own graded rows don't care which model
# recommended a selection either.
# ---------------------------------------------------------------------------


def _read_schedule_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _nfl_schedule_paths() -> list[Path]:
    """Every NFL schedule CSV on disk.

    #273: this globbed `default_nfl_source_root() / "data"`, a subdirectory that
    does not exist for NFL. `nfl/sources.py`'s own `data_path()` is
    `default_nfl_source_root().joinpath(...)` -- the source root IS the data
    directory -- so `real_schedule_path(2026)` resolves to
    `data/nfl_source/schedule_2026.csv` while this looked in
    `data/nfl_source/data/`. The `/ "data"` was carried over from
    `_ncaaf_lines_paths` below, where it is CORRECT (ncaaf_source really does
    have a `data/` subdirectory). One layout assumption, two sports, right once.

    Consequence: `root.exists()` was False, so this returned `[]` and the NFL
    grader produced ZERO rows for every date since it was written -- the fourth
    instance of this file's own rule that *exactly* zero means a read of
    something nothing writes, not a threshold to loosen. It was invisible
    because the settlement autorun is off and, when it did run, `nfl: 0` is
    indistinguishable from an offseason date.

    Both locations are searched now rather than swapping one guess for another:
    a mirror that grows a `data/` subdir later must not silently go dark again.
    """
    from syndicate.features.nfl.sources import default_nfl_source_root

    root = default_nfl_source_root()
    # Every schedule_{season}.csv the mirror has on disk -- scanning all of
    # them (rather than guessing a season from date_str's year, which is
    # wrong for the January stub of a season that started the prior
    # calendar year) so a January date still resolves against the right file.
    # Also picks up schedule_preseason_{season}.csv, which is a separate file
    # with its own rows; dates do not collide, so the union is correct.
    paths: list[Path] = []
    for candidate_root in (root, root / "data"):
        if candidate_root.exists():
            paths.extend(candidate_root.glob("schedule_*.csv"))
    return sorted(set(paths))


# Affirmative "this game has been played" values, as an ALLOWLIST.
#
# #273, and this half matters more than the path fix. `schedule_preseason_2026.csv`
# carries `status: "Scheduled"` with `away_score: "0"` / `home_score: "0"` on all
# 49 games -- PLACEHOLDER ZEROS, not results. The blank-score guard below cannot
# see them, because "0" is not blank. So repairing the path alone would have made
# the grader emit, for every unplayed preseason game:
#
#     moneyline home -> margin 0 -> "push"
#     moneyline away -> margin 0 -> "push"
#     spread / total  -> graded against a 0-0 "actual"
#
# i.e. fabricated settled outcomes on games that have not kicked off. That is
# strictly worse than the zero it replaced, and settlement would have written
# them into the ledger as real results.
#
# The broken path was the only thing preventing that -- the same shape as the
# soccer lane's `_has_usable_game_state` regression the same day: a data path
# repaired, and a guard that had been silently relying on it being broken.
# Measured across the mirror: preseason 2023/2024/2025 are `Final` on every row
# (49/49, 49/49, 48/48), 2026 is `Scheduled` on every row (49/49) with 49 of 49
# scored 0-0. `schedule_{season}.csv` (regular season) has NO status column at
# all and no 0-0 rows, so it keeps the blank-score rule unchanged.
_NFL_PLAYED_STATUSES = frozenset({"final", "final/ot", "final ot", "completed", "closed", "post", "status_final"})


def _nfl_game_is_played(game: Mapping[str, Any]) -> bool:
    """True only when the row affirmatively says the game finished.

    Allowlist, not denylist: an unrecognised status must NOT grade. A new status
    string appearing upstream should cost us a missed settlement, never an
    invented one. Rows with no `status` column keep the previous behaviour
    (scores present = played), which is correct for `schedule_{season}.csv`.
    """
    if "status" not in game:
        return True
    return str(game.get("status") or "").strip().lower() in _NFL_PLAYED_STATUSES


def _nfl_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for schedule_path in _nfl_schedule_paths():
        for game in _read_schedule_csv(schedule_path):
            if str(game.get("gameday") or "").strip() != date_str:
                continue
            if not _nfl_game_is_played(game):
                continue
            home_score = _to_float(game.get("home_score"))
            away_score = _to_float(game.get("away_score"))
            if home_score is None or away_score is None:
                continue
            home_team = str(game.get("home_team") or "").strip()
            away_team = str(game.get("away_team") or "").strip()
            title = f"{away_team} @ {home_team}"
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            spread_line = _to_float(game.get("spread_line"))
            total_line = _to_float(game.get("total_line"))
            home_moneyline = _to_float(game.get("home_moneyline"))
            away_moneyline = _to_float(game.get("away_moneyline"))

            def _ml_result(margin_for_side: float) -> str:
                if margin_for_side == 0:
                    return "push"
                return "win" if margin_for_side > 0 else "loss"

            rows.append({"sport": "nfl", "market": "moneyline", "selection": home_team, "home": home_team, "away": away_team, "title": title, "actual": home_score, "odds": home_moneyline, "result": _ml_result(actual_margin)})
            rows.append({"sport": "nfl", "market": "moneyline", "selection": away_team, "home": home_team, "away": away_team, "title": title, "actual": away_score, "odds": away_moneyline, "result": _ml_result(-actual_margin)})

            if spread_line is not None:
                # schedule_line convention (nfl/cards.py): spread_line is the
                # home team's own number (negative favors home), matching
                # the sign _nfl_market_board_rows_for_game already assumes.
                def _spread_result(covers_margin: float) -> str:
                    if covers_margin == 0:
                        return "push"
                    return "win" if covers_margin > 0 else "loss"

                rows.append({"sport": "nfl", "market": "spread", "selection": home_team, "home": home_team, "away": away_team, "title": title, "line": spread_line, "actual": actual_margin, "odds": -110, "result": _spread_result(actual_margin + spread_line)})
                rows.append({"sport": "nfl", "market": "spread", "selection": away_team, "home": home_team, "away": away_team, "title": title, "line": -spread_line, "actual": -actual_margin, "odds": -110, "result": _spread_result(-actual_margin - spread_line)})

            if total_line is not None:
                over_result = "push" if actual_total == total_line else ("win" if actual_total > total_line else "loss")
                under_result = "push" if actual_total == total_line else ("win" if actual_total < total_line else "loss")
                rows.append({"sport": "nfl", "market": "total", "selection": "over", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": over_result})
                rows.append({"sport": "nfl", "market": "total", "selection": "under", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": under_result})
    return rows


# ---------------------------------------------------------------------------
# Soccer -- moneyline (3-way)/total-at-2.5/BTTS, computed directly from
# schedule_{season}.json's real ESPN-sourced scores (soccer had no actuals
# builder at all before this; see syndicate/features/soccer/actuals.py for
# the full reasoning, including why spread/Asian-handicap is not graded
# yet). Across all 10 leagues per date.
# ---------------------------------------------------------------------------


def _soccer_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.soccer.actuals import graded_rows_for_date as _soccer_actuals_graded_rows_for_date

    try:
        return _soccer_actuals_graded_rows_for_date(date_str)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# NCAAB -- unlike every other sport here, the source artifact
# (results_by_date_payload) already carries actual_margin/actual_total AND
# the market's own ats_result/ou_result_full ("Home Cover"/"Away Cover"/
# "Push", "Over"/"Under"/"Push") pre-graded against spread_home/market_total
# -- there is no evaluation module for NCAAB (no props, no picks, no
# market_accuracy equivalent) but the raw results archive turns out to
# already BE a graded ladder, so this adapter only needs to reshape it, not
# compute it.
# ---------------------------------------------------------------------------


def _ncaab_ats_side_result(ats_result: str, *, side: str) -> str | None:
    text = str(ats_result or "").strip().lower()
    if not text:
        return None
    if "push" in text:
        return "push"
    if "home" in text:
        return "win" if side == "home" else "loss"
    if "away" in text:
        return "win" if side == "away" else "loss"
    return None


def _ncaab_ou_side_result(ou_result: str, *, side: str) -> str | None:
    text = str(ou_result or "").strip().lower()
    if not text:
        return None
    if "push" in text:
        return "push"
    if "over" in text:
        return "win" if side == "over" else "loss"
    if "under" in text:
        return "win" if side == "under" else "loss"
    return None


def _ncaab_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.ncaab.sources import results_by_date_payload

    try:
        payload = results_by_date_payload(date_str)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    raw_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []

    rows: list[dict[str, Any]] = []
    for game in raw_rows:
        if not isinstance(game, dict):
            continue
        home_team = str(game.get("home_team") or "").strip()
        away_team = str(game.get("away_team") or "").strip()
        home_score = _to_float(game.get("home_score"))
        away_score = _to_float(game.get("away_score"))
        title = f"{away_team} @ {home_team}"

        if home_score is not None and away_score is not None and home_score != away_score:
            home_ml_result = "win" if home_score > away_score else "loss"
            away_ml_result = "loss" if home_score > away_score else "win"
            rows.append({"sport": "ncaab", "market": "moneyline", "selection": home_team, "home": home_team, "away": away_team, "title": title, "actual": home_score, "result": home_ml_result})
            rows.append({"sport": "ncaab", "market": "moneyline", "selection": away_team, "home": home_team, "away": away_team, "title": title, "actual": away_score, "result": away_ml_result})

        spread_home = _to_float(game.get("spread_home"))
        home_spread_result = _ncaab_ats_side_result(game.get("ats_result"), side="home")
        away_spread_result = _ncaab_ats_side_result(game.get("ats_result"), side="away")
        if home_spread_result is not None:
            rows.append({"sport": "ncaab", "market": "spread", "selection": home_team, "home": home_team, "away": away_team, "title": title, "line": spread_home, "actual": game.get("actual_margin"), "result": home_spread_result})
        if away_spread_result is not None:
            rows.append({"sport": "ncaab", "market": "spread", "selection": away_team, "home": home_team, "away": away_team, "title": title, "line": (-spread_home if spread_home is not None else None), "actual": game.get("actual_margin"), "result": away_spread_result})

        market_total = _to_float(game.get("market_total"))
        over_result = _ncaab_ou_side_result(game.get("ou_result_full") or game.get("actual_ou"), side="over")
        under_result = _ncaab_ou_side_result(game.get("ou_result_full") or game.get("actual_ou"), side="under")
        if over_result is not None:
            rows.append({"sport": "ncaab", "market": "total", "selection": "over", "home": home_team, "away": away_team, "title": title, "line": market_total, "actual": game.get("actual_total"), "result": over_result})
        if under_result is not None:
            rows.append({"sport": "ncaab", "market": "total", "selection": "under", "home": home_team, "away": away_team, "title": title, "line": market_total, "actual": game.get("actual_total"), "result": under_result})
    return rows


# ---------------------------------------------------------------------------
# NCAAF -- follow-up to the gap noted above: cfbd_lines_{wk}.json /
# cfbd_lines_{season}_wk{N}.json (already fetched for the market board,
# ncaaf/cards.py:_smartsim2_standalone_market_lines) turns out to carry
# everything needed directly -- a real joinable id (CFBD's own numeric game
# id; 705/752 = 93.8% overlap confirmed against
# smartsim2_performance_log.jsonl's own game_id field), a real UTC
# `startDate`, multi-provider `lines` (spread/overUnder/moneylines), and
# (once played) real `homeScore`/`awayScore`. The performance log itself is
# NOT used here -- same as the NFL adapter above, grading an arbitrary
# selection+line needs only the real closing market number and the real
# final score, not which internal model picked what.
#
# Sign convention verified against ncaaf/cards.py's own
# `_smartsim2_standalone_market_lines` (`market_margin =
# -statistics.mean(spreads)`, i.e. cfbd's raw `spread` field is already
# "the home team's own signed number, negative favors home" -- e.g. "TCU
# -6.5" with TCU at home is `spread: -6.5`), the exact same convention
# `_nfl_graded_rows_for_date` above assumes for `spread_line` from
# schedule_{season}.csv. No renegotiating the sign here -- average the raw
# `spread`/`overUnder` fields directly.
# ---------------------------------------------------------------------------


def _ncaaf_lines_paths() -> list[Path]:
    from syndicate.features.ncaaf.sources import default_ncaaf_source_root

    root = default_ncaaf_source_root() / "data"
    if not root.exists():
        return []
    return sorted(root.glob("cfbd_lines_*.json"))


def _ncaaf_game_local_date(game: Mapping[str, Any]) -> str | None:
    from syndicate.features.shared.timezone import central_date_from_iso

    resolved = central_date_from_iso(game.get("startDate"))
    return resolved.isoformat() if resolved else None


def _ncaaf_market_numbers(game: Mapping[str, Any]) -> dict[str, float | None]:
    import statistics as _statistics

    lines = game.get("lines") if isinstance(game.get("lines"), list) else []
    spreads = [line["spread"] for line in lines if isinstance(line, dict) and line.get("spread") is not None]
    totals = [line["overUnder"] for line in lines if isinstance(line, dict) and line.get("overUnder") is not None]
    spread_line = _statistics.mean(spreads) if spreads else None
    total_line = _statistics.mean(totals) if totals else None
    home_moneyline = None
    away_moneyline = None
    for line in lines:
        if not isinstance(line, dict):
            continue
        if line.get("homeMoneyline") is not None and line.get("awayMoneyline") is not None:
            home_moneyline = line.get("homeMoneyline")
            away_moneyline = line.get("awayMoneyline")
            break
    return {"spread_line": spread_line, "total_line": total_line, "home_moneyline": home_moneyline, "away_moneyline": away_moneyline}


def _ncaaf_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_game_ids: set[str] = set()
    for lines_path in _ncaaf_lines_paths():
        try:
            with lines_path.open("r", encoding="utf-8") as handle:
                games = json.load(handle)
        except Exception:
            continue
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            game_id = str(game.get("id") or "").strip()
            # Several cfbd_lines_*.json snapshots can carry the same game
            # (weekly re-fetches, or the "_wkN"/"_{season}_wkN" naming
            # overlapping) -- grade each real game once per date.
            if not game_id or game_id in seen_game_ids:
                continue
            game_date = _ncaaf_game_local_date(game)
            if game_date != date_str:
                continue
            home_score = _to_float(game.get("homeScore"))
            away_score = _to_float(game.get("awayScore"))
            if home_score is None or away_score is None:
                continue
            seen_game_ids.add(game_id)

            home_team = str(game.get("homeTeam") or "").strip()
            away_team = str(game.get("awayTeam") or "").strip()
            title = f"{away_team} @ {home_team}"
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            market = _ncaaf_market_numbers(game)
            spread_line = market["spread_line"]
            total_line = market["total_line"]

            def _ml_result(margin_for_side: float) -> str:
                if margin_for_side == 0:
                    return "push"
                return "win" if margin_for_side > 0 else "loss"

            rows.append({"sport": "ncaaf", "market": "moneyline", "selection": home_team, "home": home_team, "away": away_team, "title": title, "actual": home_score, "odds": market["home_moneyline"], "result": _ml_result(actual_margin)})
            rows.append({"sport": "ncaaf", "market": "moneyline", "selection": away_team, "home": home_team, "away": away_team, "title": title, "actual": away_score, "odds": market["away_moneyline"], "result": _ml_result(-actual_margin)})

            if spread_line is not None:
                def _spread_result(covers_margin: float) -> str:
                    if covers_margin == 0:
                        return "push"
                    return "win" if covers_margin > 0 else "loss"

                rows.append({"sport": "ncaaf", "market": "spread", "selection": home_team, "home": home_team, "away": away_team, "title": title, "line": spread_line, "actual": actual_margin, "odds": -110, "result": _spread_result(actual_margin + spread_line)})
                rows.append({"sport": "ncaaf", "market": "spread", "selection": away_team, "home": home_team, "away": away_team, "title": title, "line": -spread_line, "actual": -actual_margin, "odds": -110, "result": _spread_result(-actual_margin - spread_line)})

            if total_line is not None:
                over_result = "push" if actual_total == total_line else ("win" if actual_total > total_line else "loss")
                under_result = "push" if actual_total == total_line else ("win" if actual_total < total_line else "loss")
                rows.append({"sport": "ncaaf", "market": "total", "selection": "over", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": over_result})
                rows.append({"sport": "ncaaf", "market": "total", "selection": "under", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": under_result})
    return rows


GRADED_OUTCOME_GRADERS: dict[str, GradedRowGrader] = {
    "mlb": _mlb_graded_rows_for_date,
    "wnba": _wnba_graded_rows_for_date,
    "nba": _nba_graded_rows_for_date,
    "nhl": _nhl_graded_rows_for_date,
    "nfl": _nfl_graded_rows_for_date,
    "ncaaf": _ncaaf_graded_rows_for_date,
    "soccer": _soccer_graded_rows_for_date,
    "ncaab": _ncaab_graded_rows_for_date,
}


def graded_rows_for_date(sport: str, date_str: str) -> list[dict[str, Any]]:
    sport_slug = str(sport or "").strip().lower()
    grader = GRADED_OUTCOME_GRADERS.get(sport_slug)
    if grader is None:
        return []
    return grader(date_str)


__all__ = [
    "GRADED_OUTCOME_FIELDS",
    "GRADED_OUTCOME_GRADERS",
    "graded_rows_for_date",
]
