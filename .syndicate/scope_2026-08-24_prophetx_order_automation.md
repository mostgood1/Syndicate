# SCOPE — ProphetX order automation (Stage D, this lane's third venue)

Drafted 2026-08-24, lane `exchange-markets-api-integration`, following the
same pass as `.syndicate/scope_2026-08-24_novig_order_automation.md`. Third
of the three real-API venues from this lane (polymarket / novig / prophetx)
to get an order-automation design, per `todo.md #544`'s NEXT section.
**Not started. No lane extension claimed, no code written.**

Read against the same reference this lane has used throughout: the other
session's live Kalshi automation build (`kalshi_orders.py`,
`execution_guard.py`, `execution_ledger.py`, `execute_portfolio.py`). §1 of
the Novig scope doc already established that reference is fully
venue-agnostic — nothing here repeats that finding, it applies unchanged.

---

## 1. What's different from Novig: a real order-write endpoint was found

Novig's scope hit a wall — no order-placement endpoint was found anywhere.
ProphetX's is genuinely better documented, corroborated across ProphetX's own
Medium engineering posts (`@ProphetXServiceAPI`) and `docs.prophetx.co`
search-indexed pages (the site itself is proxy-blocked from this session,
same denial every venue host in this lane gets — this is WebSearch snippets
of it, not a direct read):

| Question | Status | Detail |
|---|---|---|
| Order-write endpoint | **CONFIRMED (name + payload shape)** | `POST https://cash.api.prophetx.co/trade/private/api/v2/wagers`, payload `{lineID, odds, stake}`. Multiple independent mentions agree on the exact path and field names. |
| Auth for the write path | **CONFIRMED, and it's ONE credential, not two** | "the same API token/secret is used across different endpoint types" — the production affiliate token `prophetx_client.py`'s `api_token()` already gates reads with is very likely also what authorizes `wagers`. Not yet proven by a live call, but this removes a question the Novig scope had to leave fully open. |
| Order status vocabulary | **CONFIRMED (names), semantics documented** | Four enum fields on a wager object: `status` (`inactive`→`open`→ terminal, or `invalid` if it fails validation), `matching_status`, `winning_status`, `update_status`. Named terminal/non-terminal states: `open` (live, matchable), `canceled` (client-cancelled, full or partial), `wiped` (auto-cancelled on a state transition — e.g. every pre-match play wipes when a game goes live), `settled`/`closed` (graded). This is a RICHER status model than Kalshi's, which collapses to filled/resting/dead/unknown — `wiped` in particular has no Kalshi analogue and needs its own handling, not a fold into `dead`. |
| Related endpoints named (not fully specified) | **PARTIAL** | `place_wager`, `place_multiple_wagers` (parlay), `get_wager_histories` — read as method/endpoint NAMES from ProphetX's own integration writing, not confirmed HTTP paths. A `/me` endpoint returns `user_id`, needed to construct wager requests. |
| Odds unit on the write side | **CONSISTENT with the read side, not contradicted** | The write payload's `odds` field, in every example found, is a plain American-odds integer (e.g. matched examples in the 100–200 range) — same convention `prophetx_client.py`'s read-side research already established (`"odds": 119`). Unlike Kalshi, where the read and write sides disagreed on price UNIT entirely, nothing found here suggests a mismatch. Still unverified by a live call, so `prophetx_orders.py`'s `order_body` would keep this pure and tested rather than assumed silently. |
| **Whether "cash.api.prophetx.co" and the Affiliate API's sandbox host are the SAME product** | **UNRESOLVED — the one open question that matters most** | `prophetx_client.py`'s own header already flags `cash.api.prophetx.co` as coming from an "older article (pre-rebrand, 'Prophet Exchange')" for a TRADING endpoint, separate from the Affiliate API's `api.sandbox.prophetx.dev/partner` host. This research pass ALSO surfaced "ProphetX Play" — described as something partners embed "into your existing odds screen platform," which reads like a white-label betting WIDGET product, not necessarily the same integration surface as an algorithmic Affiliate/Trading API. Three real possibilities, not distinguished by anything found: (a) one system, `cash.api.prophetx.co` is simply the trading host and `docs.prophetx.co` is common documentation for all of it; (b) `cash.api.prophetx.co` is legacy/deprecated, superseded by a newer host under the current `docs.prophetx.co` structure; (c) "ProphetX Play" is a genuinely separate consumer-widget product whose wager endpoint is not the one an algo trader should be calling at all. **This has to be resolved by whoever gets the partner conversation with ProphetX, not guessed here** — building `prophetx_orders.py` against the wrong one of these would be worse than Kalshi's 410 on a deprecated route, because it might work well enough in testing to ship. |

## 2. The precondition, same shape as Novig's

`prophetx_client.py`'s `api_token()` already refuses by name (`no_api_token`)
with nothing configured — per the module's own header, ProphetX's Affiliate
API is partner-gated, no self-serve signup. **Requesting ProphetX partner
access — and asking directly which host and endpoint serve programmatic order
placement, given §1's unresolved question — is the actual next action**,
ahead of any order-body code. The production base URL is ALSO still
unconfirmed for the read side (`prophetx_client.py`'s `_base_url()` defaults
to the sandbox only, deliberately, for exactly this reason) — a partner
conversation should settle both at once.

## 3. Proposed build, once a credential and a confirmed host/endpoint exist

Same five-step shape as the Novig scope's §4, adapted to what's actually
different here:

1. **`prophetx_auth.py`** — thinner than Kalshi's or Novig's: the existing
   bearer-token header (`api_token()`) already IS the auth mechanism per
   research (no separate signing step found, unlike Kalshi's RSA-PSS). A
   `probe_auth()` hitting `/me` (read-only, returns `user_id`) is the cheapest
   possible live check — confirms the token authorizes calls before anything
   with a `stake` field is attempted.
2. **Read verification first**, exactly as the Novig scope insists on — run
   `prophetx_client.fetch_markets()` for real once a token exists, diff
   against `_SELECTION_FIELDS`, before touching order placement.
3. **RESOLVE §1's open question BEFORE writing `prophetx_orders.py`.** Ask
   ProphetX directly, in the same partner conversation that yields a
   credential, which host and path serve programmatic wager placement for an
   Affiliate/Trading API integration — not "ProphetX Play." Do not build
   against `cash.api.prophetx.co/trade/private/api/v2/wagers` on the strength
   of third-party corroboration alone; the payload shape (`lineID`, `odds`,
   `stake`) is a good STARTING pure-function draft for `order_body`, unit-
   tested as a dict per `kalshi_orders.order_body_v2`'s own pattern, but the
   host itself needs the partner conversation's confirmation, not a guess.
4. **`prophetx_orders.py`** — `order_body` (pure, from the `{lineID, odds,
   stake}` shape above), `submit_order`, `fetch_order`/`fetch_orders` (the
   named `get_wager_histories`), and a `venue_order_view` that maps
   ProphetX's four-field status model onto this repo's `filled`/`resting`/
   `dead`/`unknown` vocabulary — with `wiped` mapped to `dead` ONLY after
   confirming a wiped play never later contributes a fill (Kalshi's own
   `venue_order_view` docstring already warns that a partial fill followed by
   a cancellation is still a fill; the same care applies to `wiped`, which
   this repo has no precedent for at all).
5. **One `elif` in `_venue_submitter`**, same narrow-claim precedent as
   Novig's step 5.
6. **Paper mode first**, same structural guarantee `place_order` already
   provides regardless of venue.

## 4. Non-goals of this scope

- No code written yet. No credential requested yet.
- No claim taken on `pipeline/execute_portfolio.py` yet.
- §1's host/product ambiguity is NOT resolved here — it is the literal
  precondition for step 3 above, not a detail to guess past.
- Legal/ToS review is **explicitly still open**, same as Novig's — `todo.md
  #544`'s NEXT section names both venues under the same unanswered question.
