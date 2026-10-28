# NBA paper props "on a game the player was not in" -- FALSIFIED: they are DNPs on the player's own team

Lane `nba-prop-wrong-game` (closed in the same session), session c59f19b5 (side session of
local_35eb891d), 2026-10-28. Follow-up to `#744` / lane `paper-evicted-grading`.
**Substrate: the fleet** (WSL `~/syndicate-prod`, read-only), through the refresh-worker's
own state env (`backfill_archived_paper_grades._load_fleet_env`), code extract `2c8ba8be`.
**Plus ESPN's public summary API, read from this host.** No local `data/` mirror was used.

## Hypothesis (pre-registered in the brief, before any reading)

Five archived paper rows grade `player_not_in_box`. These are LeBron James on PHI v MIL
(10-24) and Kawhi Leonard x4 on MIN v TOR (10-25). The brief proposed that the prop
candidate join keys a player's line onto an OddsAPI event by something other than his
actual team on that date. Two mechanisms were offered: a stale roster lookup, or an
event-id mixup in the props pipeline.

**Falsification:** the hypothesis fails if the player is on one of the order's two
clubs on that date.

## Result: FALSIFIED. Every row's game is the player's own team's game

**The named five, read 2026-10-28 12:39-12:43Z:**

| order | player's team, three independent sources | in the order's game? |
|---|---|---|
| LeBron, MIL @ PHI 10-24 | PHI: ESPN 2026-27 roster on the fleet; fleet box PHI@NYK 10-20, CLE@PHI 10-22, DET@PHI 10-25 | yes |
| Kawhi x4, TOR @ MIN 10-25 | TOR: ESPN roster; fleet box CHI@TOR 10-21, TOR@WAS 10-23 | yes |
| (Kyrie x2, SAS @ DAL 10-24, same reason) | DAL: ESPN roster; fleet box 10-21, 10-23, 10-26 | yes |

The parent's premise that "the player was not in that game" was the grader's reason code
read as a location. `player_not_in_box` means *absent from the box*, and a player who
does not play is absent from the box. This is the same error class as
`learnings.md` 2026-09-28 (lane mlb-prop-grading-player-match): a VOID count's size is
not evidence of a join failure.

**ESPN confirms the DNPs directly** (`site.api.espn.com/.../summary`, read 12:42Z):

- **401909864 TOR @ MIN:** TOR lists Kawhi Leonard with `didNotPlay`, reason
  "LEFT KNEE SWELLING". He is also on TOR's injury list as Out.
- **401909855 MIL @ PHI:** LeBron is absent from PHI's 13 athletes, so he was inactive.
- **401909858 SAS @ DAL:** Kyrie is absent from DAL's 12 athletes, so he was inactive.

**When the bets were placed vs when the news broke** (fleet `data/news/nba/injuries/`,
ESPN collector):

- **LeBron:** questionable (back) from 10-23 21:21Z. The bet was placed 10-24 12:45Z.
  He was ruled out 17:31Z, about 5 h after the bet.
- **Kyrie:** questionable (knee) at 10-24 18:41Z. Both bets were placed at 18:48Z,
  7 min after the listing. He was ruled out (rest) 22:31-22:41Z.
- **Kawhi:** the four bets were placed 10-25 12:46Z-20:54Z. He was first listed Out at
  22:21Z, 1.5 h after the last bet and 49 min before tip.

**No bet was placed after an Out listing.** Two players were bet while questionable,
which a book also accepts; the book then voids the bet if the player does not play.

## Count: 0 wrong-team orders in the window

**Scope:** every NBA player-prop order, paper and live, from the live document and the
archive, deduped by identity, with a Central game date of 10-14 or later.

**Script:** `C:\tmp\pnig\count_wrong_team.py`, read 12:41:53Z.

**The two sources of truth:**
1. The fleet's NBA live box (keyvalue) for that date: who played, and in which game.
2. For players absent from the box: the fleet's ESPN `rosters_2026-27.csv`.

**Window:** box dates 10-20..10-28 were all readable. No NBA prop order in the window has a
game before 10-20, because the regular season opened 10-20 and preseason was 10-02..10-16.

| class | paper | live | total |
|---|---|---|---|
| played, in the order's own game | 1,538 | 46 | 1,584 |
| played, in a DIFFERENT game | 0 | 0 | **0** |
| absent from box, roster team IS in the game | 21 | 0 | 21 |
| absent from box, roster team NOT in the game | 0 | 0 | **0** |
| not on any roster, or order has no matchup | 0 | 0 | 0 |
| **total** | 1,559 | 46 | **1,605** |

**What the 21 absent rows are:**
- **14 past-game DNPs on 10-24..10-26:**
  - LeBron x1, Kyrie x2, Kawhi x4
  - VJ Edgecombe x3, Keegan Murray, Ausar Thompson, Chet Holmgren, Cason Wallace
- **7 rows on 10-28:** tonight's games, which had not started when this was read.

**Answer to the brief's question:** 0 of 1,605 NBA prop orders carry a player on a team
not in the game. The candidate join is exonerated on this population.

## What actually makes these rows ungradable

The stage that turns a DNP into what looks like a wrong game is the GRADER. The candidate
join is not involved. Two hops:

1. **`syndicate/features/nba/live_tick/tick.py:2467`:**
   `_live_extract_player_boxscore_from_espn_summary` drops every athlete with 0 minutes
   and no non-zero stat (`if mp <= 0.0 and not nonzero: continue`). That includes ESPN's
   explicit `didNotPlay` rows, so Kawhi's "LEFT KNEE SWELLING" row never reaches the box.
   Inactive players (LeBron, Kyrie) are not in ESPN's athletes list at all.
2. **`syndicate/features/shared/bet_status_nba.py:272-277`:** a player absent from the box
   returns `player_not_in_box` even when the game is `post`. That reason is transient: a
   name mismatch and a DNP look identical. NHL distinguishes them as `dnp_void` when the
   game is final (`bet_status_nhl.py:892`).

**A rename would not grade these rows. No sport settles a DNP today.** Every sport's DNP
is a named REFUSAL, not an outcome:
- NHL: `dnp_void`
- NFL: `nfl_player_did_not_play_void`, `bet_status_nfl.py:178`
- soccer: `soccer_player_did_not_appear_void`, `bet_status_soccer.py:130`

`paper_settlement` has won/lost/push and no void, so NHL's `dnp_void` row in the `#744` dry
run also stayed stale. `#690` item 4 records the same gap for NFL.

**Precedent for NBA:** `bet_status_nfl` asks ESPN's core API for the game roster on a
final-box absence. It proves a DNP from `didNotPlay: true` with no statistics, and refuses
anything ambiguous by name (`bet_status_nfl.py:98-112`).

Books void a DNP prop and return the stake. So the residue is permanent until two things
happen:
- a rule decides that paper settles `dnp_void` as a void, with P&L 0 and the stake back;
- NBA can tell a DNP from a name miss:
  - positive evidence: keep `didNotPlay` rows in the box, and use the injury feed's Out
    listing or the roster for inactives;
  - versus inference.

## Follow-ups (not built here; nothing on the fleet was written)

1. **NBA DNP grading.** Built default-off, with a reachability test, this needs:
   - the box capture keeps `didNotPlay` athletes, flagged;
   - `bet_status_nba` returns `dnp_void` on a `post` game when the player is flagged DNP,
     or is absent while on one of the two clubs' ESPN rosters;
   - `player_not_in_box` stays for a true name miss.

   File overlap: `bet_status_nba.py` is claimed by `paper-evicted-grading`, scoped
   "no-box game-line fallback ONLY".
2. **Cross-sport policy (user decision):** should paper settlement turn `dnp_void`
   (NHL, NFL, soccer, NBA) into a void, with the stake back and the bet excluded from ROI
   and hit rate? Without it, every DNP stays "stale" in the `#744` count forever.
