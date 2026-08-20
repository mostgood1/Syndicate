# hockeysim faceoff mechanism — the multi-event-per-segment engine redesign (§2A)

Starts the engine-architecture redesign the segment-approximation impact measurement
(`docs/reports/hockeysim_faceoff_segment_approximation_impact_report.md`) scoped but didn't
attempt: replacing the "exactly one faceoff, always, every segment" assumption with the REAL
measured empirical distribution — `N` faceoffs per segment, drawn from the actual 106,272-segment
measurement, applied as `N` independent sub-window draws rather than one draw over the full
segment length.

## What was built

`historical_truth/faceoff_decay_model.py::sample_segment_faceoff_count` draws `N ∈ {0..6}` from the
REAL measured distribution (not a fitted Poisson or other parametric approximation — the real
counts are already in hand: 0→48.64%, 1→37.09%, 2→11.80%, 3→2.20%, 4→0.25%, 5→0.02%, 6→0.00%).

`engine.py::_multi_event_segment_multipliers` averages `N` independent discrete-event draws, each
applying the SAME decay-curve machinery every existing curve already used — `_integrate_curve` was
already generic over any `seg_len_seconds`, so no change to the curve math itself was needed, only
to how many times and over what window lengths the engine calls it. `N==0` returns the neutral
`(1.0, 1.0)` baseline directly (no real faceoff, no applied tilt) — the fix for the single largest
share of the mismatch (48.64% of real segments). `N≥1` splits the segment into `N` equal
sub-windows (a stated simplification — real intra-segment faceoff POSITION has not been measured,
so equal spacing is the most neutral assumption available, not a claim of precision beyond what's
measured) and draws each sub-window's winner independently from the same resolved percentage,
integrating the curve over the shorter sub-window length.

**Why the mean is provably unaffected.** Every curve is mean-1.0 preserving per bucket
(`winner_mult + other_mult == 2.0` always). Summing `N` independent Poisson processes, each with
rate `base_lambda/N * multiplier_i`, gives a combined Poisson with rate
`base_lambda * mean_i(multiplier_i)` — Poisson rates add, exactly, not approximately — so applying
the AVERAGE of `N` independent draws' multipliers to the segment's full, un-split lambda is
mathematically equivalent to summing `N` separate sub-segment draws. `E[m_home] + E[m_away] == 2.0`
holds for ANY win probability and ANY `N`, checked directly against the real curve at every
sub-length the redesign actually uses, not by statistical convergence.

**Scope, deliberately narrow this pass.** Applied to the EV-gated branch only — primary/OZ, DZ, and
NZ, which all now share ONE `n_faceoffs` draw per segment (they describe facets of the SAME real
event stream for that segment, zone is a property OF a draw, not a separate draw — drawing
independently would have been a real design flaw). Strength-state (PP/PK) segments' own
assumed-single-draw mechanism is untouched — a stated next step, matching every other layer's own
"narrow first, extend later" pattern this session has followed throughout. The lineup-aware layer
is correctly EXCLUDED from the multi-event framework entirely: it is a persistent per-game
roster-quality signal, not a discrete per-draw event, and was already applied once per segment
regardless of any faceoff count — nothing about it changes here.

New flag: `faceoff_multi_event_segment_model` (default ON). `False` restores the EXACT
pre-redesign, single-draw-over-the-full-segment behavior for primary/DZ/NZ, unchanged — a clean
rollback/A-B path, same discipline as every prior faceoff flag.

## Verified

- **Reachability**: `faceoff_multi_event_segment_model=True` vs `False`, holding every other input
  identical, produces a measurably different simulated shot-total standard deviation (a
  distribution-shape reachability test, not a mean-only one — this redesign's whole point is
  distributional, not average-shifting).
- **Per-team signal preserved**: under the new default mechanism specifically, a team with a real
  `faceoff_oz_index` edge still out-shoots a weaker one on average.
- **Exact analytical proof**: `E[m_home] + E[m_away] == 2.0` checked directly against the real
  curve at `sub_len = seg_len/n` for `n ∈ {1,2,3,5,6}`, and a separate exact (non-statistical) check
  that forcing `p_home_wins=1.0` reproduces the underlying curve's own multipliers exactly at every
  `n` — confirms the averaging arithmetic itself, not just its large-sample behavior.
- **League-wide round-robin** (992-pairing, 3 sims/pairing, 2,976 games/condition, identical seeds):
  mean moved **+0.275%** (61.783 → 61.953) — well within the noise range of every individual-layer
  check this session ran, safe to ship on that basis.

## An honest, non-confirming result — stated plainly, not adjusted to fit expectations

The natural hypothesis going in was that removing the unwarranted tilt from the 48.64% of segments
with zero real faceoffs would move the simulated shot-total standard deviation CLOSER to the real
observed value (8.295), since the earlier segment-approximation report found BOTH the ON and OFF
conditions sitting below it (96.71% and 98.84% of real, respectively).

**Measured the opposite.** Std moved from 8.023 (96.71% of real, the OLD single-draw default) to
7.966 (**96.03% of real**) — a further **-0.7%** reduction relative to real, not an improvement.

**A plausible reason, not separately proven**: when `N≥2`, averaging multiple independent
zero-sum, mean-1.0 draws together (the `sum/N` in `_multi_event_segment_multipliers`) reduces the
REALIZED variance of that average relative to a single draw — the same law-of-large-numbers effect
that makes an average of several coin flips less extreme than any one flip. Combined with `N==0`
segments now contributing NO variance at all (versus the old mechanism's own tilt-driven variance
contribution there), the net effect across the whole population is a further compression, not an
expansion.

**This does not invalidate the redesign** — the mean is unaffected, the per-team signal survives,
the reachability and analytical proofs hold, and the redesign is now a more architecturally honest
representation of the real generative process (0/1/2+ real faceoffs, not a wrong constant). But it
means the redesign should NOT be sold as "the fix" for the engine's shot-total variance running
tight relative to real games — that question remains open, and this measurement, if anything,
REINFORCES the segment-approximation report's own conclusion that the true cause lives elsewhere in
the engine's other stochastic sources, not in the faceoff mechanism at all.

## A real test-quality bug found and fixed while verifying this, not after

The full suite flagged `test_faceoff_strength_state_model_flag_actually_changes_output` as newly
failing after this change — investigated rather than dismissed as flaky. Root cause: that test
compared game-TOTAL shot output between `faceoff_strength_state_model=True`/`False`, but that
mechanism is EXACTLY mean-1.0-preserving by construction (the whole point documented in
`hockeysim_faceoff_strength_state_report.md`) — it redistributes shots BETWEEN home and away, it
does not move the game total on average. The test was checking a second-order artifact of that
redistribution, not the mechanism's own real, large, well-documented effect, and was already
fragile before this change — every OTHER discrete-event reachability test in the same file
correctly measures HOME-specific shots, this was the one outlier measuring the total. This
redesign's extra RNG draws (consumed earlier in the same shared `random.Random` stream, for EV
segments) shifted which random numbers later PP/PK segments in the same simulated game consume,
tipping an already-marginal total-shots signal past its threshold for the default seed range —
exposing a pre-existing test-design weakness, not introducing a new one. Fixed by measuring HOME
shots specifically, matching every other test's own correct pattern — now passes reliably, and
tests the mechanism's actual documented effect rather than a fragile side artifact of it.

## What this does NOT do

- Does not extend to strength-state (PP/PK) segments — a stated next step for a follow-up pass, not
  attempted here.
- Does not measure or model real intra-segment faceoff POSITION — every sub-window is equal length,
  a stated simplification, not a claim of precision beyond what's measured.
- Does not close the shot-total variance gap versus real games — if anything, this measurement adds
  evidence that the gap's true cause is NOT the segment-count approximation, since fixing that
  approximation more precisely made the gap marginally larger, not smaller.
- Does not attempt a literal per-second time-stepping reconstruction of the real game clock — the
  larger redesign the original §2r docstring named as the "real" fix remains a substantially bigger
  project, out of scope for this pass.
