# NCAAF data pipeline — builders, dependency order, and what reaches the sim

> Written 2026-08-19, lane `football-model-owner`, **because it did not exist and
> should have.** `model_engine_standard.md` §2 requires a documented pipeline
> trace naming the file at each hop; the football reference documented the
> ENGINE and left the DATA pipeline undocumented. Every fact below was measured
> while building the 2026 season, not read off the code.

---

## 0. The one-line summary

**Seven builders produce NCAAF data. The sim reads NONE of them.**
`generate_smartsim2_ncaaf_projections.py` references roster, player-identity,
player-stats, returning-production, coach-continuity and transfer data **zero
times** — it is team-PPA only, four numbers per game. Everything below is built
and unread until `feature_generation_payload` is wired.

---

## 1. The builders, in DEPENDENCY ORDER

Order matters and is not obvious from the filenames. Running them alphabetically
fails.

```
build_ncaaf_team_registry_snapshot.py       (standalone)
        |
        +--> build_ncaaf_coach_continuity_snapshot.py   --registry-path
        |
build_ncaaf_roster_snapshot.py              (standalone; also writes player_identity)
        |
        +--> build_ncaaf_transfer_portal_snapshot.py    --identity-path --roster-path
                    |
                    +--> build_ncaaf_returning_production_snapshot.py
                                                        --roster-path --transfer-path
```

`build_ncaaf_player_identity_snapshot.py` exists separately but the roster
builder already emits player identity as a side effect.

**All take `--season`.** All write under
`data/ncaaf_source/source_artifacts/data/processed/<name>/`.

---

## 2. 2026 STATE, measured 2026-08-19

| artifact | rows | 2026 rows | wk1 coverage (94 FBS teams) |
|---|---|---|---|
| `roster` | 44,341 | **15,442** | 138 teams, **0 missing** |
| `player_identity` | 44,341 | **15,442** | as roster |
| `coach_continuity` | 138 | **138** | **0 missing** |
| `returning_production` | 136 | **136** | 2 missing — see below |
| `transfers` | 3,288 | **3,288** | touches 137 teams, **0 missing** |
| `team_registry` | 684 | n/a | season-agnostic |
| `player_game_stats` | **0 files, ever** | — | see §4 |

**The two `returning_production` gaps are LEGITIMATE:** North Dakota State and
Sacramento State are FCS→FBS transitions for 2026 and have no prior FBS
returning production. Not a build failure.

**Rosters APPEND, they do not overwrite.** The 2026 build left 2025's 28,899 rows
intact (44,341 total). Checked explicitly — a builder that silently replaced the
prior season would be data loss.

**2025 had 289 teams, 2026 has 138.** That is not a regression: 2025 included
FCS, 2026 is FBS-only, and 138 ≈ the FBS count. Coverage is judged against the
94 teams the week-1 slate actually needs, not against last year's total.

---

## 3. FIVE OF SEVEN BUILDERS COULD NOT RUN AT ALL. Fixed 2026-08-19.

Only `roster` and `player_game_stats` carried their own `_load_env()`. The other
five — `team_registry`, `returning_production`, `coach_continuity`,
`transfer_portal`, `player_identity` — called `CfbdClient.from_env()` directly
and died with **"Missing CFBD API key"** from a normal shell, even with a
populated `.env` beside them.

**Fixed at the shared choke point**, not in five copies:
`syndicate/features/ncaaf/cfbd.py::CfbdClient.from_env` now falls back to
`load_dotenv()` when the process environment has no key. Ordered AFTER the
environment scan, so an explicitly exported key still wins.

This is a large part of why several snapshots had never been produced.

**They also need the repo root on `sys.path`:**

```bash
PYTHONPATH=<repo-root> py -3 scripts/build_ncaaf_<name>_snapshot.py --season 2026
```

`py -3 scripts/x.py` puts the SCRIPT's directory on `sys.path`, not the repo, so
`from syndicate...` raises `ModuleNotFoundError`.

---

## 4. `player_game_stats` has NEVER produced a file

Zero outputs, ever. Its `--week` help text notes CFBD's `/games/players` returns
HTTP 400 without one, so it is per-week by construction. **For 2026 this is
expected-empty until games are played** — the season opens 08-29. It is NOT
evidence of a broken builder, and it should not be "fixed" before there is data.

---

## 5. What actually reaches the sim, and what does not

**Reaches it:** CFBD team PPA → `offense_defense_rating` → the four
`home/away_offense/defense_rating` fields. That is the entire input surface.

**Does not reach it:** everything in §2. The engine's `drive_priors` DOES read
`returning_production`, `coach_continuity` and `transfer_impact` keys — they are
in its alias lists — but no production entrypoint passes
`feature_generation_payload`, so all three fall to neutral defaults on every game.

**Before wiring them, read the Phase 3 result**
(`nfl_feature_payload_preregistration.md`): the payload path is worth **4.1%** of
the margin SD against the ratings path's **17.2%**, and the NFL payload
experiment returned a measured **NULL**. These three are the most defensible
candidates in the repo for that path — roster churn is college football's
dominant year-over-year signal — but they arrive through the weak lever.

---

## 6. Gaps that remain

- **Props: no surface.** `/ncaaf/api/props` is 404; there is no `props.py` for
  NCAAF (NFL has one). `fetch_ncaaf_oddsapi_props_local.py` exists and nothing
  consumes it.
- **Nothing here is allowlisted.** `/api/ops/artifacts/export?pattern=*ncaaf*`
  returns **0** artifacts, so none of §2 can be read or published through the
  ops API — the auditability gap recorded in `model_engine_standard.md` §3b.
- **Team-name vs team_id.** Roster/continuity/returning use `team_id` (numeric
  CFBD id); transfers use `origin_team_id`/`destination_team_id`. Comparing
  either against a team NAME silently yields zero matches — it produced a false
  "94 teams missing rosters" during this very audit. Resolve through
  `/teams/fbs?year=<season>`.
