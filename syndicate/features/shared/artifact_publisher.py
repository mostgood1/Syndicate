"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Pushes a small allowlist of frequently-refreshed ("hot") artifacts from a worker
  process to the web service's local disk, over HTTP, so the web dyno can serve
  current data without sharing a disk with the workers (Render disks are per-service).

Constraints:
- Must never raise: publish failures are logged and swallowed so a refresh loop
  never breaks because the web service is briefly unreachable.
- Only ever touches the fixed, explicit allowlist below. Bulk/historical/evaluation
  data is intentionally excluded and stays worker-local.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import json
import logging
import os
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("artifact_publisher")

HOT_ARTIFACT_PATTERNS: tuple[str, ...] = (
    # #246: the settlement inputs. `emit_settlement_inputs.emit_for_date`
    # writes these on refresh-worker and then tries to publish them, and every
    # attempt was refused -- measured 2026-08-06 23:07:
    #   [artifact_publisher] SKIP_NOT_ALLOWLISTED
    #     path=/opt/render/project/data/settlement_inputs/finals_2026-08-06.json
    # 15 refusals in a single emit pass. The emitter's own summary that run read
    # `closing_rows=7316 graded_rows=192`, so this is real settlement evidence
    # being produced on the worker and then discarded at the service boundary.
    #
    # Settlement itself runs on refresh-worker against its LOCAL copies, so this
    # does not by itself change what settles -- it is what makes the inputs
    # visible from web, which is the only place they can be inspected. #208's
    # lesson applies exactly: allowlisting permits a transfer, it does not make
    # one happen.
    # #322: the precomputed Layer 1 book grid. refresh-worker pivots the
    # 207MB book_quotes shard (measured 2026-08-09) and web reads the bounded
    # result -- web cannot do that pivot, one read is ~1.3GB resident on a 2GB
    # container. Allowlisting PERMITS the transfer; the worker autorun is what
    # makes one happen (#208).
    "*_source/data/book_grid/book_grid_*.json",
    "settlement_inputs/closing_lines_*.csv",
    "settlement_inputs/finals_*.json",
    "*_source/source_artifacts/data/live_lens/live_lens_report_*.json",
    "*_source/source_artifacts/data/live_lens/render_sync/*.json",
    # NBA/WNBA's in-game pace-adjusted live projections, written by the
    # vendored live-lens tick (now called in-process from
    # syndicate/features/wnba/live_lens.py instead of only over HTTP) and read
    # by wnba/cards.py's _artifact_live_player_lens_payload. Written on
    # live-odds-worker, read on web -- Render gives each service its own
    # disk, so this allowlist entry is what actually gets a live game's
    # projection from the worker that computes it to the service that serves
    # it, not just a path-naming fix.
    "*_source/source_artifacts/data/live_lens/live_lens_projections_*.jsonl",
    "*_source/source_artifacts/data/live_lens/live_lens_signals_*.jsonl",
    "*_source/source_artifacts/data/processed/recommendations*.json",
    "*_source/source_artifacts/data/processed/recommendations*.csv",
    "*_source/source_artifacts/data/processed/props_recommendations*.json",
    "*_source/source_artifacts/data/processed/props_recommendations*.csv",
    "*_source/source_artifacts/data/processed/game_cards_*.csv",
    "*_source/source_artifacts/data/processed/cards_sim_detail_*.json",
    "*_source/source_artifacts/data/processed/cards_props_snapshot_*.json",
    "*_source/source_artifacts/data/processed/smart_sim_*.json",
    "*_source/source_artifacts/data/market/*.json",
    # Phase 3 of migrating off the daily-update GHA cron: these were only
    # ever synced by the retired pipeline's blanket Sync-SportSourceArtifacts
    # robocopy. Confirmed live reads (not just worker-side generation) before
    # adding: season_betting_card_manifest -> nba/betting_card.py's
    # build_season_betting_card_manifest_payload, consumed by
    # blueprints/nba.py; live_player_lens_tuning -> nba/cards.py and
    # wnba/cards.py's live-game rendering. Deliberately NOT adding
    # calibration_active.json/prob_calibration.json/manifests/* -- those are
    # worker-only inputs to the odds refresh scripts, never read by any
    # blueprint, so pushing them would just reproduce the old robocopy's
    # "copy everything" bulk-data mistake.
    "*_source/source_artifacts/data/processed/season_betting_card_manifest_*.json",
    "*_source/source_artifacts/data/processed/live_player_lens_tuning_*.csv",
    "*_source/source_artifacts/current_week.json",
    # NBA/WNBA's raw (unfiltered, pre-recommendation-engine) OddsAPI player
    # props feed (scripts/fetch_basketball_oddsapi_props_local.py's flat
    # per-outcome rows). Confirmed via direct research 2026-07-23: this was
    # written worker-side but never allowlisted, so the market board's
    # Layer 1 join only ever saw the recommendation engine's own curated
    # picks -- the same gap MLB's oddsapi_pitcher_props/oddsapi_hitter_props
    # (already allowlisted above via the market/*.json pattern) had before
    # this session's market board work started reading it directly.
    "*_source/source_artifacts/data/processed/oddsapi_player_props_*.csv",
    "*_source/data/processed/oddsapi_player_props_*.csv",
    # `#310`, DIAGNOSTIC. The WNBA grader's actual result inputs, and the file
    # both recon builders are built from. Until now `recon_games_*`,
    # `recon_props_*` and dated `boxscores_*` were in no pattern here (only the
    # UNDATED `boxscores_history.csv`, two blocks down), so they could never
    # cross services and could never be inventoried from web -- meaning an
    # `/api/ops/artifacts/export` query returning nothing for them was an
    # ALLOWLIST ARTIFACT, not evidence of absence. That is the specific hole
    # that stopped this lane proving whether WNBA's zero graded rows are a
    # missing producer or a missing join.
    #
    # #208'S LESSON, CARRIED DELIBERATELY: allowlisting PERMITS a transfer, it
    # does not MAKE one happen. Adding these does not by itself publish
    # anything.
    #
    # WHAT SHOULD CHANGE: `sweep_changed_hot_artifacts` on the writing service
    # now has these in scope, so after the next WNBA refresh cycle writes them,
    # `?names_only=1&pattern=*wnba_source/data/processed/recon_*` should return
    # a non-empty listing on web.
    # WHAT WOULD PROVE IT DID: that listing being non-empty. If it stays empty
    # AND `/api/ops/wnba/artifact-counts` reports `boxscores_present: true` with
    # `recon_games: false` for the same date, the files are genuinely not being
    # produced -- the builders had their precondition and wrote nothing -- and
    # that is a producer defect, not a visibility one. Those two readings are
    # otherwise indistinguishable, which is why both are named here.
    # WNBA ONLY, and the glob is `boxscores_2*` so it takes the small dated
    # per-slate files and never `boxscores_history.csv` (NBA's is ~20MB and is
    # deliberately excluded two blocks down). A `*_source/` wildcard here would
    # pull NBA's and NHL's dated boxscores into every sweep as well, and web is
    # already OOMing at 2Gi on oversized payloads (`#302`) -- widening this is a
    # separate decision with its own measurement, not a free side effect of a
    # WNBA diagnostic.
    "wnba_source/data/processed/recon_games_*.csv",
    "wnba_source/data/processed/recon_props_*.csv",
    "wnba_source/data/processed/boxscores_2*.csv",
    "wnba_source/source_artifacts/data/processed/recon_games_*.csv",
    "wnba_source/source_artifacts/data/processed/recon_props_*.csv",
    "wnba_source/source_artifacts/data/processed/boxscores_2*.csv",
    # Same set again, one directory shallower: some sports (confirmed for WNBA)
    # write their processed artifacts straight to "<sport>_source/data/processed/"
    # rather than nesting under a "source_artifacts" nested root, so the patterns
    # above alone silently match zero files for those sports.
    "*_source/data/live_lens/live_lens_report_*.json",
    "*_source/data/live_lens/render_sync/*.json",
    "*_source/data/live_lens/live_lens_projections_*.jsonl",
    "*_source/data/live_lens/live_lens_signals_*.jsonl",
    "*_source/data/processed/recommendations*.json",
    "*_source/data/processed/recommendations*.csv",
    "*_source/data/processed/props_recommendations*.json",
    "*_source/data/processed/props_recommendations*.csv",
    "*_source/data/processed/game_cards_*.csv",
    "*_source/data/processed/cards_sim_detail_*.json",
    "*_source/data/processed/cards_props_snapshot_*.json",
    "*_source/data/processed/smart_sim_*.json",
    "*_source/data/market/*.json",
    "*_source/data/processed/season_betting_card_manifest_*.json",
    "*_source/data/processed/live_player_lens_tuning_*.csv",
    "*_source/current_week.json",
    # #43. The intelligence board state, moved off the keyvalue store. It is
    # data, not coordination state: measured at 15.5MB for 150 candidates
    # against an 8MB ceiling the store cannot be raised past (~9MB closes the
    # connection). Deduplication could not close that -- the payload is five
    # near-copies of the candidate list and they are enriched differently, so
    # they are not aliasable. This path already moves tens of MB routinely and
    # matches the stated architecture: workers write artifacts, web reads them.
    "reports/intelligence/intelligence_state.json",
    "reports/intelligence/intelligence_state_*.json",
    # #83's bounded per-date steam record. capture_phase and steam detection
    # are otherwise only observable through the raw per-observation lifecycle
    # log (odds_events/<date>.jsonl), which reached 1.2GB in a single day
    # (odds_lifecycle.py) -- allowlisting that would reproduce the exact
    # oversized-payload pattern that caused #43/#50/#54. This file is the
    # opposite by construction: capped at the newest 200 events
    # (_STEAM_EVENTS_KEEP in odds_refresh_tracking.py), each event carrying
    # capture_phase directly, so it is the cheap, bounded way to verify both
    # without exporting bulk data.
    "reports/steam/steam_events_*.json",
    # Same-moment odds-events-coverage diagnostic for the pitcher live-lens
    # investigation (see fetch_mlb_oddsapi_local.py::_diagnose_live_events_coverage):
    # OddsAPI's raw/date-filtered event counts vs. MLB's own schedule-derived
    # live count, written on whichever service runs the odds-refresh
    # subprocess. Tiny (a handful of ints per date), so allowlisting it is
    # cheap; without this it is only readable on the writing service's own
    # disk, and the writer isn't necessarily the one this is investigated from.
    "reports/mlb_odds_diag/live_events_coverage_*.json",
    # #207. Same-moment provenance of odds_history as it exists on the ODDS
    # WORKER's own disk. odds_history is written to three paths and the third
    # (reports/odds_control_plane/odds_history/) sits outside data_root() by
    # construction, so it can never be allowlisted and never crosses services --
    # meaning web literally cannot see the copy the writing service keeps. This
    # tiny summary (book counts, bookmaker-coverage %, closing-capture %) is the
    # only way to compare what the odds worker CAPTURES against what web
    # RECEIVES, which is what decides whether #205/#206's single-book and
    # missing-closing-line findings are a capture defect or a publish defect.
    "reports/mlb_odds_diag/odds_history_provenance_*.json",
    # MLB's vendored daily sim (vendor/mlb_bettingv2/tools/daily_update.py,
    # triggered from live_refresh_loop.py's MLB daily-sim gate) writes under
    # data/daily/, data/manager/, data/park/, data/umpire/ -- none of which
    # the processed/live_lens/market patterns above cover. Bulk/historical
    # paths (data/cache, data/raw/statcast, data/eval/seasons/...) are
    # deliberately excluded here, consistent with this module's "no
    # bulk/historical data" constraint above.
    "*_source/source_artifacts/data/daily/daily_summary_*.json",
    "*_source/source_artifacts/data/daily/ladders/daily_ladders_*.json",
    "*_source/source_artifacts/data/daily/top_props/daily_top_props_*.json",
    "*_source/source_artifacts/data/daily/lineups_last_known_by_team.json",
    # Daily odds/lineup snapshots: confirmed live reads on web -- MLB cards.py
    # reads snapshots/<date>/{oddsapi_game_lines,oddsapi_hitter_props,
    # oddsapi_pitcher_props,lineups}.json for market tiles and lineup state,
    # and hr_targets.py walks the date dir. These are written worker-side by
    # refresh_mlb_oddsapi.py; without publishing them the web board renders
    # ml/totals as null (observed 2026-07-16). Small per-date JSONs, not bulk.
    "*_source/source_artifacts/data/daily/snapshots/*/*.json",
    # Per-game sim artifacts: cards.py hydrates output segments and starter
    # ladder badges from data/daily/sims/<date>/sim_*.json (and game detail
    # rides the same lookup). In the GHA era these reached web via git sync;
    # worker-centric sims left them stranded worker-side, so compact cards
    # rendered without sim tiles (observed 2026-07-17). ~200-400KB per game,
    # current + next day only -- not the bulk/historical case above.
    "*_source/source_artifacts/data/daily/sims/*/sim_*.json",
    "*_source/source_artifacts/data/manager/manager_tendencies.json",
    "*_source/source_artifacts/data/manager/probable_pitcher_overrides.json",
    "*_source/source_artifacts/data/park/park_factors.json",
    "*_source/source_artifacts/data/umpire/umpire_factors*.json",
    "*_source/data/daily/daily_summary_*.json",
    "*_source/data/daily/ladders/daily_ladders_*.json",
    "*_source/data/daily/top_props/daily_top_props_*.json",
    "*_source/data/daily/lineups_last_known_by_team.json",
    "*_source/data/daily/snapshots/*/*.json",
    "*_source/data/daily/sims/*/sim_*.json",
    "*_source/data/manager/manager_tendencies.json",
    "*_source/data/manager/probable_pitcher_overrides.json",
    "*_source/data/park/park_factors.json",
    "*_source/data/umpire/umpire_factors*.json",
    # #68. The per-date betting-card payload. It lives UNDER data/eval/seasons,
    # which the comment above excludes as bulk/historical -- correctly for that
    # tree in general, and wrongly for this one file, which is a small
    # per-date artifact that merely happens to be stored there (measured:
    # 5.4KB for a full slate, one per day, same category as
    # daily_summary_*.json two blocks up).
    #
    # Excluding it had a large consequence. mlb/cards.py's
    # _betting_payload_by_game reads exactly this file, and it is the ONLY
    # source of game["markets"] -- which _mlb_game_market_recommendation_rows
    # turns into the game_market_recommendations that
    # _game_bet_candidates_from_game reads. Measured on refresh-worker
    # 2026-07-26: BETTING_PAYLOAD_READ exists=False, betting_game_count 0,
    # every MLB market block 0, MLB contributing nothing to the board, while
    # web served the same games with a full 7-key markets dict. Not
    # allowlisted meant neither the push nor the pull could ever move it, so
    # the worker could not converge no matter how long it ran.
    #
    # Deliberately narrow: scoped to the betting_day_payloads_* directory and
    # the season_betting_day_* filename, so data/eval/seasons/** at large --
    # statcast, caches, season rollups -- stays excluded as before.
    "*_source/source_artifacts/data/eval/seasons/*/betting_day_payloads_*/season_betting_day_*.json",
    "*_source/data/eval/seasons/*/betting_day_payloads_*/season_betting_day_*.json",
    # #84. NWS park weather, one small per-date JSON written worker-side by
    # scripts/fetch_mlb_weather.py; the board and (once joined, #84's open
    # half) the sim read it.
    "*_source/source_artifacts/data/weather/weather_*.json",
    # Ask the Syndicate focused-evidence inputs (syndicate/blueprints/
    # ask_the_syndicate_data.py). These are live web-side reads: the Ask
    # endpoint builds last-10 game-log tables from the boxscore histories and
    # the sim-accuracy trend from sim_vs_actual. One file per day (evals,
    # ~4.5MB) or one rolling file per sport (boxscores). NBA's
    # boxscores_history.csv (~20MB) is deliberately NOT listed -- it rides
    # the git+bootstrap lane instead; the WNBA/NHL equivalents are small.
    "mlb_source/source_artifacts/data/eval/batches/*/sim_vs_actual_*.json",
    "wnba_source/source_artifacts/data/processed/boxscores_history.csv",
    "wnba_source/data/processed/boxscores_history.csv",
    "nhl_source/source_artifacts/data/raw/player_game_stats.csv",
    "nhl_source/data/raw/player_game_stats.csv",
    # #163's MLB player game-log index (last-N starts/games, history vs
    # opponent -- syndicate/features/mlb/player_game_log.py, read by
    # ask_the_syndicate_data.py's _mlb_player_history_evidence) is the same
    # category as WNBA/NHL's boxscore/game-stats CSVs two lines up and was
    # missed when those were added: written by refresh-worker
    # (run_mlb_daily_sim_job.py's post-sim hook) but read on web, so without
    # this entry it would build correctly forever on refresh-worker's disk
    # and never once reach the service that answers Ask The Syndicate
    # questions -- confirmed live 2026-07-30 (a real "Eury Perez outs" query
    # against production returned no visuals at all post-deploy). Small
    # per-season CSVs (thousands of rows, not the NBA-scale ~20MB case that
    # rides the git+bootstrap lane instead).
    "mlb_source/source_artifacts/data/processed/mlb_pitcher_game_log.csv",
    "mlb_source/data/processed/mlb_pitcher_game_log.csv",
    "mlb_source/source_artifacts/data/processed/mlb_batter_game_log.csv",
    "mlb_source/data/processed/mlb_batter_game_log.csv",
    # #163's MLB advanced Statcast profile (whiff/barrel/xwOBA/pitch-mix --
    # syndicate/features/intelligence.py's _mlb_statcast_feature_payload,
    # read on web by both Ask The Syndicate and other MLB features). Same
    # gap as the two entries above: worker-written, web-read, never
    # allowlisted. ~9-10MB, bounded (one curated feature file per season, not
    # a growing/unbounded tree like data/cache or data/raw/statcast).
    "mlb_source/source_artifacts/data/statcast/features/player_features_latest.json",
    "mlb_source/data/statcast/features/player_features_latest.json",
    # Soccer has no source_artifacts/data/processed nesting -- build_soccer_artifacts.py,
    # poll_soccer_live_state.py, build_soccer_schedule.py, fetch_soccer_oddsapi_odds_local.py,
    # fetch_soccer_oddsapi_props_local.py, and build_soccer_picks.py all write directly
    # under soccer_source/<league>/api/ (or soccer_source/<league>/props/), so the generic
    # "*_source/..." patterns above never match soccer's files. Literal sport prefix, same
    # as the mlb_source/wnba_source/nhl_source eval/boxscore entries above.
    "soccer_source/*/api/recommendations/recommendations_*.json",
    "soccer_source/*/api/live_state/live_state_*.json",
    "soccer_source/*/api/display_prediction_dates.json",
    "soccer_source/*/api/schedule/schedule_*.json",
    # Raw bookmaker odds/props/picks (2026-07-24 market-board work): these
    # three were never allowlisted even though the refresh dispatcher has
    # scheduled fetch_soccer_oddsapi_odds_local.py/build_soccer_picks.py for a
    # while -- confirmed live in production that the fetch step runs to
    # completion (return_code=0) and presumably writes its file on whichever
    # service happened to run it, but the market board (served by web) never
    # saw a single row, because these three patterns were missing here and
    # the file never got published/pulled to web's disk.
    "soccer_source/*/api/odds/game_odds_current.csv",
    "soccer_source/*/props/*.csv",
    "soccer_source/*/api/picks/picks_*.csv",
    # CORRECTED 2026-08-08. This note used to read: "reports/intelligence/
    # board_snapshot.json and intelligence_state.json are intentionally excluded
    # here. They're written through refresh_state_store's write_json_file, which
    # already goes over the shared keyvalue (Redis) backend on Render, so all
    # three services see them without needing this HTTP push at all."
    #
    # BOTH HALVES ARE FALSE, and believing either one costs a board.
    #
    # `intelligence_state.json` IS in this list (see #43's entries above) and the
    # HTTP push is currently the ONLY way a rich board reaches web at all.
    #
    # And neither file fits the keyvalue store. Measured in production
    # 2026-08-08: intelligence_state 27,420,309 bytes and board_snapshot
    # 33,524,880 bytes, against an 8,388,608 ceiling -- rejected on every cycle.
    # `board_snapshot` is genuinely still excluded, but for the opposite reason
    # to the one stated: not because keyvalue carries it, but because web's only
    # reader of it (`read_json_file(BOARD_SNAPSHOT_PATH)`) consults the keyvalue
    # store and never looks at disk, so an entry here would push ~33.5MB every
    # cycle to a file nothing reads. Allowlisting PERMITS a transfer; it does not
    # make a reader. Add the entry with a disk-consulting read, not before.
    #
    # (It is also a near-duplicate: its `response` key is the whole state, and
    # its top-level `board_contract` is a second copy of the 6.54MB already
    # inside that -- so it carries nothing intelligence_state_<date>.json lacks.)
    #
    # #112: odds_history's per-shard payload is ALSO written through
    # write_json_file/the keyvalue backend by default -- but it can exceed the
    # 8MB keyvalue ceiling (confirmed live 2026-07-28, same class of failure
    # as #43's board_snapshot/intelligence_state), at which point
    # odds_refresh_tracking._sync_odds_history_for_refresh falls back to a
    # local-disk write + publish_hot_artifact via the #108 _write_state_payload
    # pattern. Two of the three paths it writes live under data_root() (the
    # third, reports/odds_control_plane/odds_history/, is outside data_root()
    # by construction and can't be matched by is_hot_artifact_relative_path --
    # that copy only ever reaches the SAME service's own disk, which is
    # sufficient for the refresh-worker's own next-cycle convergence but not
    # for cross-service reads). Without these two entries, publish_hot_artifact
    # would SKIP_NOT_ALLOWLISTED every fallback write and web would never see
    # an oversized shard no matter how many refresh cycles ran.
    "*_source/tracking/odds_history/*.json",
    "*_source/artifacts/*/odds_history/*.json",
    # #209: per-book quote log (syndicate/features/shared/odds_book_quotes.py).
    # Deliberately NOT a bookmaker dimension on the odds_history shards above --
    # that shard is already 54MB at 3,682 MLB keys and restoring ~5 books to its
    # 3,437 prop keys would push it toward 250MB, published every cycle on 2GB
    # services, while silently changing which book four existing single-book
    # consumers pick. This family carries the per-book truth (CLV, best-price
    # re-grade) and odds_history keeps its display-oriented single-book shape.
    # Written on live-odds-worker, read on web -- so like odds_history it needs
    # this entry to cross services at all, and unlike the #207 diagnostic it is
    # published explicitly by its own writer rather than relying on the
    # allowlist alone (allowlisting only PERMITS a push; something has to make
    # it).
    "*_source/tracking/book_quotes/*.jsonl",
    # The change log's SIDECAR, and without it the log is only half readable
    # across services. `append_book_quotes` writes rows only when (line, price)
    # CHANGES, and records "when did we last OBSERVE this market" in
    # `<date>.state.json` next to it. The `.jsonl` publishes; the sidecar did
    # not, so the service that reads quotes (refresh-worker, via
    # `pipeline/layer2_shortlist`) could never see last-seen data written by the
    # service that captures them (live-odds-worker). Different disks.
    #
    # Measured 2026-08-08 with the threading deployed and sweeps confirmed
    # running (MLB capture 21:38:09Z): `quote_seen_age_seconds` was None on
    # 112 of 112 board rows and `_freshness_factor` fell back to movement age,
    # scoring every row 0.25 -- the harshest discount -- for markets that had
    # simply not moved. The feature was live and inert.
    #
    # Cost, sized rather than assumed: 1.4MB per sport-date against the 13MB
    # `.jsonl` already published from this same directory -- roughly 10% more
    # on a path that already crosses. Deliberately narrow: this one filename
    # pattern in one already-allowlisted directory, not `tracking/**`.
    "*_source/tracking/book_quotes/*.state.json",
    # #124: the actual root cause of MLB live props reading zero everywhere
    # except web. syndicate/features/shared/live_lens_loop.py runs on
    # live-odds-worker (per its own header comment: "runs independently ...
    # in the same process (live-odds-worker)"), builds a real per-game
    # live-lens snapshot with populated liveProps/archivedLiveProps (a real
    # in-game Monte Carlo re-sim for MLB), writes it to
    # data_root()/live/{mlb,nba,wnba}_live_lens.json via write_json_file, and
    # then calls publish_changed_hot_artifacts EVERY TICK specifically to
    # push files like this one to web. None of these three paths were ever
    # in this allowlist, so that periodic push always skipped them
    # (SKIP_NOT_ALLOWLISTED) -- not a keyvalue-size failure like #43/#112,
    # just a plain missing entry. Every other service (web serving a direct
    # page request, refresh-worker's candidate-pool build) has no path to
    # this data at all and falls back to an independent, thinner recompute
    # (mlb/live_lens.py's build_live_lens_snapshot_internal) from the lighter
    # live_lens_report_*.json artifact alone, which structurally carries the
    # liveProps/archivedLiveProps keys but never actually populates them --
    # confirmed live: web's own direct recompute had real data (24/18/16
    # prop rows across 3 games), refresh-worker's had prop_row_counts=[0]*9
    # across all 9 real live games, unchanged even after fixing two other
    # once-daily artifact gaps in the same investigation. These paths are
    # NOT under a "*_source/..." prefix like everything else in this list --
    # data/live/ is its own top-level tree -- so the pattern has to be
    # written out per sport rather than reusing the generic prefix.
    "live/mlb_live_lens.json",
    "live/nba_live_lens.json",
    "live/wnba_live_lens.json",
    # The LOCKED CARD -- the day's actual recommendations, and the one input a
    # betting-day payload cannot be rebuilt without. `season_betting_day_*.json`
    # already crosses and names this file in its own `summary.card_path`, so the
    # payload has been referring to something no other service could open.
    #
    # WHY IT MATTERS NOW. The pregame game-line freeze was unreachable until
    # 2026-08-08, so the live game-lines file collapsed overnight to whatever
    # was still in progress and the payload builder dropped every game it could
    # no longer match -- 07-20 graded 1 of 14, 08-07 3 of 16. `book_quotes` can
    # rebuild the missing lines (it is append-only and kept them), but a rebuild
    # also needs the recommendations, and those live only here.
    #
    # DIAGNOSED THROUGH A MISREAD, recorded so the next person does not repeat
    # it: probing this path returned no content for EVERY date including one
    # with a known-good 10-game payload, which reads as "the cards are gone".
    # They are not -- `/api/ops/artifacts/stream` was returning **403 not
    # allowlisted**, and a check that collapses 403 onto 404 turns "I am not
    # permitted to look" into "it does not exist". Those have opposite fixes.
    #
    # Cost, measured not assumed: 7,115 bytes for a real card, and the sweep
    # only republishes files touched since its watermark, so this is ~7KB on the
    # day a card is written. Narrow on purpose, matching the sidecar entry
    # above: this one directory under `eval/seasons/*/`, not `eval/**`.
    "*_source/source_artifacts/data/eval/seasons/*/locked_cards_retuned/*.json",
)


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root()


def relative_to_data_root(path: Path) -> str | None:
    try:
        relative = Path(path).expanduser().resolve().relative_to(_data_root())
    except Exception:
        return None
    return str(relative).replace("\\", "/")


def is_hot_artifact_relative_path(relative_path: str) -> bool:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return False
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in HOT_ARTIFACT_PATTERNS)


# `#394`. relative_path -> sha256 of the content last successfully published
# from THIS process. Bounded by the artifact set, which is bounded by the
# allowlist, so it does not grow without limit.
_LAST_PUBLISHED_CHECKSUM: dict[str, str] = {}


# `#395` -- HOURLY EGRESS CIRCUIT BREAKER.
#
# `#394` stops re-uploading UNCHANGED artifacts. It does nothing for artifacts
# that genuinely change every cycle, and odds artifacts legitimately do. So the
# de-duplicator is not a spend ceiling and must not be mistaken for one.
#
# WHY A CEILING EXISTS AT ALL: on 2026-08-12 outbound bandwidth reached 1.62 TB
# for the month climbing ~7.8 GB/hr, and both workers had to be suspended by
# hand to stop it. There was no mechanism anywhere that could have stopped it
# automatically -- the publisher had no notion of how much it had sent.
#
# 2 GB/hour is a RUNAWAY BRAKE, not a tuned quota. It sits ~4x under the
# observed 7.8 GB/hr and well above anything a healthy sweep should need once
# `#394` removes the unchanged re-uploads. **It is deliberately loose**: a brake
# that trips in normal operation gets raised until it is meaningless, so this is
# sized to catch a runaway and nothing finer.
#
# IT ALSO SUPPLIES THE MEASUREMENT NOBODY HAD. Artifact SIZE was the missing
# term all day -- publish COUNTS were measurable and bytes were not, so "50/min"
# could not be turned into GB/hr without guessing an average. Every publish now
# adds to a rolling total that is logged, so the next person reasons from bytes.
#
# Rolling window, not a fixed hour: a calendar-hour reset lets a burst spend the
# whole budget at :59 and the whole budget again at :01.
_PUBLISH_BUDGET_WINDOW_SECONDS = 3600.0
_PUBLISH_BUDGET_DEFAULT_BYTES = 2 * 1024 * 1024 * 1024
_PUBLISH_BUDGET_LOG_EVERY = 25

# (epoch_seconds, bytes) for uploads inside the window. In-process, like
# `#394`'s checksum store, and cleared by a restart for the same reason: the
# safe direction is to allow work after a reboot, not to inherit a stale
# refusal that nothing can clear.
_PUBLISH_BYTES: list[tuple[float, int]] = []
_PUBLISH_BUDGET_COUNTER = [0]


def _publish_budget_max_bytes() -> int:
    raw = str(_env("SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET") or "").strip()
    if raw:
        try:
            value = int(float(raw))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return _PUBLISH_BUDGET_DEFAULT_BYTES


def _publish_budget_used_bytes() -> int:
    cutoff = time.time() - _PUBLISH_BUDGET_WINDOW_SECONDS
    while _PUBLISH_BYTES and _PUBLISH_BYTES[0][0] < cutoff:
        _PUBLISH_BYTES.pop(0)
    return sum(size for _, size in _PUBLISH_BYTES)


def _publish_budget_blocks(relative_path: str, size_bytes: int) -> bool:
    """True when sending `size_bytes` would break the hourly ceiling.

    Checked BEFORE the upload, so the breaker prevents the spend rather than
    reporting it afterwards.
    """
    ceiling = _publish_budget_max_bytes()
    used = _publish_budget_used_bytes()
    if used + max(0, int(size_bytes)) <= ceiling:
        return False
    print(
        f"[artifact_publisher] PUBLISH_BUDGET_EXCEEDED path={relative_path} "
        f"size_bytes={size_bytes} used_mb={used / 1024 / 1024:.1f} "
        f"ceiling_mb={ceiling / 1024 / 1024:.1f} window_s={int(_PUBLISH_BUDGET_WINDOW_SECONDS)} "
        f"-- REFUSING UPLOAD, set SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET to change",
        flush=True,
    )
    return True


def _publish_budget_record(size_bytes: int) -> None:
    _PUBLISH_BYTES.append((time.time(), max(0, int(size_bytes))))
    _PUBLISH_BUDGET_COUNTER[0] += 1
    if _PUBLISH_BUDGET_COUNTER[0] % _PUBLISH_BUDGET_LOG_EVERY == 0:
        used = _publish_budget_used_bytes()
        print(
            f"[artifact_publisher] PUBLISH_BUDGET uploads={len(_PUBLISH_BYTES)} "
            f"used_mb={used / 1024 / 1024:.1f} "
            f"ceiling_mb={_publish_budget_max_bytes() / 1024 / 1024:.1f}",
            flush=True,
        )


def _publish_url() -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    return base.rstrip("/") + "/api/ops/artifacts/publish"


def _admin_token() -> str:
    return _env("ADMIN_TOKEN") or _env("SYNDICATE_ADMIN_TOKEN")


def _hot_artifact_pull_watermark_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "refresh_status" / "latest" / "hot_artifact_pull_watermark.json"


# Hard ceiling on how far back a pull will ever reach.
#
# Without it this had two unbounded paths, and production hit both on
# 2026-07-25 (refresh-worker OOM crash loop + cascading web 502s):
#
# 1. No watermark meant "pull everything". Every deploy boots a worker with
#    no watermark, so every deploy pulled the entire artifact set at once.
#    That is the single OOM seen after each deploy that day.
# 2. The watermark only advances on a fully successful pull -- correct on its
#    own, but it means a FAILING pull leaves the window to grow forever. Each
#    failure makes the next attempt strictly heavier, so once the response
#    crossed what a 2GB container could parse, it could never get back under
#    it. That is a self-amplifying loop, not a transient.
#
# Both sides load the whole response in memory (the worker json.loads() it,
# the web service builds the dict to serve it), so window size translates
# directly into peak memory on two services at once.
#
# A bounded pull that succeeds beats an unbounded one that crashes: missing
# an artifact older than this window degrades one cycle, whereas the loop
# above pulls nothing at all and takes the worker down with it.
_MAX_PULL_WINDOW_SECONDS = 2 * 3600


def _hot_artifact_pull_since_epoch(*, pull_started_epoch: float) -> float | None:
    # Mirrors live_refresh_loop.py's _hot_artifact_publish_since_epoch on the
    # push side: floor = the start of the last successful pull, not each
    # call's own start time, so a slow or delayed cycle still catches
    # everything written since the last time this actually completed --
    # clamped to _MAX_PULL_WINDOW_SECONDS so neither a missing watermark nor
    # a stalled one can turn this into an unbounded fetch.
    from syndicate.features.shared.refresh_state_store import read_json_file

    payload = read_json_file(_hot_artifact_pull_watermark_path())
    try:
        stored = float(payload.get("epoch")) if isinstance(payload, dict) and payload.get("epoch") is not None else None
    except (TypeError, ValueError):
        stored = None
    window_floor = float(pull_started_epoch) - _MAX_PULL_WINDOW_SECONDS
    if stored is None or stored <= 0.0:
        return window_floor
    return max(stored, window_floor)


def _record_hot_artifact_pull_watermark(epoch: float) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    try:
        write_json_file(_hot_artifact_pull_watermark_path(), {"epoch": epoch})
    except Exception:
        # Must never raise (module-wide constraint) -- worst case, the next
        # pull just doesn't advance the watermark and re-fetches everything.
        pass


# Above this, publish the file as a raw streamed body rather than a JSON
# envelope.
#
# THE COST THIS REMOVES, which #29746931 diagnosed correctly and then did not
# fix. `publish_hot_artifact` holds FOUR full copies of every file at once:
# read_text (str) -> .encode() for the checksum (bytes) -> json.dumps (str) ->
# .encode() (bytes). That commit bounded which files the SWEEP selects, by slate
# age and by 12MB of size. It did not touch the mechanism, and it does not apply
# to `publish_hot_artifact`'s DIRECT callers at all -- the #43 board-state
# fallback, #112's odds_history fallback, and #124's live-lens loop all call it
# straight and are bounded by nothing.
#
# So the four-copy path is not hypothetical and not historical: it is what
# carries today's board state. Measured 2026-08-08, refresh-worker published
# `intelligence_state_2026_08_08.json` at 27,420,309 bytes -- and web receives it
# by json.loads-ing that whole body on a 2Gi instance that had 675MB of headroom
# at the time. odds_history shards reach 51MB on a real MLB slate.
#
# 4MB: comfortably above the ordinary artifact (kilobytes) so the common path
# keeps the proven JSON envelope, and comfortably below anything that has ever
# caused a problem here.
_PUBLISH_STREAM_MIN_BYTES = 4 * 1024 * 1024

_PUBLISH_STREAM_CHUNK_BYTES = 1024 * 1024

# Status codes that mean "this receiver predates the streaming form", as opposed
# to a real refusal. 403 is deliberately NOT here: that is the allowlist saying
# no, and retrying the same file as JSON would only be refused again.
_PUBLISH_STREAM_UNSUPPORTED_STATUSES = frozenset({400, 404, 405, 415})


def _should_stream_publish(file_path: Path) -> bool:
    try:
        return file_path.stat().st_size >= _PUBLISH_STREAM_MIN_BYTES
    except OSError:
        return False


def _file_checksum(file_path: Path) -> str:
    """sha256 of the file, one chunk resident at a time."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(_PUBLISH_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _publish_streamed(
    file_path: Path,
    *,
    relative_path: str,
    url: str,
    token: str,
    timeout_seconds: int,
) -> bool | None:
    """Publish by streaming the file's bytes. True/False on a real outcome,
    None when the receiver does not support this form and the caller should
    fall back.

    The metadata rides in headers precisely so the body can stay raw: the
    moment relative_path and checksum live *inside* the body, the body has to
    be built in memory, which is the cost being removed. urllib sends a
    file-like `data` in blocks when Content-Length is set, so the sender never
    holds more than one block.
    """
    try:
        size = file_path.stat().st_size
        checksum = _file_checksum(file_path)
    except OSError as exc:
        print(f"[artifact_publisher] SKIP_READ_FAILED path={file_path} error={exc}", flush=True)
        return False

    # `#394`/`#395` on the streamed path too. This is the path LARGE artifacts
    # take, so leaving it unguarded would exempt exactly the uploads that cost
    # the most -- the failure mode where a guard exists and the expensive case
    # routes around it.
    if _LAST_PUBLISHED_CHECKSUM.get(relative_path) == checksum:
        print(
            f"[artifact_publisher] PUBLISH_SKIPPED_UNCHANGED path={relative_path} "
            f"checksum={checksum[:12]} transport=stream",
            flush=True,
        )
        return True
    if _publish_budget_blocks(relative_path, size):
        return False

    try:
        with file_path.open("rb") as handle:
            request_obj = urllib_request.Request(
                url,
                data=handle,
                method="POST",
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                    "X-Artifact-Path": relative_path,
                    "X-Artifact-Checksum": checksum,
                    "Authorization": f"Bearer {token}",
                },
            )
            with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
                response.read()
        # Recorded only after the upload is acknowledged, same rule as the JSON
        # path: a failed publish must retry next sweep, not be suppressed by its
        # own attempt.
        _LAST_PUBLISHED_CHECKSUM[relative_path] = checksum
        _publish_budget_record(size)
        print(
            f"[artifact_publisher] PUBLISH_OK path={relative_path} url={url} transport=stream bytes={size}",
            flush=True,
        )
        return True
    except urllib_error.HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) in _PUBLISH_STREAM_UNSUPPORTED_STATUSES:
            print(
                f"[artifact_publisher] PUBLISH_STREAM_UNSUPPORTED path={relative_path} "
                f"status={exc.code} falling_back_to_json bytes={size}",
                flush=True,
            )
            return None
        print(
            f"[artifact_publisher] PUBLISH_FAILED path={relative_path} url={url} transport=stream error={exc}",
            flush=True,
        )
        return False
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(
            f"[artifact_publisher] PUBLISH_FAILED path={relative_path} url={url} transport=stream error={exc}",
            flush=True,
        )
        return False
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[artifact_publisher] PUBLISH_UNEXPECTED_ERROR path={relative_path} url={url} transport=stream error={exc}",
            flush=True,
        )
        return False


def publish_hot_artifact(path: Path, *, timeout_seconds: int = 10) -> bool:
    """Best-effort push of a single allowlisted artifact to the web service.

    Returns False (and never raises) on any condition that prevents publishing:
    not configured, not an allowlisted path, file missing, or a network error.
    """
    url = _publish_url()
    token = _admin_token()
    if not url or not token:
        print(f"[artifact_publisher] SKIP_NOT_CONFIGURED path={path} url_set={bool(url)} token_set={bool(token)}", flush=True)
        return False

    relative_path = relative_to_data_root(Path(path))
    if not relative_path or not is_hot_artifact_relative_path(relative_path):
        print(f"[artifact_publisher] SKIP_NOT_ALLOWLISTED path={path} relative_path={relative_path}", flush=True)
        return False

    file_path = Path(path)

    # Big files go up as a raw streamed body instead of a JSON envelope. See
    # _PUBLISH_STREAM_MIN_BYTES for the measurement and the reasoning; below the
    # threshold nothing changes, because the four-copy cost of a kilobyte file
    # is four kilobytes and the JSON envelope is the proven path.
    if _should_stream_publish(file_path):
        streamed = _publish_streamed(
            file_path,
            relative_path=relative_path,
            url=url,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        if streamed is not None:
            return streamed
        # None means the receiver does not understand the streaming form (an
        # older web deploy). Fall through to the JSON envelope, which every
        # deploy understands. This is what makes the change safe in either
        # deploy order, including live-odds-worker being deliberately pinned.

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[artifact_publisher] SKIP_READ_FAILED path={file_path} error={exc}", flush=True)
        return False

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # `#394` -- DO NOT RE-UPLOAD AN ARTIFACT WHOSE CONTENT HAS NOT CHANGED.
    #
    # The checksum above was already computed and already SENT, and nothing ever
    # compared it to anything. So every hot artifact was re-uploaded in full on
    # every sweep whether or not a byte had moved.
    #
    # Measured 2026-08-12 before this: refresh-worker and live-odds-worker each
    # published ~30-60 files/minute continuously, all day, in every window
    # sampled from 09:00Z onward (`hasMore=True` on all of them, so those are
    # floors). Outbound bandwidth 1.62 TB for the month and climbing ~7.8 GB/hr.
    # Both workers were suspended to stop it.
    #
    # IN-PROCESS ON PURPOSE. A restart clears this and the next sweep republishes
    # everything once, which is the correct failure direction: the risk of a
    # persisted cache is claiming something is published when the remote lost it,
    # and re-uploading a whole slate once per boot is cheap next to doing it every
    # minute forever. It is a de-duplicator, not a publish ledger.
    previous = _LAST_PUBLISHED_CHECKSUM.get(relative_path)
    if previous == checksum:
        print(
            f"[artifact_publisher] PUBLISH_SKIPPED_UNCHANGED path={relative_path} "
            f"checksum={checksum[:12]}",
            flush=True,
        )
        return True

    body = json.dumps(
        {"relative_path": relative_path, "content": content, "checksum": checksum}
    ).encode("utf-8")

    # `#395`: measured on the ACTUAL request body, not the file on disk -- the
    # JSON wrapper is what crosses the wire and is what the bill counts.
    if _publish_budget_blocks(relative_path, len(body)):
        return False

    request_obj = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            response.read()
        # Recorded only after the upload is acknowledged -- a failed publish must
        # be retried next sweep, not suppressed by its own attempt.
        _LAST_PUBLISHED_CHECKSUM[relative_path] = checksum
        _publish_budget_record(len(body))
        print(
            f"[artifact_publisher] PUBLISH_OK path={relative_path} url={url} bytes={len(body)}",
            flush=True,
        )
        return True
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] PUBLISH_FAILED path={relative_path} url={url} error={exc}", flush=True)
        return False
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] PUBLISH_UNEXPECTED_ERROR path={relative_path} url={url} error={exc}", flush=True)
        return False


def publish_hot_artifacts(paths: Any) -> int:
    """Publish an iterable of paths, returning the count that succeeded."""
    published = 0
    for path in paths or ():
        if publish_hot_artifact(path):
            published += 1
    return published


class HotArtifactSweepResult(NamedTuple):
    """Outcome of a publish_hot_artifacts_since sweep.

    publish_hot_artifact never raises -- a network blip or a momentarily
    unreachable web service just returns False and is logged, not thrown.
    That means a bare published-count return can't tell a caller "every
    candidate in this window went through" from "some silently failed" --
    a caller that advances a persisted watermark on any non-raising return
    would permanently skip a file that failed for a transient reason, the
    exact same class of "async output missing on web forever" bug this was
    built to prevent in the first place. all_succeeded lets watermark-based
    callers only advance past a window once every candidate in it is
    confirmed published, so a real failure retries on the next sweep
    instead of vanishing.
    """

    published_count: int
    failed_paths: tuple[Path, ...]

    @property
    def all_succeeded(self) -> bool:
        return not self.failed_paths


# Only TODAY's slate is hot. Everything older is an archive and belongs on disk,
# not on the wire every cycle.
#
# THE BUG THIS FIXES, measured 2026-08-08: the sweep selected purely on mtime, so
# any file the artifact PULL rewrote looked "changed" and was republished --
# regardless of the slate it described. live-odds-worker was republishing
# `oddsapi_player_props_2026-05-25.csv`, `game_cards_2026-05-26.csv` and
# `smart_sim_2026-05-27_*.json` -- MAY artifacts, two and a half months dead --
# on every boot. Web then wrote them, which moved their mtime again, so the next
# sweep picked them up once more: a publish/pull ping-pong over an archive.
#
# That is what killed the service. `publish_hot_artifact` holds FOUR full copies
# of each file at once (read_text -> encode for checksum -> json.dumps ->
# encode), so a 51MB odds-history shard is ~200MB resident, and both the sender
# (2Gi) and the receiver (web, also 2Gi, which parses the body whole) were dying
# on it. One root cause, two OOMing services.
#
# 1 = today and yesterday, because a slate crosses UTC midnight and last night's
# finals still settle this morning.
_PUBLISH_MAX_AGE_DAYS = 1

# Belt and braces, and independent of the date rule: an UNDATED file cannot be
# aged out, and `boxscores_history.csv` is exactly that shape. Sized well above a
# normal artifact and well under what four copies of it would cost on 2Gi.
#
# DELIBERATELY NOT RAISED when the streamed transport landed, even though the
# "four copies on 2Gi" half of its justification no longer applies to files this
# large. The other half still does: this bound is what stops the SWEEP shipping
# bulk artifacts (51MB odds_history shards) on every cycle, and that cost is
# bandwidth, disk churn and receiver time, not just sender memory. Making the
# transport cheap is not a reason to start moving more through it -- that would
# be the #29746931 ping-pong again, wearing a performance fix's clothes. Raise
# it only with a measured reason and its own verification.
_PUBLISH_MAX_BYTES = 12 * 1024 * 1024

_DATE_TOKEN = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")


def _artifact_date(path: Path) -> date | None:
    """The slate a file describes, from its name. None when it carries no date.

    Undated files (`current_week.json`, `boxscores_history.csv`) are NEVER aged
    out on this rule -- there is nothing to judge them against, and silently
    dropping them would be a coverage bug wearing a memory fix's clothes.
    """
    match = _DATE_TOKEN.search(path.name)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _publish_skip_reason(path: Path, today: date) -> str | None:
    """Why this file must not be published, or None to publish it."""
    artifact_date = _artifact_date(path)
    if artifact_date is not None and (today - artifact_date).days > _PUBLISH_MAX_AGE_DAYS:
        return f"stale_slate:{artifact_date.isoformat()}"
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > _PUBLISH_MAX_BYTES:
        return f"too_large:{size}"
    return None


def sweep_changed_hot_artifacts(since_epoch_seconds: float) -> HotArtifactSweepResult:
    """Sweep the allowlisted hot-artifact locations under the data root and publish
    any file modified at or after ``since_epoch_seconds``.

    Used after a refresh tick that runs per-sport work in a detached subprocess,
    where we can't easily hook every downstream write site directly.
    """
    if not _publish_url() or not _admin_token():
        return HotArtifactSweepResult(published_count=0, failed_paths=())
    root = _data_root()
    published = 0
    failed: list[Path] = []
    today = date.today()
    skipped: dict[str, int] = {}
    for pattern in HOT_ARTIFACT_PATTERNS:
        for candidate in root.glob(pattern):
            try:
                if not candidate.is_file() or candidate.stat().st_mtime < since_epoch_seconds:
                    continue
            except OSError:
                continue
            reason = _publish_skip_reason(candidate, today)
            if reason is not None:
                # Counted and logged, never silent: a sweep that quietly stops
                # publishing a whole class of artifact is indistinguishable from
                # one that has nothing to publish.
                skipped[reason.split(":", 1)[0]] = skipped.get(reason.split(":", 1)[0], 0) + 1
                continue
            if publish_hot_artifact(candidate):
                published += 1
            else:
                failed.append(candidate)
    if skipped:
        print(f"[artifact_publisher] SWEEP_SKIPPED {skipped}", flush=True)
    return HotArtifactSweepResult(published_count=published, failed_paths=tuple(failed))


def publish_changed_hot_artifacts(since_epoch_seconds: float) -> int:
    """Back-compat wrapper over sweep_changed_hot_artifacts for callers that
    only care about the published count, not per-file success (e.g. callers
    that publish synchronously right after their own subprocess finishes,
    where there's no persisted watermark to protect against advancing past
    a failed file -- see run_mlb_daily_sim_job.py / run_queued_refresh_job.py).
    """
    return sweep_changed_hot_artifacts(since_epoch_seconds).published_count


def _export_url(pattern: str | None = None, *, since_epoch: float | None = None, exact_path: str | None = None) -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    url = base.rstrip("/") + "/api/ops/artifacts/export"
    params: list[str] = []
    if exact_path:
        from urllib.parse import quote

        # ?path= is the endpoint's single-artifact form: it skips the glob
        # entirely and returns one file, so a repair fetch costs one stat and
        # one read rather than a scan of the matched set.
        params.append(f"path={quote(exact_path, safe='')}")
    elif pattern:
        from urllib.parse import quote

        params.append(f"pattern={quote(pattern, safe='')}")
    if since_epoch is not None:
        params.append(f"since={since_epoch}")
    if params:
        url += "?" + "&".join(params)
    return url


def _pull_hot_artifacts_request(url: str, token: str, *, timeout_seconds: int) -> tuple[bool, int]:
    """Returns (succeeded, files_written). succeeded distinguishes a genuine
    request failure from a successful-but-empty response (e.g. nothing
    changed since the caller's own watermark) -- pull_hot_artifacts only
    advances its persisted watermark when every sub-request succeeded, so a
    transient network blip doesn't permanently skip files modified during
    the failed window.
    """
    request_obj = urllib_request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] PULL_FAILED url={url} error={exc}", flush=True)
        return False, 0
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] PULL_UNEXPECTED_ERROR url={url} error={exc}", flush=True)
        return False, 0

    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, dict):
        print(f"[artifact_publisher] PULL_EMPTY_RESPONSE url={url}", flush=True)
        return False, 0

    root = _data_root()
    written = 0
    for relative_path, content in artifacts.items():
        normalized = str(relative_path or "").strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            continue
        if not is_hot_artifact_relative_path(normalized):
            continue
        target_path = root / Path(normalized)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Keyed by pid alone, this collided whenever two pulls for the
            # same artifact ran concurrently in the same process (the
            # intelligence_state background loop's periodic tick and an
            # on-demand request both bypassing the cache around the same
            # moment, e.g.) -- both computed the identical temp_path, the
            # first os.replace() consumed it, and the second's os.replace()
            # then failed with ENOENT ('src' -> 'dst', the exact shape seen
            # in production PULL_WRITE_FAILED errors for soccer's MLS
            # recommendations/live_state artifacts). A uuid4 suffix makes
            # every write's temp file unique regardless of what's calling
            # concurrently, without needing to know why.
            temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.pull.tmp"
            temp_path.write_text(str(content), encoding="utf-8")
            os.replace(temp_path, target_path)
            written += 1
        except Exception as exc:
            print(f"[artifact_publisher] PULL_WRITE_FAILED path={normalized} error={exc}", flush=True)
            # temp_path is only ever unique to this one write attempt (see
            # above), so if it still exists here the failure happened after
            # it was written but before/during os.replace() -- clean it up
            # rather than leaving it orphaned on disk forever.
            try:
                if "temp_path" in locals() and temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            continue

    print(f"[artifact_publisher] PULL_OK url={url} artifacts_received={len(artifacts)} written={written}", flush=True)
    return True, written


def pull_hot_artifacts(*, date_str: str | None = None, timeout_seconds: int = 30) -> int:
    """Best-effort pull of hot artifacts from the web service's disk onto
    this process's own disk.

    2026-07-20: refresh-worker's board-computation loop reads sport artifacts
    (recommendations_slate, props_recommendations, game_cards, etc.) from its
    own Render disk, which is a separate physical disk from the one
    live-odds-worker (or an on-demand web request) actually writes them to --
    Render disks are per-service, not shared, and publish_hot_artifact/
    sweep_changed_hot_artifacts above only ever push worker -> web. Confirmed
    in production: refresh-worker computed a genuinely empty candidate pool
    for hours (repeated "Missing WNBA artifact" errors reading its own local
    disk) while the identical computation, run against the web service's
    disk, produced real candidates. This is the missing other direction: web
    -> refresh-worker, pulled (refresh-worker doesn't run an HTTP server, so
    it can't receive a push). Never raises -- a network blip here should
    degrade to stale local data, not break board computation.

    date_str scopes the request to today's ?pattern=*<date>* instead of the
    full combined hot-artifact set: an unfiltered call reproducibly hit
    Render's proxy timeout (502) in production once enough sports/days had
    accumulated hot artifacts -- this module's own docstring calls the
    allowlist "small", but small-per-file times many files times many days
    is not small in aggregate. Almost every hot artifact is date-suffixed
    (recommendations/props/game_cards/sims/snapshots), so this still covers
    the files board computation actually needs; a handful of non-dated
    files (current_week.json, park_factors.json, etc.) are out of scope for
    this per-cycle pull and would need a separate, infrequent full sync.

    2026-07-20: a plain f"*{date_str}*" (date_str = ISO "YYYY-MM-DD") only
    matched hyphen-separated filenames (WNBA's
    recommendations_slate_2026-07-20.json) and silently missed
    underscore-separated ones (MLB's live_lens_report_2026_07_20.json,
    season_betting_day_2026_07_20.json) -- confirmed in production: MLB's
    candidate_generation stayed at 0 on every cycle, with artifact_status
    showing artifact_exists=false, while WNBA worked fine, because MLB's
    required artifacts were never being pulled at all.

    A single combined bracket-expression pattern (matching either
    separator in one request) was tried first and also 502'd in
    production -- matching both separators at once roughly doubles the
    combined WNBA+MLB result set, and that larger payload hit the exact
    same Render proxy timeout this date-scoping was already built to
    avoid. Two separate, smaller requests (one per format) each stay
    close to the original per-request size that was already confirmed
    safe, and a failure on one doesn't cost the other.

    2026-07-24: every call re-fetched full content for every matching file,
    every ~30s (this function's only caller ticks on that interval) --
    confirmed as the dominant contributor to two 8.6MB/28.9MB responses
    every cycle once odds-history-driven artifact growth made the matched
    set large, which itself fed sustained near-ceiling memory on a 2GB web
    instance. Now passes a persisted since= watermark (floor = the start of
    the last successful pull) so the export endpoint only returns files
    modified since then; the watermark only advances when every sub-request
    for this call succeeds, so a partial failure re-fetches that same
    window next time instead of silently skipping it.
    """
    token = _admin_token()
    if not token or not _env("SYNDICATE_WEB_PUBLISH_URL"):
        print(f"[artifact_publisher] PULL_SKIP_NOT_CONFIGURED url_set={bool(_env('SYNDICATE_WEB_PUBLISH_URL'))} token_set={bool(token)}", flush=True)
        return 0
    pull_started_epoch = time.time()
    since_epoch = _hot_artifact_pull_since_epoch(pull_started_epoch=pull_started_epoch)
    if not date_str:
        succeeded, written = _pull_hot_artifacts_request(_export_url(None, since_epoch=since_epoch), token, timeout_seconds=timeout_seconds)
        if succeeded:
            _record_hot_artifact_pull_watermark(pull_started_epoch)
        return written
    written = 0
    all_succeeded = True
    for pattern in _date_glob_patterns(date_str):
        succeeded, sub_written = _pull_hot_artifacts_request(_export_url(pattern, since_epoch=since_epoch), token, timeout_seconds=timeout_seconds)
        written += sub_written
        all_succeeded = all_succeeded and succeeded
    if all_succeeded:
        _record_hot_artifact_pull_watermark(pull_started_epoch)
    # Repair pass, AFTER the watermark is recorded and deliberately not part of
    # all_succeeded. It fetches only artifacts this worker is missing outright,
    # one exact ?path= request each and no since= filter, so it is the one
    # thing the incremental pull structurally cannot do for itself. Costs
    # nothing on a healthy worker: the list is empty once the files exist, so
    # no request is made at all. If web is missing them too it retries each
    # cycle -- one small request, and the log line says so rather than
    # pretending the board is merely quiet.
    for relative_path in _missing_required_artifact_relative_paths(date_str):
        # #233: STREAM the big ones. /export loads the whole artifact into the
        # web service's memory to answer, and book_quotes shards are 52MB
        # (measured 2026-08-06, MLB) -- every repair request for one came back
        # PULL_FAILED / written=0 against a 2GB web instance, so the file the
        # Layer 2 board's prices depend on could be correctly requested and
        # still never arrive.
        #
        # pull_streamed_artifact already exists for exactly this and reads in
        # 1MB chunks ("a 51MB shard is ~51 reads", per its own note). Routing
        # the known-large families through it makes the repair pass able to
        # deliver them at all; everything else keeps /export, which is fine for
        # the small once-a-day artifacts this list was originally built for.
        if "/book_quotes/" in relative_path or "/odds_history/" in relative_path:
            repair_succeeded, repair_written = pull_streamed_artifact(
                relative_path, timeout_seconds=max(timeout_seconds, 300)
            )
        else:
            repair_succeeded, repair_written = _pull_hot_artifacts_request(
                _export_url(exact_path=relative_path), token, timeout_seconds=timeout_seconds
            )
        written += repair_written
        print(
            f"[artifact_publisher] PULL_REPAIR_MISSING path={relative_path} "
            f"ok={repair_succeeded} written={repair_written}",
            flush=True,
        )
    # #124: the live-lens snapshots (data/live/{mlb,nba,wnba}_live_lens.json,
    # now allowlisted above) are continuously rewritten -- every ~60s while
    # games are live -- but carry no date in their filename at all, so
    # _date_glob_patterns' *2026-07-28*/*2026_07_28* patterns can NEVER match
    # them; the incremental, date-scoped pull above structurally cannot ever
    # request them, regardless of watermark freshness. The missing-artifact
    # repair pass above doesn't fit either: it only fires once, the first
    # time a path is absent, and then skips forever once ANY copy exists
    # locally -- exactly wrong for a file that needs to be fresh every
    # cycle, not merely present once. So these three are fetched
    # unconditionally, every cycle, via the same cheap single-file ?path=
    # form (one stat, one read, no since=/pattern= glob over anything else).
    # Confirmed this is where the actual live MLB prop data lives: web's own
    # direct-request recompute has real liveProps (24/18/16 rows across 3
    # live games), while every other service's independent recompute from
    # the lighter, dated live_lens_report_*.json alone produces the
    # liveProps/archivedLiveProps keys with zero rows in them.
    for relative_path in ("live/mlb_live_lens.json", "live/nba_live_lens.json", "live/wnba_live_lens.json"):
        live_lens_succeeded, live_lens_written = _pull_hot_artifacts_request(
            _export_url(exact_path=relative_path), token, timeout_seconds=timeout_seconds
        )
        written += live_lens_written
        print(
            f"[artifact_publisher] PULL_LIVE_LENS_SNAPSHOT path={relative_path} "
            f"ok={live_lens_succeeded} written={live_lens_written}",
            flush=True,
        )
    return written


def _required_daily_artifact_paths(date_str: str) -> list[Path]:
    """Absolute paths to board-critical artifacts that are written ONCE a day.

    #68. The incremental pull can repair a copy that is OLDER than web's; it
    can never repair one that is MISSING, because `since=` filters on web's
    mtime and a once-a-morning artifact stops being newer than the watermark
    within minutes. That is fine for the continuously-rewritten artifacts this
    module was designed around, and permanently wrong for these.

    Kept as an explicit, tiny list rather than derived from
    _artifact_specs_for_sport: that lives in syndicate.features.intelligence,
    which imports most of the app, and this module is called from the pull
    path on every cycle.
    """
    paths: list[Path] = []
    try:
        from syndicate.features.mlb.sources import season_betting_card_day_path

        season = int(str(date_str).strip()[:4])
        paths.append(season_betting_card_day_path(season, str(date_str).strip()))
    except Exception:
        # Must never raise -- a repair that cannot be computed just means the
        # normal incremental pull is all this cycle gets.
        pass
    try:
        # 2026-07-28: the exact same "written once, permanently un-repairable"
        # gap as season_betting_card_day_path above, confirmed live for MLB
        # props specifically absent from the board. daily_top_props is
        # generated once (or a few times) per day by the vendored daily
        # pipeline, IS allowlisted (HOT_ARTIFACT_PATTERNS), and web's own
        # disk had it fully populated (307 pitcher + hitter rows, verified
        # live) -- but refresh-worker's incremental since= pull can only
        # repair a copy OLDER than web's, never one that never arrived, and
        # this file was never in the explicit repair list that exists
        # specifically to cover that case. home.py's
        # _load_mlb_home_top_prop_items (the sole source of MLB pregame
        # props for candidate generation, via _MLBDataProvider.pregame_props)
        # reads exactly this path, so a permanently-missing copy on
        # refresh-worker means zero MLB pregame prop candidates every cycle,
        # regardless of anything downstream (filter_candidates, freshness
        # gates) -- confirmed live: MLB prop rejections in filter_candidates
        # were exactly zero, meaning props never reached it at all.
        from syndicate.features.mlb.sources import daily_top_props_path

        paths.append(daily_top_props_path(str(date_str).strip()))
    except Exception:
        pass
    try:
        # Same class of gap again, found chasing MLB LIVE props specifically
        # (pregame props were fixed by daily_top_props above and confirmed
        # live: pregame_count 0 -> 18/28). Live props stayed at zero even
        # after that fix, with a diagnostic confirming _MLBDataProvider.
        # live_props independently finds real prop-backed live games
        # (prop_backed_games=9) but every one of them has an EMPTY
        # liveProps/archivedLiveProps list (prop_row_counts=[0]*9) --
        # structurally present, no actual rows. Traced to
        # _cards_recommendation_payload_by_game (mlb/cards.py), which merges
        # betting_games (season_betting_card_day_path, already required
        # above) with recos_by_game built from THIS file
        # (daily_artifact_path(date, "_locked_policy") ->
        # daily_summary_<date>_locked_policy.json) to populate
        # markets.{pitcher,hitter,extraPitcher,extraHitter}Props, which is
        # exactly what _live_props_from_card (live_lens.py) reads to build
        # each live game's liveProps. It matches the allowlist's existing
        # "daily_summary_*.json" glob (so incremental pulls DO carry it when
        # fresh), but like season_betting_card_day_path and daily_top_props
        # it is generated once per slate and can go permanently missing on a
        # worker that booted, or had its disk reset, after the since=
        # watermark first advanced past it.
        from syndicate.features.mlb.sources import daily_artifact_path

        paths.append(daily_artifact_path(str(date_str).strip(), suffix="_locked_policy"))
    except Exception:
        pass
    try:
        # #128: the base daily_summary_<date>.json (no suffix) is a DIFFERENT
        # file from the _locked_policy one just above -- build_cards_page_context
        # (mlb/cards.py) loads it separately as `summary_path`/`summary` for its
        # own `outputs`/game_pks list AND to decide its own source_title
        # ("MLB cards unavailable" whenever `summary` is falsy). Missing from
        # this list entirely until now: confirmed live on live-odds-worker,
        # after the _locked_policy repair above landed and ran, cards still
        # reported source_title "MLB cards unavailable" and zero props --
        # this is the file that check actually gates on.
        from syndicate.features.mlb.sources import daily_artifact_path

        paths.append(daily_artifact_path(str(date_str).strip()))
    except Exception:
        pass
    try:
        # Same "written once, permanently un-repairable if never pulled"
        # class of gap as the four MLB entries above, confirmed to exist in
        # principle (not yet observed in production) for WNBA during a
        # 2026-07-29 cross-sport comparison after MLB's own version of this
        # bug was fixed. recommendations_slate_<date>.json is WNBA's sole
        # pregame-props source (syndicate.features.wnba.picks._summary_for_date,
        # the only reader _WNBADataProvider.pregame_props -> home_rails.pregame
        # ultimately depends on) -- the normal incremental pull DOES cover a
        # stale copy (HOT_ARTIFACT_PATTERNS already globs recommendations*.json),
        # but not one that never arrived at all after the since= watermark
        # advanced past it, e.g. a worker that booted or had its disk reset
        # post-watermark. processed_path_or_default never raises (returns a
        # plain path even when the file doesn't exist yet), matching this
        # function's own "must never raise" contract without needing the
        # try/except below to do that work.
        from syndicate.features.wnba.sources import processed_path_or_default as _wnba_processed_path_or_default

        selected = str(date_str).strip()
        paths.append(_wnba_processed_path_or_default(f"recommendations_slate_{selected}.json"))
        paths.append(_wnba_processed_path_or_default(f"props_recommendations_{selected}.csv"))
    except Exception:
        pass
    try:
        # Same class of gap again, found chasing why soccer's steam-move
        # board candidates couldn't resolve a real matchup: confirmed live
        # 2026-07-29 that refresh-worker's own overview build reported
        # dashboard_games_count=0 for soccer on every cycle (both today and
        # tomorrow), while web's own /soccer/mls/api/cards correctly showed
        # 16 real games -- refresh-worker never had a usable copy of the
        # per-league season schedule at all. schedule_<season>.json is a
        # once-a-season artifact (week_matches/schedule_payload,
        # syndicate/features/soccer/sources.py), already allowlisted for
        # the normal incremental pull ("soccer_source/*/api/schedule/
        # schedule_*.json" in HOT_ARTIFACT_PATTERNS above), but a
        # since=-scoped pull can never repair a copy that never arrived in
        # the first place -- same shape as every entry above. Scoped to
        # only the leagues actually in season for this date (soccer tracks
        # 10 leagues; most of the year only 1-3 are active), so this stays
        # a handful of small requests, not ten.
        from syndicate.features.soccer.sources import active_leagues_for_date
        from syndicate.features.soccer.sources import default_season
        from syndicate.features.soccer.sources import schedule_path

        selected = str(date_str).strip()
        for league in active_leagues_for_date(selected):
            try:
                paths.append(schedule_path(league, default_season(league)))
            except Exception:
                continue
    except Exception:
        pass
    try:
        # #232: the per-book quote log, for every sport that keeps one.
        #
        # This is the file the Layer 2 board's price context is built from, and
        # it had NEVER reached refresh-worker -- zero book_quotes log lines
        # there, ever, while web's copy was fine. The board consequently served
        # 138 candidates with a canonical market_key and not one price.
        #
        # It was assumed to self-heal because it IS allowlisted and DOES match
        # the `*<date>*` incremental glob. Both are true and it still never
        # arrived: the incremental pull filters on `since=`, and a 502 on that
        # path holds the watermark back, so a file that is missing outright can
        # stay missing indefinitely. That is exactly the gap this repair list
        # exists for -- an exact `?path=` request with no `since=` filter -- and
        # book_quotes simply was not on it. Costs nothing once the file exists,
        # because _missing_required_artifact_relative_paths only asks for
        # artifacts this service does not already have.
        from syndicate.features.shared.odds_book_quotes import book_quotes_path

        selected = str(date_str).strip()
        for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
            try:
                paths.append(book_quotes_path(sport, selected))
            except Exception:
                continue
        # #239: soccer alone shards by each FIXTURE's date, not by the slate
        # date. `_append_soccer_prop_book_quotes` buckets rows by
        # `commence_time[:10]` before writing, so asking only for today gets a
        # 404 forever while the quotes sit in tomorrow's file. Verified on
        # production 2026-08-06: soccer/2026-08-06 was absent while 08-07
        # (120,637 B), 08-08 (533,825), 08-09 (483,682) and 08-10 (23,318) all
        # existed on web and had never been pulled -- which is the whole reason
        # soccer rows on the board carried no price.
        #
        # Soccer only, because it is the only writer that does this; every other
        # sport writes to the slate date and a forward window for them would be
        # 404s every cycle for nothing.
        for offset in range(1, _SOCCER_FIXTURE_LOOKAHEAD_DAYS + 1):
            try:
                future = (date.fromisoformat(selected) + timedelta(days=offset)).isoformat()
                paths.append(book_quotes_path("soccer", future))
            except Exception:
                continue
    except Exception:
        pass
    return paths


# How far ahead to fetch soccer's fixture-dated quote shards (#239). Kept
# through the #237/#241 revert: it only widens which paths the EXISTING
# presence-based repair pass asks for, and adds no periodic work.
_SOCCER_FIXTURE_LOOKAHEAD_DAYS = 7


_SOURCE_TREE_MARKER = re.compile(r"(?:^|/)([a-z0-9]+_source/.*)$")


def _relative_under_data_root(path: Path, root: Path) -> str | None:
    """This artifact's path RELATIVE TO THE RUNTIME DATA ROOT, wherever the
    caller's helper happened to resolve it.

    THE BUG THIS FIXES, measured 2026-08-08. Some per-sport path helpers resolve
    through `preferred_source_roots(...)`, which appends the REPO checkout as a
    cold-start fallback. `schedule_path('mls', 2026)` therefore returns the
    repo's copy, not the runtime disk's:

        SYNDICATE_DATA_ROOT = <empty temp dir>
        schedule_path       -> <repo>/data/soccer_source/mls/api/schedule/schedule_2026.json
        is_file()           -> True          <- the git-tracked cold-start copy
        relative_to(root)   -> ValueError

    So the repair pass concluded soccer's season schedule was PRESENT because it
    found the mirror in git, and skipped it -- while the runtime disk had none.
    Both branches of the old code dropped it silently: `is_file()` short-circuits
    on the repo copy, and the `relative_to` that would have caught it raises into
    a bare `continue`. A required artifact that can never be requested is exactly
    the class this repair pass exists to eliminate, and it had a blind spot for
    precisely the sport whose helpers do the fallback.

    This is CLAUDE.md's own warning as a code path: "don't diagnose missing data
    from the local checkout". The repair pass was doing exactly that.

    Re-anchors on the `<sport>_source/...` segment, which every artifact path in
    this repo carries and which is identical under either root. Returns None when
    there is no such segment, since then there is genuinely nothing to ask for.
    """
    try:
        resolved = path.resolve()
    except Exception:
        return None
    try:
        return resolved.relative_to(root).as_posix()
    except Exception:
        pass
    match = _SOURCE_TREE_MARKER.search(resolved.as_posix())
    return match.group(1) if match else None


def _missing_required_artifact_relative_paths(date_str: str) -> list[str]:
    relative_paths: list[str] = []
    try:
        root = _data_root().resolve()
    except Exception:
        return relative_paths
    for path in _required_daily_artifact_paths(date_str):
        try:
            relative = _relative_under_data_root(path, root)
            if not relative:
                continue
            # Presence is judged ON THE RUNTIME DISK, never at whatever path the
            # helper returned -- see _relative_under_data_root. Asking "does the
            # repo have a copy" answers a question nobody asked.
            if (root / relative).is_file():
                continue
        except Exception:
            continue
        # The same allowlist the writer enforces. Asking for something outside
        # it would just be refused, and silently: worth failing here instead.
        if is_hot_artifact_relative_path(relative):
            relative_paths.append(relative)
    return relative_paths


# Sports whose odds_history shard key is the plain ISO date. Deliberately
# excludes nfl/ncaaf: _shard_key_for_row scopes those by season/week, so a
# date-named shard never exists for them and asking would just 404 every
# cycle. Kept as an explicit tuple for the same reason
# _required_daily_artifact_paths is an explicit list -- this runs on the pull
# path every cycle and must not import syndicate.features.intelligence.
_ODDS_HISTORY_DATE_SHARDED_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "nhl", "ncaab", "soccer")

# 1MB. Large enough that a 51MB shard is ~51 reads, small enough that peak
# resident cost of a transfer is a rounding error on a 4GB worker -- the
# entire point of streaming this rather than taking it through export's
# read-whole-file-into-a-dict path.
_STREAM_CHUNK_BYTES = 1024 * 1024


def odds_history_relative_paths_for_date(date_str: str, *, sports: tuple[str, ...] | None = None) -> list[str]:
    """Allowlisted odds_history shard paths the board build needs for a date.

    Only the "artifacts" path, not "tracking": both are allowlisted and both
    hold the same payload (odds_refresh_tracking._sync_odds_history_for_refresh
    writes all three copies), so pulling both would move ~51MB twice for one
    usable file. The reader's own precedence
    (odds_control_plane.odds_history_paths_for_sport) is shared -> artifacts
    -> tracking, and the shared copy lives under reports/odds_control_plane/,
    which is NOT allowlisted and so can never cross services -- on a worker
    that copy simply doesn't exist and the reader falls through to this one.
    """
    shard_key = str(date_str or "").strip()
    if not shard_key:
        return []
    return [
        f"{sport}_source/artifacts/{sport}/odds_history/{shard_key}.json"
        for sport in (sports or _ODDS_HISTORY_DATE_SHARDED_SPORTS)
    ]


def _stream_url(relative_path: str, *, since_epoch: float | None = None) -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    from urllib.parse import quote

    url = base.rstrip("/") + "/api/ops/artifacts/stream?path=" + quote(relative_path, safe="")
    if since_epoch is not None:
        url += f"&since={since_epoch}"
    return url


def _is_append_only(relative_path: str) -> bool:
    """Families that only ever grow, so a tail fetch is safe (#248).

    Deliberately a tiny explicit list rather than "ends with .jsonl". An
    append-only assumption applied to a file that is rewritten in place would
    silently concatenate two versions into corruption, and the whole point of
    this module is that a wrong transfer is worse than a slow one. `book_quotes`
    is written exclusively by `append_book_quotes`.

    `.jsonl` IS REQUIRED, not decoration (`#331`). The directory test alone also
    matched `book_quotes/<date>.state.json`, which sits in the same directory and
    is the one file here that is REWRITTEN WHOLE on every flush -- it is a dict
    of quote-key -> [line, price, last_seen]. Tail-appending to that produces a
    second JSON document glued onto the first: not a parse error the caller
    handles, but a file `read_quote_last_seen` silently returns `{}` for, which
    turns `seen_age_seconds` into "unknown" for every market on the board.
    Exactly the "looks fixed, reads wrong" failure the 11.9h-stale investigation
    ended on.

    It was latent rather than live -- the repair pass only fetched files missing
    outright, where the offset is 0 and the fetch is whole anyway -- so nothing
    had corrupted yet. `#331` reconciles the state file deliberately, which is
    what would have made it fire.
    """
    text = str(relative_path or "")
    return "/book_quotes/" in text and text.endswith(".jsonl")


def pull_streamed_artifact(relative_path: str, *, timeout_seconds: int = 120) -> tuple[bool, int]:
    """Stream ONE allowlisted artifact to local disk. Returns (ok, written).

    Never raises, same contract as the rest of this module. `ok` is False only
    on a genuine failure -- a 304 (this worker's copy is already current) is a
    success that writes nothing, which is the normal steady state.
    """
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or not is_hot_artifact_relative_path(normalized):
        return False, 0
    token = _admin_token()
    if not token or not _env("SYNDICATE_WEB_PUBLISH_URL"):
        return False, 0

    target_path = _data_root() / Path(normalized)
    local_mtime: float | None = None
    local_size = 0
    try:
        if target_path.is_file():
            stat = target_path.stat()
            local_mtime = stat.st_mtime
            local_size = int(stat.st_size)
    except Exception:
        local_mtime = None
        local_size = 0

    url = _stream_url(normalized, since_epoch=local_mtime)
    if not url:
        return False, 0
    headers = {"Authorization": f"Bearer {token}"}
    # #248: APPEND-ONLY families are fetched by their TAIL, not whole.
    #
    # `book_quotes/<date>.jsonl` only ever grows -- the capture appends, it never
    # rewrites -- so re-fetching 74MB to learn about the last few KB is pure
    # waste, and on this worker it is not merely wasteful: refresh-worker
    # plateaus at 2.65-2.70GB of 4GB (handoff_refresh_worker_oom.md) leaving
    # ~1.4GB headroom, and #241's 120s whole-shard re-stream put it into a
    # ~3-minute restart loop within the hour.
    #
    # The server needs no change: /api/ops/artifacts/stream serves via
    # send_file(conditional=True), which honours HTTP Range already.
    tail_from = local_size if (local_size > 0 and _is_append_only(normalized)) else 0
    if tail_from:
        headers["Range"] = f"bytes={tail_from}-"
    request_obj = urllib_request.Request(url, method="GET", headers=headers)

    temp_path: Path | None = None
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            remote_mtime_raw = response.headers.get("X-Artifact-Mtime")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # A 206 means the server honoured the Range and this body is only
            # the new tail -- append it in place. Anything else is a whole file
            # and replaces the local copy, which is also the correct behaviour
            # when the shard was rotated or rewritten and our offset is stale.
            appended = tail_from > 0 and getattr(response, "status", None) == 206
            if appended:
                total = 0
                with open(target_path, "ab") as handle:
                    while True:
                        chunk = response.read(_STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        total += len(chunk)
            else:
                # uuid4-suffixed for the same concurrency reason the bulk pull's
                # temp names are (see _pull_hot_artifacts_request).
                temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.stream.tmp"
                total = 0
                with open(temp_path, "wb") as handle:
                    while True:
                        chunk = response.read(_STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        total += len(chunk)
        if temp_path is not None:
            os.replace(temp_path, target_path)
            temp_path = None
        if appended:
            print(
                f"[artifact_publisher] STREAM_TAIL_OK path={normalized} appended_bytes={total} from_offset={tail_from}",
                flush=True,
            )
            return True, (1 if total else 0)
        # Stamp the copy with web's mtime, not now(): the next cycle sends
        # this back as since=, and a local mtime later than the source would
        # make an updated shard look already-current forever.
        if remote_mtime_raw:
            try:
                remote_mtime = float(remote_mtime_raw)
                os.utime(target_path, (remote_mtime, remote_mtime))
            except Exception:
                pass
        print(f"[artifact_publisher] STREAM_PULL_OK path={normalized} bytes={total}", flush=True)
        return True, 1
    except urllib_error.HTTPError as exc:
        if exc.code == 416:
            # Range Not Satisfiable: our offset is at or past the remote size,
            # i.e. we already hold everything. A success that writes nothing --
            # the same steady state a 304 represents.
            return True, 0
        if exc.code == 304:
            # Already current. The steady state, and the reason this is cheap
            # enough to call every cycle.
            return True, 0
        if exc.code == 404:
            # Web doesn't have it either (no refresh has written this date's
            # shard yet). Not an error worth failing the caller over, but say
            # so rather than letting the board look merely quiet.
            print(f"[artifact_publisher] STREAM_PULL_ABSENT path={normalized}", flush=True)
            return False, 0
        print(f"[artifact_publisher] STREAM_PULL_FAILED path={normalized} status={exc.code}", flush=True)
        return False, 0
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] STREAM_PULL_FAILED path={normalized} error={exc}", flush=True)
        return False, 0
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] STREAM_PULL_UNEXPECTED_ERROR path={normalized} error={exc}", flush=True)
        return False, 0
    finally:
        try:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def pull_odds_history_artifacts(
    *, date_str: str, sports: tuple[str, ...] | None = None, timeout_seconds: int = 120
) -> int:
    """Pull every date-sharded odds_history artifact for a date. Returns files written.

    Separate from pull_hot_artifacts on purpose: these are the files that do
    not fit its bulk transport (see api_ops_artifacts_stream's comment), and
    keeping them out of that call leaves its watermark semantics untouched.
    """
    written = 0
    for relative_path in odds_history_relative_paths_for_date(date_str, sports=sports):
        _, files = pull_streamed_artifact(relative_path, timeout_seconds=timeout_seconds)
        written += files
    return written


def _date_glob_patterns(date_str: str) -> list[str]:
    parts = str(date_str or "").strip().split("-")
    if len(parts) == 3 and all(parts):
        joined = "-".join(parts)
        return [f"*{joined}*", f"*{'_'.join(parts)}*"]
    return [f"*{date_str}*"]
