# M2 gate registration -- decision engine #736, lane `engine-learner`

Registered on main 2026-11-16 6:26 PM CST, BEFORE its data: no learner, experts or truth read of any slate on or after
2026-11-15 has been made for this lane (the learner's dev window ends at slate 2026-11-14, max_commence
2026-11-15T06:00Z; the F2 window rule keeps everything from 2026-11-15T20:00Z unread until F2's read on 11-17).
The user asked for it on 2026-11-16 ("Yes, do both", answering "Start the dev re-run, then draft the gate?").

## What is judged

Does the shadow learner's `p_decision` beat its own prior on games it never trained on?

- **Train:** slates 2026-11-09..2026-11-14, the FROZEN opinions in the kit's `train/` (sha256 below), rebuilt on
  2026-11-16 by the experts on main `981ef14f6` (it carries the live-refusals fix `2607c6ffe`; not slice 5).
- **Test:** slates 2026-11-15..2026-11-22, every game held out whole (`forward_split`, `--test-from 2026-11-15`).
  Test opinions are built AT THE READ by the same pinned experts.
- **Code:** one pinned export of origin/main `981ef14f6` (`syndicate/`, `scripts/`, `pipeline/`, `app.py`) for both
  the experts and the learner; manifest sha256 below. A later learner or experts change is NOT this gate. If F2
  passes and slice 5 (the Kalshi live prior) reaches main, the gate still reads the book prior it was registered on.
- **Truths:** live lines by outcome (slice 1 basketball scoreboards, slice 2 board chips); pregame lines by the
  close (Pinnacle, else the Shin consensus of >= 2 books; props included). Prop OUTCOMES are not graded here.

## The rule (applied by `m2_gate.py`, source below; no re-interpretation)

```
The M2 gate of decision engine #736 (lane engine-learner): one registered verdict over the learner's held-out JSON.

Registered on main BEFORE its data (test slates 2026-11-15..2026-11-22). Applies the rule exactly; no judgment.

Inputs (written by read.sh with the pinned code): out/learner_outcome.{json,txt}, out/learner_close.{json,txt}, both from
  engine_learner.py run --dates 2026-11-09..2026-11-22 --test-from 2026-11-15 --truth outcome|close

PRECONDITIONS (any failure -> `M2_VERDICT NOT_A_VERDICT <why>`, which goes back to the user):
  - each JSON: learner engine_learner/1, tau 0.5, dates 2026-11-09..2026-11-22, test_from 2026-11-15;
  - OFF reproduces the prior (reach.off_nonzero == 0, every OFF delta 0);
  - SPLIT shared=0, and train games >= 95% of the dev window's games registered below (the dev history still reads);
  - the pinned experts reproduced production on every test slate: each out/experts_out_<date>.txt has
    `RESULT date=<date> ... alarms_plus_mismatches=0 exit=0` (every dev slate did on 2026-11-16).

JUDGED STRATA (the gate):
  - LIVE, truth outcome, ON_BY_AGE `sport|family|live|a<=60`: the learner over a FRESH (<= 60 s) prior. The dev run
    showed live gains mostly against stale priors; correcting staleness is the prior's job, not a learner edge.
  - PREGAME, truth close, ON `sport|family|pregame` (props included): the learner toward the close.
  A stratum is judged at >= 30 test games with a CI. hi99 = d + 2.576*se, se = (ci95 hi - ci95 lo) / 3.92 (the
  bootstrap CI read as normal; 99% because ~20-40 strata are judged).
  PASS: hi99 < 0 AND d <= -floor. Floors: LIVE outcome 0.001 nats; PREGAME close 0.0002 nats (a soft label makes tiny
  weights significant: the dev run had 196 cells applied with every group within 0.0001 nats).
HARM (checked on EVERY ON and ON_BY_AGE key of both truths with >= 30 games): lo99 = d - 2.576*se > 0 AND
  d >= the truth's floor (outcome 0.001, close 0.0002) -- the same size test a pass must meet.
VERDICT (last line): any HARM -> FAIL; else any PASS -> PASS <strata>; else no stratum judged -> NOTHING_JUDGED;
  else FAIL. An unjudged stratum is never a pass. PASS lets M3 (the paper book) consume p_decision for the PASS strata
  only; anything else keeps the learner shadow-only and goes back to the user.

`--rehearse` skips the window and train-size preconditions (for dev-window JSON) and marks every line REHEARSAL.
```

## Dev rehearsal, 2026-11-16 (NOT the gate)

The rule above (strata, 99% bound, floors, >= 30 games, HARM) was written BEFORE this re-fit was read; only
`DEV_GAMES` was filled from it. Re-fit on slates 11-09..11-14 (test from 11-13; 804 games, 380 held out whole) with
the rebuilt opinions (experts on main `981ef14f6`: live NCAAF now opines, 23,620 re-sim rows; NHL puck lines 1,740):
`m2_gate.py --rehearse` judges 11 strata and passes 2: live NCAAF spreads, fresh prior: d_ll -0.0349 [-0.0532,
-0.0146], 55 games, hi99 -0.0096; live NCAAF totals, fresh: -0.0359 [-0.0585, -0.0120], 58 games, hi99 -0.0053.
NCAAB live totals fresh (-0.0088 [-0.0150, -0.0013], 124 games) fails at 99% (hi99 +0.0002). Every judged pregame
stratum by the close is 0 to 6 decimals. No HARM. A gain that size against a fresh live line was checked for look-ahead: on
every graded live NCAAF / NBA `live_resim` opinion the evidence is older than the line instant (min 0.1 s) and so is
the prior (min 2.3 s); `live_segment` records no evidence time (NBA and NCAAF alike: an existing gap, named here).
A forward test cannot catch a look-ahead, so this check is part of the registration, not of the read.

## When

ONE read, Tue 2026-11-24 10:30 AM CST (every test slate final; the fleet's retention sweep is off, so the inputs
persist). Command: `MSYS_NO_PATHCONV=1 wsl.exe -- setsid -w bash /mnt/c/tmp/elp/m2gate_kit/read.sh` (about
two hours at nice 19: the dev rebuild took ~70 min for six slates). The kit's launcher reproduced the 11-09 dev
opinions byte for byte on 2026-11-16 (170,196 rows, same sha256). If `out/m2_verdict.txt`
already exists, the read already ran: never run it twice. Nothing is pushed or deployed by the read; the verdict and
its table go back to the user.

## Pins

- code: export of origin/main `981ef14f6551c4f8543019457af6a3340675f328`; `manifest.py` prints `CODE_MANIFEST files=2021 sha256=e7f85c4214cea84662d323588b62e0b60b09befaafc10125733347a671b787ef`
- `m2_gate.py` sha256 `e02a16f981c80a8fc628767a88ec4f2dd8cdb1a9a8024c2d0995df694571a61f`; `read.sh` sha256 `95dfc8312a3b383a5b8d84e4cd1635acdb20300ca543d073ee793c420b97f189`; `launch.py` sha256 `3a1a38c208192eaa147e23be07b2e43bd638ad74640411f764f14a7c24105116`; `manifest.py` sha256 `2c1f6319a1c93585778f7d96948d6d9f9db83bf385bab70368c5e7d1afdfdbc4`
- dev games registered (train + test of the 2026-11-16 re-fit): outcome 804, close 427
- `train/opinions_2026-11-09.jsonl` 130,051,652 bytes, sha256 `0f3411aaebb25e9a6aa5f9b3e6646c6523e1825604e6478da865521b38fd9f58`
- `train/opinions_2026-11-10.jsonl` 154,264,104 bytes, sha256 `d49623d065bfb404abb46777717b62506b7dc1fcbc478838f56da4317778de90`
- `train/opinions_2026-11-11.jsonl` 476,891,621 bytes, sha256 `7fc4e660e98e5a94271f19e46cd4545dd7904ad44440e52a32b4a844be950f52`
- `train/opinions_2026-11-12.jsonl` 259,227,806 bytes, sha256 `52dbc4f3ff601b8ec2a2d59252d0371029e9cc68af1a24e3398b31ae01e32026`
- `train/opinions_2026-11-13.jsonl` 517,556,102 bytes, sha256 `a56d1f3210609e1b24003b985fc3b87bd924d8ebf6358c7b53d8e43802f59e16`
- `train/opinions_2026-11-14.jsonl` 362,574,435 bytes, sha256 `f33735f768c66cf9c4646128cd6d8637f9f3fd8655ecbf48fa24d81446e724ad`

## `m2_gate.py` (sha256 e02a16f981c80a8fc628767a88ec4f2dd8cdb1a9a8024c2d0995df694571a61f)

```python
"""The M2 gate of decision engine #736 (lane engine-learner): one registered verdict over the learner's held-out JSON.

Registered on main BEFORE its data (test slates 2026-11-15..2026-11-22). Applies the rule exactly; no judgment.

Inputs (written by read.sh with the pinned code): out/learner_outcome.{json,txt}, out/learner_close.{json,txt}, both from
  engine_learner.py run --dates 2026-11-09..2026-11-22 --test-from 2026-11-15 --truth outcome|close

PRECONDITIONS (any failure -> `M2_VERDICT NOT_A_VERDICT <why>`, which goes back to the user):
  - each JSON: learner engine_learner/1, tau 0.5, dates 2026-11-09..2026-11-22, test_from 2026-11-15;
  - OFF reproduces the prior (reach.off_nonzero == 0, every OFF delta 0);
  - SPLIT shared=0, and train games >= 95% of the dev window's games registered below (the dev history still reads);
  - the pinned experts reproduced production on every test slate: each out/experts_out_<date>.txt has
    `RESULT date=<date> ... alarms_plus_mismatches=0 exit=0` (every dev slate did on 2026-11-16).

JUDGED STRATA (the gate):
  - LIVE, truth outcome, ON_BY_AGE `sport|family|live|a<=60`: the learner over a FRESH (<= 60 s) prior. The dev run
    showed live gains mostly against stale priors; correcting staleness is the prior's job, not a learner edge.
  - PREGAME, truth close, ON `sport|family|pregame` (props included): the learner toward the close.
  A stratum is judged at >= 30 test games with a CI. hi99 = d + 2.576*se, se = (ci95 hi - ci95 lo) / 3.92 (the
  bootstrap CI read as normal; 99% because ~20-40 strata are judged).
  PASS: hi99 < 0 AND d <= -floor. Floors: LIVE outcome 0.001 nats; PREGAME close 0.0002 nats (a soft label makes tiny
  weights significant: the dev run had 196 cells applied with every group within 0.0001 nats).
HARM (checked on EVERY ON and ON_BY_AGE key of both truths with >= 30 games): lo99 = d - 2.576*se > 0 AND
  d >= the truth's floor (outcome 0.001, close 0.0002) -- the same size test a pass must meet.
VERDICT (last line): any HARM -> FAIL; else any PASS -> PASS <strata>; else no stratum judged -> NOTHING_JUDGED;
  else FAIL. An unjudged stratum is never a pass. PASS lets M3 (the paper book) consume p_decision for the PASS strata
  only; anything else keeps the learner shadow-only and goes back to the user.

`--rehearse` skips the window and train-size preconditions (for dev-window JSON) and marks every line REHEARSAL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATES = ("2026-11-09", "2026-11-22")
TEST_FROM = "2026-11-15"
TEST_DATES = tuple(f"2026-11-{d}" for d in range(15, 23))
MIN_GAMES = 30
Z99 = 2.576
FLOOR = {"live": 0.001, "pregame": 0.0002}
FRESH = "a<=60"
# Dev-window games (slates 11-09..11-14, train + test of the 2026-11-16 re-run with the experts on main 981ef14f6).
DEV_GAMES = {"outcome": 804, "close": 427}  # the 2026-11-16 dev re-fit, train + test games
TRAIN_SHARE_MIN = 0.95
SPLIT_RE = re.compile(r"^SPLIT train=\d+ \((\d+) games.*test=\d+ \((\d+) games.*shared=(\d+)")


def se_of(ci):
    lo, hi = ci
    return None if lo is None or hi is None else (hi - lo) / 3.92


def precheck(name, d, txt, rehearse):
    why = []
    if d.get("learner") != "engine_learner/1" or d.get("tau") != 0.5:
        why.append(f"{name}: learner/tau {d.get('learner')}/{d.get('tau')}")
    if not rehearse and ((d.get("dates") or [None])[0], (d.get("dates") or [None])[-1]) != DATES:
        why.append(f"{name}: dates {d.get('dates', [])[:1]}..{d.get('dates', [])[-1:]}")
    if not rehearse and d.get("test_from") != TEST_FROM:
        why.append(f"{name}: test_from {d.get('test_from')}")
    if (d.get("reach") or {}).get("off_nonzero") != 0:
        why.append(f"{name}: OFF moved {d.get('reach', {}).get('off_nonzero')} examples")
    if any(v.get("delta_log_loss") != 0.0 for v in (d.get("held_out", {}).get("OFF") or {}).values()):
        why.append(f"{name}: an OFF delta is not 0")
    m = next((SPLIT_RE.match(line) for line in txt.splitlines() if line.startswith("SPLIT ")), None)
    if not m:
        why.append(f"{name}: no SPLIT line")
    else:
        train_games, test_games, shared = map(int, m.groups())
        if shared:
            why.append(f"{name}: shared={shared}")
        need = DEV_GAMES.get(name)
        if not rehearse and (need is None or train_games < TRAIN_SHARE_MIN * need):
            why.append(f"{name}: train games {train_games} < {TRAIN_SHARE_MIN} x dev {need}")
        print(f"{'REHEARSAL ' if rehearse else ''}SPLIT {name} train_games={train_games} test_games={test_games} "
              f"shared={shared} dev_registered={need}")
    return why


def judge(key, v, floor):
    games, ci, d = v.get("games", 0), v.get("ci95") or [None, None], v.get("delta_log_loss")
    se = se_of(ci)
    if games < MIN_GAMES or se is None:
        return "UNJUDGED", None
    hi99 = d + Z99 * se
    return ("PASS" if hi99 < 0 and d <= -floor else "FAIL"), hi99


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="dir holding learner_{outcome,close}.{json,txt}")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()
    tag = "REHEARSAL " if a.rehearse else ""
    out = Path(a.out)
    data, txts = {}, {}
    for t in ("outcome", "close"):
        try:
            data[t] = json.loads((out / f"learner_{t}.json").read_text(encoding="utf-8"))
            txts[t] = (out / f"learner_{t}.txt").read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            print(f"{tag}M2_VERDICT NOT_A_VERDICT missing/unreadable {t}: {exc}")
            return 2
    why = [w for t in ("outcome", "close") for w in precheck(t, data[t], txts[t], a.rehearse)]
    if not a.rehearse:  # the experts reproduced production on every test slate (as on every dev slate, 11-16)
        for d in TEST_DATES:
            try:
                lines = (out / f"experts_out_{d}.txt").read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            ok = any(line.startswith(f"RESULT date={d} ") and " alarms_plus_mismatches=0 " in line
                     and line.rstrip().endswith("exit=0") for line in lines)
            print(f"EXPERTS {d} reproduction {'clean' if ok else 'NOT CLEAN'}")
            if not ok:
                why.append(f"experts {d}: no clean RESULT line")
    if why:
        print(f"{tag}M2_VERDICT NOT_A_VERDICT {'; '.join(why)}")
        return 2

    judged = []  # (key, truth, phase, v)
    for k, v in sorted(data["outcome"]["held_out"].get("ON_BY_AGE", {}).items()):
        parts = k.split("|")
        if len(parts) == 4 and parts[2] == "live" and parts[3] == FRESH:
            judged.append((k, "outcome", "live", v))
    for k, v in sorted(data["close"]["held_out"].get("ON", {}).items()):
        parts = k.split("|")
        if len(parts) == 3 and parts[2] == "pregame":
            judged.append((k, "close", "pregame", v))

    passes, n_judged = [], 0
    for k, t, phase, v in judged:
        verdict, hi99 = judge(k, v, FLOOR[phase])
        n_judged += verdict != "UNJUDGED"
        if verdict == "PASS":
            passes.append(f"{k}({t})")
        print(f"{tag}STRATUM {k} truth={t} games={v.get('games')} lines={v.get('lines')} d_ll={v.get('delta_log_loss')} "
              f"ci95={v.get('ci95')} hi99={None if hi99 is None else round(hi99, 6)} floor={FLOOR[phase]} -> {verdict}")

    harms = []
    for t in ("outcome", "close"):
        for rep in ("ON", "ON_BY_AGE"):
            for k, v in sorted(data[t]["held_out"].get(rep, {}).items()):
                se = se_of(v.get("ci95") or [None, None])
                floor = FLOOR["live"] if t == "outcome" else FLOOR["pregame"]
                if (v.get("games", 0) >= MIN_GAMES and se is not None and v["delta_log_loss"] - Z99 * se > 0
                        and v["delta_log_loss"] >= floor):
                    harms.append(f"{t}:{rep}:{k}")
                    print(f"{tag}HARM {t} {rep} {k} games={v.get('games')} d_ll={v.get('delta_log_loss')} "
                          f"ci95={v.get('ci95')}")
    applied = {t: (data[t].get("reach") or {}).get("applied_cells") for t in data}
    print(f"{tag}APPLIED_CELLS outcome={applied['outcome']} close={applied['close']}")
    if harms:
        print(f"{tag}M2_VERDICT FAIL harm={len(harms)} [{', '.join(harms)}] judged={n_judged} pass={len(passes)}")
    elif passes:
        print(f"{tag}M2_VERDICT PASS judged={n_judged} pass={len(passes)} [{', '.join(passes)}]")
    elif n_judged == 0:
        print(f"{tag}M2_VERDICT NOTHING_JUDGED strata={len(judged)}")
    else:
        print(f"{tag}M2_VERDICT FAIL judged={n_judged} pass=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
## Amendment 1 -- registered 2026-11-16 6:57 PM CST, BEFORE the data (no slate on or after 2026-11-15 read)

**NHL live strata can never pass** (`EXCLUDED_LOOKAHEAD`: not a pass, not counted as judged, still checked for HARM).
Why: a live evidence row's tick `t` is its snapshot's `generatedAt`; its game state carries its own `as_of`. A state
NEWER than its tick lets an opinion see past the line it is scored against. Measured on the dev evidence logs
(11-09..11-14, priced rows), state `as_of` minus tick `t`:

| sport | priced rows | state newer than tick | by at most | median tick minus state |
|---|---|---|---|---|
| NHL | 3,307 | **1,839** | **25.0 s** | -1.0 s (state usually AFTER the tick) |
| NCAAF | 2,800 | 318 | 0.73 s | 40.4 s |
| NFL | 34 | 34 | 0.99 s | -0.5 s |
| NBA | 2,279 | 0 | -- | 11.0 s |
| NCAAB | 12,359 | 0 | -- | 21.0 s |
| WNCAAB | 3,130 | 0 | -- | 7.0 s |

Sub-second sports are kept: on the dev breakdown below, the 822 NCAAF line-instants with any look-ahead carry no gain.
The durable fix (an opinion's instant = the later of tick and state, or the producer stamping after it reads state) is
owed in the experts (lane engine-live-prior), AFTER F2's 11-17 push, whose blob checks pin `engine_experts.py`.

`m2_gate.py` is now sha256 `6915bb6a5ecb80f2bc96581bd73ccf98d78d565a9c42d14503e53a92365d86f5` (the registered `e02a16f9...` is kept beside it as
`m2_gate.registered_e02a16f9.py`); the read task checks the new hash. Rehearsed: the dev result is unchanged (PASS on
NCAAF live spreads and totals, fresh), and a synthetic NHL fresh stratum with d_ll -0.05 over 40 games comes out
`EXCLUDED_LOOKAHEAD`, not a pass. The change:

```diff
24a25,27
> AMENDMENT 1 (2026-11-16, before the data): every LIVE stratum of a sport in LOOKAHEAD_EXCLUDED_LIVE (NHL: its
>   evidence rows carry state up to 25 s newer than their tick) is EXCLUDED_LOOKAHEAD -- never a pass, not counted as
>   judged, still checked for HARM.
45a49,54
> # AMENDMENT 1 (registered 2026-11-16, before the data): a sport whose dev evidence rows carry game state NEWER than
> # their own tick lets an opinion see past the line it is scored against, so its live strata cannot pass. Measured on
> # the dev logs 11-09..11-14 (state `as_of` minus tick `t`, priced rows): NHL 1,839 of 3,307 newer, by up to 25 s.
> # Sub-second elsewhere, kept: NCAAF 318 of 2,800 (<= 0.73 s; those line-instants carry no gain in the dev breakdown),
> # NFL 34 of 34 (<= 0.99 s); NBA, NCAAB, WNCAAB 0.
> LOOKAHEAD_EXCLUDED_LIVE = {"nhl"}
137c146,148
<         n_judged += verdict != "UNJUDGED"
---
>         if phase == "live" and k.split("|")[0] in LOOKAHEAD_EXCLUDED_LIVE:
>             verdict = "EXCLUDED_LOOKAHEAD"  # AMENDMENT 1: never a pass, never counted as judged; HARM still checked
>         n_judged += verdict not in ("UNJUDGED", "EXCLUDED_LOOKAHEAD")
```

## Dev breakdown of the NCAAF gain (11-16, NOT the gate)

Pinned kit code, the rebuilt dev opinions, test from 11-13 (58 NCAAF games), outcome truth:
- **All of it is `live_resim` on full-game lines.** `live_segment` (NCAAF segment totals) applies no weight anywhere
  (d_ll 0.00000), so its missing evidence time cannot carry any of the gain.
- **It survives removing look-ahead.** Keeping only line-instants whose evidence state is not newer than the line:
  spreads fresh -0.0369 [-0.0616, -0.0128] (37 games), totals fresh -0.0365 [-0.0564, -0.0165] (40 games). The 822
  look-ahead instants carry d_ll 0. (Line-instants the tagger could not join to an evidence row show the same gain.)
- **It is spread across the game**, not at the end: fresh spreads by clock 0-25 -0.031, 25-50 -0.048, 50-75 -0.043,
  75-95 -0.016, 95-100 +0.017 (n.s.); totals 0-25 -0.025, 25-50 -0.042, 50-75 -0.041, 75-95 -0.039, 95-100 +0.029 (n.s.).
- **It is TRANSFER, not an NCAAF fit.** Training held 8 live NCAAF games; none of their 46 leaf cells is applied. The
  test lines' weight comes from the cell tree's shared nodes, i.e. what `live_resim` earned on basketball (86 applied
  `live_resim` leaves: NBA 35, NCAAB 19, NHL 15, WNCAAB 11, NFL 6, NCAAF 0). In the gate, training also holds the 58
  dev NCAAF games, so NCAAF's own cells get their say.

## `m2_gate.py` as amended (sha256 6915bb6a5ecb80f2bc96581bd73ccf98d78d565a9c42d14503e53a92365d86f5)

```python
"""The M2 gate of decision engine #736 (lane engine-learner): one registered verdict over the learner's held-out JSON.

Registered on main BEFORE its data (test slates 2026-11-15..2026-11-22). Applies the rule exactly; no judgment.

Inputs (written by read.sh with the pinned code): out/learner_outcome.{json,txt}, out/learner_close.{json,txt}, both from
  engine_learner.py run --dates 2026-11-09..2026-11-22 --test-from 2026-11-15 --truth outcome|close

PRECONDITIONS (any failure -> `M2_VERDICT NOT_A_VERDICT <why>`, which goes back to the user):
  - each JSON: learner engine_learner/1, tau 0.5, dates 2026-11-09..2026-11-22, test_from 2026-11-15;
  - OFF reproduces the prior (reach.off_nonzero == 0, every OFF delta 0);
  - SPLIT shared=0, and train games >= 95% of the dev window's games registered below (the dev history still reads);
  - the pinned experts reproduced production on every test slate: each out/experts_out_<date>.txt has
    `RESULT date=<date> ... alarms_plus_mismatches=0 exit=0` (every dev slate did on 2026-11-16).

JUDGED STRATA (the gate):
  - LIVE, truth outcome, ON_BY_AGE `sport|family|live|a<=60`: the learner over a FRESH (<= 60 s) prior. The dev run
    showed live gains mostly against stale priors; correcting staleness is the prior's job, not a learner edge.
  - PREGAME, truth close, ON `sport|family|pregame` (props included): the learner toward the close.
  A stratum is judged at >= 30 test games with a CI. hi99 = d + 2.576*se, se = (ci95 hi - ci95 lo) / 3.92 (the
  bootstrap CI read as normal; 99% because ~20-40 strata are judged).
  PASS: hi99 < 0 AND d <= -floor. Floors: LIVE outcome 0.001 nats; PREGAME close 0.0002 nats (a soft label makes tiny
  weights significant: the dev run had 196 cells applied with every group within 0.0001 nats).
HARM (checked on EVERY ON and ON_BY_AGE key of both truths with >= 30 games): lo99 = d - 2.576*se > 0 AND
  d >= the truth's floor (outcome 0.001, close 0.0002) -- the same size test a pass must meet.
AMENDMENT 1 (2026-11-16, before the data): every LIVE stratum of a sport in LOOKAHEAD_EXCLUDED_LIVE (NHL: its
  evidence rows carry state up to 25 s newer than their tick) is EXCLUDED_LOOKAHEAD -- never a pass, not counted as
  judged, still checked for HARM.
VERDICT (last line): any HARM -> FAIL; else any PASS -> PASS <strata>; else no stratum judged -> NOTHING_JUDGED;
  else FAIL. An unjudged stratum is never a pass. PASS lets M3 (the paper book) consume p_decision for the PASS strata
  only; anything else keeps the learner shadow-only and goes back to the user.

`--rehearse` skips the window and train-size preconditions (for dev-window JSON) and marks every line REHEARSAL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATES = ("2026-11-09", "2026-11-22")
TEST_FROM = "2026-11-15"
TEST_DATES = tuple(f"2026-11-{d}" for d in range(15, 23))
MIN_GAMES = 30
Z99 = 2.576
FLOOR = {"live": 0.001, "pregame": 0.0002}
FRESH = "a<=60"
# AMENDMENT 1 (registered 2026-11-16, before the data): a sport whose dev evidence rows carry game state NEWER than
# their own tick lets an opinion see past the line it is scored against, so its live strata cannot pass. Measured on
# the dev logs 11-09..11-14 (state `as_of` minus tick `t`, priced rows): NHL 1,839 of 3,307 newer, by up to 25 s.
# Sub-second elsewhere, kept: NCAAF 318 of 2,800 (<= 0.73 s; those line-instants carry no gain in the dev breakdown),
# NFL 34 of 34 (<= 0.99 s); NBA, NCAAB, WNCAAB 0.
LOOKAHEAD_EXCLUDED_LIVE = {"nhl"}
# Dev-window games (slates 11-09..11-14, train + test of the 2026-11-16 re-run with the experts on main 981ef14f6).
DEV_GAMES = {"outcome": 804, "close": 427}  # the 2026-11-16 dev re-fit, train + test games
TRAIN_SHARE_MIN = 0.95
SPLIT_RE = re.compile(r"^SPLIT train=\d+ \((\d+) games.*test=\d+ \((\d+) games.*shared=(\d+)")


def se_of(ci):
    lo, hi = ci
    return None if lo is None or hi is None else (hi - lo) / 3.92


def precheck(name, d, txt, rehearse):
    why = []
    if d.get("learner") != "engine_learner/1" or d.get("tau") != 0.5:
        why.append(f"{name}: learner/tau {d.get('learner')}/{d.get('tau')}")
    if not rehearse and ((d.get("dates") or [None])[0], (d.get("dates") or [None])[-1]) != DATES:
        why.append(f"{name}: dates {d.get('dates', [])[:1]}..{d.get('dates', [])[-1:]}")
    if not rehearse and d.get("test_from") != TEST_FROM:
        why.append(f"{name}: test_from {d.get('test_from')}")
    if (d.get("reach") or {}).get("off_nonzero") != 0:
        why.append(f"{name}: OFF moved {d.get('reach', {}).get('off_nonzero')} examples")
    if any(v.get("delta_log_loss") != 0.0 for v in (d.get("held_out", {}).get("OFF") or {}).values()):
        why.append(f"{name}: an OFF delta is not 0")
    m = next((SPLIT_RE.match(line) for line in txt.splitlines() if line.startswith("SPLIT ")), None)
    if not m:
        why.append(f"{name}: no SPLIT line")
    else:
        train_games, test_games, shared = map(int, m.groups())
        if shared:
            why.append(f"{name}: shared={shared}")
        need = DEV_GAMES.get(name)
        if not rehearse and (need is None or train_games < TRAIN_SHARE_MIN * need):
            why.append(f"{name}: train games {train_games} < {TRAIN_SHARE_MIN} x dev {need}")
        print(f"{'REHEARSAL ' if rehearse else ''}SPLIT {name} train_games={train_games} test_games={test_games} "
              f"shared={shared} dev_registered={need}")
    return why


def judge(key, v, floor):
    games, ci, d = v.get("games", 0), v.get("ci95") or [None, None], v.get("delta_log_loss")
    se = se_of(ci)
    if games < MIN_GAMES or se is None:
        return "UNJUDGED", None
    hi99 = d + Z99 * se
    return ("PASS" if hi99 < 0 and d <= -floor else "FAIL"), hi99


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="dir holding learner_{outcome,close}.{json,txt}")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()
    tag = "REHEARSAL " if a.rehearse else ""
    out = Path(a.out)
    data, txts = {}, {}
    for t in ("outcome", "close"):
        try:
            data[t] = json.loads((out / f"learner_{t}.json").read_text(encoding="utf-8"))
            txts[t] = (out / f"learner_{t}.txt").read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            print(f"{tag}M2_VERDICT NOT_A_VERDICT missing/unreadable {t}: {exc}")
            return 2
    why = [w for t in ("outcome", "close") for w in precheck(t, data[t], txts[t], a.rehearse)]
    if not a.rehearse:  # the experts reproduced production on every test slate (as on every dev slate, 11-16)
        for d in TEST_DATES:
            try:
                lines = (out / f"experts_out_{d}.txt").read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            ok = any(line.startswith(f"RESULT date={d} ") and " alarms_plus_mismatches=0 " in line
                     and line.rstrip().endswith("exit=0") for line in lines)
            print(f"EXPERTS {d} reproduction {'clean' if ok else 'NOT CLEAN'}")
            if not ok:
                why.append(f"experts {d}: no clean RESULT line")
    if why:
        print(f"{tag}M2_VERDICT NOT_A_VERDICT {'; '.join(why)}")
        return 2

    judged = []  # (key, truth, phase, v)
    for k, v in sorted(data["outcome"]["held_out"].get("ON_BY_AGE", {}).items()):
        parts = k.split("|")
        if len(parts) == 4 and parts[2] == "live" and parts[3] == FRESH:
            judged.append((k, "outcome", "live", v))
    for k, v in sorted(data["close"]["held_out"].get("ON", {}).items()):
        parts = k.split("|")
        if len(parts) == 3 and parts[2] == "pregame":
            judged.append((k, "close", "pregame", v))

    passes, n_judged = [], 0
    for k, t, phase, v in judged:
        verdict, hi99 = judge(k, v, FLOOR[phase])
        if phase == "live" and k.split("|")[0] in LOOKAHEAD_EXCLUDED_LIVE:
            verdict = "EXCLUDED_LOOKAHEAD"  # AMENDMENT 1: never a pass, never counted as judged; HARM still checked
        n_judged += verdict not in ("UNJUDGED", "EXCLUDED_LOOKAHEAD")
        if verdict == "PASS":
            passes.append(f"{k}({t})")
        print(f"{tag}STRATUM {k} truth={t} games={v.get('games')} lines={v.get('lines')} d_ll={v.get('delta_log_loss')} "
              f"ci95={v.get('ci95')} hi99={None if hi99 is None else round(hi99, 6)} floor={FLOOR[phase]} -> {verdict}")

    harms = []
    for t in ("outcome", "close"):
        for rep in ("ON", "ON_BY_AGE"):
            for k, v in sorted(data[t]["held_out"].get(rep, {}).items()):
                se = se_of(v.get("ci95") or [None, None])
                floor = FLOOR["live"] if t == "outcome" else FLOOR["pregame"]
                if (v.get("games", 0) >= MIN_GAMES and se is not None and v["delta_log_loss"] - Z99 * se > 0
                        and v["delta_log_loss"] >= floor):
                    harms.append(f"{t}:{rep}:{k}")
                    print(f"{tag}HARM {t} {rep} {k} games={v.get('games')} d_ll={v.get('delta_log_loss')} "
                          f"ci95={v.get('ci95')}")
    applied = {t: (data[t].get("reach") or {}).get("applied_cells") for t in data}
    print(f"{tag}APPLIED_CELLS outcome={applied['outcome']} close={applied['close']}")
    if harms:
        print(f"{tag}M2_VERDICT FAIL harm={len(harms)} [{', '.join(harms)}] judged={n_judged} pass={len(passes)}")
    elif passes:
        print(f"{tag}M2_VERDICT PASS judged={n_judged} pass={len(passes)} [{', '.join(passes)}]")
    elif n_judged == 0:
        print(f"{tag}M2_VERDICT NOTHING_JUDGED strata={len(judged)}")
    else:
        print(f"{tag}M2_VERDICT FAIL judged={n_judged} pass=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
## Amendment 1, measured exposure (2026-11-16 7:38 PM CST; the rule is unchanged)

The look-ahead behind Amendment 1 is real in the evidence LOG (NHL rows stamped before their state), but on the dev
days it reached NO graded opinion. Every graded `live_resim` opinion, in every sport, matched the join's own state
(`same_state`: NHL 3,431, NCAAF 23,620, NBA 103,064, NCAAB 56,326, NFL 61). That state cannot postdate the ledger row
it priced, and the by-time fallback that could see a newer state never fired. The only expert dated by its tick is
`live_segment`, and NHL has no segment opinions. A fix that files every row at the later of tick and state
(`6d22b4d6e`, local, lane engine-live-prior) changed NO `live_resim` opinion on 11-09..11-14 and re-dated 1,099 NCAAF
segment totals. NHL live stays excluded in this gate as a precaution: the pinned code (`981ef14f6`) lacks the fix, and
its fallback path could still look ahead in the forward window.

## Amendment 2 -- registered 2026-11-17 1:57 PM CST, before any learner output, close or game-line outcome of a test slate is read for this gate

**If the pinned experts fail to match production for a sport on a test slate, that sport's live strata (or its
pregame strata) drop out. Everything else is still judged.** Until now, one such slate voided the whole read.

The user asked for this on 2026-11-17: "Yes, draft it", answering "Draft M2 gate Amendment 2 so a mismatched market
drops out instead of voiding the read?". They registered it with "Yes, register it", answering "Register Amendment 2 on main and switch the 11-24 read to it?" (2026-11-17, after the draft and its tests were put in front of them).

**Why.** The registered precondition voids the read (`M2_VERDICT NOT_A_VERDICT`) when the experts fail to reproduce
production on any test slate. The experts are pinned (`981ef14f6`); production keeps changing:
- todo #816's per-line NCAAB totals calibration loaded 2026-11-17 00:04:20Z (6:04 PM CST, during the 11-16 slate).
- F2's experts runner on 11-16 then printed `JOIN ncaab half_point checked=9266 mismatched=4296`; every other count
  was 0.
- Two more pricing loads followed on 11-17, inside the window:
  - todo #821, NBA F1 on with the outs penalties off (17:35:08Z);
  - todo #824's NCAAB totals fix (18:03:56Z).

  Whether either breaks the pinned experts' match is not measured.

Re-pinning the experts after each load would need a new amendment every time. Any load after the last re-pin would
still void the read.

**The rule** (in `m2_gate.py`; the diff is below):
- Each test slate's runner output must still carry its `RESULT` line.
- Every unit of that line's `alarms_plus_mismatches` must be attributed to a sport and a phase by the runner's own
  per-sport lines: CHECKLIST, JOIN, FALLBACK_FRAME, PRIOR, SEG_JOIN, SEG_PRIOR. These are every line that adds to the
  count in the pinned `scripts/engine_experts.py`.
- A missing `RESULT` line, or a count those lines do not account for, is still `NOT_A_VERDICT`.
- A sport and phase with any attributed alarm or mismatch on any test slate is `EXCLUDED_REPRODUCTION` for the whole
  window. Like Amendment 1's exclusions, it is never a pass, is not counted as judged, and is still checked for HARM.
- Which phase drops:
  - A live check excludes that sport's live strata. The live checks are JOIN, FALLBACK_FRAME, PRIOR, SEG_JOIN,
    SEG_PRIOR, and the live, stat_progress and live_segment checklists.
  - A pregame checklist alarm excludes that sport's pregame strata.
- The runner prints `EXPERTS <date> reproduction ...` for each slate and `EXCLUDED_REPRODUCTION <sport>|<phase>
  [<date> <check> <n>; ...]`.
- The last line gains `excluded_reproduction=[...]`. A PASS still names its strata, and only those may reach M3.
- The exclusion is by sport and phase, not finer. The runner counts mismatches per sport, not per market, and the
  learner's held-out JSON has no per-slate strata.

**What this costs, known now.** If the pinned experts repeat F2's 11-16 finding, every NCAAB live stratum drops out:
h2h, spreads and totals. That includes NCAAB live totals against a fresh prior, the dev run's near miss (hi99
+0.0002). NCAAB pregame stays in. Nothing else is excluded unless the runner attributes a failure to it.

**What has been read inside the test window before this amendment:**
- F2's experts runner outputs for 11-15 and 11-16 (lane `engine-live-prior`, code `9d6458799`, read 2026-11-17 11:15 AM
  CST). These are reproduction counts and Kalshi-against-book prices, with no outcomes. The gate's own pinned experts
  have not run on any test slate.
- The NBA live-prop grade (lane `nba-live-prop-grade`, registered `89da309e0` on 11-14, run 2026-11-17 9:30 AM CST, in
  this session). It graded NBA player props on slates 11-11..11-16 against the official box score, so NBA outcomes of
  the 11-15 and 11-16 slates have been read here.
  - It judged the stat-progress expert against fresh books, not the learner.
  - This amendment uses no outcome, and it excludes NBA only if the runner attributes a failure to NBA.
- No learner output, no close and no game-line outcome of any test slate has been read for this gate.

**Tested** (`C:\tmp\elp\m2gate_kit\amend2\test_amend2.py`, 4 passed):
- `reproduction()` on the pinned runner's real dev output: 11-13 and 11-14 are clean.
- `reproduction()` on F2's 11-16 output: `{ncaab|live: JOIN 4296}`, all 4,296 attributed.
- Synthetic lines for every check type: each lands in the right phase. A short count is unattributed, and an
  inconsistent `exit` is no `RESULT`.
- `--rehearse` on the 11-16 dev JSON: every line is identical to the current gate's except the verdict's new suffix.
  The verdict is still PASS on NCAAF live spreads and totals, fresh.
- The whole gate on the dev JSON, with the window pointed at the dev test slates (11-13, 11-14):
  - every slate clean: line for line the same as the current gate;
  - NCAAB live mismatched on one slate: the current gate prints `NOT_A_VERDICT`. The amended gate excludes the three
    NCAAB live strata only, still judges NCAAB pregame, and still PASSes NCAAF live;
  - NCAAF live mismatched: its two passes are excluded and there is no PASS;
  - an unattributed count, or a slate with no runner output: `NOT_A_VERDICT`, as before.
- The kit's `code/scripts/engine_experts.py` is the pinned runner: blob `81c5f9e7a253`, the same as `981ef14f6`'s.

**Pins.** `m2_gate.py` is now sha256 `c1a2c029c2a1816fb3f0cbc5d264128a5c3c4fb634d4fb343ea1b6986678e735`. Amendment 1's `6915bb6a...` file is kept beside it as
`m2_gate.amended1_6915bb6a.py`. read.sh, launch.py, manifest.py, the code export and the six train files are unchanged.
The read task checks the new hash, and it records the `EXCLUDED_REPRODUCTION` lines.

```diff
12,13c12,15
<   - the pinned experts reproduced production on every test slate: each out/experts_out_<date>.txt has
<     `RESULT date=<date> ... alarms_plus_mismatches=0 exit=0` (every dev slate did on 2026-11-16).
---
>   - the pinned experts ran on every test slate: each out/experts_out_<date>.txt has its
>     `RESULT date=<date> ... alarms_plus_mismatches=<n> exit=<0|1>` line, and (AMENDMENT 2) every one of its <n> is
>     attributed to a sport and phase by the runner's own per-sport lines (CHECKLIST, JOIN, FALLBACK_FRAME, PRIOR,
>     SEG_JOIN, SEG_PRIOR). n = 0 is a clean slate, as every dev slate was on 2026-11-16.
27a30,36
> AMENDMENT 2 (2026-11-17, before any test-slate outcome, close or learner output is read): a sport whose pinned
>   experts did NOT reproduce production on ANY test slate (an alarm or mismatch attributed to it there) has every
>   stratum of that phase EXCLUDED_REPRODUCTION -- a live check excludes its live strata, a pregame checklist alarm its
>   pregame strata -- never a pass, not counted as judged, still checked for HARM. The rest of the read stands. Why:
>   production's pricing moves inside the window (todo #816 calibrated NCAAB live totals from 2026-11-17 00:04Z) while
>   the experts stay pinned, so a mismatch says that sport's opinions are not what production served, and nothing about
>   any other sport or phase. The learner JSON has no per-slate strata, so one slate excludes the phase for the window.
54a64,75
> # AMENDMENT 2 (registered 2026-11-17, before any test-slate outcome, close or learner output is read): every runner
> # line that adds to RESULT's alarms_plus_mismatches (scripts/engine_experts.py run(), pinned 981ef14f6), with its
> # sport; the trailing groups are its count. CHECKLIST's kind gives the phase (pregame, else live); the rest are live.
> REPRO_LINES = (
>     ("CHECKLIST", re.compile(r"^\s+CHECKLIST (\S+) (pregame|live|stat_progress|live_segment) ok=\S+ alarms=(\d+)")),
>     ("JOIN", re.compile(r"^\s+JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
>     ("FALLBACK_FRAME", re.compile(r"^\s+FALLBACK_FRAME (\S+) judged=\d+ failed=(\d+)")),
>     ("PRIOR", re.compile(r"^\s+PRIOR (\S+) checked=\d+ prior_mismatched=(\d+) p_mismatched=(\d+)")),
>     ("SEG_JOIN", re.compile(r"^\s+SEG_JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
>     ("SEG_PRIOR", re.compile(r"^\s+SEG_PRIOR (\S+) checked=\d+ mismatched=(\d+)")),
> )
> RESULT_RE = re.compile(r"^RESULT date=(\S+) opinions=\d+ alarms_plus_mismatches=(\d+) exit=([01])\s*$")
92a114,137
> def reproduction(lines, d):
>     """AMENDMENT 2: (RESULT's alarms_plus_mismatches or None, {(sport, phase): {check: n > 0}}, attributed total)."""
>     total = None
>     for line in lines:
>         m = RESULT_RE.match(line)
>         if m and m.group(1) == d and (int(m.group(2)) > 0) == (m.group(3) == "1"):
>             total = int(m.group(2))
>     fails, attributed = {}, 0
>     for line in lines:
>         for check, rx in REPRO_LINES:
>             m = rx.match(line)
>             if not m:
>                 continue
>             if check == "CHECKLIST":
>                 phase, n = ("pregame" if m.group(2) == "pregame" else "live"), int(m.group(3))
>             else:
>                 phase, n = "live", sum(int(g) for g in m.groups()[1:])
>             if n:
>                 cell = fails.setdefault((m.group(1), phase), {})
>                 cell[check] = cell.get(check, 0) + n
>                 attributed += n
>     return total, fails, attributed
> 
> 
118c163,164
<     if not a.rehearse:  # the experts reproduced production on every test slate (as on every dev slate, 11-16)
---
>     excluded = {}  # AMENDMENT 2: (sport, phase) -> ["<date> <check> <n>", ...]
>     if not a.rehearse:  # the experts ran on every test slate; whatever did not reproduce is attributed, then excluded
124,128c170,185
<             ok = any(line.startswith(f"RESULT date={d} ") and " alarms_plus_mismatches=0 " in line
<                      and line.rstrip().endswith("exit=0") for line in lines)
<             print(f"EXPERTS {d} reproduction {'clean' if ok else 'NOT CLEAN'}")
<             if not ok:
<                 why.append(f"experts {d}: no clean RESULT line")
---
>             total, fails, attributed = reproduction(lines, d)
>             if total is None:
>                 print(f"EXPERTS {d} reproduction NO RESULT LINE")
>                 why.append(f"experts {d}: no RESULT line")
>             elif attributed != total:
>                 print(f"EXPERTS {d} reproduction UNATTRIBUTED alarms_plus_mismatches={total} attributed={attributed}")
>                 why.append(f"experts {d}: alarms_plus_mismatches={total} but {attributed} attributed to a sport")
>             elif not total:
>                 print(f"EXPERTS {d} reproduction clean")
>             else:
>                 for (sport, phase), checks in sorted(fails.items()):
>                     excluded.setdefault((sport, phase), []).extend(f"{d} {c} {n}" for c, n in sorted(checks.items()))
>                 print(f"EXPERTS {d} reproduction NOT CLEAN alarms_plus_mismatches={total} -> excluded "
>                       f"{', '.join(f'{s}|{p}' for s, p in sorted(fails))}")
>         for (sport, phase), items in sorted(excluded.items()):
>             print(f"EXCLUDED_REPRODUCTION {sport}|{phase} [{'; '.join(items)}]")
148c205,207
<         n_judged += verdict not in ("UNJUDGED", "EXCLUDED_LOOKAHEAD")
---
>         elif (k.split("|")[0], phase) in excluded:
>             verdict = "EXCLUDED_REPRODUCTION"  # AMENDMENT 2: never a pass, never counted as judged; HARM still checked
>         n_judged += verdict not in ("UNJUDGED", "EXCLUDED_LOOKAHEAD", "EXCLUDED_REPRODUCTION")
166a226
>     ex = f" excluded_reproduction=[{', '.join(f'{s}|{p}' for s, p in sorted(excluded))}]"  # AMENDMENT 2
168c228
<         print(f"{tag}M2_VERDICT FAIL harm={len(harms)} [{', '.join(harms)}] judged={n_judged} pass={len(passes)}")
---
>         print(f"{tag}M2_VERDICT FAIL harm={len(harms)} [{', '.join(harms)}] judged={n_judged} pass={len(passes)}{ex}")
170c230
<         print(f"{tag}M2_VERDICT PASS judged={n_judged} pass={len(passes)} [{', '.join(passes)}]")
---
>         print(f"{tag}M2_VERDICT PASS judged={n_judged} pass={len(passes)} [{', '.join(passes)}]{ex}")
172c232
<         print(f"{tag}M2_VERDICT NOTHING_JUDGED strata={len(judged)}")
---
>         print(f"{tag}M2_VERDICT NOTHING_JUDGED strata={len(judged)}{ex}")
174c234
<         print(f"{tag}M2_VERDICT FAIL judged={n_judged} pass=0")
---
>         print(f"{tag}M2_VERDICT FAIL judged={n_judged} pass=0{ex}")
```

## `m2_gate.py` as amended twice (sha256 c1a2c029c2a1816fb3f0cbc5d264128a5c3c4fb634d4fb343ea1b6986678e735)

```python
"""The M2 gate of decision engine #736 (lane engine-learner): one registered verdict over the learner's held-out JSON.

Registered on main BEFORE its data (test slates 2026-11-15..2026-11-22). Applies the rule exactly; no judgment.

Inputs (written by read.sh with the pinned code): out/learner_outcome.{json,txt}, out/learner_close.{json,txt}, both from
  engine_learner.py run --dates 2026-11-09..2026-11-22 --test-from 2026-11-15 --truth outcome|close

PRECONDITIONS (any failure -> `M2_VERDICT NOT_A_VERDICT <why>`, which goes back to the user):
  - each JSON: learner engine_learner/1, tau 0.5, dates 2026-11-09..2026-11-22, test_from 2026-11-15;
  - OFF reproduces the prior (reach.off_nonzero == 0, every OFF delta 0);
  - SPLIT shared=0, and train games >= 95% of the dev window's games registered below (the dev history still reads);
  - the pinned experts ran on every test slate: each out/experts_out_<date>.txt has its
    `RESULT date=<date> ... alarms_plus_mismatches=<n> exit=<0|1>` line, and (AMENDMENT 2) every one of its <n> is
    attributed to a sport and phase by the runner's own per-sport lines (CHECKLIST, JOIN, FALLBACK_FRAME, PRIOR,
    SEG_JOIN, SEG_PRIOR). n = 0 is a clean slate, as every dev slate was on 2026-11-16.

JUDGED STRATA (the gate):
  - LIVE, truth outcome, ON_BY_AGE `sport|family|live|a<=60`: the learner over a FRESH (<= 60 s) prior. The dev run
    showed live gains mostly against stale priors; correcting staleness is the prior's job, not a learner edge.
  - PREGAME, truth close, ON `sport|family|pregame` (props included): the learner toward the close.
  A stratum is judged at >= 30 test games with a CI. hi99 = d + 2.576*se, se = (ci95 hi - ci95 lo) / 3.92 (the
  bootstrap CI read as normal; 99% because ~20-40 strata are judged).
  PASS: hi99 < 0 AND d <= -floor. Floors: LIVE outcome 0.001 nats; PREGAME close 0.0002 nats (a soft label makes tiny
  weights significant: the dev run had 196 cells applied with every group within 0.0001 nats).
HARM (checked on EVERY ON and ON_BY_AGE key of both truths with >= 30 games): lo99 = d - 2.576*se > 0 AND
  d >= the truth's floor (outcome 0.001, close 0.0002) -- the same size test a pass must meet.
AMENDMENT 1 (2026-11-16, before the data): every LIVE stratum of a sport in LOOKAHEAD_EXCLUDED_LIVE (NHL: its
  evidence rows carry state up to 25 s newer than their tick) is EXCLUDED_LOOKAHEAD -- never a pass, not counted as
  judged, still checked for HARM.
AMENDMENT 2 (2026-11-17, before any test-slate outcome, close or learner output is read): a sport whose pinned
  experts did NOT reproduce production on ANY test slate (an alarm or mismatch attributed to it there) has every
  stratum of that phase EXCLUDED_REPRODUCTION -- a live check excludes its live strata, a pregame checklist alarm its
  pregame strata -- never a pass, not counted as judged, still checked for HARM. The rest of the read stands. Why:
  production's pricing moves inside the window (todo #816 calibrated NCAAB live totals from 2026-11-17 00:04Z) while
  the experts stay pinned, so a mismatch says that sport's opinions are not what production served, and nothing about
  any other sport or phase. The learner JSON has no per-slate strata, so one slate excludes the phase for the window.
VERDICT (last line): any HARM -> FAIL; else any PASS -> PASS <strata>; else no stratum judged -> NOTHING_JUDGED;
  else FAIL. An unjudged stratum is never a pass. PASS lets M3 (the paper book) consume p_decision for the PASS strata
  only; anything else keeps the learner shadow-only and goes back to the user.

`--rehearse` skips the window and train-size preconditions (for dev-window JSON) and marks every line REHEARSAL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATES = ("2026-11-09", "2026-11-22")
TEST_FROM = "2026-11-15"
TEST_DATES = tuple(f"2026-11-{d}" for d in range(15, 23))
MIN_GAMES = 30
Z99 = 2.576
FLOOR = {"live": 0.001, "pregame": 0.0002}
FRESH = "a<=60"
# AMENDMENT 1 (registered 2026-11-16, before the data): a sport whose dev evidence rows carry game state NEWER than
# their own tick lets an opinion see past the line it is scored against, so its live strata cannot pass. Measured on
# the dev logs 11-09..11-14 (state `as_of` minus tick `t`, priced rows): NHL 1,839 of 3,307 newer, by up to 25 s.
# Sub-second elsewhere, kept: NCAAF 318 of 2,800 (<= 0.73 s; those line-instants carry no gain in the dev breakdown),
# NFL 34 of 34 (<= 0.99 s); NBA, NCAAB, WNCAAB 0.
LOOKAHEAD_EXCLUDED_LIVE = {"nhl"}
# AMENDMENT 2 (registered 2026-11-17, before any test-slate outcome, close or learner output is read): every runner
# line that adds to RESULT's alarms_plus_mismatches (scripts/engine_experts.py run(), pinned 981ef14f6), with its
# sport; the trailing groups are its count. CHECKLIST's kind gives the phase (pregame, else live); the rest are live.
REPRO_LINES = (
    ("CHECKLIST", re.compile(r"^\s+CHECKLIST (\S+) (pregame|live|stat_progress|live_segment) ok=\S+ alarms=(\d+)")),
    ("JOIN", re.compile(r"^\s+JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
    ("FALLBACK_FRAME", re.compile(r"^\s+FALLBACK_FRAME (\S+) judged=\d+ failed=(\d+)")),
    ("PRIOR", re.compile(r"^\s+PRIOR (\S+) checked=\d+ prior_mismatched=(\d+) p_mismatched=(\d+)")),
    ("SEG_JOIN", re.compile(r"^\s+SEG_JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
    ("SEG_PRIOR", re.compile(r"^\s+SEG_PRIOR (\S+) checked=\d+ mismatched=(\d+)")),
)
RESULT_RE = re.compile(r"^RESULT date=(\S+) opinions=\d+ alarms_plus_mismatches=(\d+) exit=([01])\s*$")
# Dev-window games (slates 11-09..11-14, train + test of the 2026-11-16 re-run with the experts on main 981ef14f6).
DEV_GAMES = {"outcome": 804, "close": 427}  # the 2026-11-16 dev re-fit, train + test games
TRAIN_SHARE_MIN = 0.95
SPLIT_RE = re.compile(r"^SPLIT train=\d+ \((\d+) games.*test=\d+ \((\d+) games.*shared=(\d+)")


def se_of(ci):
    lo, hi = ci
    return None if lo is None or hi is None else (hi - lo) / 3.92


def precheck(name, d, txt, rehearse):
    why = []
    if d.get("learner") != "engine_learner/1" or d.get("tau") != 0.5:
        why.append(f"{name}: learner/tau {d.get('learner')}/{d.get('tau')}")
    if not rehearse and ((d.get("dates") or [None])[0], (d.get("dates") or [None])[-1]) != DATES:
        why.append(f"{name}: dates {d.get('dates', [])[:1]}..{d.get('dates', [])[-1:]}")
    if not rehearse and d.get("test_from") != TEST_FROM:
        why.append(f"{name}: test_from {d.get('test_from')}")
    if (d.get("reach") or {}).get("off_nonzero") != 0:
        why.append(f"{name}: OFF moved {d.get('reach', {}).get('off_nonzero')} examples")
    if any(v.get("delta_log_loss") != 0.0 for v in (d.get("held_out", {}).get("OFF") or {}).values()):
        why.append(f"{name}: an OFF delta is not 0")
    m = next((SPLIT_RE.match(line) for line in txt.splitlines() if line.startswith("SPLIT ")), None)
    if not m:
        why.append(f"{name}: no SPLIT line")
    else:
        train_games, test_games, shared = map(int, m.groups())
        if shared:
            why.append(f"{name}: shared={shared}")
        need = DEV_GAMES.get(name)
        if not rehearse and (need is None or train_games < TRAIN_SHARE_MIN * need):
            why.append(f"{name}: train games {train_games} < {TRAIN_SHARE_MIN} x dev {need}")
        print(f"{'REHEARSAL ' if rehearse else ''}SPLIT {name} train_games={train_games} test_games={test_games} "
              f"shared={shared} dev_registered={need}")
    return why


def reproduction(lines, d):
    """AMENDMENT 2: (RESULT's alarms_plus_mismatches or None, {(sport, phase): {check: n > 0}}, attributed total)."""
    total = None
    for line in lines:
        m = RESULT_RE.match(line)
        if m and m.group(1) == d and (int(m.group(2)) > 0) == (m.group(3) == "1"):
            total = int(m.group(2))
    fails, attributed = {}, 0
    for line in lines:
        for check, rx in REPRO_LINES:
            m = rx.match(line)
            if not m:
                continue
            if check == "CHECKLIST":
                phase, n = ("pregame" if m.group(2) == "pregame" else "live"), int(m.group(3))
            else:
                phase, n = "live", sum(int(g) for g in m.groups()[1:])
            if n:
                cell = fails.setdefault((m.group(1), phase), {})
                cell[check] = cell.get(check, 0) + n
                attributed += n
    return total, fails, attributed


def judge(key, v, floor):
    games, ci, d = v.get("games", 0), v.get("ci95") or [None, None], v.get("delta_log_loss")
    se = se_of(ci)
    if games < MIN_GAMES or se is None:
        return "UNJUDGED", None
    hi99 = d + Z99 * se
    return ("PASS" if hi99 < 0 and d <= -floor else "FAIL"), hi99


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="dir holding learner_{outcome,close}.{json,txt}")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()
    tag = "REHEARSAL " if a.rehearse else ""
    out = Path(a.out)
    data, txts = {}, {}
    for t in ("outcome", "close"):
        try:
            data[t] = json.loads((out / f"learner_{t}.json").read_text(encoding="utf-8"))
            txts[t] = (out / f"learner_{t}.txt").read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            print(f"{tag}M2_VERDICT NOT_A_VERDICT missing/unreadable {t}: {exc}")
            return 2
    why = [w for t in ("outcome", "close") for w in precheck(t, data[t], txts[t], a.rehearse)]
    excluded = {}  # AMENDMENT 2: (sport, phase) -> ["<date> <check> <n>", ...]
    if not a.rehearse:  # the experts ran on every test slate; whatever did not reproduce is attributed, then excluded
        for d in TEST_DATES:
            try:
                lines = (out / f"experts_out_{d}.txt").read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            total, fails, attributed = reproduction(lines, d)
            if total is None:
                print(f"EXPERTS {d} reproduction NO RESULT LINE")
                why.append(f"experts {d}: no RESULT line")
            elif attributed != total:
                print(f"EXPERTS {d} reproduction UNATTRIBUTED alarms_plus_mismatches={total} attributed={attributed}")
                why.append(f"experts {d}: alarms_plus_mismatches={total} but {attributed} attributed to a sport")
            elif not total:
                print(f"EXPERTS {d} reproduction clean")
            else:
                for (sport, phase), checks in sorted(fails.items()):
                    excluded.setdefault((sport, phase), []).extend(f"{d} {c} {n}" for c, n in sorted(checks.items()))
                print(f"EXPERTS {d} reproduction NOT CLEAN alarms_plus_mismatches={total} -> excluded "
                      f"{', '.join(f'{s}|{p}' for s, p in sorted(fails))}")
        for (sport, phase), items in sorted(excluded.items()):
            print(f"EXCLUDED_REPRODUCTION {sport}|{phase} [{'; '.join(items)}]")
    if why:
        print(f"{tag}M2_VERDICT NOT_A_VERDICT {'; '.join(why)}")
        return 2

    judged = []  # (key, truth, phase, v)
    for k, v in sorted(data["outcome"]["held_out"].get("ON_BY_AGE", {}).items()):
        parts = k.split("|")
        if len(parts) == 4 and parts[2] == "live" and parts[3] == FRESH:
            judged.append((k, "outcome", "live", v))
    for k, v in sorted(data["close"]["held_out"].get("ON", {}).items()):
        parts = k.split("|")
        if len(parts) == 3 and parts[2] == "pregame":
            judged.append((k, "close", "pregame", v))

    passes, n_judged = [], 0
    for k, t, phase, v in judged:
        verdict, hi99 = judge(k, v, FLOOR[phase])
        if phase == "live" and k.split("|")[0] in LOOKAHEAD_EXCLUDED_LIVE:
            verdict = "EXCLUDED_LOOKAHEAD"  # AMENDMENT 1: never a pass, never counted as judged; HARM still checked
        elif (k.split("|")[0], phase) in excluded:
            verdict = "EXCLUDED_REPRODUCTION"  # AMENDMENT 2: never a pass, never counted as judged; HARM still checked
        n_judged += verdict not in ("UNJUDGED", "EXCLUDED_LOOKAHEAD", "EXCLUDED_REPRODUCTION")
        if verdict == "PASS":
            passes.append(f"{k}({t})")
        print(f"{tag}STRATUM {k} truth={t} games={v.get('games')} lines={v.get('lines')} d_ll={v.get('delta_log_loss')} "
              f"ci95={v.get('ci95')} hi99={None if hi99 is None else round(hi99, 6)} floor={FLOOR[phase]} -> {verdict}")

    harms = []
    for t in ("outcome", "close"):
        for rep in ("ON", "ON_BY_AGE"):
            for k, v in sorted(data[t]["held_out"].get(rep, {}).items()):
                se = se_of(v.get("ci95") or [None, None])
                floor = FLOOR["live"] if t == "outcome" else FLOOR["pregame"]
                if (v.get("games", 0) >= MIN_GAMES and se is not None and v["delta_log_loss"] - Z99 * se > 0
                        and v["delta_log_loss"] >= floor):
                    harms.append(f"{t}:{rep}:{k}")
                    print(f"{tag}HARM {t} {rep} {k} games={v.get('games')} d_ll={v.get('delta_log_loss')} "
                          f"ci95={v.get('ci95')}")
    applied = {t: (data[t].get("reach") or {}).get("applied_cells") for t in data}
    print(f"{tag}APPLIED_CELLS outcome={applied['outcome']} close={applied['close']}")
    ex = f" excluded_reproduction=[{', '.join(f'{s}|{p}' for s, p in sorted(excluded))}]"  # AMENDMENT 2
    if harms:
        print(f"{tag}M2_VERDICT FAIL harm={len(harms)} [{', '.join(harms)}] judged={n_judged} pass={len(passes)}{ex}")
    elif passes:
        print(f"{tag}M2_VERDICT PASS judged={n_judged} pass={len(passes)} [{', '.join(passes)}]{ex}")
    elif n_judged == 0:
        print(f"{tag}M2_VERDICT NOTHING_JUDGED strata={len(judged)}{ex}")
    else:
        print(f"{tag}M2_VERDICT FAIL judged={n_judged} pass=0{ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```


## Context for the 11-24 read: the live re-sims changed inside the windows (filed 2026-11-18 10:39 AM CST, before the read; the rule is unchanged)

The live expert reads what the live re-sims publish, and they changed on the fleet inside both of M2's windows (train
11-09..11-14, test 11-15..11-22). So M2's fit applies weights learned on one set of re-sims to opinions from a later
set: a harder test, not an invalid one. Nothing in the rule changes; this is filed before the read so the result is
read with it. The full timeline, and how each load was found: `.syndicate/findings_2026-11-17_m3_paper_book.md`, Addendum 5.

- **NBA:** the closing-line margin anchor (`68fbb8eeb`) loaded about 11-14 9:37 AM CST. Of the train window only
  11-14's games ran anchored; every test night does. The test window also has the starter-exit refusals (loaded
  11-15 12:25 PM and 11-16 12:15 PM). Earlier train-window changes: the canonical player key (11-09), re-simming past
  midnight (11-10), recording P(overtime) (11-11).
- **NCAAF:** in the train window the only change was display-only (segment blocks, 11-11). The test window adds the
  QB-exit refusals (11-15 12:24 PM and 7:28 PM), the `#808` end-of-half switches (11-16 10:29 AM, all default OFF) and
  an MLB edit to the shared exit-gate file (11-17 9:47 AM).
- **NFL:** the test window adds the QB-exit refusals (11-15), the `#808` switches and the real timeouts left
  (11-16 10:29 AM), the drive in progress and ESPN's timeouts carried in (11-17 9:47 AM), and per-game seeding
  (11-18 2:03 AM).
- These are role loads, not commit times. NBA before 11-14 10:29 AM is approximate (see the addendum).


## Correction to the context note above (2026-11-18 11:51 AM CST, before the read; the rule is unchanged)

The note missed one change. **F1 of todo `#821`** (`feed_game_model` with the outs penalties off, in the NBA processed root's `nba_sim_total_inputs.json`) was switched on 2026-11-17 at 11:35 AM CST (`deploys.md` 17:34:59Z). It is a data-file switch, not code, so the version timeline cannot see it. It moves the NBA pregame sim's totals, which the NBA live re-sim starts from. Lane `nba-live-total-anchor` measured 11-18's 12 NBA pregame totals at +6.78 (se 1.04) above the closing line (`.syndicate/findings_2026-11-18_nba_live_total_anchor.md`). So the NBA test nights from 11-17 on start from a pregame total level unlike any
training night's. Env and data-file switches are outside M3 Addendum 5's timeline; `deploys.md` is where they are
recorded.


## POST-READ DIAGNOSIS: THE NBA LIVE TOTALS HARM (PRE-REGISTERED 2026-11-24 2:13 PM CST, before any diagnostic number was computed)

User: "Yes, diagnose it" (11-24, answering "Diagnose the NBA live totals harm before re-registering M2?").

- **It gates nothing.** The M2 verdict (FAIL, `50319e3d3`) stands whatever this finds. The diagnosis only informs how a
  fresh M2 would be registered, which is the user's call.
- **H1.** The harm comes from `#821` F1, the data-file switch flipped 2026-11-17 at 11:35 AM CST (`deploys.md`
  17:34:59Z; correction above, `89ff009f2`).
  - NBA test nights from 11-17 start from pregame totals about +6.8 above the close. No training night (11-09..11-14)
    did.
  - The registered fit applied live-expert weights of +0.66 to +1.41 on NBA live totals cells, all fitted before F1
    (e.g. `live_resim nba/totals/totals/full/live/25-50/a<=60` w +1.411 se 0.508; `totals_alt 25-50` +0.838; `totals_alt
    75-95` +0.659).
  - So the learner carried the re-sim's new over-lean into p_decision.
- **Population.** The registered read's own examples, rebuilt by its pinned code: main `981ef14f6`, sha256
  `e59d7d6f94c5` (scripts/engine_learner.py) and `b9d5db099b91` (the module).
  - Registered arguments: truth outcome, dates 11-09..11-22, test from 11-15, tau 0.5, chips from the fleet.
  - Opinions are the read's own `train/` and `test/` files in `C:\tmp\elp\m2gate_kit`.
  - The stratum is cell sport `nba`, family `totals`, phase `live`, prior age `a<=60`.
  - Run at nice 19, read-only on the fleet. Output goes to `C:\tmp\elp\m2diag\`.
- **P0, the reproduction gate.** The rebuilt `ON_BY_AGE nba|totals|live|a<=60` must give games 60, d_ll +0.024058 and
  ci95 [0.013761, 0.034215]. If it is not exact, no diagnostic number is reported.
- **Arms by game date.** PRE = 11-15 and 11-16 (before F1). POST = 11-17..11-22.
- **T1, primary.** d_ll(POST) - d_ll(PRE), each arm bootstrapped over its own games (1000 draws, seed 736), 95% CI.
  - SUPPORTED: the difference's low end > 0, AND PRE's own ci95 includes 0 or lies below it.
  - FALSIFIED: PRE's own ci95 lies above 0 (the harm was there before F1), OR the difference's high end < 0.
  - Otherwise INCONCLUSIVE. This is a stated risk: PRE has two nights only.
- **T2, mechanism.** The live_resim expert's weighted mean delta-logit toward OVER (sign flipped on under rows) on the
  stratum's rows, for train vs PRE vs POST, with game-bootstrap CIs.
  - H1 predicts POST - train > 0 with its CI above 0, and PRE - train's CI includes 0.
- **T3, where the loss is.** In POST, the weighted mean of p_decision(over) minus the realised over rate, with a
  game-bootstrap CI.
  - H1 predicts > 0 with its CI above 0: the learner priced overs too high.
  - H1 also predicts the learner's own move toward over (logit p_decision - logit p_prior) is > 0.
- **Descriptive only, no prediction:**
  - the same PRE/POST split for `nba|spreads|live|a<=60` and `nba|h2h|live|a<=60`. The NBA margin anchor loaded
    11-14, so those carry a different confound.
  - the POST harm by segment, market (totals / totals_alt) and clock bucket;
  - the POST harm with each expert's weight zeroed in turn.
