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
