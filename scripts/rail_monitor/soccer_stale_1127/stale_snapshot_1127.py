"""11-27 (the fleet-watcher's flag, Santander @ Levante not_in_resim R17/R18): label a game missing from a snapshot that
is itself stale as "snapshot_stale", not "not_in_resim", and report each sport's snapshot age. The soccer live lens sat
at 20:01:59Z from 20:02Z to 21:47Z (its memory gate skipped every tick), so every 2 PM kickoff read as a possible name
miss. Edits the running copies in C:\\tmp\\railmon (p29_orient.py, dash\\dash_update.py, railwatch\\tick.py,
railwatch\\page.py) and their repo backups. .tmp + os.replace; idempotent; asserts each anchor occurs once."""
import os
import shutil

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a\scripts\rail_monitor"
FILES = {  # running copy -> repo backup
    r"C:\tmp\railmon\p29_orient.py": os.path.join(W, "p29_orient.py"),
    r"C:\tmp\railmon\dash\dash_update.py": os.path.join(W, "dash_update.py"),
    r"C:\tmp\railmon\railwatch\tick.py": os.path.join(W, "railwatch_tick.py"),
    r"C:\tmp\railmon\railwatch\page.py": os.path.join(W, "railwatch_page.py"),
}

P29 = [
    ("import json, subprocess, sys, unicodedata, urllib.request\n",
     "import json, subprocess, sys, unicodedata, urllib.request\nfrom datetime import datetime, timezone\n"),
    ("\n\nrail = json.load(urllib.request.urlopen(",
     "\n\n"
     "# 11-27 R15-R18 (the fleet-watcher's flag): \"Real Racing Club de Santander @ Levante\" read not_in_resim in two\n"
     "# straight readings. Not a name miss (find() matches \"Racing Santander\" / \"Racing de Santander\" / \"Real Racing Club\"):\n"
     "# the soccer live lens was not rewritten from 20:01:59Z to 21:47Z, because its memory gate (300 MB headroom on the\n"
     "# 3,072 MB live-odds-worker) skipped every tick (LIVE_LENS_TICK_DIAG sport=soccer reason=low_headroom, 63 in 20-21Z),\n"
     "# so no 20:00Z kickoff was in it. A game missing from a snapshot older than this is \"snapshot_stale\": the writer, not\n"
     "# the helper. Every writer here rewrites each tick (1-4 min) while its sport has a live game; 900 s is a stall.\n"
     "STALE_SNAPSHOT_S = 900\n"
     "\n"
     "\n"
     "def snapshot_age_s(snap):\n"
     "    \"\"\"Seconds since the snapshot's generatedAt / generated_at; None when absent, unparseable or naive.\"\"\"\n"
     "    raw = (snap or {}).get(\"generatedAt\") or (snap or {}).get(\"generated_at\") if isinstance(snap, dict) else None\n"
     "    try:\n"
     "        t = datetime.fromisoformat(str(raw).replace(\"Z\", \"+00:00\"))\n"
     "    except (TypeError, ValueError):\n"
     "        return None\n"
     "    if t.tzinfo is None:\n"
     "        return None\n"
     "    return max(0.0, (datetime.now(timezone.utc) - t).total_seconds())\n"
     "\n"
     "\n"
     "rail = json.load(urllib.request.urlopen("),
    ("        index = [(names(g), g) for g in (games or []) if isinstance(g, dict)]\n",
     "        index = [(names(g), g) for g in (games or []) if isinstance(g, dict)]\n"
     "    age = snapshot_age_s(snap)\n"),
    ("        if state == \"not_in_resim\":  # say how old the snapshot is: a game that kicked off after it is not a defect\n"
     "            detail = f\"snapshot generated {(snap or {}).get('generatedAt') or (snap or {}).get('generated_at')}\"\n",
     "        if state == \"not_in_resim\":  # say how old the snapshot is: a game that kicked off after it is not a defect\n"
     "            gen = (snap or {}).get('generatedAt') or (snap or {}).get('generated_at')\n"
     "            detail = f\"snapshot generated {gen}\"\n"
     "            if age is not None and age > STALE_SNAPSHOT_S:\n"
     "                state = \"snapshot_stale\"\n"
     "                detail = (f\"snapshot generated {gen}, {age / 60:.0f} min old: its writer has not rewritten it, \"\n"
     "                          f\"so a game that started since is absent (not a name miss)\")\n"),
    ("        summaries.append(dict(sport=sport, resim_generated=snap.get(\"generatedAt\") or snap.get(\"generated_at\"),\n"
     "                              resim_games=len(index), counts=snap.get(\"counts\") or snap.get(\"coverage\")))\n",
     "        summaries.append(dict(sport=sport, resim_generated=snap.get(\"generatedAt\") or snap.get(\"generated_at\"),\n"
     "                              resim_age_s=None if age is None else round(age),\n"
     "                              resim_games=len(index), counts=snap.get(\"counts\") or snap.get(\"coverage\")))\n"),
]

DASH = [
    ("    # \"not_in_resim\" (no snapshot entry matched, possibly this helper's name miss: check); \"sport_absent_from_helper_read\"\n",
     "    # \"not_in_resim\" (no snapshot entry matched, possibly this helper's name miss: check); 11-27: \"snapshot_stale\" (no\n"
     "    # entry matched AND the sport's snapshot is over 900 s old: its writer stalled, not a name miss -- the soccer lens's\n"
     "    # memory gate 20:02-21:47Z 11-27); \"sport_absent_from_helper_read\"\n"),
    ("                if o.get(\"matchup\"):\n"
     "                    orient[f\"{o.get('sport')} {o.get('matchup')}\"] = o\n",
     "                if o.get(\"matchup\"):\n"
     "                    orient[f\"{o.get('sport')} {o.get('matchup')}\"] = o\n"
     "                elif o.get(\"sport\") and isinstance(o.get(\"resim_age_s\"), (int, float)) and o[\"resim_age_s\"] > 900:\n"
     "                    # 11-27: a sport with live rail games whose snapshot is stale. Its games still IN the snapshot\n"
     "                    # carry a model that stopped moving (soccer has no lane-age ceiling in the live join), so this\n"
     "                    # is reported even when no game is on the no-model list.\n"
     "                    stale_snapshots[o[\"sport\"]] = {\"age_s\": o[\"resim_age_s\"], \"generated\": o.get(\"resim_generated\"),\n"
     "                                                  \"games_in_snapshot\": o.get(\"resim_games\")}\n"),
    ("    reasons, details = {}, {}\n    orient = {}\n",
     "    reasons, details = {}, {}\n    orient = {}\n    stale_snapshots = {}\n"),
    ("        elif o.get(\"resim\") in (\"not_in_resim\", \"no_snapshot\"):\n",
     "        elif o.get(\"resim\") in (\"not_in_resim\", \"no_snapshot\", \"snapshot_stale\"):\n"),
    ("        \"live_games_no_model_detail\": details,\n",
     "        \"live_games_no_model_detail\": details,\n"
     "        \"stale_snapshots\": stale_snapshots,\n"),
]

TICK = [
    ("('not matched in the re-sim snapshot' if o.get('resim') == 'not_in_resim' else ",
     "('not matched in the re-sim snapshot' if o.get('resim') == 'not_in_resim' else html.escape('the live snapshot is stale, so a game that started since is absent: ' + str(o.get('detail') or '')) if o.get('resim') == 'snapshot_stale' else "),
]

PAGE = [
    ("           else (\"not matched in the re-sim snapshot\" if o.get(\"resim\") == \"not_in_resim\"\n",
     "           else (\"not matched in the re-sim snapshot\" if o.get(\"resim\") == \"not_in_resim\"\n"
     "                 else esc(\"the live snapshot is stale, so a game that started since is absent: \" + str(o.get(\"detail\") or \"\"))\n"
     "                 if o.get(\"resim\") == \"snapshot_stale\"\n"),
]

EDITS = {r"C:\tmp\railmon\p29_orient.py": P29, r"C:\tmp\railmon\dash\dash_update.py": DASH,
         r"C:\tmp\railmon\railwatch\tick.py": TICK, r"C:\tmp\railmon\railwatch\page.py": PAGE}

for path, edits in EDITS.items():
    s = open(path, encoding="utf-8", newline="").read()
    crlf = "\r\n" in s
    if crlf:
        s = s.replace("\r\n", "\n")
    changed = 0
    for old, new in edits:
        if new in s:
            continue
        assert s.count(old) == 1, (path, old[:80], s.count(old))
        s = s.replace(old, new)
        changed += 1
    if crlf:
        s = s.replace("\n", "\r\n")
    if changed:
        compile(s.replace("\r\n", "\n"), path, "exec")  # never leave a running copy that does not parse
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(s)
        os.replace(tmp, path)
    print(path, "edits applied", changed, "of", len(edits))
    dst = FILES[path]
    tmp = dst + ".tmp"
    shutil.copyfile(path, tmp)
    os.replace(tmp, dst)
    print("  copied to", dst)
