# hockeysim strength-state faceoff mechanism — closing its own stated limitation with a real per-team PP/PK-role win-rate index

Closes the one gap the strength-state (PP/PK) faceoff report explicitly flagged, not hidden:
`_strength_state_multipliers` resolved each side's win percentage via the SAME OZ→EV→blend chain
the even-strength mechanism uses — a team's faceoff performance while ALREADY on the power play
(specialist personnel are often deployed) or already shorthanded could genuinely differ from its
general/EV rate, and that chain has no way to know which role a side actually has this segment.

## The signal — real, self-verifying, disjoint from every zone index

`historical_truth/faceoff_ev_index.py`'s new `parse_playbyplay_faceoffs_by_role` mirrors the
zone-specific parser's own winner/loser attribution technique (`GameFaceoffRoleRecord`/
`_ROLE_FLIP` mirror `GameFaceoffZoneRecord`/`_ZONE_FLIP` exactly), splitting on the WINNER's own
strength-state role (`"PP"` = had the skater advantage at the draw, `"PK"` = was shorthanded)
instead of zone. Two independent indices, computed from disjoint sets of non-EV draws — a team can
be elite at winning draws while already on the power play and mediocre at winning them while
shorthanded, or vice versa, same "not each other's mirror image" discipline as OZ vs DZ.

**Measured**: 1,312 games, 14,734 PP-role draws and 14,734 PK-role draws (each side of every
non-EV draw counted once, so the two populations are the same size by construction — zero-sum).
Mean index 1.00033 (PP-role) / 1.00041 (PK-role) across 32 teams — confirms correct normalization,
same self-verifying property every zero-sum faceoff index this session built has shown.

| role | top 5 | bottom 5 |
|---|---|---|
| PP-role | WSH 1.148, OTT 1.124, NYR 1.101, COL 1.097, NJD 1.095 | MIN 0.899, FLA 0.889, PHI 0.888, CHI 0.884, BUF 0.810 |
| PK-role | OTT 1.243, NYI 1.196, TOR 1.121, MTL 1.110, PHI 1.099 | SJS 0.902, SEA 0.896, CHI 0.843, TBL 0.819, ANA 0.803 |

A real, ~30-45% top-to-bottom spread on both, and a team can rank very differently on the two
(PHI: bottom-5 on PP-role, top-5 on PK-role; CHI: bottom-5 on both) — confirming the two are
genuinely independent signals, not restatements of each other or of the general EV/OZ indices.

## The wiring — one tier ahead of the existing chain, not a replacement

`engine.py`'s new `_resolve_strength_state_faceoff_pct` sits ONE TIER ahead of the existing
`_resolve_faceoff_pct` chain, used ONLY inside the strength-state (§2x) block: it picks whichever
of `faceoff_pp_role_index`/`faceoff_pk_role_index` matches EACH SIDE'S actual role in THIS
segment (the PP-side team's own PP-role index; the PK-side team's own PK-role index), and only
when that specific value is present. A missing role index for either side falls straight through
to the unchanged OZ→EV→blend chain §2x shipped with — same raw/non-defaulted, tier-by-tier
fall-through discipline every other faceoff resolution in this file already follows.

`build_nhl_special_teams_artifact.py` writes both as two additional CSV columns, sharing the same
`playbyplay` cache read pass the EV/OZ/DZ/NZ indices already use — no new fetch.
`load_team_special_teams_map` reads them the same way. No new `SimConfig` flag was added: like OZ
being preferred over EV, this is a refinement of an existing consumption point (the strength-state
mechanism's own win-percentage resolution), not a new gated mechanism.

## Verified — including a real trap this test's OWN first draft fell into

**Reachability, the hard way.** A first draft of the engine-level reachability test gave home a
PP-role index of 1.6 and a PK-role index of 0.4, and away the mirror-image (0.4 / 1.6) — and
produced an EXACTLY identical 120-seed mean (62.500 vs 62.500, matching to 3 decimals) between the
role-index-present and role-index-absent configurations. Not a wiring bug: `_resolve_strength_state_faceoff_pct`
picks whichever side's OWN role index matches its actual role each segment, and matched
home/away magnitudes (home's PP value equals away's PK value, and vice versa) put
`p_home_wins_st_draw` back at exactly 0.5 in BOTH configurations by construction, regardless of
which side is on the PP that segment — a real design trap in the test's OWN fixture, caught only
because the realized numbers were compared exactly rather than trusting a pass/fail from a
too-forgiving `assertNotAlmostEqual`.

Rebuilt with genuinely asymmetric magnitudes (home PP=1.6/PK=0.5, away PP=1.3/PK=0.4): the mean
DID move (62.500 → 62.858), but by less than the coarse `places=0` comparison could reliably
distinguish from noise at only 120 seeds. This is not itself a bug — it is a direct, expected
consequence of `_strength_state_multipliers`'s own exact-normalization design (the whole point of
the earlier bug fix): `E[applied_mult] = 1.0` EXACTLY for ANY win probability, so shifting the win
probability via a role index moves the per-game DISTRIBUTION (which side gets the temporary
boost, and how deterministically), not the long-run mean by any reliably-detectable amount at low
sample sizes. The final, correct reachability test instead compares the exact per-seed total-shot
VECTORS across 60 seeds (not their mean) — a noise-free proof: if the role index is read at all,
at least one seed's `pp_side_wins_draw` coin flip must land differently and produce a different
realized shot count. It does.

**Empirically, on the real production data**: 992-pairing round-robin (every ordered team pair,
1 game each, real `faceoff_pp_role_index`/`faceoff_pk_role_index` from the CSV vs those two keys
stripped, falling back to the OZ/EV/blend chain) — 62.094 avg total shots/game with the role
index OFF vs 62.012 ON, a **-0.131%** delta, noise-level and in line with every other faceoff
layer's near-zero aggregate shift this session measured.

**Unit tests**: 15 new tests on the parser/index functions (role classification correctly
flipping with which side has the advantage, EV-draw exclusion, loser-role attribution via the
flip, the zero-sum self-consistency check, PP-role/PK-role independence, missing-data handling) in
`test_hockeysim_faceoff_ev_index.py`; 1 new loader test; 6 new engine tests (4 unit tests on
`_resolve_strength_state_faceoff_pct`'s own tier-fallback order, 1 reachability test using the
per-seed-vector technique above, plus the checklist confirming both new keys are 100% populated
AND consumed). **519 hockeysim/nhl tests pass overall** (up from 497), `nhl_sim_input_checklist.py`
remains a full PASS with the two new keys showing up automatically (AST-derived, not a hardcoded
list — the exact discipline a prior bug in this same checklist was fixed to enforce).

## What this does NOT do

- Does not touch the strength-state mechanism's DECAY CURVES (`segment_average_multipliers_pp_role`/
  `_pk_role`, §2x) or the exact per-segment normalization (`_strength_state_multipliers`, §2x's own
  bug fix) at all — this only refines the WIN-PERCENTAGE INPUT those curves are simulated against.
- No zone-during-PP/PK joint model still (stated in §2x, unchanged) — this mechanism treats every
  PP/PK segment's assumed draw uniformly by role only, not role-and-zone jointly.
- The near-zero measured round-robin delta is an EXPECTED property of the exact-normalization
  design, not a signal the role index has no effect at all — see the reachability section above
  for why a mean-based check understates this mechanism's real, per-game distributional effect.
