"""Pull graded MLB rows for the `#202` edge scan -- input to `run_mlb_edge_scan.py`.

Run this first, then the scan. Substrate is PRODUCTION
(`/api/ops/artifacts/export`), never the local `data/**` mirror.

MEASURED 2026-09-01 and the reason the scan reports most hypotheses as NOT
RUNNABLE: the mechanism fields below (`park_hr_mult`, platoon and pitch-mix
multipliers, `pitcher_k_rate`) survive on only **534 of 9,479 graded rows --
two dates of fifty-one**. They are requested here anyway so that the coverage
is MEASURED on every run rather than assumed.

Substrate: Render. Provenance (artifact root) recorded per row, per #617.
Adds to the earlier pull: park/platoon/pitch-mix multipliers, pitcher and batter
K rates, and the game-market (ml) rows H7 needs.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://syndicate-an21.onrender.com"
OUT = Path(__file__).resolve().parents[1] / "reports" / "edge_scan" / "scan_rows.jsonl"
PROP_KEYS = ("hitterProps", "extraHitterProps", "pitcherProps", "extraPitcherProps")
GAME_KEYS = ("ml", "totals")

KEEP = (
    "prop", "market", "market_line", "selection", "recommendation_tier", "odds",
    "model_prob_over", "market_prob_over", "market_no_vig_prob_over",
    "park_hr_mult", "park_inplay_hit_mult", "park_source",
    "batter_platoon_hr_mult", "batter_platoon_k_mult",
    "pitcher_platoon_hr_mult", "pitcher_platoon_k_mult",
    "pitcher_primary_pitch_type_hr_mult", "opponent_primary_pitch_type",
    "pitcher_k_rate", "batter_k_rate", "batter_hr_rate", "pitcher_hr_rate",
    "pa_mean", "ab_mean", "lineup_order", "batter_hand", "opponent_pitcher_hand",
    "player_name", "team", "opponent", "sim_sample_size",
)


def _token() -> str:
    for line in Path("C:/Users/tempadmin/OneDrive/Coding/Syndicate/.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ADMIN_TOKEN")


TOKEN = _token()


def _get(params: dict) -> dict:
    url = f"{BASE}/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Admin-Token": TOKEN})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=240) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return {}
            time.sleep(5)
    return {}


def main() -> int:
    names = sorted((_get({"pattern": "*betting_day_payloads_retuned/season_betting_day_*.json",
                          "names_only": "1"}).get("artifacts") or {}))
    print(f"artifacts: {len(names)}", flush=True)
    written = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for index, name in enumerate(names, start=1):
            root = "source_artifacts" if "/source_artifacts/" in name else "data"
            match = re.search(r"season_betting_day_(\d{4}_\d{2}_\d{2})\.json", name)
            date = (match.group(1) if match else "?").replace("_", "-")
            payload = _get({"pattern": name})
            artifacts = payload.get("artifacts") or {}
            doc = artifacts.get(name) or (next(iter(artifacts.values())) if artifacts else None)
            if isinstance(doc, str):
                try:
                    doc = json.loads(doc)
                except Exception:
                    doc = None
            games = (doc or {}).get("games") if isinstance(doc, dict) else None
            if not isinstance(games, dict):
                print(f"[{index}/{len(names)}] {date}: no games", flush=True)
                continue
            before = written
            for game_pk, game in games.items():
                if not isinstance(game, dict):
                    continue
                markets = game.get("markets")
                if not isinstance(markets, dict):
                    continue
                # Team-level K context for H2: mean batter K rate in this game's
                # hitter entries, which is the closest observable to "opposing
                # lineup avg K-rate" the artifact carries.
                k_rates = [
                    float(entry["batter_k_rate"])
                    for key in ("hitterProps", "extraHitterProps")
                    for entry in (markets.get(key) or [])
                    if isinstance(entry, dict) and isinstance(entry.get("batter_k_rate"), (int, float))
                ]
                lineup_k = sum(k_rates) / len(k_rates) if k_rates else None
                for bucket in PROP_KEYS + GAME_KEYS:
                    entries = markets.get(bucket)
                    if isinstance(entries, dict):
                        entries = [entries]
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        settlement = entry.get("settlement")
                        if not isinstance(settlement, dict):
                            continue
                        result = str(settlement.get("result") or "").strip().lower()
                        if result not in {"win", "loss"}:
                            continue
                        row = {"root": root, "date": date, "game_pk": game_pk,
                               "bucket": bucket, "result": result,
                               "actual": settlement.get("actual"),
                               "profit_u": settlement.get("profit_u"),
                               "stake_u": settlement.get("stake_u"),
                               "lineup_k_rate": lineup_k}
                        for field in KEEP:
                            if field in entry:
                                row[field] = entry[field]
                        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                        written += 1
            print(f"[{index}/{len(names)}] {date}: +{written - before} (total {written})", flush=True)
    print(f"\nDONE rows={written} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
