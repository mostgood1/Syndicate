"""Are the WNBA producer fixes IN FORCE on the served slate? Refuses to answer when it can't.

WHY THIS EXISTS. Four producer-side fixes landed 2026-09-01 in
`scripts/refresh_wnba_oddsapi_props.py`: the [0.01, 0.99] certainty clamp, the
`q = p * (1 + ev)` inversion, the implausible-EV refusal, and withheld TOTAL
recommendations. Every one governs what is WRITTEN into
`recommendations_slate_<date>.json`, and WNBA writes no slate between
2026-08-31 and 2026-09-16 (FIBA break, no games). Until a post-break slate
exists they are deployed and NOT in force, and the only proof is a reading of
that file. `state_basketball.md [wnba-settlement-live]` records exactly that.

WHY THE RAW ARTIFACT AND NOT A PUBLIC PAGE. `/wnba/api/cards` clamps `p_win` /
`ev_pct` at READ time (`wnba/cards.py`), which hides the thing being tested, and
`/wnba/api/picks` serves display strings. This reads the file itself through
`/api/ops/artifacts/export` (admin token).

THREE OUTCOMES, following `verify_wnba_settlement_gate.py`:

    0  PASS        the slate exists, has picks, and every in-force check holds
    1  FAIL        the question was readable and a check failed -- a defect
    3  UNREADABLE  no slate / no picks / no board for the date yet

**Exit 3 is not a failure.** On 2026-09-10 there is no WNBA game, so every
reading is UNREADABLE by construction -- that is the break, not a defect.

REPORTED, NOT GATED: prop picks with |ev_pct| > 100. The slate builder's prop
loop (`_build_local_recommendations_slate_artifact`, `ev_pct =
_float_or_none(top_play.get("ev_pct"))`) never calls `_plausible_ev_pct`; the
file's two other prop sites and both NBA sites do. So the EV refusal does not
cover props ON THE SLATE. Gating on it would fail a slate for a fix nobody
shipped; hiding it would let "EV refusal is in force" be read as covering
props. It also matters for ORDER: `ev_pct` is the slate's `score` and the
within-game sort key, so an implausible prop EV ranks FIRST.

`--check layer2` answers `todo #614` and sprint gate 7 instead: did WNBA reach
the Layer 2 board for the date, and if not, WHICH gate stopped it. The gate
order is `pipeline/layer2_shortlist.py` + `layer2_board.select_shortlist`,
read 2026-09-10. `active_sports` is derived from the rows that arrive, so it can
never say which gate it was; `per_sport_ingest.wnba` can.

Usage:
    py -3 scripts/verify_wnba_slate_hygiene.py --date 2026-09-17
    py -3 scripts/verify_wnba_slate_hygiene.py --date 2026-09-17 --check layer2
    py -3 scripts/verify_wnba_slate_hygiene.py --date 2026-09-17 --check all --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")

PASS, FAIL, UNREADABLE = 0, 1, 3
VERDICT_NAMES = {PASS: "PASS", FAIL: "FAIL", UNREADABLE: "UNREADABLE"}

_GAME_MARKETS = {"ML", "MONEYLINE", "H2H", "ATS", "SPREAD", "SPREADS", "TOTAL", "TOTALS"}
_TOTAL_MARKETS = {"TOTAL", "TOTALS"}
_CERTAINTY_HIGH, _CERTAINTY_LOW = 0.999, 0.001
_CLAMP_LOW, _CLAMP_HIGH = 0.01, 0.99
_MAX_PLAUSIBLE_EV_PCT = 100.0
_EPS = 1e-9


def _float_or_none(value):
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def evaluate_slate(payload, *, allow_totals: bool = False):
    """(verdict, reason, detail) for one parsed recommendations_slate payload. Pure."""
    games = payload.get("per_game") if isinstance(payload, dict) else None
    games = games if isinstance(games, list) else []
    picks = [p for g in games if isinstance(g, dict) for p in (g.get("picks") or []) if isinstance(p, dict)]
    markets = Counter(str(p.get("market") or "").strip() or "<none>" for p in picks)
    p_wins = [v for v in (_float_or_none(p.get("p_win", p.get("win_prob"))) for p in picks) if v is not None]
    game_ev_over, prop_ev_over, max_abs_ev, price_inside = 0, 0, 0.0, 0
    for pick in picks:
        is_game = str(pick.get("market") or "").strip().upper() in _GAME_MARKETS
        ev = _float_or_none(pick.get("ev_pct"))
        if ev is not None:
            max_abs_ev = max(max_abs_ev, abs(ev))
            if abs(ev) > _MAX_PLAUSIBLE_EV_PCT:
                if is_game:
                    game_ev_over += 1
                else:
                    prop_ev_over += 1
        price = _float_or_none(pick.get("odds", pick.get("price")))
        if price is not None and -100.0 < price < 100.0:
            price_inside += 1
    detail = {
        "date": payload.get("date") if isinstance(payload, dict) else None,
        "games": len(games),
        "picks": len(picks),
        "markets": dict(markets.most_common()),
        "p_win_n": len(p_wins),
        "p_win_min": min(p_wins) if p_wins else None,
        "p_win_max": max(p_wins) if p_wins else None,
        "certainty_claims": sum(1 for v in p_wins if v >= _CERTAINTY_HIGH or v <= _CERTAINTY_LOW),
        "p_win_outside_clamp": sum(1 for v in p_wins if v < _CLAMP_LOW - _EPS or v > _CLAMP_HIGH + _EPS),
        "total_picks": sum(1 for p in picks if str(p.get("market") or "").strip().upper() in _TOTAL_MARKETS),
        "game_ev_over_100": game_ev_over,
        "prop_ev_over_100 (REPORTED, not gated)": prop_ev_over,
        "max_abs_ev_pct": round(max_abs_ev, 3),
        "price_inside_pm100 (REPORTED, not gated)": price_inside,
    }
    if not games:
        return UNREADABLE, "the slate has zero games", detail
    if not picks:
        return UNREADABLE, "the slate has games but no picks, so no fix can show", detail
    failures = []
    if detail["certainty_claims"]:
        failures.append(f"{detail['certainty_claims']} pick(s) claim certainty (p_win >= 0.999 or <= 0.001): the clamp is not in force")
    if detail["p_win_outside_clamp"]:
        failures.append(f"{detail['p_win_outside_clamp']} p_win value(s) outside [0.01, 0.99]")
    if detail["total_picks"] and not allow_totals:
        failures.append(
            f"{detail['total_picks']} TOTAL pick(s): totals withholding is not in force "
            "(SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS absent means WITHHOLD)"
        )
    if game_ev_over:
        failures.append(f"{game_ev_over} game-market pick(s) with |ev_pct| > 100: the EV refusal is not in force")
    if failures:
        return FAIL, "; ".join(failures), detail
    return PASS, f"{len(picks)} picks over {len(games)} games, every in-force check holds", detail


def frozen_chip_note(chips):
    """A WNBA chip list that is all FINAL with no start time is a replay, not a slate.

    Measured 2026-09-10: `/api/board/game-chips?date=2026-09-10` served the four
    2026-08-30 games (ESPN 401857186..189), all FINAL, `start_time_utc` empty,
    on a date ESPN lists no WNBA game -- and Layer 2 counted them as
    `scheduled_games: 4`, `sweep_state: pending`.
    """
    wnba = [c for c in (chips or []) if isinstance(c, dict) and c.get("sport") == "wnba"]
    if wnba and all(c.get("state") == "final" and not c.get("start_time_utc") for c in wnba):
        return f"FROZEN? all {len(wnba)} WNBA chips are FINAL with no start time"
    return None


def evaluate_layer2(payload, chips=None):
    """(verdict, reason, detail) for WNBA on one Layer 2 shortlist payload. Pure."""
    chips = [c for c in (chips or []) if isinstance(c, dict) and c.get("sport") == "wnba"]
    frozen = frozen_chip_note(chips)
    detail = {
        "wnba_chips": [f"{c.get('matchup')} {c.get('state')} {c.get('start_time_utc') or '<no start>'}" for c in chips][:12],
        "frozen_chips": frozen,
    }
    if not isinstance(payload, dict) or "per_sport_ingest" not in payload:
        reason = (payload or {}).get("error") or (payload or {}).get("reason") if isinstance(payload, dict) else None
        return UNREADABLE, f"no Layer 2 shortlist for the date ({reason or 'no per_sport_ingest'}; board retention is ~4 days)", detail
    detail["written_at"] = payload.get("written_at")
    detail["active_sports"] = payload.get("active_sports")
    served = (payload.get("per_sport") or {}).get("wnba")
    ingest = (payload.get("per_sport_ingest") or {}).get("wnba")
    detail["per_sport.wnba"] = served
    detail["per_sport_ingest.wnba"] = (
        {k: ingest.get(k) for k in ("sweep_state", "scheduled_games", "quote_rows", "grid_rows", "opportunities", "candidates", "by_lane", "window_dates", "error")}
        if isinstance(ingest, dict) else ingest
    )
    if isinstance(served, dict) and int(served.get("selected") or 0) > 0:
        return PASS, f"WNBA reached Layer 2: selected {served.get('selected')} (game {served.get('game')}, prop {served.get('prop')})", detail
    if not isinstance(ingest, dict):
        return FAIL, "gate 1 (manifest): WNBA was not iterated by the build at all -- look for MANIFEST_GATE_SKIPPED_SPORTS", detail
    if ingest.get("error"):
        return FAIL, f"gate 3 (exception inside WNBA processing): {ingest.get('error')}", detail
    if int(ingest.get("quote_rows") or 0) == 0:
        live_slate = [c for c in chips if c.get("start_time_utc") and c.get("state") in {"pregame", "live"}]
        if ingest.get("sweep_state") == "no_slate":
            return UNREADABLE, "no WNBA slate in the build window", detail
        if live_slate and not frozen:
            return FAIL, f"gate 2 (quote capture): {len(live_slate)} real WNBA game(s) on the chips and zero WNBA quote rows -- capture, not Layer 2 (#626(d))", detail
        return UNREADABLE, (
            f"gate 2 (quote capture): no WNBA quote rows yet, sweep_state={ingest.get('sweep_state')}, "
            f"scheduled_games={ingest.get('scheduled_games')}" + (f"; {frozen}" if frozen else "")
        ), detail
    if int(ingest.get("opportunities") or 0) == 0:
        game_state = ((ingest.get("enrichment") or {}).get("game_state")) if isinstance(ingest.get("enrichment"), dict) else None
        detail["game_state_join"] = game_state
        return FAIL, "gate 4 (lane gate): quotes arrived and no row reached the `opportunity` lane -- read by_lane and the game-state join", detail
    if not isinstance(served, dict):
        detail["board_wide_drops"] = {k: payload.get(k) for k in ("rows_beyond_horizon", "rows_stale_kickoff", "rows_beyond_quote_age", "rows_implausible_book", "rows_uninformative_ev")}
        return FAIL, "gate 5 (pre-bucket filters): opportunities existed and none survived -- horizon / stale kickoff / quote age (counters are board-wide)", detail
    detail["value_floor.wnba"] = (payload.get("value_floor_by_sport") or {}).get("wnba")
    return FAIL, "gate 6 (post-bucket): WNBA has a per_sport entry but selected 0 -- value floor or per-game cap", detail


def unwrap_export(doc, path):
    """The export answers `{"ok", "count", "artifacts": {path: text}}` (`ops.py`)."""
    artifacts = (doc or {}).get("artifacts") if isinstance(doc, dict) else None
    if not isinstance(artifacts, dict) or not artifacts:
        return None
    text = artifacts.get(path)
    if text is None and len(artifacts) == 1:
        text = next(iter(artifacts.values()))
    return text


def _main_worktree_root():
    # `REPO_ROOT` is the checkout this copy came from, which in a session
    # worktree has no `.env` (learnings 2026-09-10). `git worktree list` names
    # the main worktree first.
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return None


def _admin_token():
    token = (os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()
    if token:
        return token
    for root in (REPO_ROOT, _main_worktree_root()):
        env_file = (root / ".env") if root else None
        if env_file and env_file.is_file():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                name, _, value = line.partition("=")
                if name.strip() in {"ADMIN_TOKEN", "SYNDICATE_ADMIN_TOKEN"} and value.strip():
                    return value.strip().strip('"').strip("'")
    return None


def _get_json(path, token=None, timeout=180):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    request = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check_slate(date, allow_totals=False):
    path = f"wnba_source/data/processed/recommendations_slate_{date}.json"
    token = _admin_token()
    if not token:
        return UNREADABLE, "no ADMIN_TOKEN in the environment or either .env", {"path": path}
    try:
        doc = _get_json("/api/ops/artifacts/export?" + urllib.parse.urlencode({"path": path}), token)
    except urllib.error.HTTPError as exc:
        return UNREADABLE, f"export HTTP {exc.code}", {"path": path}
    except Exception as exc:  # noqa: BLE001
        return UNREADABLE, f"export unreachable: {type(exc).__name__}", {"path": path}
    text = unwrap_export(doc, path)
    if text is None:
        return UNREADABLE, "no slate artifact for the date on web's disk", {"path": path, "count": (doc or {}).get("count")}
    try:
        payload = json.loads(text)
    except ValueError:
        return UNREADABLE, "slate artifact is not JSON", {"path": path, "bytes": len(text)}
    verdict, reason, detail = evaluate_slate(payload, allow_totals=allow_totals)
    detail = {"path": path, "bytes": len(text), **detail}
    if payload.get("date") not in (None, date):
        return UNREADABLE, f"slate carries date {payload.get('date')!r}, not {date!r}", detail
    return verdict, reason, detail


def check_layer2(date):
    try:
        payload = _get_json("/api/board/layer2-shortlist?" + urllib.parse.urlencode({"date": date}))
    except Exception as exc:  # noqa: BLE001
        return UNREADABLE, f"layer2-shortlist unreachable: {type(exc).__name__}", {}
    try:
        chips = (_get_json("/api/board/game-chips?" + urllib.parse.urlencode({"date": date})) or {}).get("chips") or []
    except Exception:  # noqa: BLE001
        chips = []
    return evaluate_layer2(payload, chips)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, help="Central slate date, YYYY-MM-DD")
    parser.add_argument("--check", choices=("slate", "layer2", "all"), default="slate")
    parser.add_argument("--allow-totals", action="store_true", help="only if SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS was deliberately enabled")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = {}
    if args.check in ("slate", "all"):
        results["slate"] = check_slate(args.date, allow_totals=args.allow_totals)
    if args.check in ("layer2", "all"):
        results["layer2"] = check_layer2(args.date)

    codes = [verdict for verdict, _, _ in results.values()]
    overall = FAIL if FAIL in codes else (UNREADABLE if UNREADABLE in codes else PASS)
    if args.json:
        print(json.dumps({name: {"verdict": VERDICT_NAMES[v], "reason": r, "detail": d} for name, (v, r, d) in results.items()}, indent=2, default=str))
    else:
        for name, (verdict, reason, detail) in results.items():
            print(f"[{name}] {VERDICT_NAMES[verdict]}: {reason}")
            for key, value in detail.items():
                print(f"    {key}: {value}")
    print(f"OVERALL {VERDICT_NAMES[overall]} (exit {overall})")
    return overall


if __name__ == "__main__":
    sys.exit(main())
