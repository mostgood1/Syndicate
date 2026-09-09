# web's gunicorn access log has been DEAD since 2026-09-08T23:45:58Z — and it is one of the two numbers the `[render-egress-spikes]` contradiction is between

`[2026-09-09, session 6767cdba (scheduled task `bandwidth-spike-tripwire`, user-directed), read-only, NO DEPLOY]`

## The one-line version

Web stopped emitting gunicorn access lines at **2026-09-08T23:45:58Z** and has
emitted **zero** in the 2h12m since. Lane `bandwidth-controlled-transfer` fired
its controlled transfer at **00:06:27Z — 20 minutes after the emitter died** — so
that experiment's **P2 could never have scored**, and its `0 access lines` is a
statement about the EMITTER, not about the burst.

## How this was found, and what it corrects

Running the tripwire's own reader against the 00:06Z transfer returned
`P2: access lines with ctprobe 0` and `whole-hour app served 0.000 MB`. Two
readings were available and they are opposites:

- **(a) the log DROPS LINES UNDER BURST** — which would have been direct evidence
  for the standing "the log is materially incomplete in exactly the high-volume
  hours" horn of the contradiction, or
- **(b) the emitter was already off** — in which case the zero says nothing at all
  about bursts.

`learnings.md`: an absent signal is a statement about the emitter until proven
otherwise. Separated by slicing the SAME hour either side of the burst:

| 5-min slice (UTC) | app lines | access lines | in burst |
|---|---|---|---|
| 23:40–23:45 | 313 | **207** | |
| 23:45–23:50 | 372 | **71** | |
| 23:50–23:55 | 224 | **0** | |
| 23:55–00:00 | 197 | **0** | |
| 00:00–00:05 | 194 | **0** | |
| 00:05–00:10 | 628 | **0** | **BURST** |
| 00:10–00:15 | 355 | **0** | **BURST** |
| 00:15–00:40 | 1,283 | **0** | |
| 00:40–01:51 | 5,404 | **0** | |

**It is (b).** The zeros start ~16 minutes BEFORE the burst and continue for
2h+ after it. **The burst is EXONERATED as a cause of log loss** — that horn of
the contradiction gets no support from this reading, and must not be recorded as
if it did.

Narrowed to 2-minute slices, the last access line is
**`2026-09-08T23:45:58.694Z`**; the 23:46–23:48 slice has 203 app lines and zero
access lines.

## What those lines were, and why losing them matters

They are standard gunicorn combined-format lines, and their client IPs are
**internal `10.x`**:

    10.228.19.182 - - [08/Sep/2026:18:40:00 -0500] "GET /healthz HTTP/1.1" 200 34 "-" "Render/1.0"
    10.195.148.108 - - [...] "GET /api/ops/artifacts/export?path=wnba_source%2F... HTTP/1.1" 200 37 "-" "Python-urllib/3.11"

`[render-egress-spikes]` states that internal service-to-service traffic appears
**only** in these lines, and that *"the GAP BETWEEN THEM is the unresolved
question"*. So this outage has removed the only instrument that measures one side
of the contradiction under investigation.

**Concretely: `app served MB` is now structurally 0 for any bucket after
23:47Z.** The tripwire prints that field on every capture, and
`metered ÷ app-served` is the ratio the whole 2026-09-08 finding rests on
(11.25, 2.85, 3.05, **16.84**, 9.32). Any such ratio computed from here is a
division by an artifact and will read as an infinite gap.

**The five published 2026-09-08 ratios are NOT affected** — buckets 01:00Z and
15:00–19:00Z all closed before 23:47Z, with the emitter live. This does not
retract them.

## The boundary coincides with a web deploy — mechanism NOT established

| event | time (UTC) |
|---|---|
| last access line | 23:45:58Z |
| deploy `dep-dag9rh2jnfac73ffajg0` created | 23:44:04Z |
| build ended | 23:45:49Z |
| **deploy_ended, succeeded** | **23:47:29Z** |

**TWO INFERENCES I MADE AND THEN DISPROVED — recorded so nobody re-makes them:**

1. *"That deploy changed the start command."* **FALSE.** Its commit
   `e4552e279e59` touches **`.syndicate/lanes.md` only, 8 insertions**.
2. *"`--access-logfile` was removed from `render.yaml`."* **FALSE.**
   `git log -S"access-logfile" -- render.yaml` returns **nothing** — the flag has
   never been in that file, and the live `startCommand` does not contain it.

The live start command is:

    sh -c 'PORT=${PORT:-10000}; exec gunicorn wsgi:application --bind 0.0.0.0:$PORT
      --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-1} ...'

Gunicorn writes no access log unless one is configured, so the access log was
**never** on via the start command — yet it demonstrably ran until 23:45:58Z.
The remaining channel is the environment: **`GUNICORN_CMD_ARGS` is present on
web and on NEITHER worker**, and it is **not declared in `render.yaml`** —
out-of-band env drift on the one service that had an access log.

**NOT ESTABLISHED, and deliberately not guessed at:** whether that key's VALUE
changed at 23:44Z. Its value was not read (it is a secret-shaped read and not
needed to establish the outage). Render's `deploy_started` event for this deploy
carries an `envUpdate` field in its trigger blob, which is consistent with an env
change but is **not** proof — the field was truncated in the event listing and
was not decoded.

**A live consequence either way:** an out-of-band env var that `render.yaml` does
not declare is exactly what a `blueprint_sync` **overwrites**, per `CLAUDE.md`
(*"a sync writes the WHOLE env block, not your diff"*). Whatever its value, it is
drift, and it is invisible to the blueprint.

## Owed

1. **Restore the emitter, or record deliberately that web has no access log.**
   Until then every bandwidth capture's `app served` field is silently 0 and the
   tripwire will keep printing it as if it were a measurement.
2. **Gate on it.** `bandwidth_tripwire.py` should refuse to report
   `app served MB` when the access-line count for the bucket is 0 while the edge
   log is non-empty — an unreadable instrument must not render as a small number.
   (`learnings.md` 2026-09-08: an unknown must not default to the permissive
   branch; and the tripwire's own trap 3 says reading either log alone misses
   half the picture.)
3. Decode that deploy's `envUpdate` trigger blob to close the mechanism.

## Method / substrate

Substrate `render` throughout: Render's logs API (`type=app`, `type=request`),
metrics API, services/deploys/events API. No local `data/` was read and nothing
here rests on the checkout. Read-only; no deploy taken, no env var written.
