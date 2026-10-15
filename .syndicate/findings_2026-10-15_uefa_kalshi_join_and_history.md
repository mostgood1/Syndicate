# UEFA competitions: the Kalshi join and ESPN history depth (2026-10-15)

Lane `soccer-uefa-competitions`, session 15fef1c0. Both pieces were read-only measurements: no repo change, no OddsAPI call.
Scratch artifacts (not in git): `%TEMP%\claude\...\15fef1c0-...\scratchpad\kalshi_uefa\` and `...\uefa_history\`.

## 1. Kalshi UEFA game markets vs our board

The belief listed as UNVERIFIED in the Stage 0 checkpoint ("Kalshi UEFA markets join board rows by team name") **does not hold**.

**Inputs.** Live Kalshi public API pull. Our side was the 18 UCL events from a scratch OddsAPI capture, with the real `join_kalshi_to_board` and `match_event_blob`.

| series | markets | correct event | wrong event | unjoined | Kalshi clubs we can name |
|---|---|---|---|---|---|
| KXUCLGAME | 54 | 27 (9 of 18 fixtures) | 0 | 27 | 26/36 |
| KXUCLTOTAL | 108 | 54 | 0 | 54 | – |
| KXUELGAME / KXUECLGAME | 54 / 54 | – (no UEL/UECL board in scratch) | – | – | 17/32, 9/36 |

**Full join** (game lines on, 182 board rows): **22 matches priced, all totals, zero moneylines.** Every resolved market matched on date, on both clubs and on orientation [measured].

**Causes:**

- **9 of 18 UCL fixtures have a club `canonical_team` cannot name.** `match_event_blob` skips those games outright. The clubs: Galatasaray, Fenerbahce, Slavia Praha, Sabah FK, AEK Athens, Bodø/Glimt, LASK, Shakhtar, Slovan Bratislava, Viking. The two venues also spell clubs differently (OddsAPI "Slavia Praha"/"Sabah FK" vs Kalshi "Slavia Prague"/"Sabah Masazir"), so UEFA aliases are needed on both sides.
- **Codes collide inside one series family.** KXUEL uses `LEV` for both Leverkusen and Levski Sofia, and `CEL` for both Celtic and Celje. `build_club_code_names` drops such a code, which then falls back to the GLOBAL map: `LEV` -> levante. The global map also gives `MUN` -> bayern munich (Kalshi means Man United) and `SPA` -> sparta rotterdam (Kalshi means Sparta Prague). No wrong join was observed, because names win, but the path exists.
- **CROSS-SPORT BUG, reproduced 2026-10-15 with the real join (MLB "Minnesota wins"):** every moneyline is refused `no_matching_board_row`. `_parse_title` gives moneylines `line: None`, and the join looks up `(event, "h2h", None)`, but `_event_key` indexes h2h rows at `0.0`. `SYNDICATE_KALSHI_GAME_LINES=1` is set on both fleet workers (read 21:1xZ), so this affects production in every sport. The soccer DRAW leg would also fail `_side_for_team`. A separate session was proposed for the fix; it is outside this lane.

**Consequence for UEFA Stage 0:** only Kalshi UCL TOTALS can price today, and only on the half of fixtures whose clubs we can name.

## 2. ESPN UEFA history depth (for Stage 1, `#699`)

**Request shape [measured; re-derived by the lane owner the same day]:**

- `scoreboard?dates=YYYY&limit=1000` returns a whole CALENDAR year in one request. UCL 2024 = 137/137 completed, UEL 2024 = 153.
- The range form `YYYYMMDD-YYYYMMDD` is refused with HTTP 400.
- Calendar year is not season. 2026 returns 189 events spanning two seasons, so regroup by season start.
- History goes back at least to 2010; 12,720 events were pulled.
- Qualifiers have separate slugs from 2020 on (`uefa.champions_qual`, `uefa.europa_qual`, `uefa.europa.conf_qual`). Before 2020 they sit inside the main slugs.

**Stats:**

- `summary` -> `boxscore.teams[].statistics` has 28 fields: shots, on target, possession, corners and more.
- There is **no xG**.
- Qualifier summaries are often empty (3 of 5 sampled).

**Coverage, 2014–2025 completed:**

- 626 distinct clubs in 9,105 matches.
- 509 clubs come from outside our ten leagues (184 with 20+ matches, 75 with 50+).
- League membership was taken from ESPN team ids in each domestic league's scoreboard, 2010–2026.

**Cross-league matches (both clubs from two different modelled leagues):**

- UCL 959/2,172 (44%; 63% for 2021–25), UEL 547/3,931 (14%), UECL 9%.
- 1,591 such matches cover all 28 league pairs: EPL–La Liga 138 at most, Belgium–Eredivisie 19 at least.
- **MLS and the Championship have ~0 UEFA matches**, so UEFA cannot place them.

**FotMob:** UCL `primaryId` 42 [measured]; UEL 73 / UECL 10216 [not measured]. `FOTMOB_LEAGUES` lacks them, so FotMob shot xG is unreachable for UEFA until they are added.

**Verdict for Stage 1:**

- (a) Ratings for out-of-scope clubs are feasible from results plus shots.
- (b) League offsets are feasible for the 8 European leagues: strong for the big 5, thin for Belgium/Eredivisie, none for MLS/Championship.
- Fetch cost: about 60 scoreboard requests for results, and about 2,500–6,800 summaries for team stats (2021–25 vs 2014–25).
