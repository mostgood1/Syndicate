# The coordinator session — role, contract, and limits

**Established 2026-08-17 by user decision.** One long-lived session owns
deployments, documentation upkeep, and cross-session organisation for Syndicate.
Other sessions do the engineering; this one keeps them from colliding and keeps
the ledger true.

This file is the contract. If you are a working session, you only need §2 and §3.

---

## 1. What the coordinator owns

- **Every production deploy, to all three services.** No session fires
  `render_deploy.py` or POSTs to `/deploys` on its own. See §2.
- **`render.yaml` pushes**, which are deploys wearing a different hat —
  `blueprint_sync` bypasses `autoDeploy = no` and rewrites the whole env block
  on live services. A config push is a deploy.
- **Ledger upkeep**: `state.md`, `lanes.md`, `lanes_closed.md`, `learnings.md`,
  `deploys.md`, and the todo files. Sweeps, orphan detection, obligation
  reconciliation, size budgets.
- **Lane organisation**: who holds what, what is orphaned, what collides, what
  is stale. Opening and closing lanes on behalf of sessions that have ended.
- **Cross-session routing**: relaying findings between sessions that cannot see
  each other, and holding the queue when two lanes want the same file.

## 2. If you want something deployed

Write one file. Do not wait for a reply before carrying on with other work.

```
.syndicate/deploy/requests/<UTC-timestamp>-<lane>.md
```

```markdown
service:  web | refresh-worker | live-odds-worker
sha:      <commit>, cut from <what>
reason:   what it fixes, in one line
verify:   the reading that proves it worked, and where to take it
rollback: the SHA to go back to
urgency:  and say plainly when nothing is blocked
```

`verify` is the field that matters and the one most often left vague. "Watch the
memory profile" is not a verification; "`LEDGER_CHUNKS_ACCEPTED` bytes fall below
830,832,574 within one bundle" is. **A deploy with no stated reading is a deploy
whose success cannot be claimed** — the ledger already carries fourteen of those.

The coordinator picks it up, runs `/preflight`, deploys into a safe window,
takes the reading, writes it to `deploys.md`, and reports back to your session.

**Genuinely urgent?** Message the coordinator session directly. Urgency is a
reason to talk to it, never a reason to route around it — the ~2 GB transient
and the OOM band mean a badly-timed deploy costs an in-flight sim, and the
sim-in-flight check is exactly what the coordinator holds.

## 3. What working sessions still own

Everything else, unchanged:

- your lane, your files, your commits, your measurements;
- `/lane open` before editing, `/checkpoint` before ending;
- writing your own findings to your lane block and to `deploys.md`.

**Two rules the coordinator cannot enforce for you, so they stay yours:**

1. **Open your lane with EM-DASHES.** `lane-guard` parses
   `^###\s+(\S+)\s+—\s*([^—]*)` and requires U+2014. A header written with ASCII
   hyphens does not parse, and your claimed files are then silently unguarded.
   This has already happened once, to a live lane, on 2026-08-17.
2. **`git diff --cached --numstat` before AND after every commit.** The shared
   index is state shared between processes with no lock; `HEAD` moving under it
   changes what it means. Five recorded occurrences of a revert sitting staged.

## 4. Limits — what this role does NOT give the coordinator

Stated plainly so nobody relies on something that is not true.

- **It cannot see inside your session.** It reads the ledger, the repo, git, the
  Render API, and the session roster. If a fact only exists in your context, the
  coordinator does not have it. Write it down.
- **It cannot stop you.** Enforcement is a `PreToolUse` hook if one is
  installed, and hooks fail open by design. This is a lane discipline, not a
  permission system.
- **It is not a reviewer or an approver of engineering decisions.** It does not
  adjudicate whether your fix is right. It serialises deploys, holds the
  guardrails, and takes the measurement.
- **It does not hold your context for you.** A handoff that says "see our
  earlier discussion" is not a handoff.

## 4a. Unattended sessions — the queue is a FILE queue for a reason

Scheduled-task and dispatched runs **cannot send or receive `send_message`**.
Measured 2026-08-17: the coordinator tried to reach `verify-movement-line-gate`
and was refused; the 2026-08-15 smaps request says the same thing from the other
side ("cross-session messaging was UNAVAILABLE — this lane's session is
unattended... the ledger is the channel").

Consequences, and they shape the whole protocol:

- **The request queue is files, not messages.** An unattended session can always
  write a request file; it can never DM the coordinator. Anything that requires a
  conversation excludes exactly the sessions that run while nobody is watching.
- **The coordinator POLLS `deploy/requests/` and does not wait to be told.** A
  request that arrives with no notification is the normal case.
- **The digest and `CLAUDE.md` are the only channels that reach every session**,
  attended or not, because both are read at session start. That is why the deploy
  rule lives there and not only in this file.
- An unattended session that needs a deploy and gets no reply **must not deploy
  anyway**. It records the request and ends. The work is not lost; it is queued.

## 5. The standing queue

Live state lives in `lanes.md` under the coordinator's lane, not here, so this
file stays a contract rather than a status board. The coordinator maintains:

- `.syndicate/deploy/requests/` — inbound, one file per request
- `.syndicate/deploy/done/` — executed, with the measurement appended
- `.syndicate/deploy/grants/<session_id>.json` — a scoped, expiring exception
  when a session must deploy for itself
- `.syndicate/coordinator.id` — the session id that currently holds this role.
  **Delete this file and the role stands down**; a hook that finds no
  coordinator allows everything, which is the intended off switch.
