# Polymarket SPORTS_MARKET_TYPE_PROP — measured characterisation (2026-09-01)

Lane: `polymarket-prop-quote-capture`, session 41d46db0. This is the MEASURED
decision the join's own comment demands before touching the PROP bucket
("out of scope needs to be a MEASURED decision rather than a standing one",
`polymarket_board_join.py` ~1312).

## Instruments

1. Production refresh-worker logs, deployed SHA, read 2026-09-01T17:1xZ:
   `POLYMARKET_OUT_OF_SCOPE` (17:06:12Z) and the prop modifier census
   (`soccer_prop_shapes=`, despite the name it is every-league) in
   `POLYMARKET_UNMATCHED` (17:06:12Z).
2. The venue's own catalogue, fetched UNAUTHENTICATED from the public web
   gateway `https://web.polymarket.us/gateway.events.v1.EventsService/GetEvents`
   (Connect JSON, `{"slug": ["mlb-<away>-<home>-<date>"], "limit": N}`) from a
   polymarket.us page context in the in-app browser. This endpoint returns the
   FULL market objects **including `question`** — the field
   `persist_game_slate` deliberately drops, and the only field that names the
   bet. 8 of 8 known 2026-09-01 MLB fixtures returned. No credentials involved
   (the signed `api.polymarket.us` API refuses without keys, verified 401).

## What PROP actually contains (counts, per league, 17:06Z cycle)

    mlb 2644 · ufc 593 · nfl 448 · cfb 446 · ucl 373 · lal 202 · epl 196 ·
    sea 182 · bun 181 · lg1 178 · cs2 100 · atp 96 · lol 61 · wta 55 ·
    lgscup 36 · dota2 11 · valorant 8 (+ PROP|SEGMENT variants)

MLB is the venue's LARGEST prop bucket. The 2026-08-27 state.md claim
"POLYMARKET LISTS NONE [player props]" is **FALSIFIED** — it was inferred from
two independent refusal counters (venue-side `market_type_not_a_game_line`,
board-side `board_market_not_a_game_line`), neither of which measures overlap.

## MLB PROP composition (8 games, 2026-09-01, venue catalogue)

Per game ~219-238 markets, of which ~170 player props + ~30 inning-winner
(`i1..i9-<team|draw>`) + `f5-<team|draw>` + `yrfi` (game-level, typed PROP).

Player-prop families and per-game counts (slug modifier -> meaning, from the
paired `question` text):

    hrr  54-66  hits + runs + RBIs      ("record at least N hits + runs + RBIs")
    tb   45-55  total bases
    hits 27-30  hits
    hr   18-22  home runs
    k     5-11  pitching strikeouts
    outs  4-9   outs recorded
    er    2-6   earned runs allowed
    ha    3-6   hits allowed
    wa    2-4   walks allowed

Slug grammar: `astatc-mlb-<away>-<home>-<date>-<family>-<playertoken>-gte<N>`.
Threshold `gteN` == "at least N" == board `over` at line N-0.5; outcomes are
`["Yes","No"]`, and YES is the at-least side BY THE MARKET'S OWN CONSTRUCTION
(not a guessed side constant — the `gte` token pins it).

## The player token encoding — 99 ground-truth (token, full name) pairs

Rule, validated on 97 of 99 pairs across 8 games (the implemented
`_polymarket_player_token` was run over every pair: exact=97, miss=2, and
both misses are the venue's own collision-extended forms below):

    token = first-3-of-first-name + first-3-of-SURNAME, lowercased
    - first name shorter than 3 keeps its full length: ty-fra, jj-ble, jo-ade
    - suffixes dropped: fertat (Tatis Jr.), vlague (Guerrero Jr.),
      bobwit (Witt Jr.), ronacu (Acuna Jr.), michar (Harris II)
    - SURNAME = the LAST space/hyphen-separated word: ellcru (De La Cruz -> cru),
      petarm (Crow-Armstrong -> arm), ajsha (Smith-Shawver -> sha)
    - diacritics folded: eugsua (Suárez), julrod (Rodríguez), maudub (Dubón)

The 2 exceptions are the venue's OWN league-wide collision handling:

    wilcon2  William Contreras  (Willson Contreras collides at wilcon -> digit suffix)
    bretbat  Brett Bateman      (Brett Baty collides at brebat -> 4+3 extension)

**Implication that makes exact-match safe:** the venue disambiguates its token
space LEAGUE-WIDE. A bare 3+3 token therefore identifies one player in the
venue's own vocabulary. Our side derives the token from OUR `player_name` and
requires exact equality — a venue-extended token we cannot derive (bretbat,
wilcon2) is a COVERAGE miss, never a wrong-person match. Residual wrong-person
risk needs the venue's collision management to have missed a same-token pair
AND our board to carry the other player in the same game: defended by refusing
when two board players in one game derive the same token, and by refusing
venue-side in-game token duplicates. Recorded in the module.

Full pairs (game: token=name):

sd-cin: ranvas=Randy Vasquez, niclod=Nick Lodolo, fertat=Fernando Tatis Jr.,
tyfra=Ty France, ellcru=Elly De La Cruz, manmac=Manny Machado, salste=Sal
Stewart, jacmer=Jackson Merrill, jjble=JJ Bleday, tylste=Tyler Stephenson,
matmcl=Matt McLain, eugsua=Eugenio Suarez
sf-pit: logweb=Logan Webb, pauske=Paul Skenes, junlee=Jung Hoo Lee,
bryrey=Bryan Reynolds, esmval=Esmerlyn Valdez, onecru=Oneil Cruz, spehor=Spencer
Horwitz, jakman=Jake Mangum, bralow=Brandon Lowe, dregil=Drew Gilbert,
rafdev=Rafael Devers, shawhi=Shay Whitcomb
mia-kc: randob=Randy Dobnak, tylphi=Tyler Phillips, bobwit=Bobby Witt Jr.,
kylsto=Kyle Stowers, jaccag=Jac Caglianone, jakmar=Jakob Marsee, carjen=Carter
Jensen, herher=Heriberto Hernandez, salper=Salvador Perez, josroj=Josh Rojas,
ottlop=Otto Lopez, javsan=Javier Sanoja
tor-cle: spearr=Spencer Arrighetti, bretbat=Brett Bateman, stekwa=Steven Kwan,
gavwil=Gavin Williams, josram=Jose Ramirez, natlow=Nathaniel Lowe,
vlague=Vladimir Guerrero Jr., trabaz=Travis Bazzana, geospr=George Springer,
natluk=Nathan Lukes, joade=Jo Adell, kazoka=Kazuma Okamoto, jessan=Jesus
Sanchez, spemil=Spencer Miles
det-min: tromel=Troy Melton, gletor=Gleyber Torres, dildin=Dillon Dingler,
brolee=Brooks Lee, kevmcg=Kevin McGonigle, kodcle=Kody Clemens, ryajef=Ryan
Jeffers, josbel=Josh Bell, trelar=Trevor Larnach, roylew=Royce Lewis,
spetor=Spencer Torkelson, andmor=Andrew Morris
mil-chc: robgas=Robert Gasser, matboy=Matthew Boyd, nichoe=Nico Hoerner,
andvau=Andrew Vaughn, jaccho=Jackson Chourio, seisuz=Seiya Suzuki, petarm=Pete
Crow-Armstrong, britur=Brice Turang, alebre=Alex Bregman, carkel=Carson Kelly,
micbus=Michael Busch, garmit=Garrett Mitchell, wilcon2=William Contreras
atl-wsh: jakirv=Jake Irvin, michar=Michael Harris II, drabal=Drake Baldwin,
ajsha=AJ Smith-Shawver, maudub=Mauricio Dubon, ronacu=Ronald Acuna Jr.,
matols=Matt Olson, daylil=Daylen Lile, ozzalb=Ozzie Albies, abiort=Abimelec
Ortiz, dylcre=Dylan Crews, keirui=Keibert Ruiz
sea-bos: brywoo=Bryan Woo, domcan=Dominic Canzone, josnay=Josh Naylor,
micgas=Mickey Gasper, julrod=Julio Rodriguez, cedraf=Ceddanne Rafaela,
romant=Roman Anthony, wilabr=Wilyer Abreu, ranaro=Randy Arozarena, colyou=Cole
Young, adlrut=Adley Rutschman, nicsog=Nick Sogard

Historical note: the module docstring's 2026-08-24 example `hits-jakman-gte2`
is Jake **Mangum** (measured today on sf-pit), NOT Jackson Merrill (jacmer) —
the no-guessing rule was right.

## Out of scope for this lane, measured and named

- Soccer PROP: team-level (`ftts`, `exact-score`, `fh-exact-score`) — no player
  lines observed; btts/cor-all already admitted individually.
- `i1..i9`/`f5` inning-segment winners, `yrfi`, `draw`: game/segment-level; the
  board has no matching market today (segment gate would refuse i*/f5 anyway).
- NFL PROP (448/cycle): real, unmeasured vocabulary — week-1 slugs could not be
  guessed; same mechanism applies once a fixture is resolvable. NOT this lane.
- esports/tennis (cs2/lol/valorant/dota2/atp/wta): map/set winners, not props
  we model.
