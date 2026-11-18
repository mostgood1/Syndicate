"""M3, the paper book (decision engine #736, Phase 1B; lane `engine-paper-m3`): the nightly live replay and its gate.

REGISTERED BEFORE ITS DATA: `.syndicate/findings_2026-11-17_m3_paper_book.md` (main `9f37d556c`). The rule's mechanics
live in `syndicate/features/shared/engine_paper_m3.py`; this script is the glue to the PINNED learner and experts
(`981ef14f6`, the M2 kit's code export), which the M3 kit launcher puts first on `sys.path`.

Read-only everywhere: it reads the fleet's data root (ledger, evidence log), the in-play recorder's files, the pinned
experts' opinion file and the M2 read's outputs, and writes only the files its arguments name. Run on the fleet at
nice 19. It places no order and imports no order module.

  save-fit   re-run the M2 read's own learner command (its pinned code, its opinion dirs) and save the fit whole:
             every parameter and its covariance. Usage: save-fit --out FIT.npz -- <the learner's own arguments>
  check-fit  the registered precondition: the re-run's weight table equals the read's, and the saved fit reproduces it
  replay     one slate: eligible lines -> Kalshi entries, marks, settlements, per arm (A1 gates, A2 reported)
  gate       counts (and, at a due look only, the registered look) over every slate's bets

The nightly path prints COUNTS ONLY: no mark-out, ROI or result is printed or read except by `gate` at a due look.
`--rehearse` (dev slates only) marks every line REHEARSAL and may print marks.
"""
from __future__ import annotations

import argparse
import json
import math
import runpy
import sys
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import engine_paper_m3 as m3  # noqa: E402

LIVE_BASES = ("h2h", "spreads", "totals")
OUR_SIDE = {"h2h": "home", "spreads": "home", "totals": "over"}


def _parse(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not Path(path).exists():
        return out
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


# ----------------------------------------------------------------------------- the fit


def save_fit_file(model: Any, path: Path, meta: dict[str, Any]) -> None:
    import numpy as np

    np.savez(path, theta=np.asarray(model.theta, dtype=float), cov=np.asarray(model.cov, dtype=float),
             params=np.array(json.dumps([list(p) for p in model.params])),
             meta=np.array(json.dumps({**meta, "tau": model.tau, "n_examples": model.n_examples,
                                       "n_games": model.n_games, "converged": model.converged,
                                       "message": model.message})))


def load_fit_file(path: Path) -> Any:
    import numpy as np
    from syndicate.features.shared import engine_learner as el

    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    params = [tuple(p) for p in json.loads(str(z["params"]))]
    return el.Fit(params=params, theta=z["theta"], cov=z["cov"], tau=meta["tau"], n_examples=meta["n_examples"],
                  n_games=meta["n_games"], converged=meta["converged"], message=meta["message"]), meta


def cmd_save_fit(args: argparse.Namespace, learner_args: list[str]) -> int:
    from syndicate.features.shared import engine_learner as el

    saved: dict[str, Any] = {}
    real_fit = el.fit

    def fit_and_keep(*a: Any, **k: Any) -> Any:
        model = real_fit(*a, **k)
        if "model" in saved:
            raise SystemExit("save-fit: the learner fitted twice; the registered read fits once")
        saved["model"] = model
        return model

    el.fit = fit_and_keep
    script = Path(el.__file__).resolve().parents[3] / "scripts" / "engine_learner.py"
    argv0 = sys.argv
    sys.argv = [str(script), *learner_args]
    rc = 0
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        rc = int(exc.code or 0) if not isinstance(exc.code, str) else 1
    finally:
        sys.argv = argv0
        el.fit = real_fit
    if "model" not in saved:
        print("SAVE_FIT FAILED: the learner never fitted", flush=True)
        return 2
    save_fit_file(saved["model"], Path(args.out), {"learner": el.LEARNER_VERSION, "learner_args": learner_args,
                                                    "learner_rc": rc})
    print(f"SAVE_FIT ok out={args.out} params={len(saved['model'].params)} learner_rc={rc}", flush=True)
    return 0 if rc in (0,) else rc


def cmd_check_fit(args: argparse.Namespace) -> int:
    """Precondition (registered): the re-run's weight table equals the read's, and the saved fit reproduces the
    table it printed. The learner rounds the table to 4 dp, so equality is of the table as written (|diff| <= 1e-9)."""
    from syndicate.features.shared import engine_learner as el

    read = json.loads(Path(args.read_json).read_text(encoding="utf-8"))["weights"]
    rerun = json.loads(Path(args.rerun_json).read_text(encoding="utf-8"))["weights"]
    model, meta = load_fit_file(Path(args.fit))
    bad: list[str] = []
    key = lambda r: (r["expert"], r["cell"])  # noqa: E731
    if [key(r) for r in read] != [key(r) for r in rerun]:
        bad.append(f"rows differ: read {len(read)} vs rerun {len(rerun)}")
    else:
        for a, b in zip(read, rerun):
            for f in ("w", "se", "n", "applied"):
                if (abs(a[f] - b[f]) > 1e-9) if f in ("w", "se") else a[f] != b[f]:
                    bad.append(f"{key(a)} {f} read={a[f]} rerun={b[f]}")
                    break
    for r in rerun:
        w, se = model.weight(r["expert"], tuple(r["cell"].split("/")))
        if abs(round(w, 4) - r["w"]) > 1e-9 or abs(round(se, 4) - r["se"]) > 1e-9 or \
                (w - el.APPLY_Z * se > 0.0) != r["applied"]:
            bad.append(f"saved fit {key(r)} w={w} se={se} vs table w={r['w']} se={r['se']} applied={r['applied']}")
    tag = "REHEARSAL " if args.rehearse else ""
    if bad:
        print(f"{tag}M3 NOT_A_VERDICT fit: {len(bad)} difference(s); first: {bad[0]}", flush=True)
        return 2
    print(f"{tag}M3_FIT_CHECK ok rows={len(read)} params={len(model.params)} learner={meta.get('learner')}", flush=True)
    return 0


# ----------------------------------------------------------------------------- one slate


def _days_around(d: str) -> list[str]:
    day = _date.fromisoformat(d)
    return [(day + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]


def decision_instants(ops: list[dict[str, Any]], sport: str, date_str: str, games: dict[str, dict[str, Any]],
                      root: Path | None, stats: dict[str, int]) -> dict[str, float]:
    """`line_key|t` -> t_d: the opinion's tick, or its evidence row's state `as_of` if later (registered). An opinion
    whose evidence row cannot be re-found has no t_d (refused `state_time_unknown`)."""
    import bisect

    from syndicate.features.shared import engine_experts as ee
    from syndicate.features.shared import live_evidence_log as lel

    evidence = [row for d in _days_around(date_str) for row in lel.iter_rows(sport, d, root=root)]
    index = ee.EvidenceIndex(evidence, sport=sport)
    out: dict[str, float] = {}
    times_of: dict[tuple[str, str], list[datetime]] = {}
    for op in ops:
        tick = _parse(op.get("t"))
        inputs = op.get("inputs") or {}
        ev_t = _parse(inputs.get("evidence_t"))
        if tick is None or ev_t is None:
            m3.bump(stats, "state_time_unknown:no_tick_or_evidence_t")
            continue
        key = tuple(inputs["evidence_game"]) if inputs.get("evidence_game") else None
        if key is None:
            g = games.get(str(op.get("event_id") or ""))
            if g:
                key, _how = index.find(g.get("home_team"), g.get("away_team"))
        series = index.by_game.get(key) if key else None
        if not series:
            m3.bump(stats, "state_time_unknown:no_evidence_game")
            continue
        times = times_of.get(key)
        if times is None:
            times = times_of[key] = [t for t, _row in series]
        i = bisect.bisect_left(times, ev_t)
        rows = [series[j][1] for j in range(i, len(series)) if series[j][0] == ev_t]
        as_ofs = {_parse(r.get("as_of")) for r in rows} - {None}
        if len(as_ofs) != 1:
            m3.bump(stats, "state_time_unknown:evidence_row_not_unique" if as_ofs else
                    "state_time_unknown:evidence_row_missing")
            continue
        t_d = max(tick, next(iter(as_ofs))).timestamp()
        k = f"{op.get('line_key')}|{op.get('t')}"
        out[k] = max(out.get(k, t_d), t_d)
        if t_d > tick.timestamp():
            m3.bump(stats, "state_after_tick")
    return out


def candidates_for(ops: list[dict[str, Any]], sport: str, date_str: str, fit: Any, live_pass: set[str],
                   t_d: dict[str, float], stats: dict[str, int]) -> list[m3.Candidate]:
    from syndicate.features.shared import engine_learner as el

    examples, build = el.build_examples(((date_str, op) for op in ops), lambda op: (0.0, None))
    stats["examples"] = len(examples)
    out: list[m3.Candidate] = []
    for ex in examples:
        sp, family, market, segment, phase, _bucket, age_bucket = ex.cell
        if phase != "live":
            continue
        if f"{sp}|{family}" not in live_pass:
            m3.bump(stats, "not_a_pass_stratum")
            continue
        if age_bucket != m3.FRESH_STRATUM or ex.prior_age_s is None or ex.prior_age_s > m3.FRESH_PRIOR_S:
            m3.bump(stats, "prior_not_fresh")
            continue
        base = {"spreads_alt": "spreads", "totals_alt": "totals"}.get(market, market)
        if segment != "full" or base not in LIVE_BASES:
            m3.bump(stats, "not_a_full_game_line")
            continue
        parts = ex.line_key.split("|")
        if len(parts) != 7:
            m3.bump(stats, "line_key_unreadable")
            continue
        _s, event_id, _m, _seg, _player, side, line_s = parts
        if side != OUR_SIDE[base]:
            m3.bump(stats, "not_our_side")
            continue
        try:
            line = None if line_s in ("", "None") else float(line_s)
        except ValueError:
            m3.bump(stats, "line_unreadable")
            continue
        tick = ex.key[len(ex.line_key) + 1:]
        td = t_d.get(ex.key)
        if td is None:
            m3.bump(stats, "no_decision_instant")
            continue
        out.append(m3.Candidate(sport=sp, event_id=event_id, family=family, market=market, line=line, tick=tick,
                                t_d=td, p_prior=1.0 / (1.0 + math.exp(-ex.logit_prior)),
                                p_decision=el.p_decision(ex, fit), prior_age_s=ex.prior_age_s))
    m3.bump(stats, "candidates", len(out))
    return out


def cmd_replay(args: argparse.Namespace) -> int:
    from syndicate.features.shared import live_gameline_ledger as lgl

    tag = "REHEARSAL " if args.rehearse else ""
    d = args.date
    verdict_line = [x for x in Path(args.verdict).read_text(encoding="utf-8").splitlines() if x.strip()][-1]
    live_pass, _pregame_pass = m3.pass_strata(verdict_line)
    exp_lines = Path(args.experts_out).read_text(encoding="utf-8", errors="replace").splitlines()
    total, fails, attributed = m3.reproduction(exp_lines, d)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"v": m3.M3_VERSION, "date": d, "rehearsal": bool(args.rehearse),
                              "verdict_line": verdict_line, "live_pass": sorted(live_pass), "sports": {}}
    if total is None or attributed != total:
        why = "no RESULT line" if total is None else f"alarms_plus_mismatches={total} but {attributed} attributed"
        report["slate_refused"] = f"experts reproduction unreadable: {why}"
        print(f"{tag}M3_SLATE {d} REFUSED {report['slate_refused']}", flush=True)
        (out_dir / f"report_{d}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return 0
    excluded = {s for (s, phase) in fails if phase == "live"}
    fit, _meta = load_fit_file(Path(args.fit))
    root = Path(args.root) if args.root else None
    sports = sorted({k.split("|")[0] for k in live_pass} & {s for _p, s in m3.SPORT_OF_PREFIX})
    if args.sports:
        sports = [s for s in sports if s in set(args.sports.split(","))]
    ops_all = _read_jsonl(Path(args.opinions))
    bets_path = out_dir / f"bets_{d}.jsonl"
    all_bets: list[dict[str, Any]] = []
    for sport in sports:
        st: dict[str, int] = {}
        if sport in excluded:
            report["sports"][sport] = {"excluded_reproduction": fails.get((sport, "live"))}
            print(f"{tag}M3_SLATE {d} {sport} EXCLUDED_REPRODUCTION {fails.get((sport, 'live'))}", flush=True)
            continue
        ops = [op for op in ops_all if op.get("sport") == sport and op.get("phase") == "live"
               and not op.get("refusal")]
        games: dict[str, dict[str, Any]] = {}
        for row in _read_jsonl(lgl.ledger_path(sport, d)):
            eid = str(row.get("event_id") or "")
            if eid and eid not in games and row.get("home_team") and row.get("away_team"):
                games[eid] = {"event_id": eid, "home_team": row["home_team"], "away_team": row["away_team"],
                              "commence_time": row.get("commence_time")}
        t_d = decision_instants(ops, sport, d, games, root, st)
        cands = candidates_for(ops, sport, d, fit, live_pass, t_d, st)
        rec = Path(args.recorder) / "kalshi.jsonl"
        if not rec.exists():
            report["sports"][sport] = {"refused": f"no recorder file {rec}", "stats": st}
            print(f"{tag}M3_SLATE {d} {sport} NO_RECORDER {rec}", flush=True)
            continue
        markets = m3.load_recorder(rec, sport, st)
        index = m3.KalshiIndex(markets, sport, list(games.values()))
        bets, rep = m3.replay(cands, index, date=d, stats=st)
        all_bets.extend(bets)
        report["sports"][sport] = {"opinions": len(ops), "games": len(games), **rep}
        frame = " ".join(f"{fam}:{v['verdict']}({v['lines']})" for fam, v in rep["frame"].items()) or "none"
        a1 = m3.counts(bets)
        print(f"{tag}M3_SLATE {d} {sport} opinions={len(ops)} candidates={len(cands)} "
              f"kalshi_indexed={index.stats.get('indexed', 0)} frame=[{frame}] A1 bets={a1['bets']} "
              f"games={a1['games']} unmarked={a1['unmarked']} A2 bets={m3.counts(bets, m3.ARM_A2)['bets']}",
              flush=True)
    with bets_path.open("w", encoding="utf-8") as fh:
        for b in all_bets:
            fh.write(json.dumps(b, sort_keys=True) + "\n")
    (out_dir / f"report_{d}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"{tag}M3_SLATE {d} DONE bets_file={bets_path} rows={len(all_bets)}", flush=True)
    return 0


# ----------------------------------------------------------------------------- the gate


def cmd_gate(args: argparse.Namespace) -> int:
    tag = "REHEARSAL " if args.rehearse else ""
    bets: list[dict[str, Any]] = []
    for p in sorted(Path(args.bets_dir).glob("bets_*.jsonl")):
        bets.extend(_read_jsonl(p))
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"looks": []}
    c = m3.counts(bets)
    print(f"{tag}M3_COUNTS bets={c['bets']} games={c['games']} unmarked={c['unmarked']} "
          f"looks_taken={[x['look'] for x in state['looks']]}", flush=True)
    final = next((x for x in state["looks"] if x["verdict"] != "CONTINUE"), None)
    if final is not None:
        print(f"{tag}M3_FINAL {final['look']} {final['verdict']} (no further look)", flush=True)
        return 0
    name = args.force_look if (args.rehearse and args.force_look) else \
        m3.due_look(c, [x["look"] for x in state["looks"]], args.today)
    if name is None:
        print(f"{tag}M3_NO_LOOK_DUE", flush=True)
        return 0
    if args.count_only:
        print(f"{tag}M3_LOOK_DUE {name}", flush=True)
        return 0
    res = m3.look(bets, name)
    res["taken_on"] = args.today
    if not args.rehearse:
        state["looks"].append(res)
        state_path.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    mk = res.get("markout") or {}
    z = mk.get("z")
    print(f"{tag}M3_LOOK {name} verdict={res['verdict']} z={None if z is None else round(z, 3)} "
          f"bets={res['counts']['bets']} games={res['counts']['games']} unmarked={res['counts']['unmarked']} "
          f"mean_markout={None if mk.get('mean') is None else round(mk['mean'], 5)} harm={res.get('harm')} "
          f"roi_hi95={res.get('roi_hi95')} why={res.get('why')}", flush=True)
    a2 = res.get("reported_A2") or {}
    print(f"{tag}M3_REPORTED A2 n={a2.get('n')} games={a2.get('games')} "
          f"mean_markout={None if a2.get('mean') is None else round(a2['mean'], 5)} "
          f"z={None if a2.get('z') is None else round(a2['z'], 3)}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    learner_args: list[str] = []
    if "--" in argv:
        k = argv.index("--")
        argv, learner_args = argv[:k], argv[k + 1:]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save-fit")
    s.add_argument("--out", required=True)
    s = sub.add_parser("check-fit")
    s.add_argument("--fit", required=True)
    s.add_argument("--read-json", required=True, help="the M2 read's learner_outcome.json")
    s.add_argument("--rerun-json", required=True, help="the save-fit run's own --json output")
    s.add_argument("--rehearse", action="store_true")
    s = sub.add_parser("replay")
    s.add_argument("--date", required=True)
    s.add_argument("--opinions", required=True, help="the pinned experts' opinions file for the slate")
    s.add_argument("--experts-out", required=True, help="the pinned experts runner's stdout for the slate")
    s.add_argument("--fit", required=True)
    s.add_argument("--verdict", required=True, help="the M2 read's verdict file (last line M2_VERDICT PASS ...)")
    s.add_argument("--recorder", required=True, help="the in-play recorder's folder for the slate")
    s.add_argument("--out-dir", required=True)
    s.add_argument("--sports", default=None)
    s.add_argument("--root", default=None)
    s.add_argument("--rehearse", action="store_true")
    s = sub.add_parser("gate")
    s.add_argument("--bets-dir", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--today", default=_date.today().isoformat())
    s.add_argument("--count-only", action="store_true")
    s.add_argument("--rehearse", action="store_true")
    s.add_argument("--force-look", default=None, help="REHEARSAL only: take this look regardless of counts")
    args = ap.parse_args(argv)
    if args.cmd == "save-fit":
        return cmd_save_fit(args, learner_args)
    if args.cmd == "check-fit":
        return cmd_check_fit(args)
    if args.cmd == "replay":
        return cmd_replay(args)
    return cmd_gate(args)


if __name__ == "__main__":
    raise SystemExit(main())
