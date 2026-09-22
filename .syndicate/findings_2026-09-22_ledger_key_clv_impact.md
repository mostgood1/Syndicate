# What the live-gameline ledger's pair-keyed game identity did to past CLV / realised numbers

`[measured 2026-09-22, lane dh-grading-ledger-joins, session 3692ff18]`

User question: *"assess what that did to past CLV numbers."*

Short answer: **no published number is wrong, and that is not the same as no
damage.** One window absorbed the defect in a dedupe; the window before it was
pushed past a calibration gate and the analysis refused to report at all. And
the root cause — the pair-keyed live-gameline index — is still on `main`.

---

## 1. Which numbers could be touched at all

| consumer | how it names a game | exposed? |
|---|---|---|
| `clv_join.py` / the opening ledger — **true CLV** | `_history_key` requires a non-empty `event_id` and returns `None` without one (`clv_join.py:267-290`); quote keys are `event_id\|market\|segment\|selection\|player\|line` | **NO** |
| `scripts/bucket_realised_performance.py` | finals keyed by `game_pk`; dedupes `(bucket, game_pk)` | YES |
| `scripts/subset_edge_scan.py`, `scripts/score_live_gameline_offline.py` | finals keyed by `game_pk` | YES |
| `syndicate/features/shared/live_gameline_score.py` (worker-side, feeds `live_gameline_accuracy` on every board build) | `game_pk` first, `event_id` second (`:461-465`, `:497-499`) | YES |
| `scripts/bucket_live_edges.py` | no `game_pk` at all — measures disagreement, not outcomes | row counts only |

So **true CLV is untouched.** Everything that grades an outcome against
`game_pk` is exposed.

## 2. What the defect actually did to the rows — worse than a key collision

On every doubleheader measured, **both odds events were joined to game 1's live
state and written under game 1's gamePk.** The second event's rows are phantom
duplicates of game 1 carrying game 2's market prices: same score series, same
inning, same recorded-at window.

| date / pair | G1 | G2 | ledger |
|---|---|---|---|
| 2026-09-04 DET@CLE | pk 824424, 18:10Z, 6-7 | pk 824387, 23:15Z, 3-4 | ev `062e69d4` 126 rows → 824424; ev `a78d8674` **69 rows → 824424** |
| 2026-08-29 AZ@SF | pk 823177, 20:05Z, 7-1 | pk 823176, 02:05Z, 2-7 | ev `147cde54` 339 rows → 823177; ev `f007a8d4` **222 rows → 823177** |
| 2026-08-29 BOS@NYY | pk 823539, 17:05Z, 6-0 | pk 823501, 23:15Z, 2-9 | ev `ef5ae47c` 322 rows → 823539; ev `03a0ddbd` **137 rows → 823539** |

Event→game mapping is from the day's own odds snapshot
(`mlb_source/data/daily/snapshots/<date>/oddsapi_game_lines_<date>_pregame.json`),
not inferred: `a78d8674` commences 23:46Z, `f007a8d4` 02:06Z, `03a0ddbd` 23:16Z.
Each second event's rows sit entirely inside the FIRST game's window and carry
the first game's score series (09-04: `0-0, 4-0, 5-1, 6-1, 6-2, 6-6` on both
events; 08-29 BOS@NYY: `0-0, 1-0, 2-0, 5-0, 6-0` on both).

## 3. Effect on the published realised report: **zero**

`reports/bucket_realised_mlb.json` covers 2026-09-01..09-07. Pulled all 28,627
production ledger rows for those dates and replayed
`bucket_realised_performance.py` on them (`--rows-jsonl`, so the analysis's own
code decides, not a reconstruction).

- **as production wrote it** — reproduces the published h2h buckets exactly:
  n = 95/94/94/94, edge −3.42 / +2.83 / +5.01 / −0.46 pp.
- **the 69 phantom rows dropped** — output is **byte-identical**
  (`json.dumps(A, sort_keys=True) == json.dumps(C, sort_keys=True)` → True).

Every one of the 69 was discarded by the `(bucket, game_pk)` dedupe. The
published numbers are exactly what they would have been if those rows had never
existed.

(Re-stamping them with G2's pk instead moves n by +1 in three buckets and the
edge by 0.43-0.50pp — but that is NOT the right counterfactual, because the rows
describe game 1, not game 2.)

## 4. Effect one week earlier: **the whole window was refused**

Same replay over 2026-08-26..09-01 (46,788 rows, two doubleheaders, both with
OPPOSITE winners in the two halves):

| run | h2h market calibration | verdict |
|---|---|---|
| as production wrote it | mean_pred 0.522 vs actual **0.492** (gap 0.030) | **REFUSED** — `UNMEASURED: no market passed its gate` |
| 359 phantom rows dropped | 0.523 vs **0.501** (gap 0.022) | USABLE → `live h2h full unknown_progress n=78, +1.11pp ±5.66 (+0.20σ)` |
| phantom rows re-stamped to their own pk | 0.522 vs 0.510 (gap 0.012) | USABLE → n=80, +1.17pp |

359 rows — **0.77% of the window, 74 of its 4,097 gated h2h rows** — moved the
aggregate home-win rate by 0.9pp and flipped the window from reportable to
refused.

The mechanism is one-directional, which is why so few rows moved so much: all 83
contaminated h2h rows were priced for games whose home side **won** (AZ@SF G2
2-7, BOS@NYY G2 2-9) and graded against a game whose home side **lost** (7-1,
6-0). Market had home at 0.465 / 0.555 on those rows.

**The script's own 3pp calibration gate caught this.** Its docstring says a
miscalibration that size "points at MY join, not the book" — and it was right:
the join was the doubleheader join.

## 5. What is still broken

`build_live_gameline_index` (`syndicate/features/shared/live_gameline_join.py:1257`)
maps **`(away_team, home_team)` → ONE projection**, and `:1372` stamps
`projection["game_pk"] = game.get("gamePk")`. That is the root cause of §2, and
it is unchanged on `main`. The deployed fix (`d25664f0`, refresh-worker
21:04:52Z) stops the two events' RECORDS merging in the ledger file; it does not
stop the second event being fed the first game's live state and gamePk.

**Not taken here:** that file is solely owned by lane `live-edge-basis`, and
`live_gameline_score.py` by lane `restore-measurement`. Handed over, not edited.

## 6. Today's doubleheader is not yet evidence either way

TB@NYY: G1 823543 / ev `394e1e2b` FINAL 0-2; G2 823494 / ev `574050c1` Pre-Game,
23:05Z. Today's ledger holds 132 records, **all on event `394e1e2b`** (25 with
pk 823543, 107 with none), 16:56:14Z → 17:27:29Z. Zero records after the
21:04:52Z deploy — and no MLB game was live in that interval, so that null says
nothing about the deployed key. Scheduled reading
`mlb-dh-g2-ledger-reading-0922` fires 18:40 CT, once G2 is live; the
discriminating question is whether ev `574050c1`'s rows carry **823494** (root
cause fixed) or **823543** (still pair-keyed).

## How this was measured

Read-only throughout. Production rows via
`/api/ops/artifacts/stream?path=mlb_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl`
(uncapped; the export route skips files over 8 MB). Doubleheaders enumerated
from MLB StatsAPI `schedule?sportId=1&date=<d>&hydrate=linescore`, not from the
ledger. Scratch scripts in this session's scratchpad; the analysis itself is
`scripts/bucket_realised_performance.py` unmodified, driven by `--rows-jsonl`.
