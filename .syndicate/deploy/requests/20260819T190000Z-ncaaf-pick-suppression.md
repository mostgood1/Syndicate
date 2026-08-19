# Deploy request — NCAAF pick suppression (WEB)

    service:  web (the gate is a SERVING-layer change; workers are unaffected)
    sha:      95602d2a on origin/main  (a normal main deploy, not a graft)
    reason:   PRODUCTION IS SERVING 12 NCAAF PICK CARDS RIGHT NOW that the
              model cannot justify. Measured 2026-08-19: NCAAF margin model
              MAE 13.763 vs closing line 11.586 over 220 games, paired
              dMAE +2.176, SE 0.518, t=+4.20. Every scale 6..24 loses.
    urgency:  NCAAF opens 2026-08-29. Not an outage — the opposite: the board
              is confidently serving advice it has not earned.

## Measured on the LIVE board, 2026-08-19 18:5xZ

    GET https://syndicate-an21.onrender.com/ncaaf/api/picks?week=1
    -> 12 pick cards, e.g. "Notre Dame vs Wisconsin SmartSim 2.0 candidate"

Local reproduction with the gate forced open returns the SAME 12, so the gate
is confirmed to act on exactly what production serves.

## Status: BLOCKED ON THE WEB CLAIM

Held by `nfl-odds-allowlist-deploy`, 16.7 min into a 45-min TTL — an ACTIVE
claim, not an expired one. Not forced. Watcher armed for it to free.

## verify: — by the SERVED payload, not by deploy status

```bash
curl -s "https://syndicate-an21.onrender.com/ncaaf/api/picks?week=1" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('rank_cards') or []), 'cards'); print((d.get('empty_state') or {}).get('title'))"
```

**PASS = 0 cards AND an empty_state titled "NCAAF picks are suppressed: the
model does not beat the closing line in any market this board serves."**

Both halves are required. 0 cards alone is NOT a pass — an offseason-empty
board also serves 0, and reading that as success is the exact
gate-open/gate-closed confusion the unit test `test_off_is_not_on` exists to
prevent. The empty_state title is what proves the GATE produced the zero.

## Blast radius

- Wired ONLY into NCAAF's picks surface. NFL is untouched (it defaults to deny
  in the registry, but nothing calls the gate for NFL).
- Projections/cards/board are NOT suppressed — `/ncaaf/cards` still serves the
  model's opinion. Only the BET recommendation is withheld.
- Archive and evaluation paths untouched: they are records, and suppressing
  there would destroy the evidence the gate is waiting on.

## Rollback

Deploy `b775255a` (the SHA live before this). Picks return immediately.
