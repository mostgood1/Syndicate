"""P5 backtest: the NATIVE live re-sim (P3's `live_resim`, league="wnba") at the 2026 WNBA checkpoint corpus.

Lane `wnba-native-live-cutover`. For every corpus row (game x end Q1 / Q2 / Q3 / 5:00 Q4) this runs EXACTLY the
production per-game sequence of `live_resim.build_live_lens_snapshot`:

    resume_from_summary(as-of summary)  -> P2 LiveGameState + engine GameState + facts
    load_engine_inputs(date, home, away) -> the recorded as-of pregame engine kwargs
    map_state_names                     -> state names onto the engine frames
    with_live_mechanisms                -> the mechanisms named on the COMMAND LINE (never read from env here)
    resim_live_game(..., base_seed=stable_seed(event_id, last_seq), league="wnba")

The as-of summary is the corpus builder's own `as_of_summary` (plays cut at the checkpoint, header score = the
scoring-play sum at the cut, status in progress), so the engine resumes from the state the corpus grades.

Output: one JSONL row per corpus row -- `native` = {home_win_prob, total_mean, home_margin_mean, home_cover_prob,
total_over_prob, sims_run, name_match, refusal} -- which `score_wnba_live_checkpoint_baseline.py --native` pairs
with the linear lens on the SAME rows. Cover / over are P(win | not push) against the SAME lines the linear lens is
graded on (the sim's market spread and total carried in the corpus anchors), because the scorer excludes pushes.

USER DECISION 2026-10-12: the scoring run waits for P3's mechanism re-fits. Until then this harness is exercised
only by a SMOKE (`--limit`), which proves the wiring and is NOT a result.

Run in WSL with the fleet venv at nice 19, PYTHONHASHSEED fixed (the engine's seed is per process):

  PYTHONHASHSEED=0 nice -n 19 ~/.venvs/syndicate/bin/python scripts/backtest_wnba_live_resim.py \\
      --corpus ~/wnba_bt/live_checkpoints/wnba_live_checkpoints_2026.jsonl.gz \\
      --cache <dir holding summary_<event_id>.json.gz> --inputs-root ~/wnba_live_bt/engine_inputs_asof \\
      --out ~/wnba_live_bt/native_resim.jsonl --sims 200 [--mechanisms '{"field": value}'] [--limit 2]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LEAGUE = "wnba"


def p_win_given_no_push(dist: Mapping[str, int], line: Optional[float], *, offset_sign: int = 1) -> Optional[float]:
    """P(x + sign*line > 0 | x + sign*line != 0) from an integer histogram {str(x): count}.

    Cover: x = home margin, line = home spread (home covers when margin + spread > 0).
    Over:  x = total, line = total line, sign = -1 (over when total - line > 0)."""
    if line is None or not dist:
        return None
    win = push = n = 0
    for k, c in dist.items():
        v = float(k) + offset_sign * float(line)
        n += int(c)
        if v > 0:
            win += int(c)
        elif v == 0:
            push += int(c)
    return win / (n - push) if n - push > 0 else None


def native_for_row(row: Mapping[str, Any], summary: Mapping[str, Any], *, inputs_root: Path, sims: int,
                   mechanisms: Mapping[str, Any], lr: Any, corpus: Any) -> Dict[str, Any]:
    cp = next(c for c in corpus.CHECKPOINTS if c[0] == row["checkpoint"])
    plays = list(summary.get("plays") or [])
    cut = corpus._cut_index(plays, cp[1], cp[2])
    if not cut:
        return {"refusal": "checkpoint_not_reached"}
    resumed = lr.resume_from_summary(corpus.as_of_summary(summary, cut), date=row["date"], league=LEAGUE)
    if isinstance(resumed, lr.NbaResimRefusal):
        return {"refusal": resumed.reason, "detail": resumed.detail}
    _state, gs, facts = resumed
    inputs = lr.load_engine_inputs(row["date"], facts.home_code, facts.away_code, root=inputs_root, league=LEAGUE)
    if isinstance(inputs, lr.NbaResimRefusal):
        return {"refusal": inputs.reason, "detail": inputs.detail}
    gs, match = lr.map_state_names(gs, inputs["home_players"], inputs["away_players"])
    inputs = lr.with_live_mechanisms(inputs, mechanisms)
    t0 = time.monotonic()
    res = lr.resim_live_game(inputs, gs, sims=sims, base_seed=lr.stable_seed(facts.event_id, facts.last_seq),
                             league=LEAGUE)
    if isinstance(res, lr.NbaResimRefusal):
        return {"refusal": res.reason, "detail": res.detail}
    anc = row.get("anchors") or {}
    return {
        "refusal": None, "sims_run": res["sims_run"], "seconds": round(time.monotonic() - t0, 2),
        "home_win_prob": res["home_win_prob"], "total_mean": res["total_mean"],
        "home_margin_mean": res["home_margin_mean"],
        "home_cover_prob": p_win_given_no_push(res["margin_dist"], anc.get("market_home_spread")),
        "total_over_prob": p_win_given_no_push(res["total_dist"], anc.get("market_total"), offset_sign=-1),
        "name_match": match, "resumed_at": {"period": facts.period, "clock_seconds": facts.clock_seconds,
                                            "home": facts.home_score, "away": facts.away_score},
    }


def _summary(cache: Path, event_id: str) -> Optional[Dict[str, Any]]:
    path = cache / f"summary_{event_id}.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--inputs-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--mechanisms", default="{}", help="JSON of EventSimConfig fields; {} = engine defaults (OFF)")
    ap.add_argument("--limit", type=int, default=0, help="first N anchored games only (smoke)")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)

    import build_wnba_live_checkpoint_corpus as corpus
    from syndicate.features.nba import live_resim as lr

    mechanisms = lr.live_mechanisms_from_env({lr.LIVE_MECHANISMS_ENV: args.mechanisms}) if args.mechanisms.strip() not in ("", "{}") else {}
    if args.mechanisms.strip() not in ("", "{}") and not mechanisms:
        raise SystemExit(f"REFUSED: --mechanisms names a field the engine does not have, or is unparseable: {args.mechanisms}")
    opener = gzip.open if args.corpus.endswith(".gz") else open
    with opener(Path(args.corpus).expanduser(), "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rows = [r for r in rows if r.get("anchors")]
    games = sorted({r["event_id"] for r in rows})
    if args.limit:
        games = games[: args.limit]
    games = [g for i, g in enumerate(games) if i % args.workers == args.worker]
    keep = set(games)
    out_path = Path(args.out).expanduser()
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done.add((d["event_id"], d["checkpoint"]))
    cache, inputs_root = Path(args.cache).expanduser(), Path(args.inputs_root).expanduser()
    n = refused = 0
    with out_path.open("a", encoding="utf-8") as fh:
        for r in rows:
            if r["event_id"] not in keep or (r["event_id"], r["checkpoint"]) in done:
                continue
            summary = _summary(cache, r["event_id"])
            native = ({"refusal": "summary_not_cached"} if summary is None else
                      native_for_row(r, summary, inputs_root=inputs_root, sims=args.sims, mechanisms=mechanisms,
                                     lr=lr, corpus=corpus))
            fh.write(json.dumps({"event_id": r["event_id"], "date": r["date"], "checkpoint": r["checkpoint"],
                                 "phase": r["phase"], "mechanisms": mechanisms, "sims": args.sims,
                                 "pythonhashseed": os.environ.get("PYTHONHASHSEED"), "native": native}) + "\n")
            fh.flush()
            n += 1
            refused += 1 if native.get("refusal") else 0
            print(f"RESIM {r['event_id']} {r['checkpoint']} refusal={native.get('refusal')} "
                  f"secs={native.get('seconds')}", flush=True)
    print(f"RESIM_DONE worker={args.worker} rows={n} refused={refused}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
