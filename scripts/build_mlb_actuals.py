"""Write props_actuals_{date}.json for MLB -- the reconciliation "actuals"
file format prediction_reconciliation.py's RECONCILIATION_PATTERNS already
recognizes but that nothing in this repo previously wrote for MLB.

For each daily_top_props row on a given date, resolves the player's final
box-score value for that stat (syndicate/features/mlb/box_score_stats.py)
and emits one row keyed the same way a bet logged from the board is: the
same market text _mlb_prop_candidate_from_artifact_row produces
("Pitcher <statLabel>" / bare "<statLabel>"), the player's name as
`selection` (matching how a straight prop bet's `selection` field is
recorded -- see portfolio_bets_api), and the artifact's own market line.
Deliberately never precomputes win/loss itself -- that needs the wagered
side, which this has no reliable way to know; prediction_reconciliation.py's
_row_outcome computes the outcome from actual vs line vs the prediction's
own captured side (features_snapshot.pick).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb.box_score_stats import final_stat_value
from syndicate.features.mlb.box_score_stats import load_final_feed
from syndicate.features.mlb.sources import daily_top_props_path
from syndicate.features.mlb.sources import load_json_file


def _top_props_rows(selected_date: str) -> list[dict[str, Any]]:
    payload = load_json_file(daily_top_props_path(selected_date))
    groups = payload.get("groups") if isinstance(payload, dict) and isinstance(payload.get("groups"), dict) else {}
    rows: list[dict[str, Any]] = []
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        for section in group.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for row in section.get("rows") or []:
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _market_text(row: dict[str, Any]) -> str | None:
    stat_label = str(row.get("statLabel") or "").strip()
    if not stat_label:
        return None
    group = str(row.get("group") or "").strip().lower()
    return f"Pitcher {stat_label}" if group == "pitcher" else stat_label


def build_mlb_actuals_for_date(selected_date: str) -> dict[str, Any]:
    rows = _top_props_rows(selected_date)
    feed_cache: dict[int, dict[str, Any] | None] = {}
    actuals: list[dict[str, Any]] = []
    resolved = 0
    skipped_no_game_pk = 0
    skipped_no_feed = 0
    skipped_no_stat_value = 0

    for row in rows:
        player_name = str(row.get("ownerName") or row.get("playerName") or "").strip()
        market_text = _market_text(row)
        stat = row.get("stat")
        group = row.get("group")
        game_pk = row.get("gamePk") or row.get("game_pk")
        line = row.get("marketLine") if row.get("marketLine") is not None else row.get("line")
        if not player_name or not market_text or not stat or not game_pk:
            skipped_no_game_pk += 1
            continue

        try:
            game_pk_int = int(game_pk)
        except (TypeError, ValueError):
            skipped_no_game_pk += 1
            continue

        if game_pk_int not in feed_cache:
            feed_cache[game_pk_int] = load_final_feed(selected_date, game_pk_int)
        feed = feed_cache[game_pk_int]
        if feed is None:
            skipped_no_feed += 1
            continue

        actual = final_stat_value(feed, group=group, stat=stat, player_name=player_name, player_id=row.get("ownerId"))
        if actual is None:
            skipped_no_stat_value += 1
            continue

        actuals.append(
            {
                "sport": "mlb",
                "market": market_text,
                "player": player_name,
                "selection": player_name,
                "actual": actual,
                "line": line,
            }
        )
        resolved += 1

    return {
        "date": selected_date,
        "rows": actuals,
        "summary": {
            "top_props_rows": len(rows),
            "resolved": resolved,
            "skipped_no_game_pk_or_stat": skipped_no_game_pk,
            "skipped_no_feed": skipped_no_feed,
            "skipped_no_stat_value": skipped_no_stat_value,
        },
    }


_CSV_FIELDNAMES = ("sport", "market", "player", "selection", "actual", "line")


def write_mlb_actuals_for_date(selected_date: str, *, output_root: Path | str) -> dict[str, Any]:
    result = build_mlb_actuals_for_date(selected_date)
    # ".csv", not ".json" -- prediction_reconciliation.py's RECONCILIATION_PATTERNS
    # only recognizes "props_actuals_{date}.csv" (game_results_{date} is the
    # only pattern with a .json variant); a .json file here would silently
    # never be found by the matcher.
    output_path = Path(output_root) / "mlb_source" / "reconciliation" / f"props_actuals_{selected_date}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow({key: row.get(key, "") for key in _CSV_FIELDNAMES})
    return {**result, "output_path": str(output_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write MLB props_actuals_{date}.json for reconciliation")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--output-root", default="", help="Root directory to write under (defaults to data_root())")
    args = parser.parse_args(argv)

    if args.output_root:
        output_root = Path(args.output_root)
    else:
        from syndicate.features.shared.refresh_state_store import data_root

        output_root = data_root()

    result = write_mlb_actuals_for_date(args.date, output_root=output_root)
    print(json.dumps({"date": result["date"], "summary": result["summary"], "output_path": result["output_path"]}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
