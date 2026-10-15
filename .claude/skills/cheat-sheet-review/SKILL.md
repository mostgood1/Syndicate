---
name: cheat-sheet-review
description: Read the cheat sheets' daily review -- pipeline health (published, reconciled, graded share, actual-stat tap, void reasons, faces) and each featured section's season and 7-day record, sliced by price band, EV band and sport, with flags only beyond noise. Use when asked how the cheat sheets or a section are doing, whether the reconcile ran, why bets went unsettled, or what to tune.
---

# Cheat-sheet review

Lane `cheat-sheets`. User 2026-10-15: "consider any kind of monitoring/optimizations that should happen via a daily
skill run based on section trends".

## What runs, and where

| when (CT) | what | writes |
|---|---|---|
| 7:45 AM, 11:50 PM | Windows task `SyndicateCheatSheetsReconcile`: `scripts/reconcile_cheat_sheets.py` then `scripts/review_cheat_sheets.py` (WSL, nice 19) | `<data root>/cheatsheets/<sport>/<date>.reconciled.json`, `record.json`, `reviews/<date>.md|json`, `reviews/latest.*`, and a mirror in `C:\Users\tempadmin\.claude\scheduled-tasks\cheat-sheet-review\latest.*` |
| ~8:05 AM | Claude scheduled task `cheat-sheet-review` | nothing: it READS the mirror with the Read tool and sends one notification |

The task needs no shell command, so it never stops on a permission prompt. Log: `~/syndicate-prod/logs/cheat_sheets_reconcile.log`
(each run starts with `RECONCILE_RUN start`; the review reads only the last run).

Read it by hand:

```bash
wsl -d Ubuntu-24.04 -- cat ~/syndicate-prod/data/cheatsheets/reviews/latest.md
```

## What it checks

**Health**: the record was rebuilt within 26 h; every sheet published yesterday was reconciled; the share of its props
the grader settled (warn under 80%); values on graded props (warn under 90% outside soccer: a settler moved under the
tap); "not in the box score" voids (3+ is a name-matching gap -- a nickname like "Zack" / "Zachary" Bolduc); faces;
and the last run's log for `value hooks MISSING` or a failed pull.

**Trends**: each featured section, season and last 7 days, W-L, units, ROI; and slices of its bets by price band, EV
band and sport. Scope is the official record (from `play_cards.OFFICIAL_START`), or the beta until an official day
has graded.

## The flag rule -- and what a flag is NOT

A record is FLAGGED only with **30+ bets AND |z| >= 2** on ROI (z = ROI / its standard error from the win rate and
the average payout). Below that it is printed as a reading. One day, or one week, of results is mostly noise: the
beta day's 20-5 consistency and 3-11 skater-vs-goalie are readings, not findings.

A flag is a **proposal for a person**, never an automatic change:
- tighten that section's own entry rule (e.g. the value threshold, the consistency rate, a pvp minimum sample, the
  featured price band) where a SLICE shows the losses concentrate;
- re-order or re-label a section ("already in the price");
- fix a name-matching or coverage gap the health checks name.

Never propose removing a sport, a market or a market family: accuracy ranks and stakes, it never hides (2026-10-05).
And never size up a section on results alone: a winning flag says keep it and keep watching.

Better than results, when it exists: the price at the close. `scripts/grade_play_cards.py` already measures EV at the
closing line for play cards; extending it to every featured bet is the next step for this review.
