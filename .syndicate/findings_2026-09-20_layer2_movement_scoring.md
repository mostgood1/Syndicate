# Layer 2 board scoring — is line/pricing movement leveraged?

Lane `layer2-line-movement-scoring`, session 105fd5dd, 2026-09-20.
Assessment then remediation. Every number below is a production reading or a
replay of production data through the real functions — none is from the primary
checkout, which was **882 commits behind `origin/main`** when this started.

## The answer to the question as asked

**Yes — movement is live, and it is the second-largest value term.** It was
already wired end to end, which is not the usual finding here.

    value  = ev_pct + clip(0.125 * model_edge, +/-1.5) + movement_contribution
    score  = min(value, value * book_confidence * freshness * price_reliability)

Deployed coefficients, **fitted out of the served payload rather than read from
config** (1,413 real delta -> component pairs, rms 2.7e-5): weight **0.05**,
cap **1.0**, saturating curve — equal to the documented defaults, so no env
drift.

Served board 2026-09-20T16:23:40Z, build 79 s old, 2,000 rows of 5,556:

| term | coverage | non-zero | mean \|x\| | signed mean |
|---|---|---|---|---|
| `ev_component` | 100% | — | 2.585 | — |
| `movement_component` | 94.3% | 70.7% | 0.343 | **-0.255** |
| `sim_component` | 76.1% | 76.0% | 0.740 | +0.223 |

Join health: `movement_rows_matched` 5,554 / 5,556, `openings_loaded` 5,906,
`openings_error: null`. Basis: same-book 48.2%, best-of-N 46.1%, line-moved 5.7%.
Removing the term reorders 99.5% of rows (median 61 places of 2,000); top-50
membership churns 7.

## The four gaps, and what was done

### 1 + 2 — THE SAME DEFECT, not two. **FIXED.**

`_movement_from_opening` withholds `movement_price_delta` when the line moved.
That is *correct* — a price at a different handicap is not a price move, and the
loose join key was firing steam on exactly that mistake. **But nothing replaced
it.** The 114 rows with a null `score.movement_component` were **exactly** the
114 `movement_basis=line_moved` rows.

And the steam detector reads that same withheld delta, so steam on a line move
was **not rare — it was structurally impossible**. `movement_join_key`'s own
docstring had diagnosed this blindness once already ("a sharp move usually comes
with a line move or a best-book switch, which broke the key and erased the
evidence") and fixed it *for the key*. It survived one level down in the price
gate.

Fix: a line term in probability points (|line delta| spans 0.5 to 13.0 across
markets — those cannot share a coefficient), weight **0.3096 derived** as
`0.05 x 6.192` from the measured median cents-per-probability-point, sign taken
from the already-shipped `movement_vs_pick` so no second sign rule can
contradict it, through the **same** curve and the **same** cap. Steam fires at
`15 / 6.192` pp — the same bar converted, not a looser one.

### 3 — Movement is a PENALTY, and only its promotions were countable. **FIXED.**

1,151 rows negative vs 262 positive; `movement_vs_pick` 60.5% away / 15.8%
toward. Admission reads `value_pct`, which contains movement — so movement
removes far more rows than it adds, **and every row it removed left no trace in
any counter**, because a dropped row is not in the served payload either.

The reading that exposed it: movement had admitted **0** rows and the sim **38**.
That looks like "movement does not affect admission" and actually means "we can
only see the half that never fires." Added `rows_refused_by_movement` beside
`rows_admitted_by_movement`, both forwarded to the endpoint.

Note the line-moved rows split **59 away / 55 toward** — balanced, unlike price
moves. So line movement is a genuine discovery signal, not another penalty, which
is the second reason gap 1 was worth fixing.

### 4 — No CLV harness for the weight. **BUILT — with one piece blocked.**

`scripts/decompose_movement_clv.py`, the counterpart to `decompose_sim_clv.py`.

**It could not be a copy, for two reasons worth keeping.**

*Movement is not reconstructible.* The sim decomposition works because
`sim_component = clip(0.125 * model_edge_pct, +/-1.5)` is an exact function of
one stored field. Movement is measured **against** the opening, so the opening
record's own movement is 0 by construction — storing it would persist a column of
zeros. Only `clv_price_trail` has the path.

*The obvious test is circular.* CLV is open -> close. Movement at build `Tk` is
open -> `Tk`. `Tk` lies **between**, so movement is a leading segment of the very
path CLV measures — a row that has already moved toward us has banked part of its
own CLV by arithmetic, not skill. Run naively, movement would look like the best
predictor on the board and mean nothing. The script measures **forward CLV**
(observation -> close) and prints the circular version only as a labelled control.

**BLOCKED:** the `HOT_ARTIFACT_PATTERNS` entry for the trail.
`artifact_publisher.py` is held by OPEN lane `pull-window-dated-scope`; the lane
guard refused the edit and it was left undone rather than worked around. The
holder session was not reachable in the CCD roster.

**And it would not have been sufficient anyway — the more useful finding.**
`/api/ops/artifacts/export` refuses any single file over **8 MB**. Today's
**already-allowlisted** `clv_openings/2026-09-20.jsonl` returns `count=0,
oversize_skipped=1, oversize_bytes=15,691,334`. Every openings file since
2026-09-01 is over the cap, up to **31,120,228 bytes on 09-19**, against the
allowlist comment's stated "~90 KB a day" (`artifact_publisher.py:687`) —
**345x stale at the 09-19 peak, 174x on 09-20**.

> **Corrected 2026-09-20 after independent re-measurement by session a1e40980
> (lane `pull-window-dated-scope`).** This sentence first read "up to 31.1 MB …
> 174x stale", pairing the PEAK file with a multiplier computed from a
> DIFFERENT day's file — the one defect this ledger has a standing rule about,
> a number sitting next to a number it was not derived from. Both multipliers
> are now stated with the day each belongs to. That session reproduced the
> finding from its own session rather than banking mine: 09-20 `oversize_bytes`
> **15,736,057** and 09-19 **31,120,228**. Its 09-20 reading is 44,723 bytes
> larger than mine taken ~40 min earlier, which is the file still appending, not
> a disagreement.

The trail carries many points
per key where openings carry one. Allowlisting it would have produced a pattern
that *looks satisfied and transfers nothing*: `#208`'s lesson in its nastiest
form. So `record_price_trail` now reports `bytes_on_disk`, and the harness
**refuses to print a verdict on zero rows** instead of reporting a null result.

**Scope correction, stated because I got it wrong first:** those files *are* on
web's disk. The 8 MB cap blocks the **content export to a remote caller**, not
the worker->web sync. `decompose_sim_clv.py` is unaffected — it uses the
server-side `/api/ops/clv/report` join, not a raw export. That is the pattern
that scales, and the route a trail harness should copy if a worker-side run is
not wanted.

**THE SYNC PATH IS UNMEASURED AND IS NOT BEING ASSERTED BY ANYONE.** Session
a1e40980 owns exactly that path (`pull_hot_artifacts`) and independently
declined to claim it is fine: *"The files being present on web's disk is
consistent with the sync working and only the CONTENT export refusing. I am not
going to assert the sync is fine without measuring it, and I have not measured
it today."* Two sessions now hold the same caveat from opposite directions,
which is the correct state to leave it in — an open question with a named owner,
not a null result. It has been flagged to the user as **unowned and larger than
the one-line allowlist ask**.

**UPDATE 2026-09-20, later: THE ALLOWLIST ENTRY IS IN** (`2952bf2b`, by lane
`pull-window-dated-scope`, whose user answered "do both"). It was added by the
lane that HOLDS the module, not by me and not on my request — I asked, that
session declined to act on a peer's ask, put it to its own user, and acted on
the answer. **The principle stands and stays written down: a peer is not a route
around a lane guard.** It simply did not end in a no this time. Verified by
reading the commit rather than taking the report: the line
`"reports/intelligence/clv_price_trail/*.jsonl",` is present at
`artifact_publisher.py:730`.

**AND I WAS WRONG ABOUT WHY IT MIGHT NOT WORK. The real ceiling is 12 MiB, not
8 MB, and it is a different mechanism.**

My first read was that the trail has no `publish_hot_artifact` call (true — the
openings ledger has one at `clv_opening_ledger.py:369`, the trail has none) and
therefore could never be pushed. **That inference was wrong.**
`sweep_changed_hot_artifacts` is GENERIC over the allowlist — *"sweep the
allowlisted hot-artifact locations under the data root and publish any file
modified at or after `since_epoch_seconds`"* — so the entry alone does make the
trail eligible. No call site is needed.

What the missing direct call actually costs is the EXEMPTION:

    _PUBLISH_MAX_BYTES = 12 * 1024 * 1024          # 12 MiB, sweep-only
    _publish_skip_reason() -> "too_large:<size>"   # unless the path is in
                                                    # _FAILED_DIRECT_PUBLISH

`_FAILED_DIRECT_PUBLISH` holds paths **whose DIRECT publish failed**. Openings
clears the ceiling because its direct call streams and never consults it (the
same reason `book_grid` publishes at 12,855,903 bytes against a 12,582,912
ceiling — verified in that file's own comment). **The trail has no direct call,
so it can never enter that set, and the ceiling has no fallback for it.**

**CONSEQUENCE, and it is worse than a clean failure:** the trail publishes while
it is under 12 MiB and is silently skipped as `too_large` once it crosses —
giving web a copy that is truncated IN TIME, the morning's trail without the
evening's, which looks complete. For a forward-CLV harness that is precisely the
wrong half: the observations nearest the close are the ones that go missing.

**NOT MEASURED, and it is the question:** whether the trail actually crosses
12 MiB. It cannot be read today. Openings (ONE point per bet) is 15.7–31.1 MB,
and the trail carries many points per key but much smaller records (~150 bytes
against openings' ~1,053 today), so it is genuinely uncertain and must be read,
not reasoned about. `record_price_trail`'s new `bytes_on_disk` answers it in one
build after a deploy; the sweep's own `skipped` counter (`#402`, bounded three
per reason) answers it from the other side.


## Verification

- **32 new tests, reachability BEFORE correctness** (`off != on`), per
  `model_engine_standard.md` — a correctness test passes just as happily on an
  inert feature.
- A same-line row is **byte-identical** across 7 price deltas: the calibrated
  term is not re-fitted. Nothing was absorbing line movement (those rows scored
  0.0), so this is additive in a blank region, not a second estimator.
- Cap holds for both halves, including when both inputs are supplied.
- **293 green** across every touched suite.
- **Production replay** through the real `_movement_from_opening` and
  `blended_score`: 28 MLB rows that scored exactly 0.0 now score, max
  \|component\| 1.0 (cap holds), signs correct — totals 7.5 -> 8.0 with the pick
  OVER reads *toward*, 8.5 -> 7.5 with the pick UNDER reads *toward*.

**What the replay does NOT establish:** production coverage. It joined openings
from `/api/ops/clv/report`, which is keyed with line+bookmaker; collapsing that
to the movement key picked an opening at the *same* line for 44 of 74 rows, so
they routed down the price path. That is a join artifact of the replay, not a
scoring failure — verified, not assumed (0 of 74 served rows have a null `line`).
Real coverage needs the openings ledger, which is the 15.7 MB file above.

## Not claimed

- The weight is still **unvalidated**. This lane built the instrument; it did not
  run it. `_SCORE_MOVEMENT_WEIGHT` and the new line weight both remain gated on
  the same evidence, and the derived 0.3096 makes the two halves *consistent*,
  not *correct*.
- CLV is not ROI, and the population is the published board, not the bet slate.
- Nothing is deployed. `autoDeploy` is off for `.py`; this is on `main` only.
