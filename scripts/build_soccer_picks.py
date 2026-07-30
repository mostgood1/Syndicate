"""Join a soccer league/date's simulated match output against captured
game odds (see fetch_soccer_oddsapi_odds_local.py) and write an EV/edge
picks CSV, the soccer equivalent of NBA's recommendations_{date}.csv (see
syndicate/features/nba/betting_recap.py's consumption of that shape).

Unlike recommendations_{date}.json (build_soccer_artifacts.py's raw sim
output -- what cards.py reads), this is written to a separate
api/picks/picks_{date}.csv path: it's a distinct artifact (picks compared
against a real captured market line), not the sim payload itself.

Markets covered: h2h (3-way moneyline), totals (only when the market's
posted line matches exactly what the sim projects a probability for --
2.5 -- rather than guessing at other lines), spreads (Asian-handicap-style,
graded via the sim's own scoreline_probabilities distribution rather than a
single point estimate). BTTS is not covered: confirmed unavailable from the
Odds API at the current plan/region (HTTP 422 as of 2026-07-21).

Player props: anytime-goalscorer only (market="PROP", side="anytime_scorer")
-- the one player-prop market build_soccer_artifacts.py's sim already
outputs as a ready-made 0-1 probability (anytime_scorer_probability).
Shots/shots-on-target are captured as EXPECTED COUNTS, not a probability of
clearing a specific line, and grading those against a real line would
require a new distributional model, not a data join -- out of scope here,
see #150's todo.md entry.

Usage:
    python scripts/build_soccer_picks.py --league mls --date 2026-07-22
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import unicodedata
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.atomic_artifact_write import atomic_write_csv


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and value != value) or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _american_to_implied_prob(price: float) -> float | None:
    try:
        price = float(price)
    except Exception:
        return None
    if price > 0:
        return 100.0 / (price + 100.0)
    if price < 0:
        return -price / (-price + 100.0)
    return None


def _american_to_decimal(price: float) -> float | None:
    try:
        price = float(price)
    except Exception:
        return None
    if price > 0:
        return price / 100.0 + 1.0
    if price < 0:
        return 100.0 / -price + 1.0
    return None


def _devig(probs: dict[str, float]) -> dict[str, float]:
    total = sum(value for value in probs.values() if value is not None)
    if total <= 0:
        return probs
    return {key: (value / total if value is not None else None) for key, value in probs.items()}


def _representative_price(prices: list[float]) -> float | None:
    # Median across books: robust to one outlier book without needing a
    # "preferred book" ranking decision here (fetch_soccer_oddsapi_odds_local.py
    # already orders preferred books first in the source CSV, but median is a
    # more honest single number to grade a pick against than "whichever book
    # happened to sort first").
    cleaned = [price for price in prices if price is not None]
    if not cleaned:
        return None
    return statistics.median(cleaned)


def _parse_scoreline_key(key: str) -> tuple[int, int] | None:
    try:
        home_text, away_text = str(key).split("-", 1)
        return int(home_text), int(away_text)
    except Exception:
        return None


def _spread_cover_probability(scoreline_probabilities: dict[str, float], *, is_home_side: bool, line: float) -> float | None:
    if not scoreline_probabilities:
        return None
    total = 0.0
    for key, prob in scoreline_probabilities.items():
        parsed = _parse_scoreline_key(key)
        if parsed is None:
            continue
        home_score, away_score = parsed
        margin = float(home_score - away_score)
        side_margin = margin if is_home_side else -margin
        if side_margin + float(line) > 0:
            total += float(prob)
    return total


def _ev(model_prob: float | None, price: float | None) -> float | None:
    if model_prob is None or price is None:
        return None
    decimal = _american_to_decimal(price)
    if decimal is None:
        return None
    return round(model_prob * decimal - 1.0, 4)


def build_picks(league: str, iso_date: str, *, source_root: Path, out_root: Path) -> pd.DataFrame:
    rec_path = source_root / league / "api" / "recommendations" / f"recommendations_{iso_date}.json"
    # Not date-scoped: fetch_soccer_oddsapi_odds_local.py's bulk /odds call
    # returns every upcoming event for the whole league in one request
    # (spanning multiple dates), so it's fetched/written once per league per
    # tick rather than once per date -- this reads whichever of that
    # league's currently-posted events cover iso_date's matches, matched by
    # team name below, same as build_soccer_artifacts.py --week loops over
    # every date in a matchweek from one schedule fetch.
    odds_path = source_root / league / "api" / "odds" / "game_odds_current.csv"
    if not rec_path.exists() or not odds_path.exists():
        return pd.DataFrame()

    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not matches:
        return pd.DataFrame()
    odds_df = pd.read_csv(odds_path)
    if odds_df.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for match in matches:
        matchup = match.get("matchup") or {}
        home_team = str(matchup.get("home_team") or "").strip()
        away_team = str(matchup.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        event_odds = odds_df[(odds_df["home_team"] == home_team) & (odds_df["away_team"] == away_team)]
        if event_odds.empty:
            continue
        event_id = str(event_odds["event_id"].iloc[0])
        win_prob = match.get("win_probability") or {}
        total_dist = match.get("total_distribution") or {}
        scoreline_probs = match.get("scoreline_probabilities") or {}

        # h2h: devig the 3-way market (per book median first, then devig the
        # medians) and grade model probability against it.
        h2h = event_odds[event_odds["market"] == "h2h"]
        if not h2h.empty:
            side_prices = {
                "home": _representative_price(h2h[h2h["side"] == home_team]["price"].tolist()),
                "away": _representative_price(h2h[h2h["side"] == away_team]["price"].tolist()),
                "draw": _representative_price(h2h[h2h["side"] == "Draw"]["price"].tolist()),
            }
            implied = {key: _american_to_implied_prob(price) for key, price in side_prices.items()}
            devigged = _devig(implied)
            model_probs = {"home": win_prob.get("home"), "away": win_prob.get("away"), "draw": win_prob.get("draw")}
            for side, model_prob in model_probs.items():
                price = side_prices.get(side)
                if price is None or model_prob is None:
                    continue
                market_prob = devigged.get(side)
                rows.append(
                    {
                        "league": league, "date": iso_date, "event_id": event_id,
                        "home": home_team, "away": away_team,
                        "market": "ML", "side": side, "line": None, "price": price,
                        "model_probability": round(float(model_prob), 4),
                        "market_probability": round(market_prob, 4) if market_prob is not None else None,
                        "edge": round(float(model_prob) - market_prob, 4) if market_prob is not None else None,
                        "ev": _ev(model_prob, price),
                    }
                )

        # totals: only grade the line(s) that are exactly 2.5 -- the only
        # line the sim produces a probability for (over_2_5_probability).
        # A market posting 3.0 (or any other line) for every book on a given
        # event is skipped rather than guessed at.
        totals = event_odds[event_odds["market"] == "totals"]
        over_prob = total_dist.get("over_2_5_probability")
        if not totals.empty and over_prob is not None:
            for side, model_prob in (("over", over_prob), ("under", (1.0 - over_prob) if over_prob is not None else None)):
                side_rows = totals[(totals["side"].str.lower() == side) & (totals["line"] == 2.5)]
                price = _representative_price(side_rows["price"].tolist())
                if price is None or model_prob is None:
                    continue
                market_prob = _american_to_implied_prob(price)
                rows.append(
                    {
                        "league": league, "date": iso_date, "event_id": event_id,
                        "home": home_team, "away": away_team,
                        "market": "TOTAL", "side": side, "line": 2.5, "price": price,
                        "model_probability": round(float(model_prob), 4),
                        "market_probability": round(market_prob, 4) if market_prob is not None else None,
                        "edge": round(float(model_prob) - market_prob, 4) if market_prob is not None else None,
                        "ev": _ev(model_prob, price),
                    }
                )

        # spreads: graded via the sim's own scoreline distribution (a point
        # margin estimate alone can't answer "P(cover this specific line)").
        spreads = event_odds[event_odds["market"] == "spreads"]
        if not spreads.empty and scoreline_probs:
            for side, team_name, is_home in (("home", home_team, True), ("away", away_team, False)):
                side_rows = spreads[spreads["side"] == team_name]
                for _, row in side_rows.iterrows():
                    line = row.get("line")
                    price = row.get("price")
                    if pd.isna(line) or pd.isna(price):
                        continue
                    model_prob = _spread_cover_probability(scoreline_probs, is_home_side=is_home, line=float(line))
                    if model_prob is None:
                        continue
                    market_prob = _american_to_implied_prob(price)
                    rows.append(
                        {
                            "league": league, "date": iso_date, "event_id": event_id,
                            "home": home_team, "away": away_team,
                            "market": "SPREAD", "side": side, "line": float(line), "price": price,
                            "model_probability": round(model_prob, 4),
                            "market_probability": round(market_prob, 4) if market_prob is not None else None,
                            "edge": round(model_prob - market_prob, 4) if market_prob is not None else None,
                            "ev": _ev(model_prob, price),
                        }
                    )

    return pd.DataFrame(rows)


def _normalize_player_name(value: Any) -> str:
    # Same accent/diacritic-stripping join key
    # syndicate/features/soccer/market_board.py's _normalize_soccer_name
    # uses for this exact problem (sim player names come from American
    # Soccer Analysis, a different provider than the Odds API props feed,
    # e.g. "Kevin Denkey" vs "Kévin Denkey") -- duplicated rather than
    # imported to keep this script's existing no-syndicate.features.soccer
    # dependency style (it already re-derives its own
    # _american_to_implied_prob/_devig rather than importing sources.py).
    text = " ".join(str(value or "").strip().lower().split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _props_rows_near_date(
    league: str, iso_date: str, *, source_root: Path, lookback_days: int = 3, lookahead_days: int = 10
) -> list[dict[str, Any]]:
    # fetch_soccer_oddsapi_props_local.py files its capture under the day it
    # RAN, not each event's own date (a single call returns every upcoming
    # event for the league) -- same reasoning as game_odds_current.csv being
    # a single rolling file rather than per-date, just per-date-filed
    # instead of overwritten. A pregame sweep for iso_date may have last
    # captured props on a nearby day, so this scans a bounded window rather
    # than requiring an exact iso_date match. Window matches
    # market_board.py's own _soccer_relevant_dates (±3/+10 days).
    try:
        base = date_cls.fromisoformat(iso_date)
    except ValueError:
        return []
    rows: list[dict[str, Any]] = []
    for offset in range(-lookback_days, lookahead_days + 1):
        path = source_root / league / "props" / f"{(base + timedelta(days=offset)).isoformat()}.csv"
        if not path.exists():
            continue
        try:
            rows.extend(pd.read_csv(path).to_dict("records"))
        except Exception:
            continue
    return rows


def build_prop_picks(league: str, iso_date: str, *, source_root: Path) -> pd.DataFrame:
    """Grade the sim's anytime-goalscorer probability against a real
    captured price, the player-prop analog of build_picks' game markets
    above. See this module's docstring for why only this one market.
    """
    rec_path = source_root / league / "api" / "recommendations" / f"recommendations_{iso_date}.json"
    if not rec_path.exists():
        return pd.DataFrame()
    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    player_props = payload.get("player_props") if isinstance(payload, dict) else None
    if not player_props:
        return pd.DataFrame()

    props_rows_all = _props_rows_near_date(league, iso_date, source_root=source_root)
    if not props_rows_all:
        return pd.DataFrame()

    # Odds API's anytime-goalscorer market is a single "yes" price per
    # player (no paired "no" side to devig against), so this grades the raw
    # implied probability -- an honest, simpler number than a fabricated
    # devig, not a shortcut around one that exists.
    odds_by_key: dict[tuple[str, str, str], float] = {}
    for row in props_rows_all:
        if str(row.get("market_key") or "").strip() != "player_goal_scorer_anytime":
            continue
        player_key = _normalize_player_name(row.get("player"))
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        price = _safe_float(row.get("over_price"))
        if not player_key or not (home or away) or price is None:
            continue
        key = (player_key, home, away)
        # Multiple books may quote this player; fetch_soccer_oddsapi_props_
        # local.py already orders preferred books first in the raw feed, and
        # _props_rows_near_date reads files oldest-offset-first, so the
        # first-seen price per key is the most representative single one to
        # grade against, same convention build_picks' own book-price
        # selection already uses.
        odds_by_key.setdefault(key, price)

    rows: list[dict[str, Any]] = []
    for prop_row in player_props:
        if not isinstance(prop_row, dict):
            continue
        model_prob = _safe_float(prop_row.get("anytime_scorer_probability"))
        player_name = str(prop_row.get("player_name") or "").strip()
        team = str(prop_row.get("team") or "").strip()
        if model_prob is None or not player_name or not team:
            continue
        player_key = _normalize_player_name(player_name)
        price = next(
            (odds_price for (odds_player, home, away), odds_price in odds_by_key.items() if odds_player == player_key and team in (home, away)),
            None,
        )
        if price is None:
            continue
        market_prob = _american_to_implied_prob(price)
        rows.append(
            {
                "league": league, "date": iso_date,
                "player": player_name, "team": team,
                "market": "PROP", "side": "anytime_scorer", "line": None, "price": price,
                "model_probability": round(model_prob, 4),
                "market_probability": round(market_prob, 4) if market_prob is not None else None,
                "edge": round(model_prob - market_prob, 4) if market_prob is not None else None,
                "ev": _ev(model_prob, price),
            }
        )
    # TEMP DIAGNOSTIC (#151 investigation, remove after root cause found).
    print(
        f"[build_soccer_picks] SOCCER_PROP_PICKS_BUILD_DEBUG_151 league={league} date={iso_date} "
        f"player_props_in={len(player_props)} props_rows_all={len(props_rows_all)} odds_by_key={len(odds_by_key)} "
        f"matched_rows={len(rows)} sample_odds_keys={list(odds_by_key)[:3]}",
        flush=True,
    )
    return pd.DataFrame(rows)


def _write_picks_for_date(league: str, iso_date: str, *, source_root: Path, out_root: Path) -> int:
    game_df = build_picks(league, iso_date, source_root=source_root, out_root=out_root)
    prop_df = build_prop_picks(league, iso_date, source_root=source_root)
    df = pd.concat([game_df, prop_df], ignore_index=True) if not prop_df.empty else game_df
    out_path = out_root / league / "api" / "picks" / f"picks_{iso_date}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(out_path, df)
    print(f"wrote {len(df)} picks ({len(game_df)} game, {len(prop_df)} prop) to {out_path}")
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True)
    parser.add_argument("--date", default=None, help="ISO date, default today")
    parser.add_argument("--week", type=int, default=None, help="Matchweek number (requires --season); loops over every date the schedule artifact lists for that week, same as build_soccer_artifacts.py --week")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()

    if args.week is not None:
        from syndicate.features.soccer.sources import default_season
        from syndicate.features.soccer.sources import week_date_list

        season = args.season or default_season(args.league)
        dates = week_date_list(args.league, season, args.week)
        if not dates:
            raise SystemExit(
                f"no dates found for {args.league} week {args.week} season {season}; "
                f"run scripts/build_soccer_schedule.py --league {args.league} --season {season} first"
            )
        for iso_date in dates:
            _write_picks_for_date(args.league, iso_date, source_root=Path(args.source_root), out_root=Path(args.out_root))
        return 0

    iso_date = args.date or date_cls.today().isoformat()
    _write_picks_for_date(args.league, iso_date, source_root=Path(args.source_root), out_root=Path(args.out_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
