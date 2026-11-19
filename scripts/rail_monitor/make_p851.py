"""Build C:\\tmp\\railmon\\p851_loopstages.py: the #851 lane's reader with its live window taken from argv, plus P2/P4 lines.

  py -3 make_p851.py
  usage on WSL: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p851_loopstages.py <first UTC date> <last UTC date>
  (the live window is 00-05Z on each UTC date in the range; the evening of 11-24 CST is 2026-11-25)
"""
import os

src = open(r"C:\tmp\w1124_851\loopstages.py", encoding="utf-8").read()
old_win = "    return t.hour < 5 and dt.date(2026, 11, 16) <= t.date() <= dt.date(2026, 11, 19)"
assert src.count(old_win) == 1
new_win = "    return t.hour < 5 and WIN_A <= t.date() <= WIN_B"
old_label = '("LIVE 00-05Z nights 11-15..11-18"'
assert src.count(old_label) == 1
new_label = '(f"LIVE 00-05Z on UTC dates {WIN_A}..{WIN_B}"'
head = (
    "import sys as _sys\n"
    "import datetime as _dt\n"
    "WIN_A = _dt.date.fromisoformat(_sys.argv[1])\n"
    "WIN_B = _dt.date.fromisoformat(_sys.argv[2] if len(_sys.argv) > 2 else _sys.argv[1])\n"
)
tail = r'''

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
'''
out = head + src.replace(old_win, new_win).replace(old_label, new_label) + tail
dst = r"C:\tmp\railmon\p851_loopstages.py"
open(dst + ".tmp", "w", encoding="utf-8", newline="\n").write(out)
os.replace(dst + ".tmp", dst)
print("wrote", dst, len(out))
