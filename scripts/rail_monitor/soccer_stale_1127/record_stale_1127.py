"""Record the 11-27 Santander @ Levante answer: lane STATUS, a findings section, and copy the readers into
scripts/rail_monitor/soccer_stale_1127/. .tmp + os.replace; idempotent. Stamps the clock it reads."""
import os
import shutil
from datetime import datetime, timedelta, timezone

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
now = datetime.now(timezone.utc)
ct = now - timedelta(hours=6)
stamp = ct.strftime("%I:%M %p").lstrip("0") + " CST"


def load(p):
    s = open(p, encoding="utf-8", newline="").read()
    return s, ("\r\n" if "\r\n" in s else "\n")


def save(p, s):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("wrote", p)


TAG = "Santander @ Levante not_in_resim: NOT a name miss"
s, nl = load(LANES)
head = "### layer2-rail-monitor \u2014 OPEN \u2014 opened 2026-11-15"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
marker = "- **STATUS 2026-11-27 10:33 AM CST: after-midnight rail fix (a1) LOADED on web, MET**"
status = (f"- **STATUS 2026-11-27 {stamp}: {TAG}** (the fleet-watcher's R17/R18 flag). The soccer live lens sat at "
          "20:01:59Z from 20:02Z to 21:47Z: its memory gate (300 MB headroom, live-odds-worker 3,072 MB at 98-142% of max) "
          "skipped every soccer tick (63 `LIVE_LENS_TICK_DIAG sport=soccer reason=low_headroom` in 20-21Z), so no 20:00Z "
          "kickoff was in it (Chelsea @ Forest, Nacional @ Maritimo too). `find()` matches the rail name to \"Racing "
          "Santander\" / \"Racing de Santander\" / \"Real Racing Club\". Helper change (monitor only, no deploy): a miss "
          "against a snapshot > 900 s old now reads `snapshot_stale`, and each row carries `stale_snapshots` (R18 replay: "
          "soccer 6,063 s, 6 games). Fleet findings for the user, not fixed here: soccer has no lane-age ceiling, so the 6 "
          "games in the frozen lens kept being priced (14-38 rows per build); 2 in-play PAPER orders on it (Bologna @ "
          "Venezia totals 1.5, edge 32 pp, 21 min stale), 0 live-money soccer orders. Findings 11-26 file, that section.")
if TAG in blk:
    print("lane status already there")
else:
    assert blk.count(marker) == 1
    k = blk.index(marker)
    save(LANES, s[:i] + blk[:k] + status + nl + blk[k:] + s[j:])

s, nl = load(FIND)
title = "## Santander @ Levante not_in_resim (R17/R18 11-27): the soccer live lens was frozen, not a name miss"
if title in s:
    print("findings already there")
else:
    sec = [
        "", title, "",
        "- **Flag:** the fleet-watcher, R17 (3:23 PM) and R18 (3:43 PM): `soccer Real Racing Club de Santander @ Levante` "
        "reason `not_in_resim`; its guesses were a cup match (`competition_not_modelled`) or a name-fold miss like Bodo / "
        "Kobenhavn. Neither.",
        "- **Measured:** every reading R15-R18 (2:43-3:43 PM) read the soccer snapshot as `generated 2026-11-27T14:01:59-06:00`; "
        "R15-R17 listed Chelsea @ Nottingham Forest and Nacional @ CS Maritimo the same way (all three kicked off 20:00Z). "
        "live-odds-worker: `TICK_COMPLETE` soccer True at 20:02:15Z, then not again until 21:47:56Z; "
        "`LIVE_LENS_TICK_DIAG sport=soccer ok=False reason=low_headroom` 31 in 20Z, 32 in 21Z (5-22 an hour 15-19Z), headroom "
        "210-230 MB against the 300 MB floor (`_soccer_live_lens_min_headroom_bytes`, live_lens_loop.py:534); container "
        "memory 80-143% of its 3,072 MB max in every 10 minutes 19:50-22:00Z. The autorun kept launching (58 in 19:55-22:05Z, "
        "17 `RefreshLaneBusy`). The 22:05Z lens (generated 15:57:19 CST) held 1 game, Nacional @ Maritimo 83'.",
        "- **The helper is right:** `find()` matches the rail's \"Real Racing Club de Santander @ Levante\" to \"Racing Santander\", "
        "\"Racing de Santander\" (\"Levante UD\") and \"Real Racing Club\", and still rejects a Real Sociedad @ Levante decoy "
        "(C:\\tmp\\railmon\\fold_test_1127.py).",
        "- **Helper change (monitor only):** `p29_orient.py` labels a miss against a snapshot over 900 s old `snapshot_stale` "
        "(detail: its age, \"not a name miss\") and puts `resim_age_s` on each sport's summary line; `dash_update.py` passes "
        "the reason through and adds `stale_snapshots` {sport: age_s, generated, games_in_snapshot} to every row; both page "
        "builders say \"the live snapshot is stale\". R18 replayed through it: Santander @ Levante -> `snapshot_stale` "
        "(101 min), `stale_snapshots` soccer 6,063 s / 6 games; ncaab, ncaaf, nhl, wncaab 0 s, nfl 241 s. A live run at "
        "22:14Z: rc 0, every sport 30-100 s old.",
        "- **Fleet findings (not fixed here; for the user):**",
        "  - Soccer has NO lane-age ceiling in the live join (`_MAX_LANE_AGE_SECONDS_BY_SPORT`, live_gameline_join.py:792: "
        "basketball and football only). The 6 games already in the 20:01:59Z lens kept being priced: `LIVE_GAMELINE_JOIN "
        "sport=soccer` priceable 14-38 per build 20:08-21:35Z, `LIVE_PROJECTION_JOIN` edged_modelled 325-555, from a model up "
        "to ~95 min old.",
        "  - Orders on it: 32 soccer orders submitted 20:02-21:48Z, all PAPER; 2 in play, both Bologna @ Venezia totals 1.5 at "
        "20:22Z (kalshi and polymarket ladders, edge 32.14 pp, the lens 21 min old). 0 live-money soccer orders (ledger "
        "archive shard + keyvalue document).",
        "  - The memory gate itself: the live-odds-worker ran over its cap for most of the afternoon. MLB 112 and WNBA 118 "
        "low-headroom skips on 11-27 too.",
        "- **Readers:** `scripts/rail_monitor/soccer_stale_1127/` (gate counts, priced rows, orders, the R18 replay).",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "soccer_stale_1127")
os.makedirs(dst, exist_ok=True)
for f in ("soccer_writer_1127.sh", "soccer_gate_1127.sh", "soccer_stale_priced_1127.sh", "soccer_ledger3_1127.py",
          "fold_test_1127.py", "replay_r18_1127.py", "diag_1127_santander.py", "stale_snapshot_1127.py",
          "record_stale_1127.py"):
    tmp = os.path.join(dst, f + ".tmp")
    shutil.copyfile(os.path.join(r"C:\tmp\railmon", f), tmp)
    os.replace(tmp, os.path.join(dst, f))
print("copied readers to", dst, "| stamp", stamp)
