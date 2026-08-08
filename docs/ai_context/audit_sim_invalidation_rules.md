# Audit: what invalidates a sim, and what forces a re-run

**Date:** 2026-08-08 · **Scope:** all sports, MLB in depth · **Status:** audit only, nothing changed

Commissioned as: *"we need to inspect our rules around sims overall esp MLB when
it comes to lineup/start changes and final lineups"*, flagged as blocking the
Layer 2 board rebuild. There was no written statement of these rules anywhere in
the repo; this is that statement, plus the gaps it exposes.

**Method.** Read the trigger paths in `live_refresh_loop.py`,
`run_refresh_worker.py` and `ops.py`, and traced each trigger back to the
artifact it reads and to whatever refreshes that artifact. Claims below are from
source unless marked *measured*.

---

## 1. Coverage is MLB-complete, NBA/WNBA-partial, absent everywhere else

| sport | what can invalidate a sim | mechanism |
|---|---|---|
| **MLB** | lineups, odds, probable-pitcher overrides, injuries, board gaps, tip-off | 6 triggers, per-game scoped (§2) |
| **NBA / WNBA** | lineups + injuries | `_should_force_sim_rerun` fingerprint → forces `mode="full"` odds refresh |
| **NHL, NFL, NCAAF, NCAAB, soccer** | **nothing** | interval autoruns only — purely time-driven |

`_mlb_daily_sim_decision`, `_mlb_evening_next_day_sim_decision` and
`_run_mlb_sim_tick` have **no counterpart for any other sport**.
`_LINEUP_INJURY_FETCH_PACKAGES` is `{"nba", "wnba"}`.

So for five of eight sports the answer to "what forces a re-run" is **the clock,
and only the clock**. A scratched starter, a posted lineup or a late injury
cannot cause a re-sim, because nothing reads them.

---

## 2. MLB's six triggers (`_mlb_daily_sim_decision`)

Evaluated in order; results merge into one scoped launch.

| # | trigger | fires when | input |
|---|---|---|---|
| 1 | `first_appearance` | `daily_summary_<date>.json` **does not exist** | file existence |
| 2 | `tip_off_window` | a game starts within 30 min (`SYNDICATE_EVENT_SIM_FORCE_WINDOW_MINUTES`) | schedule |
| 3 | `fingerprint_change` | per-game hash moves | lineups + odds + overrides + injuries |
| 4 | `join_mismatch` | odds↔sim join disagrees (catches probable-pitcher swaps) | market board — *gated on memory headroom* |
| 5 | `board_missing` | a scheduled game has no sim on the board | daily summary |
| 6 | `props_regen` | top-props artifact is empty | props artifact |

Checked at most every `SYNDICATE_MLB_SIM_CHECK_INTERVAL_SECONDS` (**default 600s**),
except that the tip-off window bypasses the interval.

This is a genuinely well-built set. The gaps below are not "nobody thought about
this" — they are places where the *inputs* fail the triggers.

---

## 3. FINDING 1 (headline) — "already simmed" means *a file exists*, not *the sim is still valid*

Two decisions, in the same file, that compose into the defect:

```python
# _mlb_evening_next_day_sim_decision:2356 -- writes tomorrow's summary tonight
if _mlb_daily_summary_path(target_date).exists():
    return {"force": False, "reason": "already_simmed"}

# _mlb_daily_sim_decision:1544 -- and tomorrow, this never fires again
if not _mlb_daily_summary_path(date_str).exists():
    return {"force": True, "reason": "first_appearance"}
```

The evening look-ahead sims tomorrow's slate and writes
`daily_summary_<tomorrow>.json`. When tomorrow arrives, `first_appearance` sees
the file and declines. **A sim built at 18:36 the previous evening is
indistinguishable from one built at noon on game day.** Nothing records what a
sim was computed *from*, so nothing can decide it has gone stale.

*Measured (2026-08-07, by the prior session):* the MLB daily-update for 08-07 ran
**once**, at 2026-08-06T18:36 Central — ~22 hours before the slate. `hr_targets`
got 30 rows; `k_targets` got **0**, because it ran before that day's inputs
existed. Today's artifact was the only one missing `source_snapshot_dir`.

This is the direct answer to "when does a sim become invalid": **today, it never
does.** Validity is a file-existence question, and a look-ahead run answers it
permanently.

---

## 4. FINDING 2 — the lineup input can only change as a side effect of a sim

`_mlb_sim_input_fingerprint_by_game` hashes four inputs. Three are refreshed
independently of the sim; one is not.

| input | refreshed by | independent? |
|---|---|---|
| injuries | `_fetch_mlb_injuries()`, called immediately before fingerprinting | **yes** |
| odds | the odds refresh loop | **yes** |
| overrides | manual / manager artifact | yes |
| **lineups** (`lineups_last_known_by_team.json`) | **`daily_update.py` — i.e. the sim run itself** | **NO** |

There is no `_fetch_mlb_lineups`. Grep confirms the file is only ever *mirrored*
(`refresh_mlb_source_mirror.ps1`, `refresh_mlb_oddsapi.py`), never independently
fetched. So:

```
sim runs -> lineups rewritten -> fingerprint matches -> no resim -> lineups never refresh
```

A lineup change is detected only when *something else* (odds churn, injuries, the
tip-off window) already triggered a sim that happened to rewrite the lineup file.
**Lineup posting is picked up incidentally, never deliberately.**

Note the asymmetry is not accidental — `_fetch_mlb_injuries` was added for
precisely this class of bug, and its own comment says so:

> "an injury/scratch not yet reflected in the posted lineup artifact
> (`lineups_last_known_by_team.json`) went undetected between sim runs — MLB's
> fingerprint had no injury-report input at all."

The same fix was never applied to the lineup artifact itself.

The incidental path is also weaker than it looks: `_mlb_sim_odds_fingerprint_slice`
deliberately *reduces* the odds input (#48) because hashing raw odds "made this
fire on nearly every refresh" — so the main accidental trigger was damped on
purpose.

---

## 5. FINDING 3 — there is no concept of a *final* lineup

Nothing anywhere distinguishes a **projected** lineup from a **posted/official**
one. The only `lineup_status` in the codebase is a display string in
`mlb/hr_targets.py:999`, read from a row for the UI — never a trigger input.

The artifact is named `lineups_last_known_by_team.json`: "last known", with no
confidence, no source, no posted-at. So the question "have final lineups dropped
for this game?" **cannot currently be asked**, let alone answered.

This matters most for pitcher props, which key off the starter.

---

## 6. FINDING 4 — the forced-recheck window is far narrower than the event it must catch

`tip_off_window` is the only trigger that bypasses the 600s interval, and it
defaults to **30 minutes** before first pitch. MLB posts official lineups roughly
**2–4 hours** before first pitch.

So there is a multi-hour window in which final lineups exist and the only thing
that would notice is odds churn — which §4 shows was deliberately damped. The
guaranteed catch happens 30 minutes out, by which point the market has already
moved on the same information.

---

## 7. Ranked gaps

| # | gap | severity | why |
|---|---|---|---|
| 1 | validity is file-existence, so a look-ahead sim is never redone | **high** | measured: a 22h-stale slate served all day, `k_targets` 0 |
| 2 | lineup input has no independent refresh (circular) | **high** | the named concern; detection is incidental |
| 3 | no projected-vs-final lineup concept | **medium** | blocks any correct rule for #1 and #2 |
| 4 | 30-min force window vs 2–4h lineup posting | **medium** | catches the event after the market has |
| 5 | five sports have no invalidation at all | **medium** | time-driven only; scales badly as those sports come into season |
| 6 | `join_mismatch` is skipped under low memory | low | documented partial mitigation, `#23` |

**Gap 3 is the enabler.** Fixes for 1, 2 and 4 all need to express "this sim was
built from pre-lineup data, and lineups have since posted" — which needs a lineup
state the repo does not currently carry.

---

## 8. What this audit did NOT establish

- **Whether any of this is currently costing money.** No backtest of look-ahead
  sims vs. same-day sims on settled outcomes. The mechanism is proven; the
  P&L impact is not.
- **What `daily_update.py` does internally with lineups.** Treated as a black box
  that writes the artifact; its own StatsAPI fetch cadence was not read.
- **NBA/WNBA fingerprint quality.** Confirmed the mechanism exists; did not check
  whether its inputs suffer the same circularity as MLB's lineups.
- **Whether the evening look-ahead is net positive.** It exists to warm a cold
  slate, which is real value. The finding is that nothing *redoes* it — not that
  it should stop.
