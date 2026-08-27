# Checkpoint — `polymarket-oddsapi-coverage-audit`, session `0fd6da62`

Closed 2026-08-26 ~17:0xZ. Claims released, session archived.
Full detail in `.syndicate/lanes.md` under this lane's **CLOSE-OUT** heading.

## One thing to act on

**`SYNDICATE_POLYMARKET_SPREAD_AUDIT_ON_BOOT=1` is still set on
`live-odds-worker`.** Read-only, prints one `SPREAD_SIGN_AUDIT` line per boot,
changes no behaviour — but nobody else knows it is there. Next person to boot
that service: read the line, unset the flag. Verdict is `UNDECIDED` at n=2;
NFL week 1 (2026-08-27) supplies the sample. `rate` ~1.0 = `<home>`,
~0.0 = `<away>`, anything between falsifies the finding and spreads stay refused.

## Shipped, measured

| | |
|---|---|
| `#559` | sweep partition premise false; **7,936 -> 17,413** markets; `no_candidates\|mlb\|spreads` 51 -> gone |
| `#560` | NO-side fills at YES-side price. **3 rows, $3.22**, already self-healed. Closed + archived |
| `#561` | verified another lane's fix instead of shipping mine — theirs was more correct |
| baseline | regenerated **15 -> 19 of 11,745** |
| `#570` `#571` `#572` | filed |
| workflow | `pytest-baseline-update.yml`, dispatch-only, opens a PR |

Deploys: 4, each recorded in `deploys.md` with the reading that proves it.
PRs #93 #94 #95 #96 merged. Tree clean.

## Not done — do not re-derive

1. **CI is still red and the baseline regeneration did not fix it.** Gate
   returned exit 1 = `EXIT_NEW_FAILURES` on `682f66e98`. **The failing names
   were never read** — logs 403 through this session's proxy. They are in run
   `32988066215`, step *"Full pytest suite (enforced — no NEW failures vs the
   baseline)"*. Read that list BEFORE regenerating again.
2. **The `psutil` explanation is refuted, not untested** — absent in both
   environments, same Python 3.11, same args. The divergence is unexplained.
3. **`pytest-baseline-update` has never run.** Dispatch needs `actions: write`;
   this session got `403 Resource not accessible by integration`.
4. **`#571` needs the owner of `0acabd091`** to say whether the widened
   `_candidate_keys` output is intended for the Polymarket path.

## Lane invariants

`check_lane_invariants.py` reports `VIOLATED: 4 contested file(s)`. **Pre-existing
and not this lane's** — verified by running it against a stashed tree and getting
the identical count, and this lane's name appears zero times in the output.

## Two corrections worth carrying

- **"CI was not dispatched for PR #94" was wrong.** The run existed, created
  ~18 minutes late, after I merged. "Not started yet" and "will not run" look
  identical for tens of minutes — that is `#572`'s sharpest point and it is a
  merge-safety property, not a convenience one.
- **A watcher reported a verdict from the wrong run.** It filtered by run
  `created_at` rather than commit ancestry, so a run created after the merge but
  testing a pre-merge commit was accepted. Caught before reporting it as the
  answer; the fix is `git merge-base --is-ancestor`. **Timestamps are not
  ancestry.**
