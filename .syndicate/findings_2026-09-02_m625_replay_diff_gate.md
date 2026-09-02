# `#625`(5) — the replay-diff gate: what it proves, and what it proved cannot be proved

**Lane `m625-replay-diff-gate`, 2026-09-02. Commit `dcf4d29a` on
`session/m625-replay-diff-gate`. NO DEPLOY TAKEN AND NONE NEEDED — the gate
never contends for the deploy queue, which is why this item was picked.**

## The result

    py -3 scripts/replay_diff_gate.py --date 2026-09-01     ->  PASS   (exit 0)

| | |
|---|---|
| entrypoint | `scripts.run_refresh_worker:_run_book_grid_artifact_tick` — the REAL tick |
| fixture | mirror manifest `8d5c42ba8cb18c34`, 37 files, 195,853,613 bytes |
| output diffed | production's own `book_grid_2026-09-01.json`, 12,748,528 B |
| leaves compared EXACT | **280,840** |
| clock-derived fields checked | **58,335**, all within 0.1s of one shared 3.6s offset |
| declared-excluded leaves | 26,413 (every rule carries a reason) |
| **mismatches** | **0** |
| outbound network attempts | 0, guard armed |

**Negative control.** `--perturb` drops ONE line from the 163 MB tick tape. The
gate FAILS on exactly eight fields: that cell's `price`, `observed_at`,
`age_seconds`, `lag_behind_freshest_seconds`, the row's `consensus.under`, the
best-cell `edge_vs_consensus_pct`, and `source_quote_rows` / `source_shard_bytes`.
A gate that has never been observed to fail is not known to be a gate.

## Four things that constrain every future replay target

**1. A replay of a real worker tick can WRITE TO PRODUCTION.** The tick calls
`publish_hot_artifact` (`run_refresh_worker.py:4753`) — an HTTP POST onto web's
disk — and `pull_streamed_artifact` before it. Running a worker entrypoint on a
laptop that has a live `ADMIN_TOKEN` therefore pushes a **locally-built board
into production**. `#625` law (1) has to be ENFORCED, not asserted: the child
runs behind a deny-all socket guard AND with every credential stripped. Which
mechanism actually fired is on record — `[artifact_publisher] SKIP_NOT_CONFIGURED
url_set=False token_set=False`, i.e. the credential strip caught it before the
socket guard was reached. Two mechanisms, because one silently failing is how
this class of accident happens.

**2. The fixture must PREDATE the output, per file.** Production answers from
the input as it was at T; the mirror holds it as it is now. Checked, not
assumed. True on **10 of 10** MLB dates, because the tick rebuilds yesterday
once its shard settles (`run_refresh_worker.py:4617-4625`). When it is false the
gate returns `NO_FIXTURE` and NAMES the offending files — measured: widening the
enrichment family to D+1 pulled 17 files that postdate the output by 743–1,510s.

**3. The PRODUCER COMMIT is the real precondition, and it is a narrow window.**
refresh-worker took **465 successful deploys in 21 days**. Of nine consecutive
MLB dates, only **2026-09-01** was produced by this HEAD (`e4a471c0`, live
19:26:44Z; the artifact was written 19:27:51Z, 67 seconds later). The 2026-08-29
run demonstrated the failure mode: the replay emitted `by_quote_age` and
`fresh_quotes_only`, fields production's artifact **does not have** — the diff
was measuring code drift, not correctness. This is the 2026-09-02 rule
("never measure a change by replaying it without an argument production always
passes") in its structural form: **pick the day by its producer commit.**

**4. The clock is an INPUT — and two board blocks are not replayable at all.**
Frozen to production's own `generated_at`, that field matches to the microsecond
and is deliberately left CHECKED as the assertion the freeze took effect.
Excluding it would have hidden a silently-unfrozen run behind 58,000 downstream
mismatches. One constant residual remains — **3.6s**, because production stamps
its clock *after* the pivot — estimated once and held against 58,335
constraints, so a real change to any single age still fails.

**What cannot be replayed, named rather than excused:**

- **`data_root()/live/mlb_live_lens.json` is a NON-DATED MUTABLE FILE.** There is
  no historical value to mirror, and staging today's copy would apply today's
  live games to a past date — worse than absent. It IS allowlisted
  (`artifact_publisher.py:885`) and web's disk holds **zero** files matching
  `live/*` (two reads, 45 minutes apart). Confirmed as the single cause of every
  remaining difference: **167 of 167** rows whose `projection` differs read
  `game.state = live` where production reads `pregame`, against production's own
  recorded `transitions: {"live->pregame": 229}`. `projections.rows_with_edge`
  187→53 and `margin_model.modelled_edge_rows_priced` 67→44 are those same rows
  counted again downstream.
- **`game_state.chips` needs D+1's slate** (`board_enrichment.py:70-97`, `#348`)
  while D's grid is rebuilt DURING D+1 — `D+1 settled before D's output` is FALSE
  on **9 of 9** dates. Not a fixture gap a wider pull closes.

**Follow-up this opens:** until the live-lens snapshot is DATED (or archived per
tick), the board's live-state correction — 229 rows on one day — **cannot be
verified offline by any tool.** That is a testability gap in the artifact
design, not in the harness.

## The mirror layer (`#625`(1))

`scripts/mirror_manifest.py`. Content-addressed manifest per date, mirror
refused inside the git tree or under OneDrive (refused, not merely documented),
and no `push` subcommand by construction — adding one would make the file the
bidirectional channel law (1) forbids.

Two measurements that shape it, both against production:

- `/api/ops/artifacts/export?names_only=1` inventories the **whole** hot set —
  **33,221 files / 13.97 GB in 13.0 seconds**, 2.8 MB of JSON. It never opens a
  file (`ops.py:2239-2260`). "Verify by manifest, not by timestamp" costs one call.
- **A narrow `pattern=` costs exactly the same as none.** The handler globs all
  168 `HOT_ARTIFACT_PATTERNS` first and applies `pattern=` as a post-filter
  (`ops.py:2240-2248`). Ten per-family queries are ten full walks. Take one
  inventory and filter locally.

**What the manifest can and cannot assert, stated because a guard that
overstates is worse than none:** `names_only` returns `bytes` and `mtime`, no
hash, and no endpoint provides one. So `sync` proves transfer integrity (local
length == the length production reported) and `verify` proves local non-drift
(sha256). It is **not** a claim that production's bytes equal ours.

## Not done, and why

- **(2) export-only pattern list — NOT DONE, and the gap is confirmed real.**
  `/api/ops/artifacts/export` iterates the SAME `HOT_ARTIFACT_PATTERNS` that
  gates web-publish (`ops.py:2215`), so today a worker-local family cannot be
  made exportable without also making it web-servable — the `#413` collision.
  Skipped because `artifact_publisher.py` was claimed by another lane at the
  time; that lane has since closed.
- **(3) was ALREADY DONE** by lane `m625-env-snapshots` (`66b66895`). That commit
  is on its session branch and **is not on `origin/main`**, so
  `scripts/snapshot_render_env.py` does not exist in the primary tree.
- **(4) local 3-role fleet runner and (6) the standard's §3b edit — NOT STARTED.**
