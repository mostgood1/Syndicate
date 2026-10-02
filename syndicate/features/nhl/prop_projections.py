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

PROBABILITY AND EDGE ARE WITHHELD PER MARKET UNTIL MEASURED `[2026-10-02, user
decision: "means now, edges after backtest"]`. The mean and `edge_vs_line` are
display-only (Layer 2 ranks on `edge_vs_market_pct` alone,
`layer2_board.py` "Only `edge_vs_market_pct` qualifies"). A market joins
`MEASURED_MARKETS` only once `scripts/backtest_nhl_props.py` has measured it;
until then its rows carry the mean and a stated reason, and nothing ranks on an
unvalidated claim -- the preseason lineup inference projected Adam Fox at 0.13
shots a game on 2026-10-02, which would have priced a ~90% "edge" on the under.
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

# Market codes whose probability may be published. EMPTY until the backtest measures one.
MEASURED_MARKETS: frozenset[str] = frozenset()
_WITHHELD_REASON = "NHL prop model not yet backtested for this market; probability withheld"

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


def load_nhl_prop_projections(selected_date: str) -> NhlPropProjectionIndex:
    """Read `props_recommendations_<date>.csv`. Missing or header-only -> empty index."""
    from syndicate.features.nhl.sources import processed_path

    index = NhlPropProjectionIndex(date=str(selected_date)[:10])
    path = processed_path("props_recommendations_" + index.date + ".csv")
    index.source_path = str(path)
    try:
        if not path.exists():
            return index
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        _LOGGER.exception("NHL_PROP_PROJECTIONS_READ_FAILED date=%s path=%s", index.date, path)
        return index
    for raw in rows:
        player = _norm(raw.get("player"))
        code = str(raw.get("market") or "").strip().upper()
        try:
            lam = float(raw.get("proj_lambda"))
        except (TypeError, ValueError):
            continue
        if not player or not code or not math.isfinite(lam) or lam < 0:
            continue
        index.by_key.setdefault((player, code), (_norm(raw.get("team")), _norm(raw.get("opp")), lam))
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
    withheld: dict[str, int] = {}
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
            "basis": "sim_mean_poisson",
            "model_prob_over": None,
            "edge_vs_market_pct": None,
            "probability_unavailable_reason": "row has no line to price",
        }
        if line is None or not math.isfinite(line):
            no_line += 1
            projection["edge_unavailable_reason"] = "no probability to price: row has no line"
        else:
            projection["edge_vs_line"] = round(lam - line, 3)
            projection["side"] = "over" if lam > line else "under"
            if code in MEASURED_MARKETS:
                _attach_sim_probability_edge(projection, row=row, model_prob=poisson_p_over(line, lam))
                priced += 1
            else:
                projection["probability_unavailable_reason"] = _WITHHELD_REASON
                projection["edge_unavailable_reason"] = "no probability to price: " + _WITHHELD_REASON
                withheld[code] = withheld.get(code, 0) + 1
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
        "probability_withheld_unmeasured": withheld,
        "pct_projected": round(100.0 * attached / considered, 1) if considered else 0.0,
        "source_artifact": index.source_path,
    }
    if not index.by_key:
        coverage["reason"] = "no NHL hockeysim prop projections for this date (props_recommendations empty or absent)"
    return coverage
