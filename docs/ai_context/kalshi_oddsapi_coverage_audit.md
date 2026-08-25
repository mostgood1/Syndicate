# Kalshi vs. OddsAPI — coverage audit

> **Lane:** `kalshi-oddsapi-coverage-audit` · **Branch:** `claude/kalshi-oddsapi-coverage-audit`
> **Read-only audit.** Nothing was deployed, no `render.yaml` was touched, no
> execution or pricing code was changed.
>
> **Every FACT row below was OBSERVED in a production log line, and the line's
> timestamp is beside it.** Anything not observed is in
> [SUSPECTED, UNCONFIRMED](#suspected-unconfirmed) instead, with what would
> confirm it. `kalshi_catalogue.py`'s own header says why this rule exists: a
> series that does not exist returns an empty page indistinguishable from a
> venue listing nothing, so an invented plausible ticker manufactures a false
> negative — the exact failure this integration was built to avoid.
>
> **"Kalshi does not list this" and "we cannot see that Kalshi lists this" are
> different findings and only the first is a gap in Kalshi's coverage.** They
> are marked differently throughout.

**Three tiers of evidence, and they are not equal.** Marked throughout:
**(A)** a production log line inside this audit's own window — the strongest,
and the basis of every count; **(B)** a live market page the user sent, which
is what confirmed `KXMLBTOTAL` and six MLB prop series on 2026-08-25; **(C)** a
prior observation recorded in a repo comment — `SERIES_SPORT`'s stated
invariant is that every entry was seen in a live listing with the date beside
it, so a hand-registered ticker carries tier-C provenance even where this
audit did not re-observe it. **Tier C is the weakest and is called out by name
wherever it is load-bearing** — `KXNFLTOTAL`, `KXNBATOTAL`, `KXNCAABTOTAL` and
`KXNHLTOTAL` rest on it alone here, because all four sports were out of season
or between slates on the observation date.

**Evidence base:** `mcp__Render__list_logs`, workspace `tea-d2bb5n95pdvs73cje4fg`,
services `srv-d91dpertqb8s73co8ls0` (refresh-worker) and `srv-d91dpertqb8s73co8lt0`
(live-odds-worker), window **2026-08-25 T14:02Z–20:33Z**. Direct HTTP to Kalshi
and to the live service is blocked from this sandbox; production logs and
user-confirmed market pages are the only admissible evidence, and the local
`data/` tree was not used for anything (per `CLAUDE.md` — it is a lossy mirror).

---

## 0. The one thing to read first: which SHA these readings are of

The refresh-worker deploy **`dep-da6vg28u01pc73ddmmd0` (commit `461ee74be`)
went live at 2026-08-25T20:20:57Z** — during this audit. It is the commit that
registered the six MLB props, `KXMLBTOTAL`, and soccer-by-title-prefix.

So this document contains **two generations of readings** and they must not be
mixed:

| | window | what it describes |
|---|---|---|
| **PRE** | 14:02Z – 20:19Z | the state the user has been fighting all week |
| **POST** | 20:21Z – 20:33Z | the first three log lines emitted by the fix |

Where a PRE finding is superseded by a POST one, both are shown. **A PRE
`unmapped_series` on a series the fix registers is not a live gap** — and
saying so is half the value of having read both.

---

## 1. The five gates, in the order a market meets them

This ordering is the reason the same symptom ("Kalshi has no market") has had
five different causes this week. Each gate is a **different job with a
different fix**, and only the last two are visible to the board at all.

| # | gate | refused by | reported in | the fix |
|---|---|---|---|---|
| 1 | **series registration** | `sport_for_series()` returns `None` → `unmapped_series` | `[kalshi_discovery] GAP`, `[kalshi_odds] SERIES_UNREGISTERED` | a `SERIES_SPORT` line, or make `auto_*_from_catalogue` see it |
| 2 | **series is in the fetch list** | never added to `sports_series()` | absence from `[kalshi_odds] TICK this_tick` | same as 1 — this is 1's consequence |
| 3 | **title grammar** | `_parse_title()` returns `None` → `unreadable_title` | `[kalshi_odds] BOARD_JOIN reasons`, `DAILY_BOOK unparsed` | a regex in `kalshi_catalogue` |
| 4 | **stat vocabulary** | `canonical_market_key` / `total_market_from_stat` → `None` → `stat_not_in_market_vocabulary` | `[kalshi_discovery] GAP` with `detail=` | a `market_keys` entry |
| 5 | **the join** | `event_not_on_our_board`, `market_is_for_another_date`, `no_matching_board_row`, `team_side_unresolved` | `[kalshi_odds] BOARD_JOIN` | aliases / dates / board rows |

**Gate 1 is the one that hides.** A series that does not register is never
fetched, so it cannot appear in `unreadable_title`, in `BOARD_JOIN` reasons, or
in any counter downstream. The only symptom is a board row that never gets a
price — which reads as *"Kalshi does not offer this"*. That is how `KXMLBGAME`
(the single most valuable market type, on every sport) hid for weeks, and how
`KXMLBTOTAL` hid until the user sent a live link.

Two further gates are **not refusals** and are easy to miss:

| # | gate | what it does | reported in |
|---|---|---|---|
| 2b | **per-tick fetch cap** | `SYNDICATE_KALSHI_SERIES_PER_TICK` = 60 of 193 wanted → a full rotation takes ~4 ticks / ~8 min | `TICK fetched=60 cap=60 due=89` |
| 2c | **working-set bound** | `MAX_MARKETS_PER_SERIES=400`, `MAX_STORED_MARKETS=6000` → ladders truncated *in the join's input* | `TICK trimmed=2530…2983` |

---

## 2. What Kalshi actually lists — the catalogue census

**OBSERVED 2026-08-25T20:21:24.977Z**, `[refresh_worker] KALSHI_SERIES_CATALOGUE
status=ok count=13472`, on the current live SHA. This is the signed
`/series` catalogue and it is the **only** admissible answer to "what does
Kalshi list" — see the caveat below.

| sport token | series `n` | sample tickers observed on the same line |
|---|---|---|
| MLB | **174** | `KXMLBNLCENT` `KXMLBCBA` `KXMLBHRDERBYOU` `KXMLBWINS-BAL` `KXMLBALCY` `KXMLB` `KXMLBWINS-LAA` `KXMLBHRDERBYDISTANCE` `KXMLBNL` `KXCOACHOUTMLBDATE` `KXMLBALROTY` `KXMLBWINS-CHC` |
| NBA | **351** ⚠️ | `KXGRAMBRNBA` `KXNBASHOOTINGSTARS` `KXNBAECFQUAL` `KXNBATOP3` `KXNBAPLAYOFFWINS` `KXNBA2QWINNER` |
| WNBA | **91** | `KXWNBA1QWINNER` `KXLEADERWNBA3PT` `KXWNBAPTSRECORD` `KXWNBA4QTOTAL` `KXWNBA1QSPREAD` `KXWNBA2HSPREAD` `KXWNBACOMPETE` `KXWNBA1HWINNER` `KXWNBA2HWINNER` `KXLEADERWNBAREB` `KXWNBA2H` `KXWNBAH2HPRA` |
| NHL | **52** | `KXNHLEAST` `KXNHLHART` `KXNHLPLAYOFFGOALS` `KXNHLVEZINA` `KXNHLSEASONPTS` `KXNHLWINS` `KXNHLPRICE` `KXNHLSAVES` `KXNHL2OT` `KXNHLANYGOAL` `KXESPYNHL` `KXNHLPTS` |
| NFL | **323** | `KXNFLNFCWEST` `KXNFLEXECOTY` `KXNFLWINS-SF` `KXNFL2H` `KXNFL1H` `KXLEADERNFLPTDS` `KXNFLSBMVPDEF` `KXNFLOROY` `KXNFL2Q` `KXNFLSEASONPASSYDS` `KXNFLDRAFTQB` `KXNFLMVP` |
| NCAAF | **126** | `KXNCAAFSF` `KXNCAAFB12QUAL` `KXNCAAFPLAYOFF` `KXNCAAFD3` `KXNCAAFACCREGTOP` `KXNCAAFSPREAD` `KXNCAAFQHIGHSCORE` `KXNCAAF4QBTTS` `KXNCAAFTEAMTOTAL` `KXNCAAFGAME` `KXNCAAFQF` `KXNCAAFCUSA` |
| NCAAB | **20** | `KXNCAABMENTION` `KXNCAABBIGTEN` `KXNCAABBCONF` `KXNCAABASEBALL` `KXNCAABBIG10` `KXTEAMSINNCAABBWS` `KXNCAABGAME` `KXNCAABBREG` `KXNCAABACC` `KXNCAABBFINAL` `KXNCAABBPLAYOFFS` `KXNCAABBGAME` |
| **soccer** | **not measurable by this probe** | — see below |

⚠️ **NBA's 351 INCLUDES WNBA's 91.** `series_matching` is a substring match and
`"NBA"` sits inside `"WNBA"`. Do not subtract without checking; report it as
"≤351 NBA-only".

🚫 **Soccer has no line at all, and that is a property of the probe, not of
Kalshi.** `_KALSHI_SPORT_TOKENS` is `("WNBA","NBA","NFL","NHL","NCAAF","NCAAB","MLB")`
— soccer is named by COMPETITION (`KXLALIGA…`, `KXUCL…`, `KXMLS…`), never by
the word soccer, so it cannot match a token. **We know Kalshi lists soccer
richly** (§3.8). This is "we cannot see it", not "it is absent".

### The `LISTED` line is NOT the catalogue — do not read it as one

`[kalshi_discovery] LISTED` paginates the open-**markets** endpoint and it is
**truncated on every single run observed**:

| time | markets | singles | combinatorial | series | truncated |
|---|---|---|---|---|---|
| 16:40:58Z | 40000 | 46 | 39954 | 8 | `True` |
| 16:56:30Z | 40000 | 78 | 39922 | 15 | `True` |
| 17:42:28Z | 40000 | 90 | 39910 | 9 | `True` |
| 18:33:16Z | 40000 | 40 | 39960 | 7 | `True` |
| 19:12:01Z | 40000 | 650 | 39350 | 68 | `True` |
| 19:35:45Z | 40000 | 24 | 39976 | 8 | `True` |
| 20:33:06Z | 40000 | 298 | 39702 | 12 | `True` |

**99.3–99.9% of the first 40,000 open markets are parlay combinations**
(`KXMVECROSSCATEGORY`, `KXMVECROSSCATEGORY0`, `KXMVENBASINGLEGAME`,
`KXMVENBAMULTIGAMEEXTENDED` — all observed). A whole sport can be invisible in
this line and be fully listed by Kalshi. `singles` swings 24→650 between
consecutive runs purely on pagination luck. **The `SERIES`, `GAP` and
`top_series` samples derived from it are a random 12–15-row sample of a
truncated 0.7% slice**, and every count in them is a floor.

---

## 3. Per-sport coverage

Column key — **① Kalshi lists it** (ticker + a verbatim title we observed) ·
**② we register it** (and if not, WHICH gate) · **③ board market key** (what
`market_keys` produces, and whether a board row uses it) · **④ OddsAPI**.

### 3.1 MLB

Fetched-list evidence: `[kalshi_odds] TICK` 19:52:44Z / 19:55:54Z / 20:19:36Z.
Counts in ① are Kalshi's **true per-series market count**, read off `this_tick`.

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXMLBGAME` 76 · *"New York M wins"* | ✅ hand `SERIES_SPORT` | `h2h` ✅ carried | ✅ `h2h` |
| spread / run line | `KXMLBSPREAD` 150 · *"Texas wins by over 3.5 runs?"* | ✅ hand | `spreads` ✅ | ✅ `spreads` |
| **full-game total** | `KXMLBTOTAL` · user-confirmed page `KXMLBTOTAL-26AUG251840BOSMIA-7` | ✅ hand, **since `d6cff4557` 19:51Z today** | `totals` ✅ | ✅ `totals` |
| team total | `KXMLBTEAMTOTAL` 350 · *"Will Texas score over 7.5 runs?"* | ✅ discovered | `team_totals` ⚠️ **no board row uses it** | ❌ |
| F5 total | `KXMLBF5TOTAL` 175 · *"First 5 innings: Over 6.5 runs"* | ✅ discovered | `totals_1st_5_innings` | ✅ same key |
| F5 spread | `KXMLBF5SPREAD` 100 | ✅ discovered | `spreads_1st_5_innings` | ✅ |
| F3 / F5 / F7 winner | `KXMLBF3` 75 · `KXMLBF5` 75 · `KXMLBF7` 75 | ✅ discovered | `h2h_*` | ❌ (F5 only, partially) |
| **inning total** | `KXMLBINNINGTOTAL` **306** · *"9th inning: Over 1.5 runs"* | ✅ registered — **but gate 3: `unreadable_title`, 17 markets, 17:42:28Z** | none | ❌ |
| **inning winner** | `KXMLBINNINGWIN` 27 · *"Teams tie scoring in the 9th inning?"* | ❌ **gate 1 `unmapped_series`** 17:42:28Z | none | ❌ |
| strikeouts | `KXMLBKS` 197–205 · *"Andrew Abbott: 7+ strikeouts?"* | ✅ hand | `strikeouts` ✅ | ✅ `pitcher_strikeouts` |
| outs | `KXMLBOUTS` 27 | ✅ hand | `outs` ✅ | ✅ `pitcher_outs` |
| home runs | `KXMLBHR` 133 · *"Pete Crow-Armstrong: 2+ home runs?"* | ✅ hand | `batter_home_runs` ✅ **board asked for it 8× at 19:35–20:15Z** | ✅ `batter_home_runs` |
| hits | `KXMLBHIT` | ✅ hand (today) — **tier B**, user market page | `batter_hits` | ✅ |
| total bases | `KXMLBTB` | ✅ hand (today) — **tier B** | `batter_total_bases` | ✅ |
| RBIs | `KXMLBRBI` **98** (20:33:06Z) | ✅ hand (today) | `batter_rbis` | ✅ |
| earned runs | `KXMLBERA` | ✅ hand (today) — **tier B** | `earned_runs` | ✅ `pitcher_earned_runs` |
| walks allowed | `KXMLBWA` 6–8 · *"Max Scherzer: 2+ walks allowed?"* | ✅ hand (today) — was gate 1 at 14:47Z | `walks_allowed` | ✅ `pitcher_walks` |
| hits allowed | `KXMLBHA` | ✅ hand (today) — **tier C**, production catalogue read | `hits_allowed` | ✅ `pitcher_hits_allowed` |
| **H+R+RBI** | `KXMLBHRR` **136** · *"William Contreras: 5+ hits + runs + RBIs?"* | ✅ registered — **but gate 4: `stat_not_in_market_vocabulary`, `detail="hits + runs + RBIs"`, 20:33:06Z** | `batter_hits_runs_rbis` exists | ✅ `batter_hits_runs_rbis` |
| **stolen bases** | `KXMLBSB` **44** · *"William Contreras: 1+ stolen bases?"* | ❌ **gate 1 `unmapped_series`** 20:33:06Z | none | ⚠️ `batter_stolen_bases` is a real OddsAPI key we do not request |
| division futures | `KXMLBALEAST/ALCENT/ALWEST/NLEAST/NLCENT/NLWEST` 5 each | ⚠️ **over-registered as game series** — see §6 | `h2h` (wrong) | n/a |

**`KXMLBHRR` is the highest-value single line in this whole document.** It was
registered by `461ee74be`, live at 20:20:57Z — **12 minutes before the
reading** — is the **largest single MLB prop family on the venue at 136
markets**, and every one of them refuses at gate 4
because `market_keys._MLB` holds `hits_runs_rbis` / `batter_hits_runs_rbis` but
not Kalshi's own wording `hits + runs + RBIs`. This is *precisely* the failure
the `KXWNBA3PT` comment in `market_keys.py` documents — a registered series
whose markets all refuse is indistinguishable from a series Kalshi does not
list — recurring on the same day, on a series registered 12 minutes earlier.

### 3.2 NBA

Season had not started on the observation date; treat market counts as
off-season floors, **not** as evidence about NBA coverage in season.

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXNBAGAME` 6 | ✅ discovered | `h2h` | ✅ |
| spread | `KXNBASPREAD` | ✅ discovered — `AUTO_SERIES game_sample` 19:35:08Z | `spreads` | ✅ |
| total | `KXNBATOTAL` | ✅ hand — **tier C**, not re-observed here | `totals` | ✅ |
| quarter/half ladder | `KXNBA1QWINNER` `KXNBA1QSPREAD` `KXNBA2HSPREAD` `KXNBA3QSPREAD` `KXNBA3QTOTAL` `KXNBA4QSPREAD` | ✅ discovered | `h2h_q1` `spreads_q1` `spreads_h2` `spreads_q3` `totals_q3` `spreads_q4` | ⚠️ **h1/h2 only** — this repo's bulk refresh never requests quarter markets for any basketball sport (`refresh_odds_sources.py:74`) |
| points | `KXNBAPTS` | ✅ **discovered** | `player_points` | ✅ |
| rebounds | `KXNBAREB` | ✅ discovered | `player_rebounds` | ✅ |
| assists | `KXNBAAST` | ✅ discovered | `player_assists` | ✅ |
| threes | `KXNBA3PT` | ✅ discovered | `player_threes` | ✅ |
| steals | `KXNBASTL` | ✅ discovered | `player_steals` | ✅ |
| blocks | `KXNBABLK` | ✅ discovered | `player_blocks` | ✅ |
| double-double | `KXNBA2D` | ✅ discovered | `player_double_double` | ✅ |
| triple-double | `KXNBA3D` | ✅ discovered | `player_triple_double` | ✅ |
| playoff / summer / series props | `KXNBAPLAYOFFPTS` `KXNBASUMMERPTS` `KXNBASERIESPTS` | ✅ discovered | `player_points` | ❌ |
| division futures | `KXNBACENTRAL/ATLANTIC/PACIFIC/NORTHWEST/SOUTHWEST/SOUTHEAST` 5 each, `KXNBAWINS` 312, `KXNBAMOSTWINS` 4 | ⚠️ over-registered §6 | `h2h` (wrong) | n/a |

> **Correction to a note in `kalshi_catalogue.py`'s own header.** That header
> uses `KXNBAPTS` as its example of an *invented plausible ticker*. It is a
> **real, listed, auto-discovered series** — observed in `AUTO_SERIES sample`
> at 16:55:55Z, 17:41:52Z, 18:32:38Z, 19:11:24Z, 19:35:08Z and 20:32:19Z. The
> *principle* is right and should stand; the example has since been falsified
> by production and is now misleading to a reader who checks it.

### 3.3 WNBA — the best-covered sport on the venue

Every row below observed in `TICK this_tick` at 19:52:44Z / 19:59:55Z.

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXWNBAGAME` 14 | ✅ hand | `h2h` | ✅ |
| spread | `KXWNBASPREAD` 52 | ✅ hand | `spreads` | ✅ |
| total | `KXWNBATOTAL` 45 | ✅ hand | `totals` | ✅ |
| team total | `KXWNBATEAMTOTAL` 54 | ✅ discovered | `team_totals` ⚠️ no board row | ❌ |
| quarter winners | `KXWNBA1QWINNER` `2QWINNER` `3QWINNER` `4QWINNER` 9 each | ✅ discovered | `h2h_q1…q4` | ❌ |
| quarter spreads | `KXWNBA1QSPREAD` `2Q` `3Q` `4Q` 21 each | ✅ discovered | `spreads_q1…q4` | ❌ |
| quarter totals | `KXWNBA1QTOTAL` `2Q` `3Q` `4Q` 21 each | ✅ discovered | `totals_q1…q4` | ❌ |
| half winners | `KXWNBA1HWINNER` `2HWINNER` 21 each | ✅ discovered | `h2h_h1` `h2h_h2` | ✅ |
| half spreads | `KXWNBA1HSPREAD` `2HSPREAD` 22 each | ✅ discovered | `spreads_h1` `spreads_h2` | ✅ |
| half totals | `KXWNBA1HTOTAL` `2HTOTAL` 21 each | ✅ discovered | `totals_h1` `totals_h2` | ✅ |
| points | `KXWNBAPTS` 51 | ✅ hand | `player_points` | ✅ |
| rebounds | `KXWNBAREB` 30 | ✅ hand | `player_rebounds` | ✅ |
| assists | `KXWNBAAST` 8 | ✅ hand | `player_assists` | ✅ |
| threes | `KXWNBA3PT` 22 | ✅ hand + **vocabulary widened today** (14 spellings) | `player_threes` | ✅ |
| **head-to-head PRA** | `KXWNBAH2HPRA` (catalogue 20:21:24Z) | ❓ **not in the fetch list** — gate 1 | none | ❌ |
| season leader futures | `KXLEADERWNBA3PT` `KXLEADERWNBAREB` `KXWNBAPTSRECORD` `KXWNBACOMPETE` | ❌ gate 1 | none | ❌ |

**WNBA's quarter ladder is the clearest "stop paying OddsAPI" case on the
board** — see §5.

### 3.4 NHL — the one sport with a *named, code-level* prop gap

`KALSHI_SPORT NHL n=52`, 20:21:24Z. **No NHL game-line series appears anywhere
in the 193-series fetch list**; the only NHL entries in `TICK` are
`KXNHLCENTRAL` / `KXNHLATLANTIC` / `KXNHLMETROPOLITAN` / `KXNHLPACIFIC` at 8
markets each — division futures, plus `KXNHLSEASONPTS`.

The NHL regular season had not begun on 2026-08-25, so **absence of
`KXNHLGAME`/`KXNHLTOTAL`/`KXNHLSPREAD` from today's readings is expected and is
NOT evidence Kalshi lacks them.** `market_keys._GAME_CORE`'s comment records
`KXNHLGAME` "NHL Game" as observed in a live catalogue read on 2026-08-24, and
`kalshi_catalogue`'s totals comment records `KXNHLTOTAL` registering — both
**tier C**. **`KXNHLSPREAD` is named nowhere — not in a log line, not in a
repo comment, not on a page the user sent.** It is written here only to say
that it is a guess, and it is carried in
[SUSPECTED](#suspected-unconfirmed) rather than in any table of facts.

**But there is a real, structural gap independent of the season:**

> `market_keys._BY_SPORT` has **no `nhl` entry.** It maps
> `mlb / nba / wnba / nfl / ncaaf / soccer` and nothing else. So
> `canonical_market_key("nhl", <any stat>)` can only ever return a `_GAME`
> word or a passthrough — and `auto_series_from_catalogue` **requires** that
> call to resolve before it will register a prop series.
>
> **Consequence: no NHL player-prop series can ever auto-register, in season or
> out.** Three are already visible in the catalogue at 20:21:24Z:
> **`KXNHLSAVES`**, **`KXNHLANYGOAL`**, **`KXNHLPTS`** — plus
> `KXNHLPLAYOFFGOALS`. This is exactly the failure `market_keys`'s own header
> documents for NFL: *"`KALSHI_SPORT NFL ticker_substring_n=317
> classified_n=0` — 317 NFL series listed and not one classified… The gap was
> in this file, not in the discovery."*

④ OddsAPI for NHL is **game lines only** — `refresh_nhl_oddsapi.py`'s
`--team-markets` defaults to `h2h,spreads,totals`.

### 3.5 NFL

`KALSHI_SPORT NFL n=323`, 20:21:24Z. Preseason on the observation date.

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXNFLGAME` **96** | ✅ discovered | `h2h` | ✅ |
| spread | `KXNFLSPREAD` **795** | ✅ discovered | `spreads` | ✅ |
| total | `KXNFLTOTAL` | ✅ hand — **tier C**, not re-observed here | `totals` | ✅ |
| quarter winners | `KXNFL1Q` `2Q` `3Q` `4Q` 48 each | ✅ discovered | `h2h_q1…q4` | ❌ |
| quarter spreads | `KXNFL1QSPREAD` `2Q` `3Q` `4Q` **160 each** | ✅ discovered | `spreads_q1…q4` | ❌ |
| quarter totals | `KXNFL1QTOTAL` `2Q` `3Q` `4Q` **160 each** | ✅ discovered | `totals_q1…q4` | ❌ |
| half | `KXNFL1H` 48; `KXNFL2H`, `KXNFL1HSPREAD`, `KXNFL2HTOTAL`, `KXNFL2HSPREAD`, `KXNFL*WINNER` at 0 (preseason) | ✅ discovered | `h2h_h1` `spreads_h1` `totals_h2` … | ✅ h1/h2 |
| passing TDs | `KXNFLPASSTDS` | ✅ discovered | `player_pass_tds` | ✅ |
| receptions | `KXNFLREC` | ✅ discovered | `player_receptions` | ✅ |
| season pass yds | `KXNFLSEASONPASSYDS` | ❌ gate 1 | none | ❌ |
| **fantasy H2H** | `KXNFLFFH2HSEASON` 2 · *"Jahmyr Gibbs scores more fantasy points than Bijan Robinson in the 2026-27 regul…"* | ❌ gate 1, 18:33:16Z | none | ❌ |
| division / award futures | `KXNFLAFCEAST/NORTH/SOUTH/WEST`, `KXNFLNFC*` 4 each, `KXNFLPLAYOFFHOST` 32, `KXNFLH2HWINS` 22, `KXNFLHIGHSCORE` 9, `KXNFLCOMPETE` 2, `KXNFLMVP`, `KXNFLOROY`, `KXNFLDRAFTQB`, `KXNFLEXECOTY`, `KXNFLSBMVPDEF`, `KXLEADERNFLPTDS`, `KXNFLWINS-SF` | mixed — the `*WEST`-style ones are over-registered §6 | `h2h` (wrong) | n/a |
| **celebrity game** | `KXNFLCELEBRITYGAME` 0 | ⚠️ **registered as an NFL game series** — over-registration §6 | `h2h` | n/a |

OddsAPI NFL props actually requested (`fetch_nfl_oddsapi_props_local.py`):
`player_reception_yds`, `player_receptions`, `player_rush_yds`,
`player_rush_attempts`, `player_pass_yds`, `player_pass_tds`,
`player_pass_attempts`, `player_pass_interceptions`, `player_anytime_td`.

### 3.6 NCAAF — the biggest ladders on the venue

`KALSHI_SPORT NCAAF n=126`, 20:21:24Z. In season; these are live counts.

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXNCAAFGAME` **600** · *"New Mexico St. wins"* | ✅ discovered | `h2h` | ✅ |
| **spread** | `KXNCAAFSPREAD` **1994** · *"Oklahoma wins by over 7.5 points"* | ✅ discovered | `spreads` | ✅ |
| **total** | `KXNCAAFTOTAL` · *"Over 67.5 points scored"* · 57 markets | ✅ hand — **was gate 1 `unmapped_series` at 14:47:04Z**, fixed by `d6cff4557` | `totals` | ✅ |
| team total | `KXNCAAFTEAMTOTAL` (catalogue 20:21:24Z) | ❓ not seen in the fetch list | `team_totals` | ❌ |
| quarter/half ladder | `KXNCAAF1Q` `1QTOTAL` `1QSPREAD` `1H` `1HTOTAL` `1HSPREAD` `1HWINNER` `2Q` `2QTOTAL` `2QSPREAD` `2H` `2HTOTAL` `2HSPREAD` `3Q` `3QTOTAL` `3QSPREAD` `4Q` `4QTOTAL` `4QSPREAD` — **all 0 markets on the observation date** | ✅ discovered | full period key set | ⚠️ h1/h2 only |
| **4Q both-teams-score** | `KXNCAAF4QBTTS` (catalogue 20:21:24Z) | ❓ not in fetch list | none | ❌ |
| division/sub-division games | `KXNCAAFD3GAME` 0, `KXNCAAFCSGAME` 0 | ✅ discovered | `h2h` | ❌ |
| awards / playoff futures | `KXNCAAFAWARD` **509**, `KXNCAAFWINS` **618**, `KXNCAAFPLAYOFF`, `KXNCAAFSF`, `KXNCAAFQF`, `KXNCAAFB12QUAL`, `KXNCAAFACCREGTOP`, `KXNCAAFCUSA`, `KXNCAAFHIGHSCORE`, `KXNCAAFQHIGHSCORE` | ⚠️ `KXNCAAFAWARD` is over-registered §6 | `h2h` (wrong) | n/a |

**NCAAF props:** OddsAPI supplies the full 9-market football set
(`fetch_ncaaf_oddsapi_props_local.py`, verified live 2026-08-20). **No NCAAF
player-prop series was observed on Kalshi.** *We cannot see one* — that is not
the same as Kalshi not listing one. See [SUSPECTED](#suspected-unconfirmed).

### 3.7 NCAAB

`KALSHI_SPORT NCAAB n=20`, 20:21:24Z — the smallest of the seven. Deep
off-season (season starts November).

| family | ① Kalshi | ② registered? | ③ board key | ④ OddsAPI |
|---|---|---|---|---|
| moneyline | `KXNCAABGAME` 0 · `KXNCAABBGAME` 0 | ✅ discovered | `h2h` | ✅ |
| spread | `KXNCAABBSPREAD` 0 | ✅ discovered | `spreads` | ✅ |
| total | `KXNCAABTOTAL` | ✅ hand — **tier C**, not re-observed here | `totals` | ✅ |
| regular season | `KXNCAABBREG` 0 | ✅ discovered | — | ❌ |
| conference / tourney futures | `KXNCAABBIGTEN` `KXNCAABBIG10` `KXNCAABACC` `KXNCAABBCONF` `KXNCAABBFINAL` `KXNCAABBPLAYOFFS` `KXTEAMSINNCAABBWS` `KXNCAABMENTION` `KXNCAABASEBALL` | mostly ❌ gate 1 | — | ❌ |

**Structural gap, same class as NHL:** `market_keys._BY_SPORT` has **no
`ncaab` entry** either. `_TOTAL_UNIT` *does* carry `ncaab` (so game totals
resolve), but `canonical_market_key("ncaab", "points")` returns `None`, so
**no NCAAB player-prop series can auto-register** when the season starts.
One line — `"ncaab": _BASKETBALL` — would close it, exactly as `ncaaf` already
reuses `_FOOTBALL`.

⚠️ **`KXNCAABASEBALL` is NCAA *baseball*, not basketball** — it matches the
`NCAAB` token by coincidence. Registering it under `ncaab` would price
baseball off a basketball model. It is currently refused, which is correct.

### 3.8 Soccer — an entire namespace, and it moved during this audit

**Soccer is where the largest absolute gap is**, and it is the sport this
audit's two generations differ most on.

**PRE (14:27Z – 19:12Z): every soccer competition observed was
`unmapped_series`, and ZERO soccer series were in the 193-series fetch list.**
All of the following were observed with `reason=unmapped_series`:

| series | count | verbatim sample title | observed |
|---|---|---|---|
| `KXUECLSCORE` | **120** | *"Reg Time: Final score FK Partizan Belgrade wins 5-2?"* | 19:12:01Z |
| `KXUELSCORE` | 60 | *"Reg Time: Final score FC Iberia 1999 wins 5-2?"* | 16:14:25Z |
| `KXUECLTEAMTOTAL` | 42 | *"Will Partizan Belgrade score over 2.5 goals?"* | 19:12:01Z |
| `KXEPLCORNERS` | 35 | *"9+ total corners"* | 16:14:25Z |
| `KXLALIGASCORE` | 31 | *"Final score FC Barcelona wins 7-1?"* | 19:12:01Z |
| `KXUECL1HTOTAL` | 21 | *"Over 2.5 1H goals scored"* | 19:12:01Z |
| `KXUECL1H` | 21 | *"Tie 1st Half"* | 19:12:01Z |
| `KXUECL1HSPREAD` | 14 | *"Partizan Belgrade wins by more than 1.5 goals in the 1st Half"* | 19:12:01Z |
| `KXEPLTCORNERS` | 14 | *"Aston Villa: 5+ corners"* | 16:14:25Z |
| `KXLALIGA1HSCORE` | 13 | *"Will the 1st half score be FC Barcelona wins 3-2?"* | 19:12:01Z |
| `KXUELTEAMTOTAL` | 12 | *"Will Anderlecht score over 2.5 goals?"* | 19:12:01Z |
| `KXUCL1HTOTAL` | 12 | *"Over 2.5 1H goals scored"* | 19:12:01Z |
| `KXLALIGATEAMTOTAL` | 12 | — (`top_series`) | 19:12:01Z |
| `KXEFLCUP1HTOTAL` | 12 | — (`top_series`) | 19:12:01Z |
| `KXUCL1H` | 12 | — (`top_series`) | 19:12:01Z |
| `KXCLUBFGAME` | 9 | *"Tie is the result"* | 16:40:58Z |
| `KXEGYPLTOTAL` | 6 | *"Will over 5.5 goals be scored?"* | 14:27:05Z |
| `KXEGYPLSPREAD` | 4 | *"Smouha wins by more than 2.5 goals?"* | 14:27:05Z |
| `KXARGNACBGAME` | 3 | *"Tie is the result"* | 16:40:58Z |
| `KXEFLCUPSPREAD` | 1–3 | *"Reg Time: Middlesbrough wins by more than 3.5 goals?"* | 18:33:16Z |
| `KXEFLCUPTOTAL` | 1–3 | *"Will over 6.5 goals be scored?"* | 18:33:16Z |
| `KXSVKCUPSPREAD` | 2 | *"Reg Time: Namestovo wins by more than 4.5 goals?"* | 14:47:04Z |
| `KXSVKCUPTOTAL` | 2 | *"Will over 7.5 goals be scored?"* | 14:47:04Z |
| `KXSAUDIPLTOTAL` | 1 | *"Will over 6.5 goals be scored?"* | 16:40:58Z |

Also observed in `[kalshi_discovery] SERIES` sample lines, same window:
`KXUCLTOTAL` `KXUCLSPREAD` `KXUCLWTOTAL` `KXUCLWBTTS` `KXUEL1HBTTS`
`KXUEL1HTOTAL` `KXUEL1HSPREAD` `KXUEL1H` `KXUECL1HBTTS`.

**POST (20:32:19Z) — the title-prefix fix works.** `[kalshi_discovery]
AUTO_SERIES` read `game_series=204` where every run before it read **173**, and
the `game_sample` carries **`('KXMLSTOTAL', 'soccer')`** — the first soccer
series ever to register. **+31 series in one deploy.**

**What is STILL a gap after the fix, and why — this is the actionable half:**

1. **Only the 10 competitions Syndicate models can ever register.**
   `soccer_league_from_title` matches a title PREFIX against
   `LEAGUE_DISPLAY_NAMES` = `EPL, La Liga, Bundesliga, Serie A, Ligue 1, MLS,
   Eredivisie, Primeira Liga, Championship, Belgian Pro League`. **UCL, UEL,
   UECL, EFL Cup, Saudi PL, Egyptian PL, Slovak Cup, Club Friendlies and the
   Argentine competition are none of them**, so they stay `unmapped_series` —
   *by design, not by defect*. Confirmed post-fix: `KXEFLCUPSPREAD count=3
   reason=unmapped_series` and `KXEFLCUPTOTAL count=1` at **20:33:06Z**, on the
   fixed SHA. **This is a decision for the user, not a bug:** UEFA club
   competition is the single largest untouched block on the venue
   (`KXUECLSCORE` alone is 120 markets), and covering it means adding the
   competition to the soccer module, not patching Kalshi code.
2. **Soccer PLAYER props still cannot register.**
   `KXLALIGAGOAL count=5 reason=unmapped_series sample='Francisco Garcia: 1+
   goals'` at **20:33:06Z** — La Liga *is* a modelled competition, so the
   competition is not the problem. `auto_series_from_catalogue` requires the
   SERIES title to match `\bplayer\s+<stat>$`; Kalshi's soccer prop series are
   titled *"La Liga Goal"*, with no word "Player". The football/basketball
   sports pass this gate only because Kalshi words *their* series
   *"…Player Points"*. **Different wording, same gate — and no ticker prefix
   would fix it.**
3. **Corners are correctly refused and must stay refused.** `KXEPLCORNERS`
   *"9+ total corners"* / `KXEPLTCORNERS` *"Aston Villa: 5+ corners"*.
   `total_market_from_stat` now checks the tail against the sport's scoring
   unit, so *"Over 4.5 corners?"* returns `None` instead of becoming a **goals**
   total at 4.5 — which would have matched a real board row on
   `(market, line, side)` and priced a corners market off a goals model with
   nothing reading wrong. Landed today in `461ee74be`.
4. **Exact-score and 1H-score families have no board shape at all.**
   `KXUECLSCORE` (120), `KXUELSCORE` (60), `KXLALIGASCORE` (31),
   `KXLALIGA1HSCORE` (13) — a correct-score market is not a 2-way line and the
   board carries no key for it. Genuinely out of scope until someone builds
   one; listed here so it stops re-appearing in the queue as if it were work.

④ **OddsAPI soccer**, for comparison: game markets are `h2h, totals, spreads`
**only** — `_game_markets()` is pinned to `DEFAULT_GAME_MARKETS` because the
bulk endpoint 422s the entire call for every league if one segment key is
included (`#343`, confirmed live 2026-08-19). Player markets are
`player_goal_scorer_anytime, player_first_goal_scorer, player_last_goal_scorer,
player_shots_on_target, player_shots, player_assists, player_to_receive_card,
player_to_receive_red_card`.

---

## 4. Alt lines and ladders — do we capture the whole ladder or one rung?

**The answer is: the RECORD keeps whole ladders; the JOIN'S INPUT does not.**
Those are two different artifacts and conflating them is what made this
invisible.

Kalshi lists **each strike as its own market**, so a spread ladder is hundreds
of rows. Measured true ladder sizes, `TICK this_tick`, 2026-08-25 19:49–20:19Z:

| series | markets Kalshi lists | in the join's working set |
|---|---|---|
| `KXNCAAFSPREAD` | **1994** | **400** (20%) |
| `KXNCAAFWINS` | 618 | 400 |
| `KXNCAAFGAME` | 600 | 400 |
| `KXNCAAFAWARD` | 509 | 400 |
| `KXNFLSPREAD` | **795** | **400** (50%) |
| `KXMLBTEAMTOTAL` | 350 | 350 ✅ |
| `KXNBAWINS` | 312 | 312 ✅ |
| `KXMLBINNINGTOTAL` | 306 | 306 ✅ |
| `KXMLBKS` | 197–205 | whole ✅ |
| `KXMLBF5TOTAL` | 175 | whole ✅ |
| `KXNFL*QSPREAD/QTOTAL` | 160 each | whole ✅ |

Two bounds apply, in this order (`pipeline/kalshi_odds_refresh.py:737–786`):

- **`MAX_MARKETS_PER_SERIES = 400`** — truncates any single ladder.
- **`MAX_STORED_MARKETS = 6000`** — then trims whole series **by staleness**,
  freshest kept. Observed `trimmed=` per tick: **2530, 2588, 2614, 2975, 2983,
  862, 888**. On a busy tick, **~1 market in 3 that Kalshi listed is not in the
  set the join prices against.**

**The capture layer is whole and is the thing to trust.** `_record_daily_book`
is called with `full_markets` — *before* both bounds — writing one dated file
per (venue, sport, date) with unparsed rows kept and their raw titles.
Observed `[kalshi_odds] DAILY_BOOK` at **20:11:06Z**:
`status=ok files=32 errors=0 listed=7324 parsed=4848 undated=1651 unparsed={'unreadable_title': 2476}`.

That ordering was itself a defect fixed **today** (`e4ae9ebec`, live 18:56Z):
`_record_daily_book` had been called with `all_markets`, *after* both bounds,
so the record inherited the working set's truncation — `KXNCAAFSPREAD` 1994→400
in the one place whose entire purpose is keeping whole ladders.

**So, precisely:**
- **Alt/ladder capture for the record: WHOLE**, since 18:56Z today, all sports.
- **Alt/ladder availability to the join and therefore to a board row: ONE RUNG
  IN FIVE for `KXNCAAFSPREAD`, one in two for `KXNFLSPREAD`**, whole for every
  other family observed. A board row asking for a spread at a strike beyond
  the first 400 will report Kalshi as having no market. **Kalshi has it.**
- The 400 cap is not sorted by relevance — it is `markets[:400]` in the order
  the API returned them, so *which* rungs survive is arbitrary rather than
  centred on the current line.

---

## 5. The reverse direction — what we could stop paying OddsAPI for

Kalshi and Polymarket are free direct API calls; OddsAPI is metered. These are
markets **Kalshi demonstrably carries** that OddsAPI is currently billed for.

**Ranked by confidence, highest first:**

| # | market family | Kalshi evidence | OddsAPI cost today | confidence |
|---|---|---|---|---|
| 1 | **WNBA half lines** (`h2h_h1/h2`, `spreads_h1/h2`, `totals_h1/h2`) | `KXWNBA1HWINNER/2HWINNER` 21, `1HSPREAD/2HSPREAD` 22, `1HTOTAL/2HTOTAL` 21 — **all six, every tick** | 4 of the 7 keys in `_WNBA_GAME_MARKETS` exist only to serve these | **HIGH** — registered, fetched, board keys exist |
| 2 | **WNBA player props** (points/rebounds/assists/threes) | `KXWNBAPTS` 51, `KXWNBAREB` 30, `KXWNBAAST` 8, `KXWNBA3PT` 22 | 4 of the 13 keys in `_WNBA_PLAYER_PROP_MARKETS` | **HIGH** — all four hand-registered, vocabulary widened today |
| 3 | **MLB game lines** (`h2h`, `spreads`, `totals`) | `KXMLBGAME` 76, `KXMLBSPREAD` 150, `KXMLBTOTAL` (user-confirmed) | the MLB game-odds request | **MEDIUM** — see the blocker below |
| 4 | **NCAAF `h2h` + `spreads`** | `KXNCAAFGAME` **600**, `KXNCAAFSPREAD` **1994** | the NCAAF game-odds request | **MEDIUM** — biggest volume, but the 400 cap means Kalshi covers only ~20% of the spread ladder as things stand |
| 5 | **NFL `h2h` + `spreads`** | `KXNFLGAME` 96, `KXNFLSPREAD` 795 | the NFL game-odds request | **MEDIUM** — same cap caveat at 50% |
| 6 | **MLB props** (K/outs/HR/hits/TB/RBI/ER/BB/H allowed) | 8 series registered, `KXMLBKS` 205 + `KXMLBHR` 133 alone | most of `DEFAULT_HITTER_MARKETS` + `PITCHER_MARKET_KEY_MAP` | **MEDIUM** — registered today, join not yet demonstrated |

**Do not cancel anything on this table yet, and here is the measurement that
says why.** `[kalshi_odds] BOARD_JOIN`, **20:16:06Z**:

```
kalshi_markets=6000 board_rows=1290 matched=54
reasons={'unreadable_title': 3703, 'market_is_for_another_date': 1274,
         'no_matching_board_row': 907, 'event_not_on_our_board': 60,
         'team_side_unresolved': 7}
```

and three minutes later, **20:19:38Z**: `board_rows=617 matched=0`.

**54 of 1290, then 0 of 617.** And `[layer2_shortlist] VENUE_REPRICE_KEYS`
(19:35:00Z – 20:18:22Z, ten consecutive readings) lists `sources_offered` for
mlb / wnba / nfl / soccer and **Kalshi appears in none of them** — only
`polymarket_us` and `oddsapi` do — while `unmatched_by_sport` reads
`{'mlb': 4204, 'wnba': 1516, 'nfl': 2132, 'soccer': 9335}`.

So: **capture is healthy (6000–7324 markets), the join is not.** Replacing an
OddsAPI market with a Kalshi one requires the join to work for that family,
and today it demonstrably does not. **The sequence is: fix the join, measure
`matched` per family, then cancel.** Cancelling first converts a metered
market into a missing one.

**`unreadable_title: 3703 of 6000 — 62%** — is the single biggest lever in the
system and it is a **gate-3 grammar job**, not a registry job. It is larger
than every registry gap in this document combined.

---

## 6. Over-registration — the mirror image, and it is not harmless

`auto_game_series_from_catalogue` registers any sport-token series whose title
*tail* resolves via `canonical_game_market`. **Season-long futures pass that
test**, because Kalshi titles them *"…AL West Winner"*, *"…Award"*,
*"…Season Points"* — and `winner`/`total` are game-market words.

Observed **registered and fetched** in `TICK this_tick`:

`KXMLBALEAST` `KXMLBALCENT` `KXMLBALWEST` `KXMLBNLEAST` `KXMLBNLCENT`
`KXMLBNLWEST` (5 each) · `KXNBACENTRAL` `KXNBAATLANTIC` `KXNBAPACIFIC`
`KXNBANORTHWEST` `KXNBASOUTHWEST` `KXNBASOUTHEAST` (5 each) · `KXNBAWINS` 312 ·
`KXNBAMOSTWINS` 4 · `KXNFLAFCEAST/NORTH/SOUTH/WEST` `KXNFLNFCEAST/NORTH/SOUTH/WEST`
(4 each) · `KXNFLPLAYOFFHOST` 32 · `KXNFLH2HWINS` 22 · `KXNFLHIGHSCORE` 9 ·
`KXNHLCENTRAL` `KXNHLATLANTIC` `KXNHLMETROPOLITAN` `KXNHLPACIFIC` (8 each) ·
`KXNCAAFAWARD` **509** · `KXNCAAFWINS` **618** · `KXNFLCELEBRITYGAME` ·
`KXNBASLAMDUNK` · `KXNBAPTSALLGAMES` · `KXWNBAWINS` 19 · `KXNHLSEASONPTS`

**Why this is not merely untidy:** these consume the two scarce resources the
real markets need.

- **The per-tick fetch budget.** `series_wanted=193`, `cap=60`. `KXNCAAFAWARD`
  and `KXNCAAFWINS` together are **1127 markets** of pure futures, and each
  occupies a slot in a 60-wide window that a live game-line series then waits
  another ~8 minutes for.
- **The 6000-market working set.** Those same 1127 (capped to 800) are ~13% of
  everything the join can see — pushing real ladders past the trim.
- **They are `undated` by construction.** `DAILY_BOOK undated=1651` at
  20:11:06Z: a season future has no game day to be filed under, which is
  correct behaviour, but it means the write cost buys nothing.

**Cheapest correct fix:** these are `SERIES_OUT_OF_SCOPE` candidates —
"we do not model this" is a *different state* from "we have not looked at this
yet", and `SERIES_OUT_OF_SCOPE`'s own comment says the queue is only useful if
it means the second.

---

## 7. GAP TABLE — every live gap, with a URL to paste a link back from

**URL shape.** The reliable, series-level page is
`https://kalshi.com/markets/<series-lower>`. The full per-event form the brief
names is
`https://kalshi.com/markets/<series-lower>/<slug>/<event-ticker>` — `<slug>` is
Kalshi's own title slug and **we hold it for exactly one series.** The one
recorded slug is `KXMLBGAME` → `kalshi.com/markets/kxmlbgame/professional-baseball-game`,
noted while chasing that series' root cause on 2026-08-24.

For `KXMLBTOTAL` we have the user-confirmed EVENT TICKER
`KXMLBTOTAL-26AUG251840BOSMIA-7` and **not** its slug — so this table does not
print one. Guessing a slug is the same invented-string error as guessing a
ticker, and it fails the same way: a wrong slug 404s, and a 404 reads as
"Kalshi does not list this". The series URL always resolves and the page
carries the slug, so that is what is given.

**Sorted by value: markets × how cheap the fix is.**

| # | series | markets | gate | what it costs to fix | URL |
|---|---|---|---|---|---|
| 1 | `KXMLBHRR` | **136** | 4 `stat_not_in_market_vocabulary` — `detail="hits + runs + RBIs"` | **one `market_keys._MLB` line** | https://kalshi.com/markets/kxmlbhrr |
| 2 | `KXMLBSB` | **44** | 1 `unmapped_series` | one `SERIES_SPORT` line + `"stolen bases": "batter_stolen_bases"` | https://kalshi.com/markets/kxmlbsb |
| 3 | `KXNCAAFSPREAD` | **1994 listed, 400 seen** | 2c working-set cap | raise `MAX_MARKETS_PER_SERIES`, or select rungs near the line instead of `[:400]` | https://kalshi.com/markets/kxncaafspread |
| 4 | `KXNFLSPREAD` | **795 listed, 400 seen** | 2c | same | https://kalshi.com/markets/kxnflspread |
| 5 | `KXMLBINNINGTOTAL` | **306** | 3 `unreadable_title` | a grammar for `"<N>th inning: Over <L> runs"` **and** a board key for a single-inning total (none exists today) | https://kalshi.com/markets/kxmlbinningtotal |
| 6 | `KXUECLSCORE` | **120** | 1 — competition not modelled | a product decision (add UEFA club comps to soccer), not a Kalshi fix | https://kalshi.com/markets/kxueclscore |
| 7 | `KXUELSCORE` | 60 | 1 — competition not modelled | same | https://kalshi.com/markets/kxuelscore |
| 8 | `KXUECLTEAMTOTAL` | 42 | 1 — competition not modelled | same | https://kalshi.com/markets/kxueclteamtotal |
| 9 | `KXEPLCORNERS` | 35 | 4 — **correctly refused** | a corners board market + model. **Do not "fix" by widening the totals unit.** | https://kalshi.com/markets/kxeplcorners |
| 10 | `KXLALIGASCORE` | 31 | 3/4 — correct-score has no board shape | a new market type | https://kalshi.com/markets/kxlaligascore |
| 11 | `KXMLBINNINGWIN` | 27 | 1 `unmapped_series` | registry line + a 3-way inning grammar (*"Teams tie scoring in the 9th inning?"*) | https://kalshi.com/markets/kxmlbinningwin |
| 12 | `KXUECL1HTOTAL` / `KXUECL1H` | 21 each | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxuecl1htotal |
| 13 | `KXEPLTCORNERS` | 14 | 4 — correctly refused | as #9 | https://kalshi.com/markets/kxepltcorners |
| 14 | `KXUECL1HSPREAD` | 14 | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxuecl1hspread |
| 15 | `KXLALIGA1HSCORE` | 13 | 3/4 | as #10 | https://kalshi.com/markets/kxlaliga1hscore |
| 16 | `KXUELTEAMTOTAL` `KXUCL1HTOTAL` `KXUCL1H` `KXLALIGATEAMTOTAL` `KXEFLCUP1HTOTAL` | 12 each | 1 — competition not modelled | same as #6 | `https://kalshi.com/markets/<ticker-lower>` |
| 17 | `KXCLUBFGAME` | 9 | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxclubfgame |
| 18 | `KXEGYPLTOTAL` / `KXEGYPLSPREAD` | 6 / 4 | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxegypltotal |
| 19 | **`KXLALIGAGOAL`** | 5 | 1 — **soccer prop series title says "Goal", not "Player Goal"** | a soccer-specific prop-title rule; `_PLAYER_PROP_TITLE` cannot see it | https://kalshi.com/markets/kxlaligagoal |
| 20 | `KXARGNACBGAME` | 3 | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxargnacbgame |
| 21 | `KXEFLCUPSPREAD` / `KXEFLCUPTOTAL` | 3 / 1 | 1 — **EFL *Cup* ≠ "Championship"** | add the competition, or accept | https://kalshi.com/markets/kxeflcupspread |
| 22 | `KXSVKCUPSPREAD` / `KXSVKCUPTOTAL` | 2 each | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxsvkcupspread |
| 23 | `KXSAUDIPLTOTAL` | 1 | 1 — competition not modelled | same as #6 | https://kalshi.com/markets/kxsaudipltotal |
| 24 | `KXNFLFFH2HSEASON` | 2 | 1 `unmapped_series` | fantasy-points H2H has no board shape | https://kalshi.com/markets/kxnflffh2hseason |
| 25 | **`KXNHLSAVES` `KXNHLANYGOAL` `KXNHLPTS`** | catalogue-only (off-season) | 1 — **`_BY_SPORT` has no `nhl` key**, so no NHL prop can EVER register | `"nhl": {...}` in `market_keys._BY_SPORT` | https://kalshi.com/markets/kxnhlsaves |
| 26 | **all NCAAB player props** | none listed yet (off-season) | 1 — **`_BY_SPORT` has no `ncaab` key** | one line: `"ncaab": _BASKETBALL` | — |
| 27 | `KXWNBAH2HPRA` | catalogue-only | 1 `unmapped_series` | a head-to-head-player grammar | https://kalshi.com/markets/kxwnbah2hpra |
| 28 | `KXNCAAFTEAMTOTAL` `KXNCAAF4QBTTS` | catalogue-only | 1/3 | registry + BTTS grammar | https://kalshi.com/markets/kxncaafteamtotal |

**The two rows worth doing tonight are #1 and #2** — together **180 live
markets**, both one-line changes, both in files that already hold the right
shape, and #1 is a series we registered *today* whose every market still
refuses.

---

## 8. SUSPECTED, UNCONFIRMED

**Nothing in this section is a fact.** These are the ones worth the user
checking on kalshi.com and sending a link for — which is the point of the
exercise. Each says exactly what would confirm it.

| suspicion | why it is plausible | what would confirm it |
|---|---|---|
| **NHL game lines exist** (`KXNHLGAME`, `KXNHLTOTAL`, `KXNHLSPREAD`) | `market_keys._GAME_CORE`'s comment records `KXNHLGAME` "NHL Game" from a live catalogue read 2026-08-24, but **this audit did not observe any of the three**. NHL is out of season. | a kalshi.com page once the season starts, or a `KALSHI_SPORT NHL` line naming them |
| **NCAAB game lines are seasonal, not absent** | `KXNCAABGAME`/`KXNCAABBGAME`/`KXNCAABBSPREAD` are in the fetch list at **0 markets** — registered and empty, which is exactly what off-season looks like | non-zero counts in `TICK this_tick` in November |
| **NCAAF player props** | OddsAPI carries the full 9-market football set for NCAAF; Kalshi carries NFL props (`KXNFLPASSTDS`, `KXNFLREC`) | any `KXNCAAF*` series with a *"Player <stat>"* title, in `SERIES_UNREGISTERED` or on a market page |
| **MLB props beyond the 9 registered** — runs scored, batter strikeouts, doubles | OddsAPI requests `batter_runs_scored` and `batter_strikeouts`; `market_keys._MLB` already resolves `runs_scored` | a `GAP` row naming e.g. `KXMLBRUNS`. **Do not add a registry line from this guess** — that is the invented-ticker trap |
| **Soccer beyond La Liga/MLS/EPL** on the modelled 10 (Bundesliga, Serie A, Ligue 1, Eredivisie, Primeira Liga, Belgian Pro League) | La Liga, EPL and MLS series are all confirmed listed; Kalshi runs dozens of competitions | a `GAP`/`SERIES` line, or a market page. The title-prefix fix means **any of these registers with no deploy the moment Kalshi lists it** |
| **NBA in-season depth** | every NBA count here is off-season (`KXNBAGAME` = 6) | re-run this audit after opening night |
| **The full soccer namespace is larger than the 24 series listed** | `LISTED` was truncated on all 7 observed runs and soccer surfaced only on the two luckiest ones (19:12Z: 68 series; 16:14Z) | widening the `GAP` cap (§9), or a `SERIES_UNREGISTERED` line once one fires |

**Explicitly NOT claimed:** that Kalshi lacks any market family in this
document. Every "❌" above means *we did not observe it*, and for an
off-season sport that is the expected reading.

---

## 9. Recommendations, cheapest first

Every one is **log-only or one line**. None was applied — this lane is
read-only, and `pipeline/kalshi_discovery.py` is being actively edited today by
`exchange-market-apis` (session `01Sia2rPD72eFTriy28azzs2`).

1. **`market_keys._MLB` += `"hits + runs + rbis": "batter_hits_runs_rbis"`.**
   136 live markets, measured 20:33:06Z. One line.
2. **`market_keys._BY_SPORT` += `"ncaab": _BASKETBALL`** and an `"nhl"` map.
   Without them, no NCAAB or NHL prop series can *ever* auto-register — the
   identical defect this file's own header documents for NFL.
3. **Register `KXMLBSB`** + `"stolen bases": "batter_stolen_bases"`. 44 markets.
4. **Make `unparsed_by_family` name the SERIES.** In `venue_daily_odds`
   (line 336) an unparsed row's `family` is the refusal REASON, so
   `DAILY_BOOK` reads `unparsed={'unreadable_title': 2476}` — the gate without
   the subject. `f"{reason}:{series}"` turns the single largest number in this
   audit into a ranked work queue. **This one line would have made most of this
   document a single log read.**
5. **Widen the `GAP` cap from 12** (`pipeline/kalshi_discovery.py`). At 12 rows
   against 68 gap series (19:12:01Z) it under-reports by ~5×, and it is the
   line the user has been working from all week. **Note it is inert without a
   deploy**, which is why it was not applied here.
6. **Move the futures series to `SERIES_OUT_OF_SCOPE`** (§6) — recovers ~13% of
   the working set and ~24 slots of a 60-wide fetch window.
7. **Then, and only then, revisit `unreadable_title` at 62% of 6000.** It is
   worth more than everything above put together, and it is the reason the
   "stop paying OddsAPI" table in §5 cannot yet be acted on.
8. **Correct the `KXNBAPTS` example** in `kalshi_catalogue.py`'s header — the
   principle is right, the example is now falsified by production (§3.2).

---

## 10. Method, and what this audit cannot tell you

- **Everything above is production log evidence or user-confirmed market
  pages.** The local `data/` tree was not read.
- **`LISTED`/`SERIES`/`GAP` are a sample, not a census.** Truncated on 7 of 7
  runs; 12–15 rows each; ~0.7% of markets are singles. **Every count from them
  is a floor.** `KALSHI_SERIES_CATALOGUE` (§2) is the only census, and it
  counts *series*, not markets, and cannot see soccer.
- **Two SHAs.** Readings before 20:20:57Z describe the pre-fix system.
- **Off-season sports are not measurable today** — NHL, NCAAB, NBA and (mostly)
  NFL. Their "❌"s are *"we did not observe it"*.
- **No claim here is that a market family is absent from Kalshi.**

### To regenerate

`scripts/audit_kalshi_oddsapi_coverage.py` prints the exact `list_logs` queries
that produced every table, so a later reader re-derives rather than trusts
this snapshot. It makes **no** network call of its own — direct HTTP to Kalshi
and to the live service is blocked from these sandboxes, which is why the
Render MCP log reads are the method.
