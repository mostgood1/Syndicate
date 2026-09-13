"""Grade Layer 2 opportunities from the worker's opening ledger.

Lane `layer2-live-scorecard-gate` (2026-09-12). Every market the board publishes
is recorded ONCE, at first sighting, by `clv_opening_ledger.record_openings` on
refresh-worker and pushed to web. This settles those openings against final
scores and reports the split that decides whether live Layer 2 value is real:

  phase   in_play | pregame. From the record's `game_state` when present
          (records written after the lane's deploy). Older records carry no
          state, so their own clock decides: captured_at >= commence_time is
          `in_play_by_clock`, otherwise `pregame_by_clock`. The suffix is kept
          so the two derivations are never pooled silently.
  age     how long since we had OBSERVED the price when it was first published:
          `quote_seen_age_seconds`, else `book_age_seconds` (a recorded move is
          an observation, so it bounds the capture clock from above), else
          `unclocked`.
  book    the published best book.
  market  market/segment.
  window  only with --split-at: `w0`..`wN` by the sighting's `captured_at`, so
          results can be read across an upstream regime change. On 2026-09-12
          two live-odds-worker deploys changed how often odds were captured,
          and one pooled number would average three different pipelines.

Every cell reports `games` beside `n`. Bets on one game are not independent --
measured 2026-09-12, four final NCAAF games swung the in-play cell by -5.2 to
+5.5 units EACH -- so a cell's real sample is closer to its game count than to
its bet count.

Usage (read-only against production unless files are given):

  py -3 scripts/layer2_live_scorecard.py --date 2026-09-12 --sport ncaaf
  py -3 scripts/layer2_live_scorecard.py --date 2026-09-12 --openings-file o.jsonl --chips-file c.json
  py -3 scripts/layer2_live_scorecard.py --date 2026-09-12 --sport ncaaf \
      --split-at 2026-09-12T22:34:15Z --split-at 2026-09-13T00:14:31Z

The opening ledger comes through `/api/ops/artifacts/export?path=` with
`ADMIN_TOKEN`. On 2026-09-12 that file was 17.5 MB by 2 PM CT, so run this once
after a slate, not in a loop. Scores come from `/api/board/game-chips`.

Each graded row is a flat 1-unit bet at the PUBLISHED price. Only full-game
h2h, spreads and totals can be settled from a final score; everything else is
counted under `ungraded` BY REASON -- including a row that matched no scoreboard
game, which is a join failure and must never read as "no final yet".

THE JOIN. Ledger rows carry the odds feed's full names ("Penn State Nittany
Lions"); chips carry the scoreboard's ("Penn State", key "penn state"). The team
alias registry resolves both to one key, but it lives under `data/`, which a
session worktree does not check out -- measured 2026-09-12: with the registry
empty, 0 of 932 NCAAF opportunities joined while two games were final. So the
registry key is tried first and a NAME PREFIX is the fallback, over names with
accents, apostrophes and periods removed ("San José State", "Hawaiʻi"): both
teams must hit the SAME chip, and the longest chip name wins, so "texas" cannot
claim a "Texas Tech" row. A tie between two chips is refused as ambiguous.
Abbreviated scoreboard names ("App State", "Southern Miss") still need the
registry; run with it available for a complete join. Measured 2026-09-12 ~2:20
PM CT over 932 NCAAF opportunities: prefix + normalization alone left 32 rows
`no_chip_match`; with `SYNDICATE_NCAAF_SOURCE_ROOT` pointing at a checkout that
carries the registry, 0.

A board date's ledger also carries games from OTHER dates (the shortlist builds
over a window), and the scoreboard for `--date` cannot settle those. They are
counted as `not_on_board_date` from the kickoff's CENTRAL date, not as unmatched.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from zoneinfo import ZoneInfo

    _CENTRAL: Any = ZoneInfo("America/Chicago")
except Exception:  # tzdata missing: the date split is disabled, and main() says so
    _CENTRAL = None

DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
OPENINGS_PATH_TEMPLATE = "reports/intelligence/clv_openings/{date}.jsonl"
AGE_BUCKETS: tuple[tuple[float, str], ...] = ((120.0, "<=120s"), (300.0, "<=300s"), (900.0, "<=900s"))
GRADABLE_MARKETS = frozenset({"h2h", "spreads", "totals"})
_IN_PLAY_STATES = frozenset({"live", "in progress", "in_progress", "halftime"})
_EXACT_MATCH_BONUS = 10_000
_DROPPED_CHARACTERS = str.maketrans("", "", "'’ʻ‘`.")


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def decimal_odds(american: float) -> float:
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / -american)


def normalize_name(value: Any) -> str:
    """Lowercase, accents stripped, apostrophes and periods removed, spaces collapsed."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.lower().translate(_DROPPED_CHARACTERS).split())


def central_date(value: Any) -> str | None:
    parsed = _parse_ts(value)
    if parsed is None or parsed.tzinfo is None or _CENTRAL is None:
        return None
    return parsed.astimezone(_CENTRAL).date().isoformat()


def parse_openings(text: str) -> list[dict[str, Any]]:
    """JSONL -> records. Malformed lines are skipped, as `load_openings` does."""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def phase_of(record: Mapping[str, Any]) -> str:
    state = str(record.get("game_state") or "").strip().lower()
    if state:
        if state in _IN_PLAY_STATES:
            return "in_play"
        if state in {"final", "finished", "completed"}:
            return "final"
        return "pregame"
    captured = _parse_ts(record.get("captured_at"))
    commence = _parse_ts(record.get("commence_time"))
    if captured is None or commence is None:
        return "unknown"
    return "in_play_by_clock" if captured >= commence else "pregame_by_clock"


def observed_age_seconds(record: Mapping[str, Any]) -> float | None:
    seen = _as_float(record.get("quote_seen_age_seconds"))
    return seen if seen is not None else _as_float(record.get("book_age_seconds"))


def age_bucket(record: Mapping[str, Any]) -> str:
    age = observed_age_seconds(record)
    if age is None:
        return "unclocked"
    for ceiling, label in AGE_BUCKETS:
        if age <= ceiling:
            return label
    return ">900s"


def window_of(captured_at: Any, boundaries: Sequence[datetime]) -> str:
    """`wI` = on or after I boundaries. A sighting AT a boundary belongs to the later window.

    Unsplit runs read `all`; a sighting whose time cannot be parsed is named
    `unknown_time` rather than guessed into a window.
    """
    if not boundaries:
        return "all"
    parsed = _parse_ts(captured_at)
    if parsed is None or parsed.tzinfo is None:
        return "unknown_time"
    return f"w{sum(1 for boundary in boundaries if parsed >= boundary)}"


def window_legend(boundaries: Sequence[datetime]) -> list[str]:
    if not boundaries:
        return []
    stamps = [b.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for b in sorted(boundaries)]
    legend = [f"w0: before {stamps[0]}"]
    legend += [f"w{i}: {stamps[i - 1]} to {stamps[i]}" for i in range(1, len(stamps))]
    legend.append(f"w{len(stamps)}: from {stamps[-1]}")
    return legend


def grade(record: Mapping[str, Any], away_score: int, home_score: int) -> str | None:
    """'win' | 'loss' | 'push', or None when a final score cannot settle it."""
    market = str(record.get("market") or "").strip().lower()
    side = str(record.get("side") or "").strip().lower()
    line = _as_float(record.get("line"))
    if market == "h2h" and side in {"away", "home"}:
        if away_score == home_score:
            return "push"
        return "win" if (side == "away") == (away_score > home_score) else "loss"
    if market == "spreads" and line is not None and side in {"away", "home"}:
        margin = (away_score - home_score if side == "away" else home_score - away_score) + line
        return "push" if margin == 0 else ("win" if margin > 0 else "loss")
    if market == "totals" and line is not None and side in {"over", "under"}:
        diff = (away_score + home_score) - line
        if diff == 0:
            return "push"
        return "win" if (diff > 0) == (side == "over") else "loss"
    return None


def _team_key(sport: str, name: Any) -> str:
    """The alias registry's canonical key, or the lowercased name when it has none."""
    text = str(name or "").strip().lower()
    if not text:
        return ""
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        canon = chip_join_key(sport, text)
    except Exception:
        canon = None
    return str(canon or text).strip().lower()


def _side_names(side: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        value for value in (normalize_name(side.get("key")), normalize_name(side.get("name"))) if value
    )


def index_chips(chips: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """sport -> every chip of the date, in ANY state, so a non-final match is nameable."""
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for chip in chips:
        if not isinstance(chip, Mapping):
            continue
        away = chip.get("away") if isinstance(chip.get("away"), Mapping) else {}
        home = chip.get("home") if isinstance(chip.get("home"), Mapping) else {}
        try:
            scores: tuple[int, int] | None = (int(away.get("score")), int(home.get("score")))
        except (TypeError, ValueError):
            scores = None
        out[str(chip.get("sport") or "").strip().lower()].append({
            "state": str(chip.get("state") or "").strip().lower(),
            "scores": scores,
            "away": _side_names(away),
            "home": _side_names(home),
            "matchup": chip.get("matchup") or f"{away.get('name')} @ {home.get('name')}",
        })
    return dict(out)


def _match_strength(sport: str, record_name: Any, chip_names: frozenset[str]) -> int:
    """0 = no match; exact/registry matches outrank any prefix; longer prefixes outrank shorter."""
    text = normalize_name(record_name)
    if not text:
        return 0
    canon = normalize_name(_team_key(sport, record_name))
    best = 0
    for name in chip_names:
        if name in (text, canon):
            best = max(best, _EXACT_MATCH_BONUS + len(name))
        elif text.startswith(name + " "):
            best = max(best, len(name))
    return best


def match_chip(record: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str | None]:
    sport = str(record.get("sport") or "").strip().lower()
    scored: list[tuple[int, Mapping[str, Any]]] = []
    for chip in candidates:
        away = _match_strength(sport, record.get("away_team"), chip["away"])
        home = _match_strength(sport, record.get("home_team"), chip["home"])
        if away and home:
            scored.append((away + home, chip))
    if not scored:
        return None, "no_chip_match"
    scored.sort(key=lambda item: -item[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous_chip_match"
    return scored[0][1], None


def _market_identity(record: Mapping[str, Any]) -> tuple:
    return (record.get("sport"), record.get("event_id"), record.get("market"), record.get("segment"),
            record.get("side"), record.get("line"), record.get("player_name"))


def settle(
    records: Sequence[Mapping[str, Any]],
    chips: Sequence[Mapping[str, Any]],
    *,
    sport: str | None = None,
    board_date: str | None = None,
    min_ev_pct: float = 0.0,
    dedupe_markets: bool = True,
    split_at: Sequence[datetime] = (),
) -> dict[str, Any]:
    """One settled row per published opportunity, plus the counts of what was not settled.

    `dedupe_markets` keeps the EARLIEST sighting of a market across books: the
    ledger keys on bookmaker, so a best-book change records the same bet twice,
    and grading both would double-count one decision.

    `board_date` names the date the chips describe. A row whose kickoff falls on
    another Central date cannot be settled by them and is counted as
    `not_on_board_date`; omitted, every row is matched against the chips.

    `split_at` stamps each row's `window` from the KEPT sighting, so with
    dedupe a bet stays in the window where it was first published.
    """
    wanted = str(sport or "").strip().lower()
    chosen: dict[Any, Mapping[str, Any]] = {}
    skipped: collections.Counter[str] = collections.Counter()
    for record in records:
        if wanted and str(record.get("sport") or "").strip().lower() != wanted:
            continue
        ev = _as_float(record.get("ev_pct"))
        if ev is None or ev <= min_ev_pct:
            skipped["not_positive_ev"] += 1
            continue
        if _as_float(record.get("price")) is None:
            skipped["no_price"] += 1
            continue
        key = _market_identity(record) if dedupe_markets else record.get("key")
        held = chosen.get(key)
        if held is not None:
            skipped["duplicate_market_later_sighting"] += 1
        if held is None or str(record.get("captured_at") or "") < str(held.get("captured_at") or ""):
            chosen[key] = record

    by_sport = index_chips(chips)
    settled: list[dict[str, Any]] = []
    ungraded: collections.Counter[str] = collections.Counter()
    for record in chosen.values():
        row_sport = str(record.get("sport") or "").strip().lower()
        price = _as_float(record.get("price")) or 0.0
        base: dict[str, Any] = {
            "phase": phase_of(record),
            "age": age_bucket(record),
            "book": str(record.get("bookmaker") or "unknown"),
            "market": f"{record.get('market')}/{record.get('segment')}",
            "window": window_of(record.get("captured_at"), split_at),
            "ev_pct": _as_float(record.get("ev_pct")),
            "price": price,
            "game": None,
            "result": None,
            "pnl": None,
        }
        settled.append(base)
        if str(record.get("market") or "").strip().lower() not in GRADABLE_MARKETS or str(record.get("player_name") or ""):
            ungraded["market_not_gradeable_from_score"] += 1
            continue
        if str(record.get("segment") or "").strip().lower() not in {"full", "full_game", ""}:
            ungraded["segment_not_full_game"] += 1
            continue
        kickoff_date = central_date(record.get("commence_time"))
        if board_date and kickoff_date and kickoff_date != board_date:
            ungraded["not_on_board_date"] += 1
            continue
        chip, reason = match_chip(record, by_sport.get(row_sport, []))
        if chip is None:
            ungraded[reason or "no_chip_match"] += 1
            continue
        if chip["state"] != "final":
            ungraded["game_not_final"] += 1
            continue
        if chip["scores"] is None:
            ungraded["final_score_unparseable"] += 1
            continue
        result = grade(record, *chip["scores"])
        if result is None:
            ungraded["unsettleable_side_or_line"] += 1
            continue
        base["game"] = chip["matchup"]
        base["result"] = result
        base["pnl"] = {"win": decimal_odds(price) - 1.0, "loss": -1.0, "push": 0.0}[result]
    return {"rows": settled, "ungraded": dict(ungraded), "skipped": dict(skipped)}


def summarize(rows: Sequence[Mapping[str, Any]], dims: Sequence[str]) -> list[dict[str, Any]]:
    cells: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(d) for d in dims)
        cell = cells.setdefault(
            key, {"n": 0, "ev_sum": 0.0, "win": 0, "loss": 0, "push": 0, "units": 0.0, "games": set()}
        )
        cell["n"] += 1
        cell["ev_sum"] += row.get("ev_pct") or 0.0
        if row.get("result"):
            cell[row["result"]] += 1
            cell["units"] += row.get("pnl") or 0.0
            cell["games"].add(row.get("game"))
    out = []
    for key, cell in cells.items():
        graded = cell["win"] + cell["loss"] + cell["push"]
        out.append({
            **dict(zip(dims, key)),
            "n": cell["n"],
            "graded": graded,
            "games": len(cell["games"]),
            "mean_ev_shown_pct": round(cell["ev_sum"] / cell["n"], 3),
            "w_l_p": f"{cell['win']}-{cell['loss']}-{cell['push']}",
            "units": round(cell["units"], 3),
            "roi_pct": round(cell["units"] / graded * 100.0, 2) if graded else None,
        })
    return sorted(out, key=lambda c: (-c["n"],) + tuple(str(c[d]) for d in dims))


def _http_json(url: str, headers: Mapping[str, str] | None = None, timeout: float = 180.0) -> Any:
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def fetch_openings(base_url: str, date: str, token: str) -> list[dict[str, Any]]:
    path = OPENINGS_PATH_TEMPLATE.format(date=date)
    url = f"{base_url.rstrip('/')}/api/ops/artifacts/export?path={urllib.parse.quote(path, safe='')}"
    payload = _http_json(url, headers={"X-Admin-Token": token})
    artifacts = payload.get("artifacts") if isinstance(payload, Mapping) else None
    if not isinstance(payload, Mapping) or not payload.get("ok") or not isinstance(artifacts, Mapping):
        raise RuntimeError(f"export refused: {payload.get('error') if isinstance(payload, Mapping) else payload!r}")
    if not artifacts:
        # ABSENT is a real answer and must not print as an empty scorecard.
        raise RuntimeError(f"no opening ledger on web for {date} ({path})")
    return parse_openings(next(iter(artifacts.values())))


def fetch_chips(base_url: str, date: str, sport: str | None) -> list[dict[str, Any]]:
    query = {"date": date}
    if sport:
        query["sports"] = sport
    payload = _http_json(f"{base_url.rstrip('/')}/api/board/game-chips?{urllib.parse.urlencode(query)}")
    return [chip for chip in (payload.get("chips") or []) if isinstance(chip, Mapping)]


_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phase", ("phase",)),
    ("phase_x_age", ("phase", "age")),
    ("phase_x_book", ("phase", "book")),
    ("phase_x_market", ("phase", "market")),
)
_SPLIT_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("window", ("window",)),
    ("phase_x_window", ("phase", "window")),
    ("phase_x_window_x_age", ("phase", "window", "age")),
)


def _print_table(title: str, cells: Sequence[Mapping[str, Any]], dims: Sequence[str]) -> None:
    print(f"\n{title}")
    print(" ".join(f"{d:>18}" for d in dims)
          + f" {'n':>5} {'graded':>6} {'games':>5} {'evShown':>8} {'W-L-P':>10} {'units':>8} {'ROI%':>7}")
    for cell in cells:
        roi = "-" if cell["roi_pct"] is None else f"{cell['roi_pct']:.2f}"
        print(" ".join(f"{str(cell[d])[:18]:>18}" for d in dims)
              + f" {cell['n']:5d} {cell['graded']:6d} {cell['games']:5d} {cell['mean_ev_shown_pct']:8.2f}"
              + f" {cell['w_l_p']:>10} {cell['units']:8.2f} {roi:>7}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, help="board date, YYYY-MM-DD")
    parser.add_argument("--sport", default=None, help="e.g. ncaaf; omit for every sport")
    parser.add_argument("--min-ev-pct", type=float, default=0.0)
    parser.add_argument("--openings-file", default=None, help="local JSONL instead of fetching")
    parser.add_argument("--chips-file", default=None, help="local /api/board/game-chips JSON instead of fetching")
    parser.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--admin-token-env", default="ADMIN_TOKEN")
    parser.add_argument("--no-dedupe", action="store_true", help="grade every ledger key, including best-book changes")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--split-at", action="append", default=[],
                        help="ISO time with a zone; repeat to split results into windows by captured_at")
    args = parser.parse_args(argv)

    boundaries: list[datetime] = []
    for value in args.split_at:
        parsed = _parse_ts(value)
        if parsed is None or parsed.tzinfo is None:
            print(f"--split-at needs an ISO time with a zone, e.g. 2026-09-12T22:34:15Z; got {value!r}", file=sys.stderr)
            return 2
        boundaries.append(parsed)
    boundaries.sort()

    if _CENTRAL is None:
        print("WARNING: no tz data for America/Chicago; other-date games count as no_chip_match", file=sys.stderr)
    if args.openings_file:
        records = parse_openings(Path(args.openings_file).read_text(encoding="utf-8"))
    else:
        token = str(os.environ.get(args.admin_token_env) or "").strip()
        if not token:
            print(f"set {args.admin_token_env} or pass --openings-file", file=sys.stderr)
            return 2
        records = fetch_openings(args.base_url, args.date, token)
    if args.chips_file:
        chips_payload = json.loads(Path(args.chips_file).read_text(encoding="utf-8"))
        chips = [c for c in (chips_payload.get("chips") or []) if isinstance(c, Mapping)]
    else:
        chips = fetch_chips(args.base_url, args.date, args.sport)

    result = settle(records, chips, sport=args.sport, board_date=args.date,
                    min_ev_pct=args.min_ev_pct, dedupe_markets=not args.no_dedupe, split_at=boundaries)
    rows = result["rows"]
    finals = sum(1 for c in chips if str(c.get("state") or "").strip().lower() == "final")
    specs = _TABLES + (_SPLIT_TABLES if boundaries else ())
    tables = {name: summarize(rows, dims) for name, dims in specs}
    legend = window_legend(boundaries)
    if args.json:
        print(json.dumps({"date": args.date, "sport": args.sport, "records_in": len(records),
                          "chips": len(chips), "finals": finals, "opportunities": len(rows),
                          "ungraded": result["ungraded"], "skipped": result["skipped"],
                          "windows": legend, "tables": tables}, indent=1, default=str))
        return 0
    print(f"date={args.date} sport={args.sport or 'all'} records_in={len(records)} "
          f"opportunities={len(rows)} chips={len(chips)} finals={finals}")
    print(f"skipped={result['skipped']}")
    print(f"ungraded={result['ungraded']}")
    if legend:
        print("windows by captured_at: " + "; ".join(legend))
    for name, dims in specs:
        _print_table(name, tables[name], dims)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
