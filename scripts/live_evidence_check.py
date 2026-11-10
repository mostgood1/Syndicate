"""Read-only checks for the live evidence log (Phase 1B M0, lane `live-evidence-log`).

Three readings, each its own subcommand, all read-only:

  nba-crosscheck --date D   NBA's own per-tick history (`nba/live_resim.py`, written by the NBA tick itself) is an
                            independent writer of the same ticks. Every FRESH NBA history row should have a
                            live-evidence row with the same (event, t) and the same numbers. Prints coverage and
                            every field mismatch.
  probe [--wait S]          Read each sport's CURRENT snapshot from the shared store, then rebuild the evidence at
                            that snapshot's own `t` from the log and compare every fresh lane. Waits up to S seconds
                            for the collector to catch the tick (default 75). Prints matched / missing / mismatched.
  size --date D             Bytes and rows per sport for one day.

Run on the fleet with the worker's environment (so the shared store and data root are the fleet's). Exit 1 when
a check finds a mismatch, 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import live_evidence_log as lel  # noqa: E402

# (live-evidence field path, NBA history field)
NBA_FIELDS = (
    (("state", "period"), "period"),
    (("state", "clockSeconds"), "clock_s"),
    (("state", "homeScore"), "home_score"),
    (("state", "awayScore"), "away_score"),
    (("proj", "total"), "total"),
    (("proj", "homeMargin"), "margin"),
    (("modelHomeWinProb",), "p_home"),
    (("simsRun",), "sims"),
)


def _get(row: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = row
    for part in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def nba_crosscheck(date: str, root: Path | None = None) -> int:
    from syndicate.features.nba import live_resim as nba

    hist_path = nba.live_resim_history_path(date, root=root)
    if not hist_path.exists():
        print(f"NBA_CROSSCHECK date={date} history=MISSING path={hist_path}")
        return 0
    fresh = []
    with hist_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("refusal") is None and not r.get("carried_forward") and r.get("source") == nba.LIVE_RESIM_LENS_SOURCE:
                fresh.append(r)
    # Key on the INSTANT, never the text: the history writes `t` in UTC (`...+00:00`) and the snapshot's
    # `generatedAt` carries the Central offset (`...-06:00`). Matched as strings, 422 of 422 same-instant ticks
    # read as missing (fleet, 2026-11-09).
    ev = {}
    for row in lel.iter_rows("nba", date, root=root):
        if row.get("refusal") is None and not row.get("carried"):
            ev[(str(row.get("event_id")), lel._parse(row.get("t")))] = row
    matched, missing, mismatches, used = 0, [], [], set()
    for h in fresh:
        key = (str(h.get("event_id")), lel._parse(h.get("t")))
        row = ev.get(key)
        if row is None:
            missing.append((key[0], str(h.get("t"))))
            continue
        matched += 1
        used.add(key)
        for path, field in NBA_FIELDS:
            if not _same(_get(row, path), h.get(field)):
                mismatches.append((key[0], str(h.get("t")), ".".join(path), _get(row, path), h.get(field)))
    coverage = (matched / len(fresh)) if fresh else None
    log_only = len(set(ev) - used)
    print(f"NBA_CROSSCHECK date={date} history_fresh={len(fresh)} log_fresh={len(ev)} matched={matched} "
          f"missing={len(missing)} log_only={log_only} coverage={coverage if coverage is None else round(coverage, 4)} "
          f"field_mismatches={len(mismatches)}")
    for m in mismatches[:20]:
        print("   MISMATCH", m)
    for k in missing[:10]:
        print("   MISSING", k)
    # A tick the history has and the log does not is a FAILURE, not a pass: exit 0 on 0 of 422 matched was how
    # the first reading came back green.
    return 1 if (mismatches or missing) else 0


def _fresh_lanes(snapshot: Mapping[str, Any]) -> list[tuple[tuple, Mapping[str, Any], Mapping[str, Any]]]:
    out = []
    for g in snapshot.get("games") or []:
        for i, lane in enumerate(g.get("gameLens") or []):
            if isinstance(lane, Mapping) and lel._is_fresh_projection(lane):
                out.append(((g.get("event_id") or g.get("home_name"), lane.get("key")), g, lane))
    return out


def _published_vs_read(lane: Mapping[str, Any], row: Mapping[str, Any]) -> list[tuple[str, Any, Any]]:
    """(field, what the snapshot lane published, what the read row offers), for the fields a live learner needs.

    Read straight off the raw lane under either naming (projection camelCase or lane-level snake_case), so it does
    not share lel.lane_row's notion of where a field lives."""
    projection = lane.get("projection") if isinstance(lane.get("projection"), Mapping) else {}
    live_state = lane.get("live_state") if isinstance(lane.get("live_state"), Mapping) else {}
    state = row.get("state") if isinstance(row.get("state"), Mapping) else {}
    out = []
    for camel, snake in (("homeScore", "home_score"), ("awayScore", "away_score"), ("period", "period")):
        published = projection.get(camel, live_state.get(snake))
        if published is not None:
            out.append((f"state.{camel}", published, state.get(camel)))
    for camel, snake in (("marginDist", "margin_dist"), ("totalRunsDist", "total_dist")):
        published = projection.get(camel) or lane.get(snake)
        if isinstance(published, Mapping) and published:
            out.append((camel, len(published), len(row.get(camel) or {})))
    return out


def probe(wait_s: float, root: Path | None = None) -> int:
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    base = Path(data_root())  # snapshots always come from the store; `root` only relocates the log
    bad = 0
    for sport, name in lel.LIVE_SNAPSHOTS.items():
        snap = read_json_file(base / "live" / name)
        if not isinstance(snap, Mapping):
            print(f"PROBE sport={sport} snapshot=absent")
            continue
        t, date = lel._snapshot_t(snap), str(snap.get("date") or "")
        lanes = _fresh_lanes(snap)
        if not lanes:
            print(f"PROBE sport={sport} t={t} fresh_lanes=0 (nothing live to compare)")
            continue
        deadline = time.monotonic() + wait_s
        while True:
            have = lel.evidence_at(lel.iter_rows(sport, date, root=root), t)
            if all(have.get(k) and have[k].get("t") == t for k, _g, _l in lanes) or time.monotonic() > deadline:
                break
            time.sleep(5)
        matched = missing = mismatched = unread = 0
        for key, g, lane in lanes:
            row = have.get(key)
            if row is None or row.get("t") != t:
                missing += 1
                continue
            want = lel.normalize_row(lel.lane_row(sport, date, t, row.get("observed_at"), g, lane))
            diffs = [k for k in ("state", "proj", "marginDist", "totalRunsDist", "modelHomeWinProb", "simsRun", "as_of")
                     if json.dumps(want.get(k), sort_keys=True, default=str) != json.dumps(row.get(k), sort_keys=True, default=str)]
            # Independent of lane_row: a score or margin distribution the SNAPSHOT carries, wherever the producer put
            # it, must be readable under the shared names. Comparing lane_row with itself cannot see a field
            # lane_row never extracts (nfl 2026-11-09: state in `live_state`, 15/15 "matched" with state empty).
            gaps = [name for name, published, logged in _published_vs_read(lane, row) if published != logged]
            if diffs or gaps:
                mismatched += bool(diffs)
                unread += bool(gaps)
                print(f"   MISMATCH sport={sport} key={key} fields={diffs} unread={gaps}")
            else:
                matched += 1
        bad += mismatched + unread
        print(f"PROBE sport={sport} t={t} fresh_lanes={len(lanes)} matched={matched} missing={missing} "
              f"mismatched={mismatched} unread={unread}")
    return 1 if bad else 0


def size(date: str, root: Path | None = None) -> int:
    for sport in lel.LIVE_SNAPSHOTS:
        p = lel.log_path(sport, date, root=root)
        if p.exists():
            n = sum(1 for _ in p.open(encoding="utf-8"))
            print(f"SIZE sport={sport} date={date} bytes={p.stat().st_size} rows={n}")
        else:
            print(f"SIZE sport={sport} date={date} bytes=0 rows=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("nba-crosscheck"); a.add_argument("--date", required=True)
    b = sub.add_parser("probe"); b.add_argument("--wait", type=float, default=75.0)
    c = sub.add_parser("size"); c.add_argument("--date", required=True)
    for p in (a, b, c):
        p.add_argument("--root", default=None, help="data root override (default: the store's data root)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None
    if args.cmd == "nba-crosscheck":
        return nba_crosscheck(args.date, root)
    if args.cmd == "probe":
        return probe(args.wait, root)
    return size(args.date, root)


if __name__ == "__main__":
    raise SystemExit(main())
