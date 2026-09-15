"""Read lane `layer2-row-parity`'s goals off the SERVED board.

    py -3 scripts/verify_layer2_row_parity.py                      # live POST
    py -3 scripts/verify_layer2_row_parity.py --from-file board.json

Sends the same request the board page sends (`slim_aliases`, `drop_row_diagnostics`
-- the unslimmed path is the one that OOMs web) and reports, for the rows a reader
actually sees:

  movement    Layer 2 `not_tracked` rows (goal 0); rows whose displayed odds pair
              straddles even money but whose delta is not the cents move (goal 0);
              steam rows not `same_book` (goal 0); tracked/flat rows without a
              `movement_vs_pick` verdict (goal 0)
  sparkline   rows carrying `movement_series`, and malformed ones (goal 0)
  headshot    MLB / NFL player rows with `headshot_url`, against rows with a player
  explainer   Layer 2 rows with `detail`, against all Layer 2 rows
  legacy      non-Layer-2 prop/game rows on the board (goal 0)

A REPORT, not a gate: it prints counts and exits 0. The lane's verification
names which counts must read what.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.request
from typing import Any

DEFAULT_URL = "https://syndicate-an21.onrender.com/api/intelligence/query"
QUERY = {
    "question": "top edges today",
    "mode": "recommendation",
    "timing": "all",
    "background": False,
    "force_refresh": False,
    "slim_aliases": True,
    "drop_row_diagnostics": True,
}


def _cents(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value >= 100:
        return value - 100
    if value <= -100:
        return value + 100
    return None


def _rows(payload: dict) -> list[dict]:
    body = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    rows = body.get("top_opportunities") or body.get("ranked_all") or []
    return [row for row in rows if isinstance(row, dict)]


def measure(payload: dict) -> dict[str, Any]:
    rows = _rows(payload)
    layer2 = [r for r in rows if r.get("source") == "layer2_shortlist"]
    legacy = [r for r in rows if r.get("source") != "layer2_shortlist" and r.get("candidate_type") in ("prop", "game")]

    states = collections.Counter(str(r.get("movement_state") or "-") for r in layer2)
    crossing_wrong = []
    for r in layer2:
        start, end, delta = r.get("movement_price_from"), r.get("movement_price_to"), r.get("movement_price_delta")
        a, b = _cents(start), _cents(end)
        if a is None or b is None or delta is None:
            continue
        if (float(start) < 0) != (float(end) < 0) and abs(float(delta) - (b - a)) > 0.01:
            crossing_wrong.append((r.get("sport_slug"), r.get("market"), start, end, delta))
    steam = [r for r in layer2 if r.get("steam") is True]
    steam_not_same_book = [r for r in steam if r.get("movement_basis") != "same_book"]
    no_verdict = [r for r in layer2 if r.get("movement_state") in ("tracked", "flat") and not r.get("movement_vs_pick")]

    with_series = [r for r in layer2 if r.get("movement_series")]
    # A LINE THAT SLOPES AGAINST ITS OWN ARROW. Goal 0: after the 2026-09-15
    # redesign the series' ends are the label's price pair, so the two cannot
    # disagree. The first design read 45 of 94 at 18:08:02Z.
    series_vs_arrow_disagree = 0
    series_vs_arrow_judged = 0
    for r in with_series:
        verdict = r.get("movement_vs_pick")
        series = r.get("movement_series")
        if verdict not in ("toward", "away") or not isinstance(series, list) or len(series) < 2:
            continue
        series_vs_arrow_judged += 1
        rising = series[-1][1] > series[0][1]
        if rising != (verdict == "toward"):
            series_vs_arrow_disagree += 1
    malformed = 0
    for r in with_series:
        series = r.get("movement_series")
        ok = (
            isinstance(series, list)
            and len(series) >= 2
            and all(isinstance(p, list) and len(p) == 2 for p in series)
            and all(series[i][0] <= series[i + 1][0] for i in range(len(series) - 1))
            and len({p[1] for p in series}) >= 2
            # The bases the 2026-09-15 redesign emits. "fair"/"price" were the first
            # design's; a row still carrying one was built before it and counts
            # as malformed here on purpose, so a stale shard is visible.
            and r.get("movement_series_basis") in ("same_book", "best_price")
        )
        malformed += 0 if ok else 1

    def faces(sport: str) -> dict[str, int]:
        players = [r for r in layer2 if r.get("sport_slug") == sport and r.get("player_name")]
        return {
            "player_rows": len(players),
            "with_headshot": sum(1 for r in players if r.get("headshot_url")),
            "with_projection": sum(1 for r in players if r.get("projected") is not None),
            "projection_rows_with_headshot": sum(1 for r in players if r.get("projected") is not None and r.get("headshot_url")),
        }

    detail = [r for r in layer2 if str(r.get("detail") or "").strip()]
    return {
        "rows": len(rows),
        "layer2_rows": len(layer2),
        "movement": {
            "states": dict(states),
            "not_tracked": states.get("not_tracked", 0),
            "crossing_delta_not_cents": len(crossing_wrong),
            "crossing_examples": crossing_wrong[:5],
            "steam_rows": len(steam),
            "steam_not_same_book": len(steam_not_same_book),
            "tracked_or_flat_without_vs_pick": len(no_verdict),
            "vs_pick": dict(collections.Counter(str(r.get("movement_vs_pick") or "-") for r in layer2)),
        },
        "sparkline": {
            "rows_with_series": len(with_series),
            "series_vs_arrow_disagree": series_vs_arrow_disagree,
            "series_vs_arrow_judged": series_vs_arrow_judged,
            "malformed": malformed,
            "basis": dict(collections.Counter(str(r.get("movement_series_basis")) for r in with_series)),
        },
        "headshot": {"mlb": faces("mlb"), "nfl": faces("nfl")},
        "explainer": {"layer2_rows_with_detail": len(detail), "layer2_rows": len(layer2)},
        "legacy_prop_game_rows": len(legacy),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--from-file")
    args = parser.parse_args(argv)
    if args.from_file:
        with open(args.from_file, encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        request = urllib.request.Request(
            args.url, data=json.dumps(QUERY).encode("utf-8"), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read())
    print(json.dumps(measure(payload), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
