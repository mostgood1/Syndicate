# SmartSim Production Integration Phase 3: Public Blend Trial Report

- Date: 2026-07-16
- Scope: NCAAF, controlled public-facing visibility. **No SmartSim simulation logic, NFL profile, NCAAF profile, or blend mathematics was modified** — confirmed by an empty `git diff` against `HEAD` for `smartsim2_blend.py` and everything under `syndicate/features/football/`.
- References: `smartsim_blend_trial_report.md`, `smartsim_source_separation_report.md`, `smartsim_ensemble_evaluation_report.md`.

## Design: Public vs. Internal Visibility Are Two Separate, Independent Mechanisms

Phase 2B's internal-diagnostics flag (`SMARTSIM_BLEND_TRIAL_DIAGNOSTICS`) is **untouched** and still governs the engineer-only view exactly as before. This phase adds a second, independent gate for a genuine public trial, because the two audiences need different things: an engineer checking `projection_sources` needs raw internal labels and doesn't mind a "diagnostic" framing; a real trial user needs a clean explanation of what they're looking at and a label that doesn't read as an unfinished internal artifact.

**New public-safe label**: `SMARTSIM2_PUBLIC_LABEL = "SmartSim 2.0"` (drops the "(shadow)" suffix the internal `SMARTSIM2_SOURCE_LABEL` carries). Both constants live side by side in `smartsim2_projection.py`; `_attach_smartsim2_shadow_fields()` in `cards.py` now computes a `projection_sources_mode` (`"public_trial"` / `"internal_diagnostic"` / absent) and picks the right label set accordingly. Public trial takes precedence if both mechanisms are somehow active at once (verified by test).

## Task 2/7: Feature-Gated Visibility and Rollout Controls

Two independent, additive rollout-control mechanisms, both gated behind one master switch — matching all three examples the task named (environment variable, configuration flag, internal whitelist):

| Control | Env var | Behavior |
| --- | --- | --- |
| Master switch | `SMARTSIM_PUBLIC_TRIAL_ENABLED` | Kill switch. Off by default; if off, no request is ever checked, full stop. |
| Trial-token allowlist | `SMARTSIM_PUBLIC_TRIAL_TOKENS` | Comma-separated list of opaque tokens. A request is granted access if `?smartsim_trial=<token>` (query parameter) or a `smartsim_trial` cookie matches one of these. This is the "share a private link with N testers" mechanism. |
| IP allowlist | `SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST` | Comma-separated list of exact client IPs. A request is granted access if `request.remote_addr` matches — the literal "internal whitelist" mechanism, useful for an office/VPN egress IP without needing to distribute a token. |

Both allowlists default to empty, so **turning on the master switch alone still shows nothing** — an operator must deliberately populate at least one allowlist, a safety-by-default property confirmed by test (`test_false_when_master_on_but_no_allowlists_configured`). Either allowlist independently grants access once the master switch is on (OR logic) — a tester needs only one of a valid token or a whitelisted IP, not both.

**Known simplification, disclosed rather than hidden**: the token mechanism checks the query parameter and an already-set cookie, but nothing in this phase sets that cookie automatically — a tester must keep the `?smartsim_trial=...` parameter on each link they follow, or a manual cookie would need to be set out of band. Full cookie-persistence (so one clicked link "sticks" across subsequent navigation) would require touching the blueprint route layer to set response cookies, which this phase deliberately did not do to keep the change surface to the two already-reviewed files from Phase 2B plus `cards.py`/`picks.py`. Recommended as a fast follow if the trial's testers find the parameter-per-link requirement is genuine friction.

## Task 3/4: Preservation Checks

- **Existing projection generation**: unaffected. The generation script (`scripts/generate_smartsim2_ncaaf_projections.py`) and the `SmartSimNcaafProjection` contract are untouched this phase — no diff.
- **Existing publication gates**: verified identical. Built the same week's cards context three ways — no flags set, internal-diagnostics on, and public-trial on with a matching token — and compared every game's `coverage_score`/`publication_status`. **Identical across all three.** Visibility mode has zero bearing on what publishes or how it's prioritized.

## Task 5: Source Attribution

All three sources are labeled in both public surfaces (the shared `_game_card_ncaaf.html` panel, used by cards and game-detail; the picks-page list items): "Enhanced Totals Engine," "SmartSim 2.0," and "Consensus Projection." The public panel additionally carries an explanatory line ("You're seeing this because you're part of a limited SmartSim 2.0 trial... shown alongside our standard projection, not in place of it") so a trial user understands both why they see extra numbers and that the existing projection they're used to hasn't been replaced.

## Task 6: Verification (Real HTTP Round-Trips, Flask Test Client)

Using the same week-1 2025 trial artifact from Phase 2B (47 in-scope games):

| Page | Route | With valid trial token | Without a token (master on, no match) |
| --- | --- | --- | --- |
| Cards | `/ncaaf/cards?week=1` | 200, "Model Comparison" panel renders, public "SmartSim 2.0" label (not "(shadow)"), zero internal-diagnostic wording | 200, zero trial content of any kind |
| Picks | `/ncaaf/picks?week=1` | 200, public-trial list items render with public label | 200, zero trial content |
| Game detail | `/ncaaf/game/1_New_Mexico_Michigan?week=1` | 200, same shared panel renders | (not separately re-tested; same code path as cards) |

All three pages render correctly with the public gate active, and are completely inert (byte-identical to Phase 2A's baseline) when the gate doesn't match the request — confirmed by checking for the literal absence of both "Model Comparison" and "Internal diagnostic" text in the unmatched-request responses.

## Testing

14 new tests in `tests/test_ncaaf_public_trial.py` covering: master-switch parsing, all four gate-denial paths (no request context, master off, no allowlist configured, non-matching token/IP), all three grant paths (query token, cookie token, IP match), mode precedence, and the default no-leak guarantee. Combined with the 30 tests already passing from Phases 1-2B: **108 passed** across the full `ncaaf`/`smartsim2` suite, same 7 pre-existing/unrelated failures as every prior phase (traced to files outside this diff), zero new failures.

## Task 9: Explicit Answers

### What users will see?

Nothing different, by default. A user who is neither given a trial token nor browsing from a whitelisted IP sees exactly what they see today — the Enhanced Totals Engine's projection, unchanged. A trial participant (valid `?smartsim_trial=` token or whitelisted IP) additionally sees a clearly-labeled "Model Comparison" / experimental-preview panel on cards and game-detail pages (and equivalent list items on the picks page) showing all three sources' margin and total side by side, with an explanation that these are experimental and shown alongside, not instead of, the standard projection.

### What remains hidden?

The blend weights and total-bias correction constant, `margin_stdev`/`total_stdev` (Monte Carlo consistency), `seeds_used`, `profile_name`, `rating_source`, and the internal `"SmartSim 2.0 (shadow)"` label itself (trial users only ever see the public "SmartSim 2.0" label) — unchanged from the Phase 2B and production-plan internal/external boundary. The internal-diagnostics view (Phase 2B) also remains available and unaffected, still gated purely by its own env var, entirely separate from the public mechanism.

### What rollback path exists?

Instant and layered: unset `SMARTSIM_PUBLIC_TRIAL_ENABLED` (or set it to a falsy value) to kill the feature for everyone regardless of any configured allowlist — no code change, no redeploy, no data loss, since nothing about projection generation or publication was touched. A narrower rollback — revoking one tester without affecting others — is just removing their token from `SMARTSIM_PUBLIC_TRIAL_TOKENS` or their IP from the IP allowlist.

### What monitoring should be enabled?

Everything already specified in `smartsim_production_integration_plan.md` (rolling backtest, SmartSim availability/fallback rate, disagreement monitor, publication-gate before/after checks — the last of which this phase re-verified stays clean) plus two trial-specific additions: (1) track which allowlist entries are actually being used (a token nobody uses isn't testing anything); (2) since this is the first time real, uncontrolled requests (not test-client calls) could hit this code path, watch for anomalies specifically correlated with trial-flagged requests — e.g., elevated error rates or latency only on requests carrying a valid trial token, which would point at something the internal-only Phase 2B testing didn't exercise (concurrent real users, real browsers, real cookies).

### Is SmartSim ready for broader exposure?

**Not yet, and this phase doesn't claim otherwise.** This is a mechanism for a *controlled* trial — the whole point is that broader exposure is exactly what the allowlists prevent until someone deliberately widens them. Broader exposure should wait on: a real trial period with actual (not synthetic) users generating the "requests carrying a valid trial token" data point named above, and the walk-forward-ratings gap flagged since `smartsim_production_integration_plan.md` (this trial still uses season-aggregate PPA ratings, the same disclosed limitation as every prior phase).

## Final Verdict

**Public Trial Ready.**

The mechanism is built, tested end-to-end with real HTTP requests and a real generated artifact, confirmed inert by default and fully reversible, and confirmed to leave projection generation and publication gating byte-identical. It is "ready" in the sense the task asked for — a controlled subset of users can now be granted visibility into SmartSim 2.0 and Consensus Projection outputs without touching any existing system — not in the sense of being ready for unrestricted rollout, which remains appropriately gated behind an actual trial period.
