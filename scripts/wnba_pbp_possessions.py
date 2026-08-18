"""Extract WNBA possession/pace series from the pbp snapshot family.

`#454`, first concrete step. Lane `game-shape-capture` (scope addition).

WHAT THIS IS FOR. `game_shape.py` refuses to publish possession pace for
basketball because the card-context payload has no box stats. Possessions do
exist, in a different family: `live_pbp_stats_<date>.jsonl` carries
`pbp_possessions` with a real `poss_est` (`FGA + TOV + 0.44*FTA - OREB`,
`vendor/wnba_betting_repo/app.py:3572`). This reads that family and produces the
per-game series a model could actually be fitted on.

**IT LEADS WITH THE DENOMINATOR AND REFUSES BELOW A FLOOR.** That is the whole
design, not a courtesy. Measured on the tracked mirror 2026-08-16: 120 game
records, **17** with possession data, on **2** dates, and several of those 17
carry PLACEHOLDER game ids (`0000000001`, `0000000002`). A tool that printed a
mean pace off that would produce an authoritative-looking number resting on
roughly one real game -- `#377`'s failure exactly. So `--min-games` is enforced
and the refusal names the shortfall.

THREE TRAPS THIS ENCODES, each measured rather than anticipated:

1. **`pbp_possessions["home"]` and `["away"]` are 0.0 on EVERY populated
   record.** The real data is keyed by TEAM TRICODE. The existing consumer
   (`app.py:45316`) resolves tricode first, so this is a trap for new code
   rather than an active bug -- a reader that goes straight to `home`/`away`
   gets a plausible-looking zero rather than an obvious miss. This module
   resolves by tricode and COUNTS how often it had to fall back, so the trap
   shows up as a number instead of as silence.

2. **Placeholder game ids are present and must be excluded.** `0000000001`
   upward are fixtures, not games. Counting them inflates n, which is the one
   quantity this tool exists to state honestly.

3. **The checkout is a lossy mirror.** CLAUDE.md's standing rule: never scope a
   backtest from it. Every output here is labelled with the root it read, and
   the coverage block is designed to be re-run against a production mirror
   without changing the code.

NOT DONE HERE, deliberately: no model, no fit, no calibration. This produces the
series and its denominator. Fitting anything on the current mirror would be
fitting on ~1 game.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Keys that exist on the record but are structurally zero -- see trap 1.
_NON_TEAM_KEYS = frozenset({"home", "away", "total", "unknown", "UNKNOWN"})

# A real WNBA event id is a 9-digit ESPN id (e.g. 401856947) or a "AAA@BBB"
# slug. Fixtures count up from 1 and are zero-padded.
_PLACEHOLDER_MAX = 100_000


def _is_placeholder_game_id(game_id: Any) -> bool:
    text = str(game_id or "").strip()
    if not text:
        return True
    if not text.isdigit():
        # "SEA@TOR" and similar slugs are real.
        return False
    try:
        return int(text) < _PLACEHOLDER_MAX
    except ValueError:
        return True


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def team_possessions(pbp_possessions: Any) -> dict[str, dict[str, Any]]:
    """Possession blocks keyed by TEAM TRICODE only.

    Drops `home`/`away`/`total`/`unknown` -- see trap 1. Returning them would
    hand a caller two zero-valued teams alongside the real ones.
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(pbp_possessions, Mapping):
        return out
    for key, block in pbp_possessions.items():
        if key in _NON_TEAM_KEYS or not isinstance(block, Mapping):
            continue
        poss = _as_float(block.get("poss_est"))
        if poss is None or poss <= 0:
            continue
        out[str(key)] = {
            "poss_est": poss,
            "tov": _as_float(block.get("tov")),
            "oreb": _as_float(block.get("oreb")),
            "dreb": _as_float(block.get("dreb")),
        }
    return out


def quarters_complete(pbp_quarters: Any) -> bool:
    """Did this snapshot reach the end of regulation?

    **This was missing from the first version and the omission produced a wrong
    answer, which is why it is now a named function with its own test.** The
    snapshots are LIVE and most are mid-game: measured on the mirror, a
    `pace_per_team` of **2.5** (CHI@DAL, one quarter played) and **27.18**
    (CON@TOR, halftime) sat in the output next to real ~75-possession games.
    Pace is possessions per team per FULL game; on a partial snapshot the same
    arithmetic produces a number that is not a pace at all, just a running
    count. Averaging those together is meaningless.

    `q_totals` carries `q1..q4`; all four non-null means regulation is done.
    Overtime games simply carry more elsewhere -- this is a floor, not a
    claim of exactness.
    """
    if not isinstance(pbp_quarters, Mapping):
        return False
    totals = pbp_quarters.get("q_totals")
    if not isinstance(totals, Mapping):
        return False
    return all(totals.get(f"q{n}") is not None for n in (1, 2, 3, 4))


def game_row(game: Any, *, date: str) -> dict[str, Any] | None:
    """One row per snapshot, ANNOTATED. Exclusion is the caller's decision.

    Returns the row with `placeholder` and `complete` on it rather than
    filtering here, so `scan` can COUNT each exclusion reason instead of
    silently dropping records -- a coverage tool that hides why it dropped
    something reads as full coverage.
    """
    if not isinstance(game, Mapping):
        return None
    game_id = game.get("game_id") or game.get("event_id")
    teams = team_possessions(game.get("pbp_possessions"))
    # Two-team games only; anything else means the record is malformed and a
    # "pace" off it would not mean what it says.
    if len(teams) != 2:
        return None
    (a_tri, a), (b_tri, b) = sorted(teams.items())
    total = a["poss_est"] + b["poss_est"]
    return {
        "date": date,
        "game_id": str(game_id or ""),
        "placeholder": _is_placeholder_game_id(game_id),
        "complete": quarters_complete(game.get("pbp_quarters")),
        "period": ((game.get("pbp_quarters") or {}).get("current") or {}).get("period"),
        "teams": [a_tri, b_tri],
        f"poss_{a_tri}": round(a["poss_est"], 2),
        f"poss_{b_tri}": round(b["poss_est"], 2),
        "total_possessions": round(total, 2),
        # Possessions per team per full game. Only meaningful when `complete`.
        "pace_per_team": round(total / 2.0, 2),
        "tov_total": (a["tov"] or 0) + (b["tov"] or 0),
        "oreb_total": (a["oreb"] or 0) + (b["oreb"] or 0),
    }


def scan(roots: list[Path]) -> dict[str, Any]:
    """Read every pbp snapshot under `roots`. Returns rows plus the coverage."""
    coverage = {
        "roots": [str(r) for r in roots],
        "files": 0,
        "game_records": 0,
        "with_possessions": 0,
        "placeholder_excluded": 0,
        "partial_excluded": 0,
        "duplicate_snapshots_collapsed": 0,
        "home_away_keys_zero": 0,
        "dates_seen": set(),
        "dates_with_possessions": set(),
    }
    rows: list[dict[str, Any]] = []
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("live_pbp_stats_*.jsonl")))
    for path in files:
        coverage["files"] += 1
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            payload = record.get("payload") if isinstance(record, Mapping) else None
            if not isinstance(payload, Mapping):
                continue
            date = str(payload.get("date") or "")
            coverage["dates_seen"].add(date)
            for game in payload.get("games") or []:
                coverage["game_records"] += 1
                if isinstance(game, Mapping):
                    poss_obj = game.get("pbp_possessions")
                    if isinstance(poss_obj, Mapping):
                        # Count the trap explicitly rather than let it be silent.
                        ha = [poss_obj.get("home"), poss_obj.get("away")]
                        if any(isinstance(b, Mapping) for b in ha) and not any(
                            _as_float((b or {}).get("poss_est")) for b in ha if isinstance(b, Mapping)
                        ):
                            if team_possessions(poss_obj):
                                coverage["home_away_keys_zero"] += 1
                row = game_row(game, date=date)
                if row is None:
                    continue
                coverage["with_possessions"] += 1
                coverage["dates_with_possessions"].add(date)
                if row["placeholder"]:
                    coverage["placeholder_excluded"] += 1
                    continue
                if not row["complete"]:
                    coverage["partial_excluded"] += 1
                    continue
                rows.append(row)

    # DEDUPLICATE. The snapshots are periodic, so the same game appears once
    # per tick that was mirrored -- measured: SEA@TOR and CON@TOR each appeared
    # TWICE with byte-identical totals. Counting those as two games inflates
    # exactly the denominator this tool exists to state honestly. Keyed by
    # (game_id, teams); the highest total wins, since possessions only accrue.
    best: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row["game_id"], tuple(row["teams"]))
        prior = best.get(key)
        if prior is None or row["total_possessions"] > prior["total_possessions"]:
            best[key] = row
    coverage["duplicate_snapshots_collapsed"] = len(rows) - len(best)
    deduped = sorted(best.values(), key=lambda r: (r["date"], r["game_id"]))

    coverage["dates_seen"] = sorted(coverage["dates_seen"])
    coverage["dates_with_possessions"] = sorted(coverage["dates_with_possessions"])
    coverage["usable_games"] = len(deduped)
    return {"coverage": coverage, "rows": deduped}


def summarise(rows: list[dict[str, Any]], *, min_games: int) -> dict[str, Any]:
    """Aggregate ONLY if the sample clears the floor.

    Below it, the return states the shortfall instead of a number. "A rate, not
    a count" is a standing rule here; so is refusing to publish a rate whose
    denominator cannot support it.
    """
    n = len(rows)
    if n < min_games:
        return {
            "status": "refused",
            "reason": "insufficient_sample",
            "n": n,
            "min_games": min_games,
            "shortfall": min_games - n,
            "note": (
                "No aggregate is emitted. The series is still returned per game "
                "so it can be inspected; do not average it."
            ),
        }
    paces = [r["pace_per_team"] for r in rows]
    paces_sorted = sorted(paces)
    mid = n // 2
    median = paces_sorted[mid] if n % 2 else (paces_sorted[mid - 1] + paces_sorted[mid]) / 2.0
    mean = sum(paces) / n
    return {
        "status": "ok",
        "n": n,
        "mean_pace_per_team": round(mean, 2),
        "median_pace_per_team": round(median, 2),
        "min_pace": round(min(paces), 2),
        "max_pace": round(max(paces), 2),
    }


def default_roots() -> list[Path]:
    repo = Path(__file__).resolve().parents[1]
    return [repo / "data" / "wnba_source"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=None,
                        help="Artifact root to scan (repeatable). Defaults to data/wnba_source.")
    parser.add_argument("--min-games", type=int, default=10,
                        help="Refuse to emit an aggregate below this many usable games.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args(argv)

    roots = [Path(r) for r in args.root] if args.root else default_roots()
    result = scan(roots)
    result["summary"] = summarise(result["rows"], min_games=args.min_games)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    cov = result["coverage"]
    print("WNBA pbp possessions -- COVERAGE FIRST")
    print(f"  roots                    : {', '.join(cov['roots'])}")
    print(f"  files scanned            : {cov['files']}")
    print(f"  game records             : {cov['game_records']}")
    print(f"  with possession data     : {cov['with_possessions']}")
    print(f"  placeholder ids excluded : {cov['placeholder_excluded']}")
    print(f"  partial (mid-game) excl. : {cov['partial_excluded']}")
    print(f"  duplicate snapshots      : {cov['duplicate_snapshots_collapsed']}")
    print(f"  USABLE GAMES             : {cov['usable_games']}")
    print(f"  dates seen               : {len(cov['dates_seen'])}")
    print(f"  dates with possessions   : {len(cov['dates_with_possessions'])} {cov['dates_with_possessions']}")
    print(f"  home/away keys zero      : {cov['home_away_keys_zero']}  (real data is tricode-keyed)")
    print()
    summary = result["summary"]
    if summary["status"] == "refused":
        print(f"  AGGREGATE REFUSED: n={summary['n']} < min_games={summary['min_games']} "
              f"(short by {summary['shortfall']})")
        print(f"  {summary['note']}")
    else:
        print(f"  n={summary['n']}  mean pace/team={summary['mean_pace_per_team']}  "
              f"median={summary['median_pace_per_team']}  "
              f"range={summary['min_pace']}..{summary['max_pace']}")
    print()
    for row in result["rows"]:
        print(f"  {row['date'] or '(no date)':<12} {row['game_id']:<12} "
              f"{'/'.join(row['teams'])}  total={row['total_possessions']}  "
              f"pace/team={row['pace_per_team']}  complete={row['complete']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
