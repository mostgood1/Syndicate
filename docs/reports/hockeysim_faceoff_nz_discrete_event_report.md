# hockeysim NZ discrete-event model — reversing an earlier decision, with evidence

Closes the last remaining faceoff-zone signal this session's gap analysis ever identified.
`hockeysim_faceoff_nz_calibration_report.md` (§2p) checked NZ against real SEASON-AGGREGATE shot
generation, found no correlation, and deliberately declined to wire `faceoff_nz_index` at all —
matching the standing rule against publishing an unconsumed field. This report explains why that
decision has now been reversed, with a real measurement behind the reversal, not just a change of
mind.

## Why the earlier decision gets revisited

`hockeysim_faceoff_dz_segment_validation_report.md` (§2s) proved a general principle the NZ
decision hadn't yet accounted for: a null SEASON-AGGREGATE correlation does not rule out a real
SEGMENT-LEVEL effect — DZ's own season correlation was equally null, yet its segment-level effect
was real (just backwards). Given that precedent, NZ's segment-level effect deserved the same direct
check DZ got, rather than resting on the season-aggregate result alone.

## The segment-level check

Same population and methodology as every other zone-specific check this session ran —
`compute_post_faceoff_shots(..., winner_zone="N")`, 20,642 real EV faceoffs the winner took in the
neutral zone:

| window | winner share | ratio |
|---|---|---|
| 10s | 0.7203 | 2.576x |
| 15s | 0.6892 | 2.218x |
| 20s | 0.6373 | 1.757x |
| 30s | 0.5945 | 1.466x |

**A real, monotonically decaying effect, in the EXPECTED direction** (unlike DZ's reversal) —
weaker than OZ's spike (0.93 at 10s), stronger than the general blended population's own 10s figure
would suggest in isolation, but the correct comparison (see below) shows it is actually the WEAKER
signal once properly integrated.

## The marginal decay curve

`scripts/build_nhl_faceoff_decay_curve.py --winner-zone N`: raw ratio 2.97x at (0,5]s, decaying
smoothly and almost monotonically to exact parity (1.000x) by (45,60]s, staying close (1.04x)
through (60,90]s — fully converged, held flat at 1.0/1.0 beyond that like the general and OZ
curves (not DZ's unresolved tail).

## A real correction caught before shipping

An early draft of this module's docstring claimed the NZ curve was "stronger than the general
curve's blend" — reasoning loosely from the marginal buckets, where NZ's mid-range buckets
(10-30s) do sit slightly above the general curve's own. Checking the actual comparison the engine
uses — the TIME-WEIGHTED INTEGRAL both curves produce, at the same seven segment lengths (5s to
1200s) — showed the opposite: **NZ's integrated effect is consistently BELOW the general curve's
own at every length tested**, because the general curve's strong early bucket is disproportionately
driven by the OZ-heavy portion of its pooled population (OZ's raw per-draw shot rate is far larger
than NZ's, even though NZ is the largest of the three zone populations by draw count). Caught by
computing the actual integrated values before publishing the claim, not by a test failure —
consistent with this session's practice of verifying a claim against the metric that's actually
used, not a proxy for it.

## The model and wiring

`historical_truth/faceoff_decay_model.py::segment_average_multipliers_nz` — same normalization and
integration discipline as every curve this session built (mean-1.0 per bucket, shared
`_integrate_curve` helper).

`faceoff_nz_index` is now wired end to end for the first time: `scripts/build_nhl_special_teams_artifact.py`
writes it as a new CSV column (reusing the same `playbyplay` cache and zone-split records the
OZ/DZ indices already parse — no new fetch), `loaders.load_team_special_teams_map` reads it, and
`engine.py` applies it as a THIRD additional multiplicative layer, composed alongside DZ (not a
tier of the OZ/EV/blend fallback chain, which never included NZ). Gated on BOTH sides carrying real
`faceoff_nz_index` data, the same bilateral discipline DZ already established.

**Wired straight to the discrete-event curve, with no legacy fallback** — unlike DZ (which had a
genuine wrong-direction period worth preserving for historical rollback), NZ was never live with
any wiring at all before this pass, so there is nothing prior to fall back to.
`faceoff_nz_discrete_event_model=False` disables the layer entirely rather than switching to a
different mechanism.

## Real per-team data

Regenerated `team_special_teams_latest.csv` with the new column: mean index 0.99997 across 32
teams (confirms correct normalization), real spread TOR (1.125x) to SEA (0.927x), ~21%
top-to-bottom — the same real spread measured when the index was first built in §2p, unchanged
since the underlying computation itself never changed, only its wiring.

## Verified

- **17 new unit tests** on the NZ curve (short-segment exact reproduction, the corrected
  weaker-than-general comparison at 6 segment lengths, the mean-1.0 invariant across 9 lengths,
  full-reconvergence at long segments, a real effect at the engine's typical ~42.5s length,
  invalid-input handling) — 85 total in the decay-model test file.
- **3 new reachability tests**: the NZ layer changes output (strong vs weak index); a one-sided
  value is a near no-op (bilateral gate actually gates); `faceoff_nz_discrete_event_model=False`
  fully disables the layer.
- **1 new loader test** confirming the CSV column round-trips into the resolved map correctly.
- **League-wide aggregate barely moved**: 992-pairing round-robin, NZ layer off 61.795 vs on
  61.774 avg total shots/game — a −0.034% delta, essentially zero.
- **456 hockeysim/nhl tests pass** (up from 435), checklist re-confirmed full PASS after wiring.

## What this does NOT do

- No further zone-specific curve remains to build — EV, OZ, DZ, and NZ are now all wired with
  their own real, measured, discrete-event treatment. What's left unbuilt is deliberate:
  strength-state-specific (PP/PK) faceoff effects, and the vendor's original block-rate ratio.
- The `faceoff_alpha`/`faceoff_diff_clip`/`faceoff_mult_clip_*` legacy sensitivity constants are
  now dead code on every zone-specific path (only the diminishing set of legacy-fallback branches
  still reads them) — not removed this pass, since `faceoff_discrete_event_model=False` (or the
  DZ-specific `faceoff_dz_discrete_event_model=False`) still legitimately needs them for rollback.
