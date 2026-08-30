# Unknown-submit live evidence — captured observations

Dedicated file. Written by the `unknown-submit-balance-evidence-capture` watcher
and by interactive sessions pulling the matching worker logs. Never `lanes.md`
or `state.md` — those are contended.

---

## 2026-08-30T17:13:55Z — the two RESOLVED unknown submits, recovered from logs

Interactive follow-up to the watcher's first run. The watcher reported
`unknown_submits=[]` with a passing positive control (`recent_orders_60m=12`,
newest submit 12.6 min old, `execution_enabled=true`, `live_armed=true`, kill
switch clear) — a real null. But `unknown_submits_resolved=2` said the mechanism
had already fired twice, so those two were chased down.

### THE HEADLINE, so nobody re-opens this hunt

**`balance_evidence` for these two rows does not exist and cannot be recovered.
It is not that the instrument missed them — the instrument postdates them.**

| thing | shipped | vs. the events |
|---|---|---|
| `UNKNOWN_ORDER_PROBE` emitter | `8edf77e5` 2026-08-27T22:18:43-05:00 (= 08-28T03:18:43Z) | **before** the resolutions — lines exist |
| `_balance_evidence` | `98e103e1` 2026-08-29T16:47:19-05:00, `3371ad96` 2026-08-29T18:19:21-05:00 | **after** both resolutions (08-28T19:37Z) |

Confirmed against the log body, not just the commit dates: `balance_settled`
appears **0 times** in 86 probe lines. The field is absent from the emitter as it
stood at `8edf77e5` — `git show 8edf77e5:...venue_settlement.py` prints
`unknown=`, `evidenced=`, `findings=` and nothing else.

So `balance_evidence` still has **zero observations**. This capture does not
change that; it explains why these two were never going to supply one.

### The two rows (verbatim, from `/api/portfolio/live?on=all&show=all`)

Both are hidden from the default payload: an operator resolution of `not_placed`
sets `status=rejected`, which makes the row a non-position, so `show=all` is
required to see them. `operator_resolution` is **not serialized** into `orders[]`
in either view — the `unknown_submits_resolved` counter is computed server-side
over `whole_book` (`syndicate/blueprints/intelligence.py:4516`). It was read here
off the `show=all` payload, where the field IS present.

```
idempotency_key        4b9fbe5912ef6a1688a68a21
venue_ticker           aec-mlb-kc-tor-2026-08-27
sport/market/segment   mlb / h2h / first5   side=away  price=-102.0
selected_date          2026-08-27
requested_stake        $6.22
submitted_at           2026-08-27T22:23:46.399832Z
venue_resolved_at      2026-08-27T22:23:47.022476Z
status                 rejected   (pre_resolution_status=failed)
venue_order_id         null
prior_attempts         (absent)
error                  PolymarketUSAuthError: http_503:
                       https://api.polymarket.us/v1/orders:
                       {"code":14,"message":"The server was unable to process your request.","details":[]}
operator_resolution    {"finding":"not_placed","note":null,"at":"2026-08-28T19:37:37.871054Z"}
balance_evidence       ABSENT — code shipped 2026-08-29, after this row was resolved
```

```
idempotency_key        639bc1935572d48068a28408
venue_ticker           tsc-nfl-sf-lv-2026-08-27-total-36pt5
sport/market/segment   nfl / totals / full  side=under  line=36.5  price=113.0
selected_date          2026-08-27
requested_stake        $1.99
submitted_at           2026-08-28T00:09:17.292118Z
venue_resolved_at      2026-08-28T00:09:18.814863Z
status                 rejected   (pre_resolution_status=failed)
venue_order_id         null
prior_attempts         (absent)
error                  PolymarketUSAuthError: http_503:
                       https://api.polymarket.us/v1/orders:
                       {"code":14,"message":"The server was unable to process your request.","details":[]}
operator_resolution    {"finding":"not_placed","note":null,"at":"2026-08-28T19:37:32.127168Z"}
balance_evidence       ABSENT — code shipped 2026-08-29, after this row was resolved
```

Payload-level: `unknown_submits=[]`, `unknown_submit_dollars=0`,
`unknown_submits_resolved=2`, `book_count=390`, `hidden_count=163`.

### The worker lines (`live-odds-worker`, verbatim body — all 86 identical)

```
[venue_settlement] UNKNOWN_ORDER_PROBE venue=polymarket unknown=2 evidenced=0 findings=[{'idempotency_key': '4b9fbe5912ef6a1688a68a21', 'market': 'aec-mlb-kc-tor-2026-08-27', 'selected_date': '2026-08-27', 'stake_dollars': 6.22, 'resolution_rows': 0, 'sole_claim': True}, {'idempotency_key': '639bc1935572d48068a28408', 'market': 'tsc-nfl-sf-lv-2026-08-27-total-36pt5', 'selected_date': '2026-08-27', 'stake_dollars': 1.99, 'resolution_rows': 0, 'sole_claim': True}]
```

- **86 emissions**, covered window `2026-08-28T03:31:31.787Z .. 19:29:29.807Z`
  (~16h, one per placing tick, ~11 min apart). Byte-identical apart from the
  timestamp — no drift, no partial state.
- First emission 03:31:31Z, ~13 min after `8edf77e5` was committed (03:18:43Z):
  that is the deploy landing, and it is why nothing exists earlier.
- Last emission 19:29:29Z, **8 minutes before** the operator resolutions. The
  probe went quiet because the rows cleared, which is the intended behaviour.

Closing the loop on the `syndicate` (web) service:

```
2026-08-28T19:37:32.261677556Z  [execution_ledger] OPERATOR_RESOLUTION key=639bc1935572d48068a28408 finding=not_placed venue=polymarket ticker=tsc-nfl-sf-lv-2026-08-27-total-36pt5 stake=1.99
2026-08-28T19:37:38.0023413Z    [execution_ledger] OPERATOR_RESOLUTION key=4b9fbe5912ef6a1688a68a21 finding=not_placed venue=polymarket ticker=aec-mlb-kc-tor-2026-08-27 stake=6.22
```

### Reading

**`not_placed` for both — on operator authority, corroborated by the probe, NOT
by balance arithmetic.** The probe independently found `resolution_rows: 0` and
`sole_claim: True` for each across all 86 passes, and `evidenced=0` throughout:
the venue's own resolution feed never showed these markets, and no other order
competed for the claim. The operator then looked at the venue screen and
answered `not_placed`. Two independent lines of evidence agreeing. What is
missing is only the third — the balance delta — which had no code yet.

Cause on both: `PolymarketUSAuthError: http_503` from `POST /v1/orders`. Same
error, two orders, ~1h45m apart. The venue 503'd on the submit and never
answered; the order never reached the book.

### CORRECTION TO THE TASK'S PREMISE — the window is HOURS, not minutes

The task brief says a row "clears within minutes" and treats the capture window
as the binding constraint. Measured, on the only two instances that exist:

| row | submitted | resolved | open for |
|---|---|---|---|
| `4b9fbe59…` | 08-27T22:23:46Z | 08-28T19:37:37Z | **21h 14m** |
| `639bc193…` | 08-28T00:09:17Z | 08-28T19:37:32Z | **19h 28m** |

Both sat unknown for the better part of a day, because clearing one requires a
human to open the venue's screen. **An hourly watcher is comfortably fast enough
— it would have caught either row ~20 times.** The "short window" premise is not
supported by evidence and should not drive the cadence up. A retry could still
clear a row faster than an operator, so the minutes case is possible in
principle; it has just never happened.

This also retires the reading offered in the watcher's first report — that two
windows "closed before anything observed them", implying a missed catch. They
did not close early. The instrument simply did not exist yet, and the probe that
DID exist observed them 86 times.

### Still owed

`balance_evidence` populated on a real unknown submit — **zero observations**,
unchanged. It needs a NEW unknown submit occurring after 2026-08-29. The hourly
watcher is the right instrument and its cadence is adequate; leave it running.
Nothing here should be read as the measurement the two closed lanes owe.
