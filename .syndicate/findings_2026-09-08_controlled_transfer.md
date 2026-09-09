# Controlled transfer — the measurement basis, and the pre-registration

`[lane bandwidth-controlled-transfer, session 40d9e921, 2026-09-08 23:4xZ]`

User decision: run option 2 from lane `render-egress-transport` — make one of the
two contradicting numbers KNOWN, instead of instrumenting a component.

**The main transfer has NOT fired.** This file records what the calibration found
first, because it changes what "known bytes" means, and the predictions, because
a prediction written after the reading is not a prediction.

---

## 1. THE UNIT I WAS ABOUT TO USE WAS WRONG BY 4.8x

The probe's calibration request received **283,308 B**. The edge log recorded
**58,753 B** for that same request — a 4.8x gap on one uncontended request, with
nobody else's traffic anywhere near it. 4.8x is the gzip ratio of a JS file, so I
tested it instead of assuming: four requests, two assets, two `Accept-Encoding`
values, each with a unique `ctprobe` token, then both Render logs read for those
exact tokens.

| asset | asked | client received | `content-encoding` | edge `responseBytes` | app access size |
|---|---|---|---|---|---|
| `cards-parity.js` | `identity` | 283,308 | (none) | **58,753** | **0** |
| `cards-parity.js` | `gzip` | 55,516 | gzip | **58,753** | **0** |
| `syndicate-logo.png` | `identity` | 60,588 | (none) | **60,944** | **0** |
| `syndicate-logo.png` | `gzip` | 60,588 | (none) | **60,944** | **0** |

**Two things fall out, and both are instrument facts, not theories.**

**(a) Render counts the ORIGIN's bytes, not the client's.** The JS logs `58,753`
whether the client asked for `identity` or `gzip` — the same number both times.
The origin always sends gzip (Cloudflare normalises `Accept-Encoding` toward it),
and Cloudflare inflates it for a client that asked for `identity`. So the 283,308
B my client received cost Render 58,753 B. **A client-side byte count is not the
quantity the meter counts, and using one as "known bytes" would have produced a
~5x error in the headline ratio** — in the direction that would have looked like
a discovery. The incompressible PNG is the clean unit: `60,944 = 60,588 body +
356 headers`, identical under both encodings.

**(b) The app log records `0` bytes for a static response.** All four requests,
both assets, both encodings: the gunicorn access line matched and its size field
was `0`, for responses of 55–283 KB. It is not a parse failure — `/api/intelligence/query`
in the same window logs real sizes (95.967 MB over 29 requests). **So `app.served_bytes`
is not a measure of what web sent; it is a measure of what web sent MINUS an entire
response class.** Every `metered ÷ app-served` ratio in the ledger — 11.25, 2.85,
3.05, 16.84, 9.32, and the older 1.04 / 0.17 / 0.035 — has a denominator with
that hole in it.

**What this does NOT explain.** The spikes are still unexplained, and this does
not rescue the log-incompleteness horn on its own: in the 16:00Z bucket the EDGE
log (which counts correctly, per (a)) carries 101.4 MB against 2,470.7 MB metered.
A 24x gap survives an instrument that undercounts only the app-log side.

## 2. PRE-REGISTERED — written before the transfer fires

Design: N requests for `syndicate-logo.png`, each with a unique `ctprobe` token
and the UA `syndicate-controlled-transfer/1.0`, entirely inside one clock hour.
Known volume, on the meter's own basis, is `N x 60,944 B`.

- **P1 — log completeness, no meter needed.** The edge log will show exactly N
  requests carrying exactly `N x 60,944 B`. If it shows materially fewer, the
  edge log drops lines under load and the second horn is CONFIRMED for the first
  time. If it matches, that horn is dead for edge traffic at this rate.
- **P2 — the app log will report ~0 bytes for all N.** Follows from (b) above; it
  is stated so that a nonzero result falsifies my reading of the four-request
  table rather than being absorbed.
- **P3 — the meter.** `metered_delta ÷ known_bytes` lands at ~1.0 (the meter is
  edge bytes), or at 1.7–2.2 (the ledger's normal-hour coefficient, which was
  inferred from correlated pairs and never controlled), or elsewhere. **I predict
  ~1.0**, because the coefficient's evidence is three uncontrolled pairs and one
  of them (`edge 55.0 -> meter 123.2`) sits in an hour whose composition nobody
  pinned. A result near 2.0 would mean the meter bills roughly double the bytes
  that leave, which is a billing claim and would need a second arm at a different
  volume before anyone acts on it.
- **Falsifier for the whole exercise:** if the hour carries an unexplained spike,
  the meter delta is uninterpretable and the run is void — not evidence for any
  of the three. Say so and re-run.

## 3. GATE — why it has not fired yet

`learnings.md` 2026-09-07 (no production reading while another session loads the
service) and 2026-09-08 (no self-refreshing board open against the service under
diagnosis). At 23:44Z the last 10 minutes carried **45.6 MB over 59 requests**,
34.3 MB of it from a Windows Chrome UA on `73.75.177.190` and 6.8 MB from a Linux
X11 Chrome UA on the same IP — the 30 s `installSharedBoardAutoRefresh` poller
that `skipWhenHidden: false` keeps firing at a hidden tab.

The gate is load-bearing here rather than procedural: subtracting a large
background from the meter would mean trusting the very log whose completeness P1
is testing. The probe refuses to fire above `--require-quiet-mb` and refuses to
straddle an hour boundary; both refusals are recorded in its output.

---

## 4. THE READING — scored by a SECOND READER, and what I add to it

`[2026-09-09 ~02:5xZ, session 40d9e921 — the lane owner, reading after the fact]`

**The primary record is not here.** Session `6767cdba` (the `bandwidth-spike-tripwire`
scheduled task, which I had armed as a backup in case this session did not survive
the two-hour settle) read the bucket at 02:3xZ and scored all three predictions in
the lane block, with the access-log half in
`.syndicate/findings_2026-09-09_web_access_log_dead.md` and lane
`web-access-log-emitter-dead`. **Read those, not a paraphrase of them.** Its
scoring is P1 CONFIRMED (~8% edge-log deficit, pager artifact ruled out), P2 VOID
(the emitter died at 23:45:58Z, 20 minutes before the transfer), P3 a coefficient
of **1.516–1.575** on real delivered bytes after correcting for P1.

I reached the same three conclusions independently before seeing theirs, by a
different route, and the numbers agree: my narrow-window rescan found **2,403 of
2,596** (0.9257) against their 2,399 (0.9187) — same finding, ~7–8%, and I also
ruled out **id collision in the dedup** (2,417 raw entries, 2,417 unique ids),
which their paging check does not cover. Two independent scans of the same
window differing by 4 lines is itself a small measure of the log's jitter.

**THREE THINGS I ADD.**

### (a) There is no "normal-hours coefficient" — the ratio is a continuum, not two regimes

The second reader places 1.52–1.58 "inside the ledger's existing 1.7–2.2x
normal-hours rule, slightly below it." That is true of my hour and not true of
its neighbours. Same instrument pair, same service, settled buckets:

| bucket | metered | edge logged | reqs | metered/edge | |
|---|---|---|---|---|---|
| 2026-09-09 01:00Z | 401.11 | 241.52 | 2,531 | **1.66** | the controlled hour |
| 2026-09-09 00:00Z | 437.73 | 203.57 | 366 | **2.15** | board traffic, no transfer |
| 2026-09-08 23:00Z | 315.35 | 88.48 | 285 | **3.56** | board traffic |
| 2026-09-08 17:00Z | 2,962.71 | 275.03 | 536 | 10.77 | SPIKE |
| 2026-09-08 16:00Z | 2,470.66 | 101.39 | 449 | 24.37 | SPIKE |

**1.66 → 2.15 → 3.56 → 10.77 → 24.37 is a smooth ladder, not a normal regime and
a spike regime.** The two hours either side of the controlled one, with no probe
traffic in them, sit ABOVE the 1.7-2.2 band and above the calibrated coefficient.
So "the meter charges ~1.5-1.6x" is a statement about ONE hour whose composition
was 62% identical 60 KB static files — not a property of the meter. Anything that
multiplies edge bytes by a constant to predict the bill remains unsupported, and
the spike hours may be the far end of one mechanism rather than a separate one.

(One row deliberately omitted: 2026-09-09 02:00Z read 45.47 MB at 13 minutes and
120.20 MB at ~50 minutes. Still settling, so it is not evidence of anything —
noted only because its ratio of 0.462 would look like a finding to anyone who
sampled it once.)

### (b) A mechanism for the dead access log that explains the key count

The other lane's hypothesis is "an environment change carried by that deploy,"
with `GUNICORN_CMD_ARGS` present on web, absent on the workers, absent from
`render.yaml`. What that leaves unexplained is the ledger's own record that web
went **84 → 85 keys, exactly +1** — the key was NEW, so nothing of ours was
overwritten, and no `--access-logfile` exists anywhere in our config or start
command. Yet access lines existed for weeks and stopped at that deploy.

**Hypothesis: Render injects its own default `GUNICORN_CMD_ARGS` containing
`--access-logfile -`, and a user-set value replaces the injected default
wholesale.** That accounts for all three facts at once: logging with no flag of
ours, a NEW key rather than an edit, and the emitter dying at the first deploy
after the key was set. **Falsifier, one env edit and a deploy:** set it to
`--max-requests 1000 --max-requests-jitter 100 --access-logfile -`. If access
lines return, confirmed; if they do not, this paragraph is wrong and the cause is
elsewhere. Cheap, reversible, and it restores the instrument either way.

### (c) The quiet gate held at fire time and then failed for the hour — worth separating

The pre-fire check is a 10-minute window; the meter's unit is an hour. Mine
passed at 5.493 MB and the hour still ended 43% background, because the board
came back at ~00:2xZ: 51.16 MB from a Windows Chrome UA and 21.20 MB from an X11
Chrome UA on `73.75.177.190`, plus 17.32 MB of `coverage_watch` polling and 13.94
MB from `174.253.98.187`. **A gate scoped tighter than the instrument's
resolution can pass and still leave the reading contaminated.** For the second
arm, the gate should hold for the whole hour, not the ten minutes before firing —
which in practice means watching during the transfer and voiding the run if
background arrives, not just checking before it.
