# Deleting vendor/mlb_bettingv2 — scope `[2026-10-19, session 2d413211, lane mlb-vendor-deletion-scope]`

**Question (user, 2026-10-19):** "scope the vendor/mlb_bettingv2 deletion". Analysis only; nothing changed.

## Bottom line

**Deleting vendor/mlb_bettingv2 loses no running code and no upstream work.** Nothing in production imports, runs, reads or writes the tree:
- the daily sim, live lens, checklist, producers and web assets all run Syndicate's copies (deploys.md 10-16 / 10-19);
- the fleet has written **0** files under the tree since the 2026-10-16 18:42Z switch.

The vendored copy is **ahead of** upstream mostgood1/MLB-BettingV2, so there is nothing left to pull from it, and the "a re-pull reverts our engine work" hazard goes away with the tree.

Five pieces of pre-work stand between here and a clean `git rm`. Plus one decision for the user: the generated copies become hand-maintained source.

## Measured inventory (origin/main, 2026-10-19)

The repo has 190 git-tracked files under vendor/mlb_bettingv2. These cover:
- the engine: sim_engine 31 modules;
- tools: eval 55, tune 40, web 26, datasets 8, statcast 3, smoke 3, oddsapi 3, other 7;
- data: 12 tracked inputs.

Native counterparts exist for:
- every sim_engine module (`syndicate/features/mlb/sim_engine/`);
- the 20 tools files production reaches (`syndicate/features/mlb/native/tools/`);
- the 12 tracked inputs (`engines/mlb/data/`);
- the 4 betting-card assets (`syndicate/static/mlb/betting_card/`);
- the live-lens / web-helper slice of tools/web/flask_frontend.py (`live_lens_port/app_slice.py`).

The other ~120 tools files are reached by nothing in Syndicate.

References outside vendor/, data/, reports/ and .syndicate/, classified by an AST check (code strings and imports, docstrings excluded):

| class | files | at deletion |
|---|---|---|
| mention-only (comments/docstrings, incl. generated provenance notes) | 77 | harmless; reword the ones that read as live instructions |
| operator hint strings in code | 3 | **replace**: `mlb_live_prop_grading.py` suggests running `vendor/.../tools/datasets/backfill_statsapi_feed_live.py`, which has no native copy; `fetch_statcast_raw_pitches_x64.py` and `build_mlb_batted_ball_artifact.py` name the vendored `.venv_x64` interpreter |
| generators / harnesses / migration / `sync_vendor_upstream.py` (vendor is their source by design) | 6 | retire or freeze (decision below); drop MLB from `sync_vendor_upstream.py` |
| tests still EXERCISING vendored modules (missed by the 10-16 test sweep: other import shapes) | **7** | **repoint first**: test_fetch_daily_oddsapi_markets, test_mlb_asof_lineup_projection, test_mlb_conditional_mix_wiring, test_mlb_game_line_config_ab, test_mlb_multi_profile_pitch_overrides, test_roster_artifact_roundtrip, test_sim_input_disabled_by_config |
| VENDORED-ONLY tests (code production never runs) | 3 | **retire**: the two `/api/live-lens` ROUTE tests and `test_render_live_lens_refresh_*` in test_mlb_refresh_runner |
| vendor-comparison tests (`--check`, byte-identity, data-root equality; they skip when vendor is absent) | 6 | **replace with post-deletion invariants** (no vendored import, roots at engines/mlb), or they go silently green-by-skip |
| vendored path used only as test DATA | 2 | none (test_data_mirror_write_guard, test_run_mlb_daily_sim_job) |
| `engines/mlb/data/tuning/*.json` | 2 | none: provenance notes naming old eval dirs, not paths anything reads |

Docs: CLAUDE.md (the vendor-upstream mapping line) and 7 files under `docs/`. The engine standard REQUIRES a file:line pipeline trace, so `docs/ai_context/mlb_sim_engine_reference.md` must be re-pointed at the native paths.

## Upstream: the vendored copy is AHEAD (measured by blob hash vs mostgood1/MLB-BettingV2 HEAD, pushed 2026-10-12)

- **137 of 190** files are identical, **30 differ**, and **23 are absent upstream**.
- In the 30 that differ, at least 99% of upstream's lines are already in the vendored copy for **27**. The remainder (0.9-1.1%, 41 lines across 5 engine files) reads as local refactors:
  - pitch-type alternates moved into `data/pitch_codes.py`;
  - the rate combine rewritten.
- Upstream's three 2026-10-12 commits (#1-#3, "shelled-starter hook", "measured baserunning ...") are **Syndicate work pushed upstream in adapted form**. The local copy is the origin ("SHELLED HOOK (Syndicate lane mlb-starter-length, 2026-10-03)") and carries later engine work upstream never received (10-06 stolen-base / steals-of-third / double-steal changes).
- **Nothing exists only upstream.** After deletion, Syndicate's copy is the only one carrying the current engine.

## Fleet (production)

- The fleet checkout's vendor/mlb_bettingv2 is 44 MB; its data/ is 36 MB. That data is phase 4's rollback state.
- 0 files have been modified under it since 2026-10-16 18:42:31Z, three days covering a production sim and a live game.
- **Archive the data dir before deleting.** It is gitignored runtime state that `git rm` will not remove, and the native engine never reads it again.

## What deletion changes about maintenance (the decision)

The three generated trees become **source we edit directly**:
- `syndicate/features/mlb/sim_engine/`
- `syndicate/features/mlb/native/tools/`
- `syndicate/features/mlb/live_lens_port/`

Today their headers say "GENERATED -- do not edit by hand", and `--check` fails on a hand edit. With vendor gone:
- `port_mlb_sim_engine.py` and `port_mlb_live_lens.py` have nothing to generate from (they print "vendor tree absent" and exit 0);
- their `--check` tests skip;
- the two parity harnesses lose their vendored arm.

Proposal: rewrite the generated headers to "frozen from vendor/mlb_bettingv2 at <sha>; maintained here", and retire the generators and parity harnesses. Keep them in git history only; leaving them would advertise a regeneration path that no longer exists. The mechanical EDITS stay, and they work without vendor: `_ENGINE_FILE` virtual paths under engines/mlb, `_NATIVE_ROOT`, `_SYNDICATE_ROOT`.

## Proposed sequence

1. **Pre-work (one lane, one landing):**
   - repoint the 7 tests, with a JUnit before/after over the same files;
   - retire the 3 VENDORED-ONLY tests;
   - replace the 3 hint strings;
   - replace the 6 vendor-comparison tests with post-deletion invariants;
   - re-point the engine reference doc.
2. **Freeze:** rewrite the generated headers; retire the generators and parity harnesses; drop MLB from `sync_vendor_upstream.py` and the CLAUDE.md vendor mapping; update the auto-memory note.
3. **Delete:** `git rm -r vendor/mlb_bettingv2` in one commit. Then run the full test suite and a fresh-interpreter import trace of every production entry point, with the tree physically absent.
4. **Fleet:**
   - archive `vendor/mlb_bettingv2/data` to the prod data disk;
   - fast-forward. Nothing imports the tree, so no restart is needed. The `.pyc` caches in the old dir are inert.
   - verify on the next production sim and live-lens tick, with the same 1 s process recorder plus "0 files under vendor/".
5. **Rollback:** `git revert` of the deletion commit, plus restoring the data archive.

## Not covered here

- Other sports' vendor trees (nba/wnba/nhl): separate scopes.
- The ~120 unreached vendored tools: deleted with the tree. Nothing references them; confirm with the step-3 trace.
