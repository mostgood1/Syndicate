"""NHL player-prop projections onto board rows (Layer 1 and Layer 2).

THE PRODUCER EXISTED; THE JOIN DID NOT `[2026-10-02, lane nhl-player-props-projection]`.
`scripts/build_nhl_artifacts.py::build_props_for_date` writes
`props_recommendations_<date>.csv` from hockeysim's boxscore engine
(`hockeysim/player_props.py`), but nothing stamped it onto a board row: the NHL
branch of `board_enrichment._attach_projections_by_sport` called the GAME join
only, and that join reported "prop_projections has no NHL branch" for 339 of 339
prop rows on 2026-10-02. (The CSV was also header-only, for a separate reason:
its name join matched 0 lines -- fixed in the producer in the same lane.)

WHAT A ROW GETS. `projected` is the sim's per-game mean (`proj_lambda`) and
`model_prob_over` is P(X > line) under a Poisson with that mean -- the SAME
pricing the producer writes into the CSV's `p_over`, so the board and the
artifact cannot disagree. Pricing from the mean rather than copying `p_over`
means an alternate line the producer never saw is priced by the same rule
instead of being refused. Edge and fair go through the shared
`_attach_sim_probability_edge`, which de-vigs two-sided rows and suppresses the
edge on live rows, exactly as every other sport's prop joins do.

EVERY LINE IS ITS OWN DECISION `[2026-10-02, user decision "Restore, with per-line gates";
supersedes "means now, edges after backtest"]`. Probability and edge are priced on every line,
and a line is refused only on ITS OWN facts, each one measured by `scripts/backtest_nhl_props.py`
(2025-26, as-of inputs):

  * the player has no line slot (or is a goalie the sim does not start) -- the engine gives him
    no ice time, so he projects ~0 (0.001 SOG against 0.86 actual over 4,146 player-games);
  * the game is preseason -- split-squad lineups: 45% of skaters who played were absent from the
    sim lineup and the starting goalie was right 0 of 116 times;
  * the artifact carries no line context (written before the producer recorded it) -- unknown is
    refused, never treated as passing.

There is NO market-level withhold list. The model is still unmeasured-to-worse against a player's
own average in most markets; `projection_skill` stamps that on every row.
"""

from __future__ import annotations

import csv
import logging
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.shared.probability_refusal import refuse_published_certainty
from syndicate.features.shared.timezone import central_date_from_iso

_LOGGER = logging.getLogger(__name__)

SOURCE = "nhl_hockeysim_props"

# Per-line refusal reasons (the board's `edge_unavailable_reason` vocabulary for NHL props).
REFUSE_NO_SLOT = "player has no line slot in the sim lineup (projected ~0 ice time)"
REFUSE_NOT_STARTER = "goalie is not the sim's projected starter"
REFUSE_PRESEASON = "preseason game: sim lineups are unreliable for split-squad rosters"
REFUSE_NO_CONTEXT = "artifact row carries no line context; refused rather than assumed fit"


def line_refusal(context: Mapping[str, Any] | None, code: str) -> str | None:
    """The per-line reason this row may not carry a probability, or None when it may."""
    ctx = context or {}
    game_type = str(ctx.get("game_type") or "").strip().lower()
    if not game_type:
        return REFUSE_NO_CONTEXT
    if game_type == "preseason":
        return REFUSE_PRESEASON
    if code == "SAVES":
        return None if str(ctx.get("sim_starter") or "") == "1" else REFUSE_NOT_STARTER
    return None if str(ctx.get("line_slot") or "").strip() else REFUSE_NO_SLOT

# Board market key (OddsAPI, `_alternate` stripped) -> props_recommendations market code.
_MARKET_CODES = {
    "player_shots_on_goal": "SOG",
    "player_goals": "GOALS",
    "player_assists": "ASSISTS",
    "player_points": "POINTS",
    "player_total_saves": "SAVES",
    "player_blocked_shots": "BLOCKS",
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())


def market_code(market: Any) -> str | None:
    """Accept the NHL grid's own code ("SOG") AND the OddsAPI key ("player_shots_on_goal").

    The book grid stores the CODE -- measured on the fleet's book_grid_2026-10-02.json, all 339
    prop rows read SOG/GOALS/ASSISTS/POINTS -- so a key-only map left every row "unsupported".
    """
    raw = str(market or "").strip()
    if raw.upper() in _MARKET_CODES.values():
        return raw.upper()
    key = raw.lower()
    if key.endswith("_alternate"):
        key = key[: -len("_alternate")]
    return _MARKET_CODES.get(key)


# Goalie SAVES are OVERDISPERSED around the sim mean: variance ~2.2x the mean on 2025-26 (lane
# nhl-saves-overdispersion). Priced by a negative binomial NB(mean = lam, size k), variance lam + lam^2 / k,
# k fit by maximum likelihood on 768 production-form sim-starter goalie-games (props harness, 56 dates).
# H26 (pre-registered, two-fold by date halves, all 881 book lines out of fold): NB - Poisson Brier
# -0.0118 [-0.0161, -0.0076]. Every other market keeps Poisson.
SAVES_NB_K = 16.367


def nb_p_over(line: float, mean: float, k: float) -> float:
    """P(X > line), X ~ NB(mean, size k). An integer line's push mass counts as not-over (as Poisson)."""
    mu = max(1e-9, float(mean))
    upto = math.floor(float(line))
    log_p = k * math.log(k / (k + mu))       # pmf(0)
    ratio = mu / (k + mu)
    term = math.exp(log_p)
    cdf = 0.0
    for i in range(upto + 1):
        if i:
            term *= (i - 1 + k) / i * ratio
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def price_p_over(market_code: str, line: float, lam: float) -> float:
    """Production's P(over) for one NHL prop line: NB for SAVES, Poisson for every other market."""
    if str(market_code or "").upper() == "SAVES":
        return nb_p_over(line, lam, SAVES_NB_K)
    return poisson_p_over(line, lam)


def pricing_basis(market_code: str) -> str:
    return "sim_mean_negbin" if str(market_code or "").upper() == "SAVES" else "sim_mean_poisson"


def poisson_p_over(line: float, lam: float) -> float:
    """P(X > line), X ~ Poisson(lam). An integer line's push mass counts as not-over."""
    lam = max(0.0, float(lam))
    k = math.floor(float(line)) + 1
    term = math.exp(-lam)
    cdf = 0.0
    for i in range(k):
        if i:
            term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


@dataclass
class NhlPropProjectionIndex:
    date: str
    source_path: str = ""
    # (player, market code) -> (team, opp, lambda)
    by_key: dict[tuple[str, str], tuple[str, str, float]] = field(default_factory=dict)
    # (player, market code) -> line context written by the producer (line_slot, sim_starter, game_type)
    context: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    # pairs filled from the all-markets file (absent from props_recommendations)
    from_all_markets: int = 0

    @property
    def players(self) -> int:
        return len({player for player, _ in self.by_key})

    def lookup(self, player: Any, code: str, teams: set[str]) -> float | None:
        hit = self.by_key.get((_norm(player), code))
        if hit is None:
            return None
        team, opp, lam = hit
        # A same-named player in ANOTHER game must not price this row.
        if teams and not ({team, opp} & teams):
            return None
        return lam


def _read_projection_rows(path: Any) -> list[dict[str, str]] | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        _LOGGER.exception("NHL_PROP_PROJECTIONS_READ_FAILED path=%s", path)
        return None


def load_nhl_prop_projections(selected_date: str) -> NhlPropProjectionIndex:
    """Read `props_recommendations_<date>.csv`, then fill from `props_recommendations_all_markets_<date>.csv`.

    The first file holds only the (player, market) pairs the producer had a current line for; the
    second holds EVERY projected player x market (lane nhl-player-props-projection, 2026-10-03:
    166 of 232 unprojected board rows were projected players missing just that pair). A pair in
    both keeps the first file's row. Missing or header-only files -> an empty index.
    """
    from syndicate.features.nhl.sources import processed_path

    index = NhlPropProjectionIndex(date=str(selected_date)[:10])
    primary = processed_path("props_recommendations_" + index.date + ".csv")
    fallback = processed_path("props_recommendations_all_markets_" + index.date + ".csv")
    index.source_path = str(primary)
    for path in (primary, fallback):
        rows = _read_projection_rows(path)
        if rows is None:
            continue
        for raw in rows:
            player = _norm(raw.get("player"))
            code = str(raw.get("market") or "").strip().upper()
            try:
                lam = float(raw.get("proj_lambda"))
            except (TypeError, ValueError):
                continue
            if not player or not code or not math.isfinite(lam) or lam < 0:
                continue
            if (player, code) not in index.by_key:
                index.by_key[(player, code)] = (_norm(raw.get("team")), _norm(raw.get("opp")), lam)
                index.context[(player, code)] = {
                    k: str(raw.get(k) or "") for k in ("line_slot", "proj_toi", "sim_starter", "game_type")
                }
                if path is fallback:
                    index.from_all_markets += 1
    return index


def attach_nhl_prop_projections(
    grid: Iterable[Mapping[str, Any]],
    index: NhlPropProjectionIndex,
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Stamp `projection` onto NHL player-prop rows. Returns prop coverage.

    Date-scoped on the row's CENTRAL kickoff date, like the NHL game join, so the
    denominator covers the same slate the artifact does.
    """
    from syndicate.features.shared.wnba_game_projections import _attach_sim_probability_edge

    considered = 0
    attached = 0
    unsupported_market = 0
    unmatched = 0
    no_line = 0
    priced = 0
    refused: dict[str, int] = {}
    for row in grid:
        if str(row.get("kind") or "") != "prop":
            continue
        if selected_date:
            row_day = central_date_from_iso(row.get("commence_time"))
            if row_day is not None and row_day.isoformat() != str(selected_date)[:10]:
                continue
        considered += 1
        code = market_code(row.get("market"))
        if code is None:
            unsupported_market += 1
            continue
        teams = {t for t in (_norm(row.get("home_team")), _norm(row.get("away_team"))) if t}
        lam = index.lookup(row.get("player_name"), code, teams)
        if lam is None:
            unmatched += 1
            continue
        try:
            line = float(row.get("line"))
        except (TypeError, ValueError):
            line = None
        projection: dict[str, Any] = {
            "projected": round(lam, 3),
            "source": SOURCE,
            "basis": pricing_basis(code),
            "model_prob_over": None,
            "edge_vs_market_pct": None,
            "probability_unavailable_reason": "row has no line to price",
        }
        if line is None or not math.isfinite(line):
            no_line += 1
            projection["edge_unavailable_reason"] = "no probability to price: row has no line"
        else:
            projection["edge_vs_line"] = round(lam - line, 3)
            # `side` NAMES THE FRAMING OF `model_prob_over`, never the model's lean
            # `[2026-10-08, user: "fix all three sports", lane layer2-board-ui-redesign]`.
            # Every reader (`layer2_board._model_prob_for_side` / `_model_edge_for`,
            # `board_enrichment`, the Ask adapter) complements the probability when
            # this differs from the row's side. Writing the LEAN here ("under" when
            # the mean is below the line) told them an OVER probability was an UNDER
            # one, so every under-leaning prop shipped P(under) and a sign-flipped
            # edge on its OVER row. Measured on the served board 2026-10-08 15:47Z:
            # 297 of 520 NHL prop rows (Gage Goncalves o0.5 assists showed 76.4%,
            # the sim's own P(over) 23.6%) and 7 WNBA rows, 273 tagged "sim agrees".
            # The lean is kept, under its own name.
            projection["side"] = "over"
            projection["lean"] = "over" if lam > line else "under"
            refusal = line_refusal(index.context.get((_norm(row.get("player_name")), code)), code)
            if refusal is None:
                _attach_sim_probability_edge(projection, row=row, model_prob=price_p_over(code, line, lam))
                # Display ladder for the board's sim-spread chart (lane layer2-board-ui-redesign).
                from syndicate.features.shared.price_ladder import price_ladder

                projection["ladder"] = price_ladder(lambda t, _c=code, _l=lam: price_p_over(_c, t, _l), line)
                priced += 1
            else:
                projection["probability_unavailable_reason"] = refusal
                projection["edge_unavailable_reason"] = "no probability to price: " + refusal
                refused[refusal] = refused.get(refusal, 0) + 1
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1

    coverage: dict[str, Any] = {
        "supported": True,
        "players_in_source": index.players,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "unsupported_market_rows": unsupported_market,
        "unmatched_player_rows": unmatched,
        "rows_without_line": no_line,
        "rows_with_probability": priced,
        "probability_refused_by_line": refused,
        "pct_projected": round(100.0 * attached / considered, 1) if considered else 0.0,
        "source_artifact": index.source_path,
        "pairs_from_all_markets_file": index.from_all_markets,
    }
    if not index.by_key:
        coverage["reason"] = "no NHL hockeysim prop projections for this date (props_recommendations empty or absent)"
    return coverage
