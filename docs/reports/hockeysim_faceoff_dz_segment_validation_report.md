# hockeysim DZ-specific segment-level validation — a real effect, the WRONG direction

Closes the item `hockeysim_faceoff_discrete_event_redesign_report.md` explicitly left open: "DZ's
own segment-level effect was never separately measured." The result contradicts the story that
justified building `faceoff_dz_index` in the first place — stated here as plainly as every other
finding this session, surprising or not.

## The DZ mechanism's original claim

§2o's own docstring: "a team that wins its own DZ draws well typically clears the puck and starts a
breakout, which does TWO things at once: suppresses the OPPONENT's sustained shot generation from
that zone-time... AND can spring the winning team's own transition/rush chance." Both halves of
that claim predict the SAME direction as the general EV/OZ effect already validated (§2q): the
faceoff winner should out-shoot the team that just lost the draw in the following seconds.

## Method

Extended `historical_truth/faceoff_segment_effect.py` with a `winner_zone` filter (backward
compatible — `None` reproduces the exact original unfiltered behavior, 13 pre-existing tests
unchanged). `scripts/validate_nhl_faceoff_dz_segment_effect.py` restricts the same winner/other
post-faceoff shot-counting methodology §2q already validated to draws the winner took in THEIR OWN
defensive zone (`winner_zone="D"`) — 19,458 of the 58,762 total real EV faceoffs.

## Result — consistent across all 4 window sizes, and consistently in the WRONG direction

| window | DZ draws | winner share | shots/100s winner | shots/100s other | ratio | for comparison: all-zone EV winner share |
|---|---|---|---|---|---|---|
| 10s | 19,458 | 0.4189 | 0.3280 | 0.4550 | 0.721x | 0.7935 |
| 15s | 19,458 | 0.4639 | 0.4479 | 0.5177 | 0.865x | 0.7337 |
| 20s | 19,458 | 0.4723 | 0.5018 | 0.5605 | 0.895x | 0.6882 |
| 30s | 19,458 | 0.4665 | 0.5502 | 0.6293 | 0.874x | 0.6361 |

**The team that wins a defensive-zone draw is OUT-SHOT, not out-shooting, in the following seconds
— at every window tested.** This is the OPPOSITE direction from the general EV/OZ effect (winner
share 0.79 at 10s, well above 0.5) and from what the DZ mechanism's own justification predicted.
Unlike the general effect's clean monotonic decay toward 0.5, the DZ-specific ratio does not show
the same tidy convergence pattern — it stays below parity throughout the measured range, rising
only slightly (0.42 → 0.47) rather than crossing back toward 1.0.

## OZ-specific comparison — confirms OZ's direction, isolates DZ as the real anomaly

Ran the same `winner_zone` filter with `"O"` instead, as a sanity check this measurement technique
itself is sound:

| window | OZ draws | winner share | ratio |
|---|---|---|---|
| 10s | 18,662 | 0.9309 | 13.47x |
| 15s | 18,662 | 0.8760 | 7.06x |
| 20s | 18,662 | 0.8344 | 5.04x |
| 30s | 18,662 | 0.7779 | 3.50x |

**Winning your own offensive-zone draw produces an EVEN STRONGER effect than the blended EV
population** (0.93 winner share at 10s vs. 0.79 blended) — exactly what real hockey intuition
predicts (you keep the puck exactly where a shot is most likely) and exactly the direction the OZ
mechanism (§2n, already shipped) assumes. This is a genuinely useful confirmation: the measurement
technique itself produces the expected strong positive result when pointed at the zone it should,
which makes the DZ result's opposite direction a real finding about DZ specifically, not an
artifact of the method.

## A real, coherent alternative explanation

A faceoff taken in a team's own defensive zone happens BECAUSE the puck was already there when the
stoppage occurred — winning the draw does not instantly transport the puck to center ice. A clean
clear is only one possible outcome; the puck often stays live in the zone (a loose-puck battle, a
blocked clearing attempt, an iced clear that gets recovered by the opposing team on the ensuing
draw... though that specific case is excluded here by construction, since the counted window ends
at the very next EV faceoff). The team that just lost the draw is frequently STILL the team
applying pressure moments later — the data is consistent with that being the dominant pattern, not
the "clean breakout, immediate suppression" story the mechanism assumed.

## What this means for the shipped mechanism

`engine.py`'s `faceoff_dz_index` (§2o) currently applies `m_dz_h` (>1 when the home team's own DZ
win-rate index is elevated) to boost `lam_h` — i.e., a team good at winning its own DZ draws gets
MORE of its own shots boosted. **This segment-level measurement suggests that direction may be
backwards relative to what a faithful, real-data-grounded model would show**: real DZ wins are
followed by relatively FEWER shots for the winner, not more, in the immediate aftermath.

This is NOT a recommendation to blindly flip the sign — `faceoff_dz_index` itself (the per-team
relative differentiation, verified independently: real spread, correct zero-sum normalization,
genuine independence from the OZ index at r=0.69) is unaffected by this finding; only the WIRING
DIRECTION composing it into the engine is now in question. Changing engine behavior based on this
finding is deliberately NOT done in this pass — flagged as the next well-scoped item, matching this
session's own discipline of measuring before changing (§2q wasn't redesigned in the same pass it
was validated either; §2r came after, once the shape of the fix was clear).

## Verified

- **4 new unit tests** for the `winner_zone` filter (matching population, exclusion, backward
  compatibility with `None`, and that the truncation boundary still considers every EV faceoff
  regardless of ITS zone — truncation is about not double-counting a shot, not about which draws
  are studied).
- **17 total tests pass** in `test_hockeysim_faceoff_segment_effect.py` (13 pre-existing + 4 new),
  confirming the extension didn't disturb the already-validated general-population behavior.
- **Robust across 4 independently-run window sizes**, all showing the same below-parity direction —
  not a single-run artifact.

## What remains genuinely open

- **Whether to change the DZ mechanism's wiring direction** — the natural next step this report
  sets up, not attempted here.
- **Whether a genuinely faithful DZ mechanism should suppress the WINNER's shots rather than boost
  them** (the literal implication of a naive read of this data) needs its own careful design pass —
  this measurement establishes the DIRECTION problem, not automatically the correct fix, since
  "the winner gets fewer shots" and "the winner should be modeled as getting fewer shots" are not
  automatically the same claim (a segment-level effect this specific may itself need the same
  discrete-event treatment §2r gave the general case, rather than a simple sign flip on a still-flat
  per-segment constant).
- **Zone-specific effects for OZ specifically** (isolating `winner_zone="O"`, the mirror case) —
  not run this pass, would be a natural, cheap addition using the same new filter.
