from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Handedness(str, Enum):
    R = "R"
    L = "L"
    S = "S"


class PitchType(str, Enum):
    # Small canonical set; map Statcast/StatsAPI to these externally.
    FF = "FF"  # 4-seam
    SI = "SI"  # sinker
    FC = "FC"  # cutter
    SL = "SL"  # slider
    CU = "CU"  # curveball
    CH = "CH"  # changeup
    FS = "FS"  # splitter
    KC = "KC"  # knuckle curve
    KN = "KN"  # knuckleball
    OTHER = "OTHER"


class PitchCall(str, Enum):
    BALL = "BALL"
    CALLED_STRIKE = "CALLED_STRIKE"
    SWINGING_STRIKE = "SWINGING_STRIKE"
    FOUL = "FOUL"
    IN_PLAY = "IN_PLAY"
    HIT_BY_PITCH = "HIT_BY_PITCH"


class BattedBallType(str, Enum):
    GROUND = "GROUND"
    LINE = "LINE"
    FLY = "FLY"
    POP = "POP"


class BaseState(str, Enum):
    EMPTY = "---"
    FIRST = "1--"
    SECOND = "-2-"
    THIRD = "--3"
    FIRST_SECOND = "12-"
    FIRST_THIRD = "1-3"
    SECOND_THIRD = "-23"
    LOADED = "123"


Count = Tuple[int, int]  # balls, strikes


@dataclass(frozen=True)
class WeatherMultipliers:
    hr_mult: float = 1.0
    inplay_hit_mult: float = 1.0
    xb_share_mult: float = 1.0


@dataclass
class WeatherFactors:
    """Weather context for a game.

    This is intentionally lightweight and robust to missing data.
    """

    source: str = ""
    fetched_at: str = ""
    condition: str = ""
    temperature_f: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    wind_direction: str = ""  # out|in|cross|unknown
    wind_raw: str = ""
    is_dome: Optional[bool] = None

    def multipliers(self) -> WeatherMultipliers:
        # If dome/closed roof, treat as neutral.
        if self.is_dome is True:
            return WeatherMultipliers()

        # Temperature: warmer -> slightly more offense; colder -> slightly less.
        temp = self.temperature_f
        if isinstance(temp, (int, float)):
            delta = float(temp) - 70.0
            temp_factor = 1.0 + 0.003 * delta
            temp_factor = max(0.85, min(1.15, temp_factor))
        else:
            temp_factor = 1.0

        wind = self.wind_speed_mph
        wind_speed = float(wind) if isinstance(wind, (int, float)) else 0.0
        wind_dir = (self.wind_direction or "unknown").lower()
        wind_factor = 1.0
        if wind_speed > 10.0:
            adj = 0.02 * (wind_speed - 10.0)
            if wind_dir == "out":
                wind_factor = 1.0 + adj
            elif wind_dir == "in":
                wind_factor = 1.0 - adj
        wind_factor = max(0.75, min(1.25, wind_factor))

        hr_mult = temp_factor * wind_factor
        hr_mult = max(0.75, min(1.35, hr_mult))

        # Hits-in-play respond more gently than HR.
        inplay_hit_mult = 1.0 + 0.0015 * (float(temp) - 70.0) if isinstance(temp, (int, float)) else 1.0
        inplay_hit_mult = max(0.90, min(1.10, inplay_hit_mult))

        # Extra-base share is a small nudge only.
        xb_share_mult = 1.0 + 0.0008 * (float(temp) - 70.0) if isinstance(temp, (int, float)) else 1.0
        xb_share_mult = max(0.92, min(1.08, xb_share_mult))

        return WeatherMultipliers(hr_mult=hr_mult, inplay_hit_mult=inplay_hit_mult, xb_share_mult=xb_share_mult)


@dataclass(frozen=True)
class ParkMultipliers:
    hr_mult: float = 1.0
    inplay_hit_mult: float = 1.0
    xb_share_mult: float = 1.0


@dataclass
class ParkFactors:
    """Park context for a game.

    This is a heuristic geometry-based adjustment (not a true historical park factor).
    It is designed to be stable and data-light, using venue field dimensions when available.
    """

    source: str = ""
    fetched_at: str = ""
    venue_id: Optional[int] = None
    venue_name: str = ""
    roof_type: str = ""
    roof_status: str = ""

    left_line: Optional[float] = None
    center: Optional[float] = None
    right_line: Optional[float] = None

    # Optional derived overrides (e.g., Statcast-derived park multipliers).
    hr_mult_override: Optional[float] = None
    inplay_hit_mult_override: Optional[float] = None
    xb_share_mult_override: Optional[float] = None

    def multipliers(self) -> ParkMultipliers:
        # If derived overrides exist, use them.
        if isinstance(self.hr_mult_override, (int, float)) or isinstance(self.inplay_hit_mult_override, (int, float)) or isinstance(self.xb_share_mult_override, (int, float)):
            hr_mult = float(self.hr_mult_override) if isinstance(self.hr_mult_override, (int, float)) else 1.0
            inplay_hit_mult = float(self.inplay_hit_mult_override) if isinstance(self.inplay_hit_mult_override, (int, float)) else 1.0
            xb_share_mult = float(self.xb_share_mult_override) if isinstance(self.xb_share_mult_override, (int, float)) else 1.0
            hr_mult = max(0.85, min(1.15, hr_mult))
            inplay_hit_mult = max(0.90, min(1.10, inplay_hit_mult))
            xb_share_mult = max(0.92, min(1.08, xb_share_mult))
            return ParkMultipliers(hr_mult=hr_mult, inplay_hit_mult=inplay_hit_mult, xb_share_mult=xb_share_mult)

        # Closed roof / dome: treat as neutral (weather already handles the dome case too).
        if (self.roof_status or "").lower() == "closed":
            return ParkMultipliers()
        if "dome" in (self.roof_type or "").lower():
            return ParkMultipliers()

        dims = [self.left_line, self.center, self.right_line]
        dims_f = [float(x) for x in dims if isinstance(x, (int, float)) and x > 0]
        if len(dims_f) < 2:
            return ParkMultipliers()

        avg = sum(dims_f) / float(len(dims_f))
        baseline = 370.0
        # Smaller park -> higher HR; larger park -> lower HR.
        # 10ft smaller => ~+2% HR (conservative).
        hr_mult = 1.0 + 0.0020 * (baseline - avg)
        hr_mult = max(0.88, min(1.12, hr_mult))

        # Larger outfields can slightly increase hit-in-play and extra bases.
        inplay_hit_mult = 1.0 + 0.0008 * (avg - baseline)
        inplay_hit_mult = max(0.95, min(1.07, inplay_hit_mult))

        xb_share_mult = 1.0 + 0.0010 * (avg - baseline)
        xb_share_mult = max(0.95, min(1.10, xb_share_mult))

        return ParkMultipliers(hr_mult=hr_mult, inplay_hit_mult=inplay_hit_mult, xb_share_mult=xb_share_mult)


@dataclass(frozen=True)
class UmpireMultipliers:
    called_strike_mult: float = 1.0


@dataclass
class UmpireFactors:
    """Umpire context for a game.

    We only model the home-plate umpire, via a small called-strike multiplier.
    If unknown, this remains neutral.
    """

    source: str = ""
    fetched_at: str = ""
    home_plate_umpire_id: Optional[int] = None
    home_plate_umpire_name: str = ""
    called_strike_mult: float = 1.0

    def multipliers(self) -> UmpireMultipliers:
        m = float(self.called_strike_mult or 1.0)
        m = max(0.92, min(1.08, m))
        return UmpireMultipliers(called_strike_mult=m)


@dataclass(frozen=True)
class Player:
    mlbam_id: int
    full_name: str
    primary_position: str
    bat_side: Handedness
    throw_side: Handedness


@dataclass
class BatterProfile:
    player: Player
    # Per-PA targets; the pitch engine approximates these.
    k_rate: float = 0.22
    bb_rate: float = 0.08
    hbp_rate: float = 0.008
    hr_rate: float = 0.03
    inplay_hit_rate: float = 0.28
    xb_hit_share: float = 0.22  # of hits (excluding HR), fraction that are 2B/3B
    triple_share_of_xb: float = 0.12  # of (2B+3B), fraction that are 3B

    # Stolen base propensity (best-effort; used for SB prop approximation).
    # sb_attempt_rate is per "steal opportunity" (roughly: times reaching 1B).
    sb_attempt_rate: float = 0.0
    sb_success_rate: float = 0.72
    vs_pitch_type: Dict[PitchType, float] = field(default_factory=dict)
    vs_pitch_type_hr: Dict[PitchType, float] = field(default_factory=dict)

    # Platoon split multipliers (best-effort). Keys are metric names:
    # "k", "bb", "hr", "inplay". Values are multipliers vs that pitcher hand.
    platoon_mult_vs_lhp: Dict[str, float] = field(default_factory=dict)
    platoon_mult_vs_rhp: Dict[str, float] = field(default_factory=dict)

    # Home/road split multipliers keyed by venue side.
    # Values use the same metric names as platoon multipliers.
    venue_mult_home: Dict[str, float] = field(default_factory=dict)
    venue_mult_away: Dict[str, float] = field(default_factory=dict)

    # Venue-specific multipliers keyed by home-team id for the ballpark.
    # For example, games in Fenway Park key to BOS team_id regardless of opponent.
    vs_venue_hr_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_k_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_bb_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_inplay_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_history: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # Statcast quality bag. `#440` -- CONTRACT SETTLED 2026-08-18.
    #
    # This is a UNION, not a fixed schema, and it is PARTIAL BY DESIGN. Three
    # consumers read it and each takes only the keys it recognises:
    #
    #   simulate.py:163  _statcast_shape_rate_mults  reads the RAW metrics and
    #                    DERIVES {k,bb,hr,inplay,pitch_count,xb} from them
    #   simulate.py:1400 lookahead pressure          reads BOTH raw metrics and
    #                    the derived multipliers, guarding each with isinstance
    #
    # Every read is guarded and `_rate_ratio_mult` returns 1.0 for a missing or
    # non-numeric value, so supplying a SUBSET is legal and safe. The old comment
    # here listed only k/bb/hr/inplay, which described the DERIVED OUTPUT and led
    # to a hunt for a producer that could never have existed.
    #
    # RAW metrics (feed these):
    #   chase_swing_rate  zone_rate  csw_rate  contact_rate  xwoba
    #   ev_mean  ev_max  pulled_air_rate  pitch_velo_mean  pitch_extension_mean
    #
    # DERIVED multipliers (k/bb/hr/inplay): DO NOT FEED alongside the raw
    # metrics. `_statcast_shape_rate_mults` already derives them, and supplying
    # both makes the lookahead add pressure from a value the shape function has
    # separately applied -- double-counting, the failure measured 2026-08-17.
    statcast_quality_mult: Dict[str, float] = field(default_factory=dict)

    # Optional: batter-vs-pitcher head-to-head multipliers keyed by pitcher MLBAM id.
    # Intended to be applied only when the current pitcher matches.
    vs_pitcher_hr_mult: Dict[int, float] = field(default_factory=dict)
    vs_pitcher_k_mult: Dict[int, float] = field(default_factory=dict)
    vs_pitcher_bb_mult: Dict[int, float] = field(default_factory=dict)
    vs_pitcher_inplay_mult: Dict[int, float] = field(default_factory=dict)
    vs_pitcher_history: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # Batted-ball type tendencies (share of balls in play).
    # Defaults match the pitch-model prior distribution.
    bb_gb_rate: float = 0.44
    bb_fb_rate: float = 0.25
    bb_ld_rate: float = 0.20
    bb_pu_rate: float = 0.11
    bb_inplay_n: int = 0


@dataclass
class PitcherProfile:
    player: Player
    k_rate: float = 0.24
    bb_rate: float = 0.08
    hbp_rate: float = 0.008
    hr_rate: float = 0.03
    inplay_hit_rate: float = 0.27

    # Optional season-to-date sample sizes (best-effort, may be 0 if unknown).
    # Used to size uncertainty when sampling per-game pitcher rates.
    batters_faced: float = 0.0
    balls_in_play: float = 0.0

    arsenal: Dict[PitchType, float] = field(default_factory=dict)  # usage probs
    # Count x batter-hand conditional mixes, keyed "<bucket>|<hand>". Empty means
    # "fall back to `arsenal`", which is exactly the pre-2026-08-18 behaviour.
    # DECLARED, not setattr: `dataclasses.replace()` drops setattr attributes,
    # which is how `position_substitutions` stayed permanently off.
    conditional_arsenal: Dict[str, Dict[PitchType, float]] = field(default_factory=dict)
    count_bucket_map: Dict[str, str] = field(default_factory=dict)  # "b-s" -> bucket
    conditional_arsenal_source: str = ""
    # Optional pitch-type outcome multipliers (e.g., Statcast-derived vs global priors).
    pitch_type_whiff_mult: Dict[PitchType, float] = field(default_factory=dict)
    pitch_type_inplay_mult: Dict[PitchType, float] = field(default_factory=dict)
    pitch_type_hr_mult: Dict[PitchType, float] = field(default_factory=dict)
    # Cache-only Statcast (pybaseball) provenance for the above multipliers.
    statcast_splits_source: str = ""
    statcast_splits_n_pitches: int = 0
    statcast_splits_start_date: str = ""
    statcast_splits_end_date: str = ""
    arsenal_source: str = "default"  # default|statcast
    arsenal_sample_size: int = 0
    stamina_pitches: int = 90
    role: str = "RP"  # SP/CL/SU/MR/LR (starter/closer/setup/middle/long)

    # Availability multiplier (0..1) derived from recent usage / fatigue.
    # Defaults to 1.0 (fully available).
    availability_mult: float = 1.0

    # Platoon split multipliers (best-effort). Keys are metric names:
    # "k", "bb", "hr", "inplay". Values are multipliers vs that batter side.
    platoon_mult_vs_lhb: Dict[str, float] = field(default_factory=dict)
    platoon_mult_vs_rhb: Dict[str, float] = field(default_factory=dict)

    # Home/road split multipliers keyed by venue side.
    venue_mult_home: Dict[str, float] = field(default_factory=dict)
    venue_mult_away: Dict[str, float] = field(default_factory=dict)

    # Venue-specific multipliers keyed by home-team id for the ballpark.
    vs_venue_hr_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_k_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_bb_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_inplay_mult: Dict[int, float] = field(default_factory=dict)
    vs_venue_history: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # Statcast quality bag. `#440` -- CONTRACT SETTLED 2026-08-18.
    #
    # This is a UNION, not a fixed schema, and it is PARTIAL BY DESIGN. Three
    # consumers read it and each takes only the keys it recognises:
    #
    #   simulate.py:163  _statcast_shape_rate_mults  reads the RAW metrics and
    #                    DERIVES {k,bb,hr,inplay,pitch_count,xb} from them
    #   simulate.py:1400 lookahead pressure          reads BOTH raw metrics and
    #                    the derived multipliers, guarding each with isinstance
    #
    # Every read is guarded and `_rate_ratio_mult` returns 1.0 for a missing or
    # non-numeric value, so supplying a SUBSET is legal and safe. The old comment
    # here listed only k/bb/hr/inplay, which described the DERIVED OUTPUT and led
    # to a hunt for a producer that could never have existed.
    #
    # RAW metrics (feed these):
    #   chase_swing_rate  zone_rate  csw_rate  contact_rate  xwoba
    #   ev_mean  ev_max  pulled_air_rate  pitch_velo_mean  pitch_extension_mean
    #
    # DERIVED multipliers (k/bb/hr/inplay): DO NOT FEED alongside the raw
    # metrics. `_statcast_shape_rate_mults` already derives them, and supplying
    # both makes the lookahead add pressure from a value the shape function has
    # separately applied -- double-counting, the failure measured 2026-08-17.
    statcast_quality_mult: Dict[str, float] = field(default_factory=dict)

    # Batted-ball type tendencies (share of balls in play allowed).
    # Defaults match the pitch-model prior distribution.
    bb_gb_rate: float = 0.44
    bb_fb_rate: float = 0.25
    bb_ld_rate: float = 0.20
    bb_pu_rate: float = 0.11
    bb_inplay_n: int = 0

    # Optional leverage index hint (0-1). Higher means preferred in high leverage.
    leverage_skill: float = 0.5


@dataclass(frozen=True)
class Team:
    team_id: int
    name: str
    abbreviation: str


@dataclass
class Lineup:
    batters: List[BatterProfile]
    pitcher: PitcherProfile
    bench: List[BatterProfile] = field(default_factory=list)
    bullpen: List[PitcherProfile] = field(default_factory=list)


@dataclass
class ManagerProfile:
    pull_starter_pitch_count: int = 95
    pull_starter_third_time_penalty: float = 0.04
    # Keep starters in longer early (useful for F5 markets) unless they blow up.
    starter_min_innings: int = 5
    starter_blowup_run_diff: int = 6  # allow early hook if game gets out of hand
    closer_leverage_max_run_diff: int = 3
    use_closer_in_9th_only: bool = True
    pinch_hit_aggressiveness: float = 0.15


@dataclass
class TeamRoster:
    team: Team
    manager: ManagerProfile
    lineup: Lineup


@dataclass(frozen=True)
class PitchResult:
    pitch_type: PitchType
    call: PitchCall
    is_strike: bool
    is_ball: bool
    in_play: bool
    batted_ball_type: Optional[BattedBallType] = None
    # If in_play=True, one of: OUT, 1B, 2B, 3B, HR, ROE, FC
    in_play_result: Optional[str] = None


@dataclass
class InningHalfState:
    batting_team: Team
    fielding_team: Team
    outs: int = 0
    bases: BaseState = BaseState.EMPTY
    # Runner MLBAM ids on bases (0 => empty). This lets us attribute runs and baserunning stats.
    runner_on_1b: int = 0
    runner_on_2b: int = 0
    runner_on_3b: int = 0
    runs_scored: int = 0
    next_batter_index: int = 0


@dataclass
class GameConfig:
    # *** BROKEN. DO NOT ENABLE. Kept only so the finding is not re-derived. ***
    #
    # Measured 2026-08-18: switching this on inflates run scoring by 8-35% across
    # 4 games (7.27 -> 9.07, 11.33 -> 12.47, 9.47 -> 10.20, 10.67 -> 14.40).
    # **A variance-reduction technique MUST be distribution-preserving. This one
    # is not, so it cannot be used no matter how much variance it removes.**
    #
    # A first bug WAS found and fixed and did not account for it: the key used
    # `half.next_batter_index`, which simulate.py:3178 advances MODULO the lineup
    # length, so it held 9 values and replayed the same stream 4-5 times per
    # game -- that version inflated scoring up to 126%. With a monotonic per-team
    # PA counter the reseed now fires exactly once per PA with 104 distinct seeds
    # in a 104-PA game, verified, AND SCORING IS STILL INFLATED.
    #
    # Residual cause not isolated. The marginal uniforms are clean (draws 1-5
    # from 40,000 freshly-seeded streams sit within 1.2 sd of 0.5), so it is not
    # a biased head. Suspicion is the JOINT structure of early Mersenne Twister
    # output across independently-seeded streams, which is a known weakness --
    # MT is seeded for one long stream, not for many short ones.
    #
    # IF THIS IS EVER REVISITED: do not reseed MT. Use a counter-based generator
    # with real substreams (numpy PCG64 `.jumped(n)`, or Philox), which is
    # designed for exactly this and carries no head-of-stream problem.
    #
    # COMMON RANDOM NUMBERS. Re-seed the game RNG at the start of every plate
    # appearance from (seed, batting team, that team's PA index) rather than
    # letting one stream run the whole game.
    #
    # Why: with a single per-game stream, comparing two engine configurations is
    # far noisier than it looks. The first pitch whose outcome differs shifts
    # every subsequent draw, so the two arms are effectively running different
    # games from that point on. Measured 2026-08-18, the market harness had a
    # seed-to-seed noise floor of 0.00326 Brier against effects of ~0.00138 --
    # noise 2.4x the effect, and the sign flipped in 3 of 4 markets between two
    # seeds. Sharing a seed across arms LOOKS like common random numbers and is
    # not, because control flow depends on the RNG.
    #
    # A team's Nth plate appearance is the same logical event in both arms by
    # definition of a batting order, so seeding on it re-synchronises the arms
    # after any divergence instead of letting one early difference randomise the
    # rest of the game. Inning is deliberately NOT in the key: it shifts when
    # scoring differs, which would break the alignment this exists to create.
    #
    # DEFAULT OFF. It changes every simulated result (different draws), so it is
    # a measurement tool to be switched on for BOTH arms of a comparison, never
    # a silent change to what production simulates.
    crn_pa_seeding: bool = False
    innings: int = 9
    extra_innings: int = 3
    # Baseball full-game markets settle to a winner. Keep tied finals opt-in only.
    allow_ties_after_max_innings: bool = False
    # Extra-innings placed runner (regular-season MLB rule): each extra
    # half-inning starts with the previous lineup spot on second base.
    extras_placed_runner: bool = True
    # End the game as soon as the home team takes the lead in the bottom of
    # the final regulation inning or later (walk-off). Without this, walk-off
    # halves play to 3 outs and inflate totals/home margins.
    end_on_walkoff: bool = True
    rng_seed: Optional[int] = None
    max_pitches_per_pa: int = 20
    weather: WeatherFactors = field(default_factory=WeatherFactors)
    park: ParkFactors = field(default_factory=ParkFactors)
    umpire: UmpireFactors = field(default_factory=UmpireFactors)

    # Sensitivity knobs: scale the strength of weather/park multipliers without
    # changing the underlying heuristics.
    #
    # Implemented as exponent weights in log-space (mult^weight):
    # - 1.0 => as-is
    # - 0.0 => neutralize (force to ~1.0)
    # - >1 => amplify
    weather_hr_weight: float = 1.0
    weather_inplay_hit_weight: float = 1.0
    weather_xb_share_weight: float = 1.0
    park_hr_weight: float = 1.0
    park_inplay_hit_weight: float = 1.0
    park_xb_share_weight: float = 1.0
    # `#440` P2: in-sim POSITION-PLAYER substitution (pinch hitters, defensive
    # replacements). Dark-launched OFF, like every other behaviour change here.
    #
    # THIS MUST BE A DECLARED FIELD, not an attribute set on an instance.
    # `dataclasses.replace()` rebuilds a GameConfig from its declared fields
    # only, and the sim calls `replace(cfg, rng_seed=...)` on every run -- so a
    # monkey-patched attribute is silently discarded before the first pitch and
    # the feature reads as permanently disabled. Caught by the reachability test.
    position_substitutions: bool = False
    # Toggle batted-ball-informed baserunning: DP, sac flies, and runner advancement.
    # When False, falls back to a simpler forced-advance baserunning model.
    bip_baserunning: bool = True
    # Tuning knobs for the batted-ball-informed OUT logic.
    # These are intentionally simple (global) until we model speed/arm/depth.
    bip_dp_rate: float = 0.06
    bip_sf_rate_flypop: float = 0.48
    bip_sf_rate_line: float = 0.36
    # Tuning knobs for the batted-ball-informed HIT baserunning logic.
    # These scale the probabilities that runners score on singles/doubles.
    # 1.0 = baseline behavior.
    bip_1b_p2_scores_mult: float = 1.15  # runner on 2B scores on 1B
    bip_2b_p1_scores_mult: float = 1.15  # runner on 1B scores on 2B
    bip_1b_p1_to_3b_rate: float = 0.24
    bip_ground_rbi_out_rate: float = 0.18
    bip_out_2b_to_3b_rate: float = 0.24
    bip_out_1b_to_2b_rate: float = 0.14
    bip_misc_advance_pitch_rate: float = 0.004
    bip_roe_rate: float = 0.012
    bip_fc_rate: float = 0.04
    bip_fc_runner_on_3b_score_rate: float = 0.0
    # Optional: sample per-game pitcher rates (K/BB/HBP/HR/in-play hit).
    # This injects "today" uncertainty while keeping within-game consistency.
    pitcher_rate_sampling: bool = True
    # Optional tuning hook: overrides for PitcherDistributionConfig fields.
    # Example: {"bf_scale": 0.2, "bf_min_n": 40.0}
    # Kept as a dict to avoid circular imports from sim_engine.pitcher_distributions.
    pitcher_distribution_overrides: Dict[str, Any] = field(default_factory=dict)
    # Optional tuning hook: overrides for PitchModelConfig fields.
    # Example: {"base_ball": 0.33, "base_in_play": 0.24}
    # Kept as a dict to avoid circular imports from sim_engine.pitch_model.
    pitch_model_overrides: Dict[str, Any] = field(default_factory=dict)

    # Pitching change / bullpen management model.
    # - off: never change pitchers (starter goes the whole game)
    # - legacy: deterministic hook + role/leverage reliever selection (backwards compatible)
    # - v2: probabilistic hook w/ fatigue + TTO pressure + closer constraints
    manager_pitching: str = "v2"
    # Optional tuning hook: overrides for manager pitching behavior.
    # Intended for quick A/B sweeps without expanding the public config surface.
    # Example: {"hook_jitter_pitches": 6, "starter_hook_spread": 8.0}
    manager_pitching_overrides: Dict[str, Any] = field(default_factory=dict)
    # Play-by-play logging. Keep off by default to avoid huge outputs.
    # off: no PBP, pa: PA-level only, pitch: pitch+PA+inning events
    pbp: str = "off"
    pbp_max_events: int = 0  # 0 => unlimited


@dataclass
class GameResult:
    home_team: Team
    away_team: Team
    home_score: int
    away_score: int
    innings_played: int
    batter_stats: Dict[int, Dict[str, int]]
    pitcher_stats: Dict[int, Dict[str, float]]
    away_inning_runs: List[int] = field(default_factory=list)
    home_inning_runs: List[int] = field(default_factory=list)
    pbp_mode: str = "off"
    pbp_truncated: bool = False
    pbp: List[Dict[str, Any]] = field(default_factory=list)

