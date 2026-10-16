"""Lane `wnba-native-live-cutover` (P5). Score the P5 run. (1) native(k) vs linear lens -- the committed scorer's paired table. (2) 5:00-Q4 split: both real
fives resumed vs any sampled. (3) availability variants vs k, native vs native, paired on the same rows.
Usage: python3 p5_score.py <corpus.jsonl.gz> <run_dir> <scorer_dir>"""
import glob
import gzip
import json
import os
import sys
from collections import defaultdict

corpus_path, run_dir, scorer_dir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, scorer_dir)
import score_wnba_live_checkpoint_baseline as sc  # noqa: E402

rows = [json.loads(l) for l in gzip.open(corpus_path, "rt")]
rows = [r for r in rows if r.get("anchors")]


def load(rule):
    out = {}
    for f in glob.glob(os.path.join(run_dir, f"native_{rule}_w*.jsonl")):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                out[(d["event_id"], d["checkpoint"])] = d
    return out


nat = {r: load(r) for r in ("k", "regular_k2_min20", "exempt_apps3of5")}
print("rows per rule:", {r: len(v) for r, v in nat.items()}, "corpus anchored rows:", len(rows))
f = lambda x: "  -   " if x is None else f"{x:+.4f}"  # noqa: E731
ci = lambda c: "-" if not c or c[0] is None else f"[{c[0]:+.3f},{c[1]:+.3f}]"  # noqa: E731


def table(title, cells, native):
    print(f"\n{title}  (negative = first better)")
    print(f"{'cell':26} {'n':>4} {'paired':>6} | {'totAE':>8} {'CI':>17} | {'ML':>8} {'CI':>17} | {'cover':>8} {'CI':>17} | {'over':>8} {'CI':>17} | refusals")
    out = {}
    for k, rs in sorted(cells.items()):
        s = sc.score_native_cell(rs, native)
        out[k] = s
        g = lambda m: (f(s.get(f"{m}_diff")), ci(s.get(f"{m}_diff_ci")))  # noqa: E731
        print(f"{k:26} {s['n']:>4} {s.get('total_ae_n', 0):>6} | {g('total_ae')[0]:>8} {g('total_ae')[1]:>17} | {g('ml')[0]:>8} {g('ml')[1]:>17} | "
              f"{g('cover')[0]:>8} {g('cover')[1]:>17} | {g('over')[0]:>8} {g('over')[1]:>17} | {s['refusals'] or '-'}")
    return out


cells = defaultdict(list)
for r in rows:
    cells[f"{r['phase']}/{r['checkpoint']}"].append(r)
res = {"native_k_vs_linear": table("(1) NATIVE (k inputs) - LINEAR LENS", cells, nat["k"])}

split = defaultdict(list)
for r in rows:
    if r["checkpoint"] != "q4_5min":
        continue
    nm = ((nat["k"].get((r["event_id"], r["checkpoint"])) or {}).get("native") or {}).get("name_match") or {}
    both = nm.get("home_on_floor_matched") == 5 and nm.get("away_on_floor_matched") == 5
    split[f"{r['phase']}/q4 {'both_real' if both else 'any_sampled'}"].append(r)
res["q4_split"] = table("(2) 5:00 Q4, NATIVE (k) - LINEAR, split by real five", split, nat["k"])


def as_lens(native_k):
    """Rows whose `linear_lens` is replaced by native(k)'s prediction, so the scorer pairs variant vs k."""
    out = []
    for r in rows:
        nk = ((native_k.get((r["event_id"], r["checkpoint"])) or {}).get("native") or {})
        if nk.get("refusal") is not None or nk.get("total_mean") is None:
            continue
        rr = dict(r)
        rr["linear_lens"] = {**r["linear_lens"], "total_proj": nk["total_mean"], "home_win_prob": nk.get("home_win_prob"),
                             "home_cover_prob": nk.get("home_cover_prob"), "total_over_prob": nk.get("total_over_prob")}
        out.append(rr)
    return out


krows = as_lens(nat["k"])
for v in ("regular_k2_min20", "exempt_apps3of5"):
    vc = defaultdict(list)
    for r in krows:
        vc[f"{r['phase']}/{r['checkpoint']}"].append(r)
    res[f"{v}_vs_k"] = table(f"(3) NATIVE {v} - NATIVE k", vc, nat[v])

json.dump(res, open(os.path.join(run_dir, "p5_scores.json"), "w"), indent=1, default=str)
print("\nwrote", os.path.join(run_dir, "p5_scores.json"))
