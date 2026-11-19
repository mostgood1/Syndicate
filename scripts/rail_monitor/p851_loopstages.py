import sys as _sys
import datetime as _dt
WIN_A = _dt.date.fromisoformat(_sys.argv[1])
WIN_B = _dt.date.fromisoformat(_sys.argv[2] if len(_sys.argv) > 2 else _sys.argv[1])
"""Time each stage of live-odds-worker's main loop iteration from its own log lines. Run from ~/syndicate-prod.

Iteration i: loop_tick_begin_i -> tick_start (pre: autoruns) -> tick_end (the odds tick) -> loop_sleep
(post: disk maint, Polymarket slate, execution tick, ledger rebuild) -> loop_tick_begin_{i+1} (sleep).
Inside post, markers: POLYMARKET_US_SLATE_WRITE (end of a slate sweep, either thread), VENUE_BALANCES /
VENUE_SETTLEMENT / EXECUTION (execution tick), LEDGER_REBUILD.
"""
import datetime as dt
import glob
import re
import subprocess

UTC = dt.timezone.utc
PAT = ("LIVE_ODDS_WORKER_MEMORY|POLYMARKET_US_SLATE_WRITE|VENUE_BALANCES|VENUE_SETTLEMENT|"
       r"\] EXECUTION|ORDER_PATH|LEDGER_REBUILD|ODDS_SWEEP_LAUNCHED|\[venue_poll\]")
ev = []
for f in sorted(glob.glob("logs/live-odds-worker.log*")):
    out = subprocess.run(["grep", "-aE", PAT, f], capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if "ALL_PROCESS_MEMORY" in line or not re.match(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z ", line):
            continue
        t = dt.datetime.fromisoformat(line[:23] + "+00:00")
        body = line[25:]
        if body.startswith("LIVE_ODDS_WORKER_MEMORY"):
            m = re.search(r'"stage": "([a-z_]+)"', body)
            if m:
                ev.append((t, "S:" + m.group(1)))
        elif "POLYMARKET_US_SLATE_WRITE" in body:
            ev.append((t, "SLATE"))
        elif "VENUE_BALANCES" in body:
            ev.append((t, "BAL"))
        elif "VENUE_SETTLEMENT" in body:
            ev.append((t, "SETTLE"))
        elif "] EXECUTION" in body:
            ev.append((t, "EXEC"))
        elif "ORDER_PATH" in body:
            ev.append((t, "ORDER"))
        elif "LEDGER_REBUILD" in body:
            ev.append((t, "LEDGER"))
        elif "ODDS_SWEEP_LAUNCHED" in body:
            ev.append((t, "LAUNCH"))
        elif "[venue_poll]" in body:
            ev.append((t, "VPOLL"))
ev.sort()
print(f"events {len(ev)}: {ev[0][0]:%m-%d %H:%MZ}..{ev[-1][0]:%m-%d %H:%MZ}")


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


begins = [i for i, e in enumerate(ev) if e[1] == "S:loop_tick_begin"]
its = []
for a, b in zip(begins, begins[1:]):
    seg = ev[a:b + 1]
    t0, t1 = ev[a][0], ev[b][0]
    st = {k: next((e[0] for e in seg if e[1] == k), None) for k in ("S:tick_start", "S:tick_end", "S:loop_sleep")}
    if not all(st.values()) or (t1 - t0).total_seconds() > 3 * 3600:
        continue
    post = [e for e in seg if st["S:tick_end"] <= e[0] <= st["S:loop_sleep"]]
    rec = {
        "t0": t0, "total": (t1 - t0).total_seconds(),
        "pre": (st["S:tick_start"] - t0).total_seconds(),
        "tick": (st["S:tick_end"] - st["S:tick_start"]).total_seconds(),
        "post": (st["S:loop_sleep"] - st["S:tick_end"]).total_seconds(),
        "sleep": (t1 - st["S:loop_sleep"]).total_seconds(),
        "post_slate": [e[0] for e in post if e[1] == "SLATE"],
        "post_exec": [e[0] for e in post if e[1] in ("BAL", "SETTLE", "EXEC", "ORDER")],
        "post_ledger": [e[0] for e in post if e[1] == "LEDGER"],
        "launch_in_tick": sum(1 for e in seg if e[1] == "LAUNCH" and st["S:tick_start"] <= e[0] <= st["S:tick_end"]),
        "launch_out": sum(1 for e in seg if e[1] == "LAUNCH" and not (st["S:tick_start"] <= e[0] <= st["S:tick_end"])),
        "tick_end": st["S:tick_end"], "loop_sleep": st["S:loop_sleep"],
    }
    # split post: slate first, then execution, then the rest
    s_end = rec["post_slate"][0] if rec["post_slate"] else None
    x_first = rec["post_exec"][0] if rec["post_exec"] else None
    x_last = rec["post_exec"][-1] if rec["post_exec"] else None
    te = st["S:tick_end"]
    if s_end and (x_first is None or s_end <= x_first):
        rec["slate_s"] = (s_end - te).total_seconds()
        base = s_end
    else:
        rec["slate_s"] = 0.0
        base = te
    rec["exec_s"] = (x_last - base).total_seconds() if x_last and x_last >= base else 0.0
    rec["rest_s"] = rec["post"] - rec["slate_s"] - rec["exec_s"]
    its.append(rec)


def live_window(t):
    return t.hour < 5 and WIN_A <= t.date() <= WIN_B


for label, sel in ((f"LIVE 00-05Z on UTC dates {WIN_A}..{WIN_B}", lambda r: live_window(r["t0"])),
                   ("ALL logged iterations", lambda r: True)):
    R = [r for r in its if sel(r)]
    if not R:
        continue
    print(f"\n== {label}: {len(R)} iterations ==")
    T = sum(r["total"] for r in R)
    for k in ("pre", "tick", "post", "sleep"):
        xs = [r[k] for r in R]
        print(f"  {k:6s} p50 {q(xs, .5):6.0f}s p90 {q(xs, .9):6.0f}s max {max(xs):6.0f}s  share {100 * sum(xs) / T:4.1f}%")
    xs = [r["total"] for r in R]
    print(f"  ITERATION p50 {q(xs, .5):.0f}s p90 {q(xs, .9):.0f}s max {max(xs):.0f}s")
    for k in ("slate_s", "exec_s", "rest_s"):
        xs = [r[k] for r in R]
        print(f"  post.{k:8s} p50 {q(xs, .5):5.0f}s p90 {q(xs, .9):5.0f}s max {max(xs):5.0f}s  share of all time {100 * sum(xs) / T:4.1f}%  "
              f"nonzero in {sum(1 for x in xs if x > 1)}")
    long_post = [r for r in R if r["post"] > 120]
    print(f"  iterations with post > 120 s: {len(long_post)} of {len(R)}; of those with a SLATE write inside: "
          f"{sum(1 for r in long_post if r['post_slate'])}; with execution markers: {sum(1 for r in long_post if r['post_exec'])}; "
          f"slate is the larger part in {sum(1 for r in long_post if r['slate_s'] >= max(r['exec_s'], r['rest_s']))}; "
          f"exec in {sum(1 for r in long_post if r['exec_s'] > max(r['slate_s'], r['rest_s']))}; "
          f"rest in {sum(1 for r in long_post if r['rest_s'] > max(r['slate_s'], r['exec_s']))}")
    print(f"  ODDS_SWEEP_LAUNCHED in tick spans {sum(r['launch_in_tick'] for r in R)}, outside {sum(r['launch_out'] for r in R)}")
    slate_all = [e[0] for e in ev if e[1] == "SLATE" and sel({"t0": e[0]})]
    in_post = sum(1 for s in slate_all if any(r["tick_end"] <= s <= r["loop_sleep"] for r in R))
    print(f"  POLYMARKET_US_SLATE_WRITE lines in window: {len(slate_all)}; inside a main-loop post span: {in_post}")

print("\nLONGEST 12 live iterations:")
L = sorted([r for r in its if live_window(r["t0"])], key=lambda r: -r["total"])[:12]
for r in L:
    print(f"  {r['t0']:%m-%d %H:%M:%SZ} total {r['total']:5.0f} pre {r['pre']:4.0f} tick {r['tick']:4.0f} post {r['post']:4.0f} "
          f"(slate {r['slate_s']:4.0f} exec {r['exec_s']:4.0f} rest {r['rest_s']:4.0f}) sleep {r['sleep']:3.0f}")

# --- confound check: is the tick_end -> first execution marker gap long ONLY when a slate write falls inside it? ---
print("\nCONFOUND CHECK (live window): tick_end -> first BAL marker")
R = [r for r in its if live_window(r["t0"])]
w, wo = [], []
for r in R:
    bal = next((e[0] for e in ev if e[1] == "BAL" and r["tick_end"] <= e[0] <= r["loop_sleep"]), None)
    if not bal:
        continue
    gap = (bal - r["tick_end"]).total_seconds()
    has = any(r["tick_end"] <= s <= bal for s in r["post_slate"])
    (w if has else wo).append(gap)
print(f"  with a SLATE write before BAL: n {len(w)} p50 {q(w, .5):.0f}s p90 {q(w, .9):.0f}s min {min(w) if w else 0:.0f}s")
print(f"  without:                       n {len(wo)} p50 {q(wo, .5):.0f}s p90 {q(wo, .9):.0f}s max {max(wo) if wo else 0:.0f}s")
# slate sweep durations by thread: venue_poll thread's sweeps = SLATE lines NOT inside a main-loop post span
sl = sorted(e[0] for e in ev if e[1] == "SLATE" and live_window(e[0]))
print(f"  SLATE writes in live windows: {len(sl)}; gaps between successive writes p50 {q([(b - a).total_seconds() for a, b in zip(sl, sl[1:]) if (b - a).total_seconds() < 3600], .5):.0f}s")

# --- counterfactual: the same live iterations without the main-loop slate sweep (and without the execution tick) ---
R = [r for r in its if live_window(r["t0"])]
a = [r["total"] for r in R]
b = [r["total"] - r["slate_s"] for r in R]
c = [r["total"] - r["slate_s"] - r["exec_s"] for r in R]
print("\nCOUNTERFACTUAL iteration length, live window (same iterations, parts subtracted; ignores knock-on effects):")
print(f"  as measured:            p50 {q(a, .5):.0f}s p90 {q(a, .9):.0f}s max {max(a):.0f}s; over 180 s {sum(1 for x in a if x > 180)} of {len(a)}")
print(f"  minus main-loop slate:  p50 {q(b, .5):.0f}s p90 {q(b, .9):.0f}s max {max(b):.0f}s; over 180 s {sum(1 for x in b if x > 180)} of {len(b)}")
print(f"  minus slate and exec:   p50 {q(c, .5):.0f}s p90 {q(c, .9):.0f}s max {max(c):.0f}s; over 180 s {sum(1 for x in c if x > 180)} of {len(c)}")


# --- #851 P2 / P4, added by the rail monitor (reading R-D) ---
print("\n#851 P2: gaps between ODDS_SWEEP_LAUNCHED lines per sport, live window")
_launch = {}
for _f in sorted(glob.glob("logs/live-odds-worker.log*")):
    _out = subprocess.run(["grep", "-aE", "ODDS_SWEEP_LAUNCHED|POLYMARKET_ARTIFACT_STALE", _f], capture_output=True, text=True, errors="replace").stdout
    for _line in _out.splitlines():
        if not re.match(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z ", _line):
            continue
        _t = dt.datetime.fromisoformat(_line[:23] + "+00:00")
        if not live_window(_t):
            continue
        if "POLYMARKET_ARTIFACT_STALE" in _line:
            _launch.setdefault("__stale__", []).append(_t)
            continue
        _m = re.search(r"sports=([a-z0-9_,]+)", _line)
        for _s in (_m.group(1).split(",") if _m else []):
            _launch.setdefault(_s, []).append(_t)
_all = []
for _s, _ts in sorted(_launch.items()):
    if _s == "__stale__":
        continue
    _ts = sorted(set(_ts))
    _g = [(b - a).total_seconds() for a, b in zip(_ts, _ts[1:]) if (b - a).total_seconds() < 3600]
    _all += _g
    if _g:
        print(f"  {_s:8s} n {len(_g):4d} p50 {q(_g, .5):5.0f}s p90 {q(_g, .9):5.0f}s max {max(_g):5.0f}s")
if _all:
    print(f"  ALL      n {len(_all):4d} p50 {q(_all, .5):5.0f}s p90 {q(_all, .9):5.0f}s")
print(f"#851 P4: POLYMARKET_ARTIFACT_STALE lines in the live window: {len(_launch.get('__stale__', []))}")
