---
description: Hard gate before any Syndicate deploy
argument-hint: <what is being deployed>
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git log:*)
---

Deploy candidate: `$ARGUMENTS`

Answer every question. A missing answer is a FAIL, not a shrug.

1. **Scope.** `git diff` against the deployed SHA in `state.md`. Is this
   exactly one substantive change? If we are diagnosing and the answer is
   no, FAIL — split it.

2. **Expected effect.** State it as a number and a window.
   "Egress drops below 2 GB/hr within 90 minutes." Not "should help."

3. **Measurement.** Where does the number come from, and who reads it?
   If nobody is assigned to read it, FAIL.

4. **Blast radius.** Which services restart? For any service on a
   persistent disk, note that deploys are stop-then-start with downtime
   and that instances cannot overlap.

5. **Rollback.** Exact command or PR revert, stated now.

6. **Ledger check.** Does `learnings.md` contain a rule this deploy
   violates? Does an OPEN lane in `lanes.md` touch the same files?

7. **Verdict.** PASS or FAIL. On PASS, append the pending row to
   `.syndicate/deploys.md` with the measurement column left empty and a
   reminder timestamp. On FAIL, list the shortest path to PASS.

8. **Take the locks.** This checklist is the REASONING gate; it is not the
   mechanical one, and passing it deploys nothing. `deploy-guard.py` wants two
   readings that outlive this session:

   ```bash
   python scripts/deploy_claim.py acquire --service <svc> --holder <lane>
   python scripts/deploy_preflight.py --service <svc> --holder <lane>
   ```

   The claim answers "is this service mine"; the preflight answers "is anything
   in flight right now", and its CLEAR expires in 15 minutes — so run it LAST,
   immediately before deploying, not at the top of the checklist. Release the
   claim once the measurement is written.
