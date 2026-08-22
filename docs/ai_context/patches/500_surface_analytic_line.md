# `#500` — surface `analytic_line` on a line-mismatch refusal

**PREPARED, NOT APPLIED. Blocked cross-lane.** `live_gameline_join.py` is claimed
by lane `live-edge-basis` (`lanes.md`: *"left guarded because it now SOLELY owns
`live_gameline_join.py`"*). Per the session protocol this lane does not edit
across lanes. This file is the whole change, ready to apply once that lane
releases the file or a user override is logged.

Prepared by lane `wnba-live-props-data`, 2026-08-21.

## Why

`#499` is REACHED but its interval has never been APPLIED: on 2026-08-21, 0 of 65
totals rows matched their lens line, so none entered `price_moneyline`. Two
explanations are indistinguishable from the served board and have opposite
consequences:

- the lens line simply sat off-ladder for those two games (benign — wait for
  another slate), or
- the lens line is stale, or not on the half-point grid the board quotes at, in
  which case `abs(analytic_line - row_line) > 1e-6` can **never** be false and
  totals are reached-but-permanently-inert.

The refusal names the rule it applied but not the number it applied it to, so
nothing on the row distinguishes these. One live reading settles it if the row
carries `analytic_line`.

## Reachability — checked BEFORE writing the patch

`_apply_verdict()` does `block = dict(verdict)` (`live_gameline_join.py:918`) and
then sets six extra keys. **There is no key whitelist**, so any key added to the
returned verdict dict reaches `row["live_gameline"]` and is serialised onto the
board. Confirmed against the live payload: `sigma`, `std_err_basis` and
`prob_std_err` all originate in these same dicts and are all visible on served
rows.

This check exists because `#499` itself shipped INERT — `d06a70d4` was correct
code that never ran, with 128 tests passing. A field that is added but dropped
downstream is the same failure wearing a different hat.

## The change

Two call sites, both inside `price_analytic_line_market()`. They are separate
returns on purpose (totals vs. spreads) and both must carry the fields, or the
diagnosis works for one market and silently not the other.

**Totals branch — `live_gameline_join.py:620-625`:**

```diff
         if abs(analytic_line - row_line) > 1e-6:
             return {
                 "model_prob": None, "market_prob": None, "edge_pp": None,
                 "std_err_basis": None, "prob_std_err": None, "priceable": False,
                 "withheld_reason": REASON_ANALYTIC_LINE_MISMATCH, "sigma": float(sigma),
+                # `#500`: name the NUMBER the rule was applied to, not just the
+                # rule. Without these two fields a permanent mismatch (stale or
+                # off-grid lens line) is indistinguishable from an ordinary
+                # off-ladder miss, and `#499` cannot be closed either way.
+                "analytic_line": float(analytic_line),
+                "line_delta": round(row_line - analytic_line, 4),
             }
```

**Spreads branch — `live_gameline_join.py:650-656`:**

```diff
     if abs(analytic_line - row_line) > 1e-6:
         out: dict[str, Any] = {
             "model_prob": None, "market_prob": None, "edge_pp": None,
             "std_err_basis": None, "prob_std_err": None, "priceable": False,
             "withheld_reason": REASON_ANALYTIC_LINE_MISMATCH, "sigma": float(sigma),
+            "analytic_line": float(analytic_line),
+            "line_delta": round(row_line - analytic_line, 4),
         }
         return out
```

Both `analytic_line` and `row_line` are already local floats at each site (they
are what the `abs(...)` test compares), so nothing new is computed or fetched.

## The reading that settles `#499`

With a live slate, group totals rows by `analytic_line`:

```bash
py -3 -c "import json,urllib.request,collections; d=json.load(urllib.request.urlopen('https://syndicate-an21.onrender.com/api/board/book-grid?sport=wnba',timeout=120)); c=collections.Counter((r.get('market'),(r.get('live_gameline') or {}).get('analytic_line')) for r in d.get('rows') or [] if r.get('market') in ('totals','totals_alt')); print(c)"
```

- `analytic_line` on the half-point grid **and** inside the board's ladder →
  the mismatch is an ordinary off-ladder miss; `#499` is fine, keep waiting.
- `analytic_line` off-grid (e.g. `146.4413908854167`, i.e. the model MEAN rather
  than a quoted line) or far outside the ladder → **totals can never clear this
  gate**; `#499` is inert in outcome and the gate itself needs rethinking
  (round to the quoted grid, or price the totals distribution at the row's line
  rather than refusing).

The second outcome is the one worth having the instrument for; it is currently
unfalsifiable, and `#499` reads as a success while possibly delivering nothing.

## Not in scope

Do **not** relax the `1e-6` tolerance as part of this. The exact-match rule is
deliberate and documented at the spreads site — one probability describes one
number, and answering other numbers from it invents a distribution. This patch
only makes the refusal legible; whether the rule is right is the question the
reading above is meant to inform.
