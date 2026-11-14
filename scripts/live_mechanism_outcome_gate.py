"""todo #784 -- the OUTCOME GATE for a change to a `SYNDICATE_<LEAGUE>_LIVE_MECHANISMS` env value.

WHY THIS EXISTS, and it is one specific incident (learnings.md 2026-11-11, lane `ncaab-score-effect-load`).

On 2026-11-10 07:49:46Z NCAAB's live re-sim loaded RC46 (`score_effect_k` 0.005 + `possession_alternation` 1.0 +
`solver_endgame_pts_per_team` 0.46). The gate that chose it scored the margin's MEAN (point |err|) at most
checkpoints -- "the harness has no distribution to score" -- and the distribution only from 30 / 36 min, on the
2025-26 corpus. RC46 is mainly a WIDTH change, and live spreads and moneylines are priced off the re-sim's margin
DISTRIBUTION from the tip on (`live_gameline_join._two_way_home_prob`). Replayed on 240 rated 2026-27 games and scored
on the finals, totals tied and win Brier was worse beyond 1.96 SE at 20 m (+0.011 +- 0.009) and 36 m
(+0.007 +- 0.005). It was reverted at 22:56:28Z, six minutes before the slate's first live game. The registered
post-load reading -- an effect ratio -- came back NOT FALSIFIED. Nothing in the process asked the outcome question.

WHAT IT DOES. Re-sims the CURRENT season's completed games from their real play-by-play state on two values of the
league's mechanisms key -- the one running now and the candidate -- with the SAME seeds (production's own
`stable_seed`), production's own inputs (`ncaab/live_resim.build_engine_inputs`, the dated team and player priors the
fleet serves) and the replay harness's state (`state_at` / `resume_game_state`). At every checkpoint the live pricing
reads (tip, 10, 20, 30, 36 min for NCAAB) it scores both arms against the real finals:

  margin:  CRPS, |central-80% coverage - 0.80|          (spreads and moneylines read this distribution)
  total:   CRPS, |central-80% coverage - 0.80|          (totals are served raw from the sim)
  win:     Brier and log loss of the result's home_win_prob

paired candidate - current over games. Every metric is lower-is-better. Coverage is scored as distance from nominal,
not as "higher", because the 7-field config over-covers (0.83-0.91) and RC46 under-covers (0.69-0.83): neither
direction is good by itself.

THE FLAG RULE (the DEFAULT; todo #784). A cell is WORSE when its own 1.96 x bootstrap-SE interval clears 0, against
ONE current-arm Monte Carlo draw (production's seeds). This rule is known to refuse NULL changes: two A/A runs (the
running value against itself, candidate seeds salted; findings PHASE 2 STEP 3j) flagged 4 and 2 cells on 11-03..12,
because every candidate on those dates shares that one draw. Read any WORSE cell beside an A/A receipt for the same
dates (`--aa-salts`).

OPT-IN, FALSIFIED AS A DEFAULT `[2026-11-13, lane outcome-gate-null-baseline, findings PHASE 2 STEP 3k]`:
`--current-salts K` (the current arm is the mean of K seed-salted draws: 0, 1001, ...) and `--flag-rule family` (WORSE
needs z above the 95th percentile of the max standardized deviation over all 30 cells in one joint bootstrap). With
K = 4 both A/A transitions flagged 0 cells, but RC46 -- reverted 2026-11-10 on outcome scoring -- was not refused
either (20 m win Brier z 3.10 against a critical value of 3.47). The critical values ran 2.98-3.63, inflated by the
coverage cells: |coverage - 0.80| folds near 0.80, so its bootstrap is skewed and dominates the max. Do not make it the
default until a redesign refuses RC46 and passes the A/A pairs. Every receipt carries a `legacy` block (one draw,
per-cell) whichever rule is chosen, and the 1.96 x SE is printed beside each cell.

OPT-IN, UNDER CONFIRMATION `[2026-11-14, lane gate-smooth-family, findings PHASE 2 STEP 3l]`: `--family-cells smooth`
runs the max-T over the 20 SMOOTH cells only (margin / total CRPS, win Brier, win log loss); the two coverage metrics
keep their z on the receipt and the printout but are never flagged. CRPS already scores the whole predictive
distribution, the 80% interval included, so a width change that miscalibrates shows there. Post hoc on 11-03..12 (K = 4)
its critical values ran 2.82-2.95, it refused 1 of 60 null pairings, and it refused RC46 on 20 m win Brier -- chosen
after seeing that data, so it is confirmed or not on games after 11-12, pre-registered (main e990f0bac). Its power is
set by GAMES, not sims: it refused RC46 on ~20% of 150-game subsets and ~56% of 300-game ones.

ANY RULE BUT THE DEFAULT (`rule_id`: `percell-k1` today) writes its receipt as `...__rule-<rule id>.json`, and
`check_receipt` re-derives the rule from the receipt's own fields and refuses any rule but the default. Before this, an
opt-in run wrote the default's file name: on 2026-11-13 22:58Z the STEP 3k validation overwrote the live receipts with
family-rule verdicts that would have cleared RC46 (restored by hand; no preflight ran in between).

THE RECEIPT. `<main tree>/.syndicate/deploy/outcome_gate/<league>__<candidate12>__<current12>.json`, keyed on the
sha256 of the canonical JSON of each value, so it names the exact TRANSITION. `deploy_preflight.py` reads it (through
`check_receipt` below -- one source for the predicate, the same file on both sides) and returns OUTCOME_GATE when a
changed key has no fresh receipt, too few games, a rule other than the default, or WORSE cells not explicitly
accepted.

Run it ON THE FLEET (WSL), at nice 19, from a worktree at origin/main with the fleet's venv:

    nice -n 19 ~/.venvs/syndicate/bin/python scripts/live_mechanism_outcome_gate.py --league ncaab \\
        --candidate-file /path/candidate.json --current-from-role live-odds-worker \\
        --dates 2026-11-03..2026-11-09 --data-root ~/syndicate-prod/data

The half-split and exact-target switches are copied from the running role's environ (booleans; nothing else is read).
Values are printed: a mechanisms value is engine config, not a secret. Exit 0 = receipt written with no WORSE cell,
1 = receipt written WITH worse cells, 2 = no receipt (too few games, bad value, unsupported league).

One run can score several candidates (`--candidate-file` repeated) and A/A noise checks (`--aa-salts 1,2`) against ONE
shared K-draw current arm, so the current arm is paid for once: the cost is K + candidates arms. `--dump-arms PATH`
writes every arm's per-game features, so a rule can be re-scored without re-simulating.

Read-only against production: reads the fleet's data root and one process's environ, writes only the receipt.

`--seed-salt N` (todo #765 STEP 3j) re-seeds the CANDIDATE arm only, so the same value can be run against itself: an
A/A run, which measures how many WORSE cells a null transition produces. Why it is needed: the two arms' streams
diverge within a few possessions of any real change, so the "paired" comparison is close to unpaired in its Monte Carlo
part, and every candidate scored on the same dates shares ONE current arm (STEP 3i: three candidates, one common 10 m /
20 m cost). A salted receipt carries `seed_salt` and its own file name, and `check_receipt` refuses one, so a noise
check can never clear a load.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import zlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]

# Every league whose mechanisms key this gate can replay. A key for a league not listed here (NBA today:
# `SYNDICATE_NBA_LIVE_MECHANISMS` runs through a different engine path) gets NO receipt, so preflight refuses it until
# the gate is extended or the operator waives with a reason -- never a silent pass.
LEAGUES: dict[str, dict[str, Any]] = {
    "ncaab": {
        "env_key": "SYNDICATE_NCAAB_LIVE_MECHANISMS",
        "switch_keys": ("SYNDICATE_NCAAB_HALF_SPLIT", "SYNDICATE_NCAAB_EXACT_TARGET"),
        "role": "live-odds-worker",
        "worker_script": "scripts/run_live_odds_refresh_worker.py",
        # Elapsed game seconds. Live NCAAB spreads, moneylines and totals are priced at every state from the tip.
        "checkpoints": {"0m": 0.0, "10m": 600.0, "20m": 1200.0, "30m": 1800.0, "36m": 2160.0},
    },
}

# The floor on scored games, enforced by PREFLIGHT as well as here so `--min-games 1` cannot satisfy it. Measured on
# the RC46 replays: 240 games gave win-Brier SEs of +-0.005..0.009, enough to resolve RC46's +0.007..0.011; 54 games
# (one slate) gave +-0.006..0.025, which cannot. 150 sits between them.
MIN_GAMES = 150
# A receipt describes a population and code at one time; past this age the season has moved under it.
MAX_RECEIPT_AGE_SECONDS = 7 * 24 * 3600
RECEIPT_SUBDIR = Path(".syndicate") / "deploy" / "outcome_gate"
COVERAGE_NOMINAL = 0.80
METRICS = ("margin_crps", "margin_cov80_dev", "total_crps", "total_cov80_dev", "win_brier", "win_logloss")
# The current arm: mean of K draws. Salt 0 is production's own seed (and the candidate's, so a real candidate keeps
# common random numbers with draw 0); the others sit far from any candidate or A/A salt.
DEFAULT_CURRENT_SALTS = 1  # K = 4 + the family rule was FALSIFIED as a default 2026-11-13 (see THE FLAG RULE)
CURRENT_SALT_BASE = 1000
FAMILY_ALPHA = 0.05
FAMILY_DRAWS = 2000
# The cells the family rule's max-T runs over (`--family-cells`). "smooth" leaves out the two folded |coverage - 0.80|
# metrics: they are still scored, printed and stored with their z, but never flagged (lane gate-smooth-family; why in
# THE FLAG RULE).
FAMILY_CELLS: dict[str, tuple[str, ...]] = {
    "all": METRICS,
    "smooth": ("margin_crps", "total_crps", "win_brier", "win_logloss"),
}
DEFAULT_FLAG_RULE = "per-cell"
DEFAULT_FAMILY_CELLS = "all"
_KEY_RE = re.compile(r"^SYNDICATE_([A-Z0-9]+)_LIVE_MECHANISMS$")


# --------------------------------------------------------------------------------------------------------------------
# Shared with deploy_preflight.py. Stdlib only: preflight loads this module on Windows without the engine.
# --------------------------------------------------------------------------------------------------------------------

def canonical_value(raw: Any) -> str:
    """One spelling per VALUE: JSON is re-serialised with sorted keys and no whitespace; empty / unset is ''."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    except ValueError:
        return text


def value_hash(raw: Any) -> str:
    return hashlib.sha256(canonical_value(raw).encode("utf-8")).hexdigest()


def league_of_key(key: str) -> Optional[str]:
    match = _KEY_RE.match(str(key or ""))
    return match.group(1).lower() if match else None


def rule_id(flag_rule: str = DEFAULT_FLAG_RULE, current_salts: int = DEFAULT_CURRENT_SALTS,
            family_cells: str = DEFAULT_FAMILY_CELLS, alpha: float = FAMILY_ALPHA) -> str:
    """The flag rule as one string: `percell-k1` (K = current-arm draws), `family-smooth-k4-a0.05`, ..."""
    k = max(1, int(current_salts))
    if flag_rule == "per-cell":
        return f"percell-k{k}"
    return f"family-{family_cells}-k{k}-a{float(alpha):g}"


DEFAULT_RULE_ID = rule_id()


def receipt_rule_id(receipt: Mapping[str, Any]) -> str:
    """The rule a receipt was scored by, DERIVED from its own fields (never from a stored label). A receipt without the
    fields predates the opt-in rules -- code before 6095654a3 had one rule, one current draw per-cell -- so absent is
    per-cell K = 1 by construction, not a permissive guess."""
    fam = receipt.get("family") or {}
    return rule_id(str(receipt.get("flag_rule") or "per-cell"), len(receipt.get("current_salts") or [0]),
                   str(receipt.get("family_cells") or "all"), float(fam.get("alpha") or FAMILY_ALPHA))


def receipt_name(league: str, candidate_hash: str, current_hash: str, seed_salt: int = 0, rule: str = "") -> str:
    """The gate's name for one transition. A salted (noise-check) run and a run scored by any rule other than the
    default each get their own name, so neither can overwrite the default receipt or be read by preflight."""
    suffix = f"__salt{int(seed_salt)}" if int(seed_salt or 0) else ""
    if rule and rule != DEFAULT_RULE_ID:
        suffix += f"__rule-{rule}"
    return f"{league}__{candidate_hash[:12]}__{current_hash[:12]}{suffix}.json"


def salted_seed(seed: int, salt: int) -> int:
    """`seed` unchanged at salt 0 (the gate's own paired seeds); otherwise a different 31-bit seed per salt."""
    if not int(salt or 0):
        return int(seed)
    return zlib.crc32(f"{int(seed)}|seed-salt|{int(salt)}".encode("utf-8")) & 0x7FFFFFFF


def root_from_gitfile(text: str, repo: Path, windows: bool) -> Optional[Path]:
    """The primary checkout from a worktree's `.git` FILE (`gitdir: <main>/.git/worktrees/<name>`).

    WHY NOT GIT: the gate runs in WSL from a worktree Windows git created, whose `.git` file says `gitdir: C:/...`.
    WSL git cannot follow that (measured 2026-11-11: `rev-parse --git-common-dir` rc=128), and falling back to the
    worktree would put the receipt where preflight -- which reads the PRIMARY tree, on Windows -- never looks."""
    match = re.match(r"^\s*gitdir:\s*(.+?)\s*$", text or "", re.M)
    if not match:
        return None
    raw = match.group(1)
    drive = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if drive and not windows:
        raw = f"/mnt/{drive.group(1).lower()}/" + drive.group(2).replace("\\", "/")
    # Absolute by its spelling, not by this platform's Path rules (a /mnt/c path is not "absolute" on Windows).
    absolute = raw.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", raw))
    gitdir = Path(raw) if absolute else (repo / raw).resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return None


def main_tree_root(start: Path = REPO) -> Path:
    """The primary checkout, where deploy-guard and preflight read (deploy_preflight._main_worktree_root's rule)."""
    dot_git = start / ".git"
    if dot_git.is_file():
        try:
            found = root_from_gitfile(dot_git.read_text(encoding="utf-8", errors="replace"), start,
                                      sys.platform.startswith("win"))
        except OSError:
            found = None
        if found is not None and found.is_dir():
            return found
    for args in (["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                 ["git", "rev-parse", "--git-common-dir"]):
        try:
            done = subprocess.run(args, cwd=str(start), capture_output=True, text=True, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        raw = (done.stdout or "").strip()
        if done.returncode != 0 or not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (start / common).resolve()
        if common.name == ".git" and common.parent.is_dir():
            return common.parent
    return start


def receipt_dir(root: Optional[Path] = None) -> Path:
    return (root or main_tree_root()) / RECEIPT_SUBDIR


def check_receipt(directory: Path, league: str, candidate_hash: str, current_hash: str, now: float,
                  accept_regression: str = "") -> tuple[Optional[str], dict]:
    """(problem or None, detail) for one changed key. Pure apart from reading the one file it names.

    Refuses on: no receipt for this exact transition; unreadable; a hash inside that does not match (a renamed
    file); a seed-salted noise check; scored by a rule other than DEFAULT_RULE_ID (read from the receipt's own fields,
    so a renamed opt-in receipt refuses too); older than MAX_RECEIPT_AGE_SECONDS or stamped in the future; fewer than
    MIN_GAMES scored; WORSE cells without `accept_regression`. Each refusal names its remedy."""
    path = Path(directory) / receipt_name(league, candidate_hash, current_hash)
    detail: dict[str, Any] = {"receipt": str(path), "league": league,
                              "candidate_hash": candidate_hash[:12], "current_hash": current_hash[:12]}
    if league not in LEAGUES:
        return (f"no outcome replay exists for league {league!r} (the gate replays {sorted(LEAGUES)}); extend "
                f"scripts/live_mechanism_outcome_gate.py or waive with --no-outcome-gate \"<reason>\""), detail
    if not path.is_file():
        return (f"no outcome-gate receipt for {league} {current_hash[:12]} -> {candidate_hash[:12]}: run "
                f"scripts/live_mechanism_outcome_gate.py on the fleet for this exact transition"), detail
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- unreadable is not a pass
        return f"outcome-gate receipt {path.name} is unreadable ({type(exc).__name__})", detail
    if receipt.get("candidate_hash") != candidate_hash or receipt.get("current_hash") != current_hash:
        return f"outcome-gate receipt {path.name} names a different transition than its file name", detail
    if int(receipt.get("seed_salt") or 0):
        return (f"outcome-gate receipt {path.name} is a seed-salted noise check (salt {receipt.get('seed_salt')}), "
                f"not a gate reading: run the gate without --seed-salt"), detail
    rule = receipt_rule_id(receipt)
    detail["rule"] = rule
    if rule != DEFAULT_RULE_ID:
        return (f"outcome-gate receipt {path.name} was scored by the opt-in rule {rule}, not the default "
                f"{DEFAULT_RULE_ID}; preflight takes only the default rule's verdict: re-run the gate without "
                f"--flag-rule / --current-salts / --family-cells / --family-alpha"), detail
    written = receipt.get("written_at")
    age = (now - float(written)) if isinstance(written, (int, float)) else None
    detail.update(written_at_iso=receipt.get("written_at_iso"), games=receipt.get("games"),
                  worse=receipt.get("worse") or [], better=receipt.get("better") or [])
    if age is None or age < -120:
        return f"outcome-gate receipt {path.name} has no readable written_at", detail
    detail["age_hours"] = round(age / 3600, 1)
    if age > MAX_RECEIPT_AGE_SECONDS:
        return (f"outcome-gate receipt {path.name} is {age / 86400:.1f} days old (limit "
                f"{MAX_RECEIPT_AGE_SECONDS // 86400}); re-run it on this season's games"), detail
    games = receipt.get("games")
    if not isinstance(games, int) or games < MIN_GAMES:
        return (f"outcome-gate receipt {path.name} scored {games} games (floor {MIN_GAMES}); widen --dates"), detail
    worse = receipt.get("worse") or []
    if worse and not str(accept_regression or "").strip():
        return ("the candidate scores WORSE beyond 1.96 SE on " + ", ".join(worse) + " (" + path.name + "). "
                "Do not load it, or accept with --accept-outcome-regression \"<reason>\""), detail
    if worse:
        detail["accepted_regression"] = str(accept_regression).strip()
    return None, detail


# --------------------------------------------------------------------------------------------------------------------
# Scoring. numpy only, imported inside, so the shared block above stays importable without it.
# --------------------------------------------------------------------------------------------------------------------

def _crps(samples: Iterable[float], y: float) -> float:
    import numpy as np

    x = np.sort(np.asarray(list(samples), float))
    n = len(x)
    return float(np.mean(np.abs(x - y)) - np.sum((2 * np.arange(1, n + 1) - n - 1) * x) / (n * n))


def game_features(cp: Mapping[str, Any], final_home: int, final_away: int) -> dict[str, float]:
    """Per game x checkpoint x arm. `cp` holds `rows` ([home window, away window, home OT, away OT] per sim), the
    score at the checkpoint (`h0`, `a0`) and the result's `home_win_prob`."""
    import numpy as np

    rows = np.asarray(cp["rows"], float)
    h0, a0 = float(cp.get("h0") or 0), float(cp.get("a0") or 0)
    margin = (h0 - a0) + rows[:, 0] - rows[:, 1] + rows[:, 2] - rows[:, 3]
    total = (h0 + a0) + rows[:, 0] + rows[:, 1] + rows[:, 2] + rows[:, 3]
    real_margin, real_total = final_home - final_away, final_home + final_away
    lo_m, hi_m = np.quantile(margin, [0.1, 0.9])
    lo_t, hi_t = np.quantile(total, [0.1, 0.9])
    p = min(max(float(cp["home_win_prob"]), 1e-3), 1 - 1e-3)
    win = 1.0 if final_home > final_away else 0.0
    return {
        "margin_crps": _crps(margin, real_margin),
        "margin_in80": float(lo_m <= real_margin <= hi_m),
        "total_crps": _crps(total, real_total),
        "total_in80": float(lo_t <= real_total <= hi_t),
        "win_brier": (p - win) ** 2,
        "win_logloss": -(win * np.log(p) + (1 - win) * np.log(1 - p)),
        "margin_sd": float(margin.std()),
        "margin_err": float(real_margin - margin.mean()),
        # The MEANS, reported as shifts (not scored): totals are served raw from the sim's mean, so a candidate that
        # moves the mean total moves every priced total, whether or not CRPS can resolve it.
        "total_mean": float(total.mean()),
        "margin_mean": float(margin.mean()),
    }


def score_cells(paired: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]], checkpoints: Iterable[str],
                draws: int = 1000, seed: int = 13) -> dict[str, dict[str, dict[str, float]]]:
    """paired[game][cp][arm] -> features (arm in {current, candidate}). Returns cells[cp][metric] with the arm means,
    the paired difference and its 1.96 x bootstrap SE. Coverage cells score |coverage - 0.80| per draw."""
    import numpy as np

    cells: dict[str, dict[str, dict[str, float]]] = {}
    for cp in checkpoints:
        games = sorted(g for g, by_cp in paired.items()
                       if cp in by_cp and {"current", "candidate"} <= set(by_cp[cp]))
        if not games:
            continue
        n = len(games)
        idx = np.random.default_rng(seed).integers(0, n, size=(draws, n))
        keys = ["margin_crps", "margin_in80", "total_crps", "total_in80", "win_brier", "win_logloss", "margin_sd",
                "margin_err"]
        has_means = all("total_mean" in paired[g][cp][arm] for g in games for arm in ("current", "candidate"))
        if has_means:
            keys += ["total_mean", "margin_mean"]
        col = {arm: {k: np.array([paired[g][cp][arm][k] for g in games], float) for k in keys}
               for arm in ("current", "candidate")}
        out: dict[str, dict[str, float]] = {"_n": {"games": float(n)}}
        for metric in METRICS:
            if metric.endswith("_cov80_dev"):
                base = "margin_in80" if metric.startswith("margin") else "total_in80"
                cur, cand = col["current"][base], col["candidate"][base]
                point = abs(cand.mean() - COVERAGE_NOMINAL) - abs(cur.mean() - COVERAGE_NOMINAL)
                boot = np.abs(cand[idx].mean(axis=1) - COVERAGE_NOMINAL) - np.abs(cur[idx].mean(axis=1) - COVERAGE_NOMINAL)
                out[metric] = {"current": float(abs(cur.mean() - COVERAGE_NOMINAL)),
                               "candidate": float(abs(cand.mean() - COVERAGE_NOMINAL)),
                               "current_coverage": float(cur.mean()), "candidate_coverage": float(cand.mean()),
                               "diff": float(point), "se196": float(1.96 * boot.std())}
            else:
                cur, cand = col["current"][metric], col["candidate"][metric]
                d = cand - cur
                out[metric] = {"current": float(cur.mean()), "candidate": float(cand.mean()),
                               "diff": float(d.mean()), "se196": float(1.96 * d[idx].mean(axis=1).std())}
        out["_info"] = {"margin_sd_current": float(col["current"]["margin_sd"].mean()),
                        "margin_sd_candidate": float(col["candidate"]["margin_sd"].mean()),
                        "resid_sd_current": float(col["current"]["margin_err"].std()),
                        "resid_sd_candidate": float(col["candidate"]["margin_err"].std())}
        if has_means:
            for name in ("total_mean", "margin_mean"):
                d = col["candidate"][name] - col["current"][name]
                out["_info"][f"{name}_shift"] = float(d.mean())
                out["_info"][f"{name}_shift_se196"] = float(1.96 * d[idx].mean(axis=1).std())
        cells[cp] = out
    return cells


def flag_cells(cells: Mapping[str, Mapping[str, Mapping[str, float]]]) -> tuple[list[str], list[str]]:
    """(worse, better) as `cp:metric` labels. Every metric is lower-is-better."""
    worse, better = [], []
    for cp, by_metric in cells.items():
        for metric in METRICS:
            cell = by_metric.get(metric)
            if not cell:
                continue
            if cell["diff"] - cell["se196"] > 0:
                worse.append(f"{cp}:{metric}")
            elif cell["diff"] + cell["se196"] < 0:
                better.append(f"{cp}:{metric}")
    return worse, better


def current_salt_list(k: int) -> list[int]:
    """The current arm's K salts: 0 (production's seed) then CURRENT_SALT_BASE + 1 .. K - 1."""
    return [0] + [CURRENT_SALT_BASE + j for j in range(1, max(1, int(k)))]


def average_arms(arms: list) -> dict:
    """features[game][cp] averaged over K draws of the same value. A game x checkpoint missing from ANY draw is
    dropped, so every averaged value rests on all K. Each draw's metric is averaged (not its sims pooled), so the
    finite-sims terms in Brier and CRPS stay the same size as the candidate's single draw. K = 1 returns the draw."""
    if not arms:
        return {}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for game, by_cp in arms[0].items():
        for cp, feats in by_cp.items():
            rows = [a.get(game, {}).get(cp) for a in arms]
            if any(r is None for r in rows):
                continue
            keys = set(feats).intersection(*(set(r) for r in rows))
            out.setdefault(game, {})[cp] = {k: float(sum(r[k] for r in rows) / len(rows)) for k in sorted(keys)}
    return out


def pair(current: Mapping[str, Mapping[str, Mapping[str, float]]],
         candidate: Mapping[str, Mapping[str, Mapping[str, float]]]) -> dict:
    """paired[game][cp] = {current, candidate} for every game x checkpoint both arms scored."""
    paired: dict[str, dict[str, dict[str, Mapping[str, float]]]] = {}
    for game, by_cp in candidate.items():
        for cp, feats in by_cp.items():
            cur = current.get(game, {}).get(cp)
            if cur is not None:
                paired.setdefault(game, {})[cp] = {"current": cur, "candidate": feats}
    return paired


def family_flags(paired: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]], checkpoints: Iterable[str],
                 alpha: float = FAMILY_ALPHA, draws: int = FAMILY_DRAWS, seed: int = 17,
                 metrics: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """WORSE / BETTER against a family-wise max-T critical value, one-sided each way.

    ONE joint bootstrap over games: a game drawn once counts at every checkpoint it has, so the cells' draws are
    correlated the way the cells are. Per cell z = diff / sd(boot). The WORSE critical value is the (1 - alpha)
    quantile over draws of max over the FAMILY's cells of (boot - diff) / sd, so a null change crosses it in ANY family
    cell with probability about alpha. BETTER is the mirror. A cell whose draws do not vary (identical arms) is never
    flagged. `metrics` (default: all of METRICS) names the family; every other metric still gets its z, listed under
    `report_only`, and is never flagged. The bootstrap does not depend on the family, so a cell's z is the same
    whichever family it is scored in."""
    import numpy as np

    cps = list(checkpoints)
    family = tuple(metrics) if metrics is not None else METRICS
    unknown = [m for m in family if m not in METRICS]
    if unknown or not family:
        raise ValueError(f"family metrics must be a non-empty subset of {METRICS}: {unknown or 'empty'}")
    games = sorted({g for g, by_cp in paired.items() for cp in cps
                    if cp in by_cp and {"current", "candidate"} <= set(by_cp[cp])})
    result: dict[str, Any] = {"rule": f"max-T family-wise one-sided alpha {alpha} over {len(family)} metrics",
                              "alpha": alpha, "draws": draws, "metrics": list(family), "report_only": [],
                              "worse": [], "better": [], "z": {}, "critical_worse": None, "critical_better": None,
                              "n_cells": 0, "games": len(games)}
    if not games:
        return result
    n = len(games)
    idx = np.random.default_rng(seed).integers(0, n, size=(draws, n))
    weights = np.bincount((idx + n * np.arange(draws)[:, None]).ravel(), minlength=draws * n).reshape(draws, n)
    weights = weights.astype(float)
    labels, points, boots = [], [], []
    for cp in cps:
        mask = np.array([1.0 if cp in paired[g] and {"current", "candidate"} <= set(paired[g][cp]) else 0.0
                         for g in games])
        if not mask.any():
            continue
        wsum = weights @ mask
        live = wsum > 0

        def col(arm: str, key: str):
            return np.array([float(paired[g][cp][arm][key]) if mask[i] else 0.0 for i, g in enumerate(games)])

        for metric in METRICS:
            if metric.endswith("_cov80_dev"):
                base = "margin_in80" if metric.startswith("margin") else "total_in80"
                cur, cand = col("current", base) * mask, col("candidate", base) * mask
                point = abs(cand.sum() / mask.sum() - COVERAGE_NOMINAL) - abs(cur.sum() / mask.sum() - COVERAGE_NOMINAL)
                safe = np.where(live, wsum, 1.0)
                boot = np.abs(weights @ cand / safe - COVERAGE_NOMINAL) - np.abs(weights @ cur / safe - COVERAGE_NOMINAL)
            else:
                d = (col("candidate", metric) - col("current", metric)) * mask
                point = d.sum() / mask.sum()
                boot = weights @ d / np.where(live, wsum, 1.0)
            boot = np.where(live, boot, point)
            labels.append(f"{cp}:{metric}")
            points.append(float(point))
            boots.append(boot)
    point_arr, boot_arr = np.array(points), np.vstack(boots)
    sd = boot_arr.std(axis=1)
    ok = sd > 0
    safe_sd = np.where(ok, sd, 1.0)
    z = np.where(ok, point_arr / safe_sd, 0.0)
    t = np.where(ok[:, None], (boot_arr - point_arr[:, None]) / safe_sd[:, None], 0.0)
    in_family = np.array([lab.split(":", 1)[1] in family for lab in labels])
    tf = t[in_family]
    crit_w = float(np.quantile(tf.max(axis=0), 1 - alpha))
    crit_b = float(np.quantile((-tf).max(axis=0), 1 - alpha))
    result.update(
        n_cells=int(in_family.sum()), critical_worse=crit_w, critical_better=crit_b,
        z={lab: float(v) for lab, v in zip(labels, z)},
        report_only=[lab for lab, f in zip(labels, in_family) if not f],
        worse=[lab for lab, v, o, f in zip(labels, z, ok, in_family) if f and o and v > crit_w],
        better=[lab for lab, v, o, f in zip(labels, z, ok, in_family) if f and o and -v > crit_b],
    )
    return result


def write_receipt(directory: Path, payload: Mapping[str, Any]) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / receipt_name(payload["league"], payload["candidate_hash"], payload["current_hash"],
                                    int(payload.get("seed_salt") or 0), receipt_rule_id(payload))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------------------------------------------------
# The replay (fleet only: production's engine, the fleet's data root, a forked pool).
# --------------------------------------------------------------------------------------------------------------------

def role_environ(worker_script: str, keys: Iterable[str]) -> dict[str, str]:
    """The running worker's values for `keys` only, from /proc. Raises when the worker cannot be found or read."""
    wanted = set(keys)
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "python" not in cmd or worker_script not in cmd:
            continue
        out: dict[str, str] = {}
        for item in (proc / "environ").read_bytes().split(b"\0"):
            key, sep, value = item.decode("utf-8", "replace").partition("=")
            if sep and key in wanted:
                out[key] = value
        return out
    raise RuntimeError(f"no running process for {worker_script}")


def _season(date: str) -> int:
    day = dt.date.fromisoformat(date)
    return day.year + 1 if day.month >= 7 else day.year  # ESPN's season is the year it ends


def expand_dates(spec: str) -> list[str]:
    out: list[str] = []
    for part in [p.strip() for p in str(spec).split(",") if p.strip()]:
        if ".." in part:
            lo, hi = (dt.date.fromisoformat(x) for x in part.split(".."))
            while lo <= hi:
                out.append(lo.isoformat())
                lo += dt.timedelta(days=1)
        else:
            out.append(dt.date.fromisoformat(part).isoformat())
    return out


_HARNESS = None


def _harness():
    global _HARNESS
    if _HARNESS is None:
        import importlib.util

        sys.path.insert(0, str(REPO))
        spec = importlib.util.spec_from_file_location("bbi_outcome_gate", REPO / "scripts" / "backtest_basketball_intervals.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _HARNESS = module
    return _HARNESS


def ncaab_tasks(data_root: Path, date: str) -> tuple[list[dict], dict]:
    """Completed men's D1 games of one date with matched finals, play-by-play and the ids production priced."""
    import csv

    s = _harness()
    season = _season(date)
    games_csv = data_root / "ncaab_source" / "data" / "processed" / "rotation_stints" / f"games_{date}.csv"
    pregame_path = data_root / "ncaab_source" / "data" / "pregame_sim" / f"pregame_sim_{date}.json"
    cov = {"table_rows": 0, "score_match": 0, "events": 0, "priced_ids": 0}
    if not games_csv.is_file() or not pregame_path.is_file():
        cov["missing"] = [p.name for p in (games_csv, pregame_path) if not p.is_file()]
        return [], cov
    pregame = (json.loads(pregame_path.read_text(encoding="utf-8")) or {}).get("games") or {}
    box = s.read_box(data_root, "ncaab", date)
    tasks = []
    with games_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cov["table_rows"] += 1
            if str(row.get("score_match")) != "1" or str(row.get("season")) != str(season):
                continue
            cov["score_match"] += 1
            events = s.events_path(data_root, "ncaab", season, row["event_id"])
            if not events.is_file():
                continue
            cov["events"] += 1
            p = pregame.get(str(row["event_id"]))
            if not p:
                continue
            cov["priced_ids"] += 1
            tasks.append({"league": "ncaab", "game_id": str(row["event_id"]), "date": date,
                          "phase": row.get("season_type") or "", "season": season, "events_path": str(events),
                          "final": {"home": row.get("official_home"), "away": row.get("official_away")},
                          "game_row": row, "box_rows": box.get(str(row["event_id"]), []),
                          "team_ids": {"home": str(p["home"]["espn_id"]), "away": str(p["away"]["espn_id"])},
                          "neutral": bool(p.get("neutral_site")),
                          "codes": {"home": str(p["home"].get("abbr") or ""), "away": str(p["away"].get("abbr") or "")}})
    return tasks, cov


def build_jobs(tasks: Iterable[dict], arms: Iterable[tuple], checkpoints: Mapping[str, float], sims: int) -> list[tuple]:
    """One job per game and arm. `arms` = (arm_id, value, salt): each arm carries its own salt, so the current arm's K
    draws and every candidate (or A/A) arm are explicit."""
    arms = list(arms)
    return [(t, arm_id, value, checkpoints, sims, int(salt or 0)) for t in tasks for arm_id, value, salt in arms]


def _replay_one(job) -> dict:
    task, arm, value, checkpoints, sims, salt = job
    try:
        return _replay_ncaab(task, arm, value, checkpoints, sims, salt)
    except Exception:  # noqa: BLE001 -- a failed game is reported, never silently dropped
        return {"game_id": task["game_id"], "arm": arm, "error": traceback.format_exc()[-1200:]}


def _replay_ncaab(task, arm, value, checkpoints, sims, salt=0) -> dict:
    from syndicate.features.basketball_engine.resume import GameState
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.shared import basketball_interval_backtest as bib

    if value:
        os.environ[lr.LIVE_MECHANISMS_ENV] = value
    else:
        os.environ.pop(lr.LIVE_MECHANISMS_ENV, None)
    mech = lr.live_mechanisms_from_env()
    game = _harness().build_game(task)
    inputs = lr.build_engine_inputs(task["date"], task["team_ids"]["home"], task["team_ids"]["away"],
                                    neutral=task["neutral"], home_code=task["codes"]["home"],
                                    away_code=task["codes"]["away"])
    if isinstance(inputs, lr.NcaabResimRefusal):
        return {"game_id": task["game_id"], "arm": arm, "refusal": inputs.reason}
    cfg = inputs["cfg"]
    off = [k for k, v in mech.items() if getattr(cfg, k) != v]
    if off:  # the arm must actually reach the engine config, or the comparison is of nothing
        return {"game_id": task["game_id"], "arm": arm, "error": f"cfg does not carry {off}"}
    names: dict[str, str] = {}
    for frame in (inputs["home_players"], inputs["away_players"]):
        names.update({str(k): str(v) for k, v in zip(frame["athlete_id"], frame["player_name"])})
    engine = lr.ncaab_engine(league="ncaab")
    kwargs = {k: inputs[k] for k in lr._ENGINE_KWARGS}
    out = {"game_id": task["game_id"], "arm": arm, "final": task["final"], "mechanisms": sorted(mech), "cps": {}}
    for cp, t in checkpoints.items():
        if t <= 0:
            state_obj, h0, a0, seed_key = GameState(), 0, 0, 0
        else:
            state = bib.state_at(game, t)
            state_obj, _ = bib.resume_game_state(game, state, names, with_floor=True)
            h0, a0, seed_key = int(state.home_score), int(state.away_score), int(round(state.elapsed))
        rows: list[list[int]] = []

        def simulate(rng, g, h0=h0, a0=a0, rows=rows):
            hb, ab, hq, aq = engine.simulate_pbp_game_boxscore(rng=rng, **kwargs, state=g)
            rows.append([int(sum(hq[:2])) - h0, int(sum(aq[:2])) - a0, lr._ot_points(hb), lr._ot_points(ab)])
            return hb, ab, hq, aq

        seed = salted_seed(lr.stable_seed(task["game_id"], seed_key, "ncaab"), salt)
        res = lr.resim_live_game(inputs, state_obj, sims=sims, base_seed=seed, simulate=simulate, league="ncaab")
        if isinstance(res, lr.NcaabResimRefusal):
            out["cps"][cp] = {"refusal": res.reason}
            continue
        out["cps"][cp] = {"rows": rows, "h0": h0, "a0": a0, "home_win_prob": res["home_win_prob"]}
    return out


def run_arms(league: str, arms: Iterable[tuple], dates: list[str], data_root: Path, sims: int, procs: int,
             log=print) -> tuple[dict, dict]:
    """(features[arm_id][game][cp], coverage) for every (arm_id, value, salt) in `arms`, in one pool."""
    from multiprocessing import get_context

    spec = LEAGUES[league]
    arms = list(arms)
    tasks, coverage = [], {}
    for date in dates:
        got, cov = ncaab_tasks(data_root, date)
        coverage[date] = cov
        tasks += got
    log(f"tasks {len(tasks)} over {len(dates)} dates x {len(arms)} arms")
    jobs = build_jobs(tasks, arms, spec["checkpoints"], sims)
    by_arm: dict[str, dict[str, dict[str, dict[str, float]]]] = {arm_id: {} for arm_id, _v, _s in arms}
    notes: dict[str, int] = {}
    with get_context("fork").Pool(procs) as pool:
        for i, res in enumerate(pool.imap_unordered(_replay_one, jobs), 1):
            if "error" in res or "refusal" in res:
                key = f"{res['arm']}:{res.get('refusal') or 'error'}"
                notes[key] = notes.get(key, 0) + 1
                if "error" in res and notes[key] <= 3:
                    log(f"ERROR {res['game_id']} {res['arm']}: {res['error'][-400:]}")
                continue
            try:
                fh, fa = int(float(res["final"]["home"])), int(float(res["final"]["away"]))
            except (TypeError, ValueError, KeyError):
                notes["no_final"] = notes.get("no_final", 0) + 1
                continue
            for cp, data in res["cps"].items():
                if "rows" in data:
                    by_arm[res["arm"]].setdefault(res["game_id"], {})[cp] = game_features(data, fh, fa)
            if i % 100 == 0:
                log(f"{i}/{len(jobs)} game-arms done")
    coverage["_notes"] = notes
    return by_arm, coverage


def _git_head(path: Path) -> str:
    """The code commit the replay ran. From WSL a Windows worktree's `.git` file names a `C:/` gitdir that git
    cannot follow, so retry with the translated gitdir (the same translation as `root_from_gitfile`)."""
    commands = [["git", "rev-parse", "HEAD"]]
    dot_git = path / ".git"
    if dot_git.is_file():
        match = re.match(r"^\s*gitdir:\s*(.+?)\s*$", dot_git.read_text(encoding="utf-8", errors="replace"), re.M)
        drive = re.match(r"^([A-Za-z]):[\\/](.*)$", match.group(1)) if match else None
        if drive and not sys.platform.startswith("win"):
            gitdir = f"/mnt/{drive.group(1).lower()}/" + drive.group(2).replace("\\", "/")
            commands.append(["git", f"--git-dir={gitdir}", "rev-parse", "HEAD"])
    for command in commands:
        try:
            done = subprocess.run(command, cwd=str(path), capture_output=True, text=True, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return ""


def _read_value(text: Optional[str], path: Optional[str]) -> Optional[str]:
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    return text


def _print_candidate(label: str, cps: list, cells: Mapping, fam: Mapping, flag_rule: str, worse: list, better: list,
                     legacy: Mapping) -> None:
    for cp in cps:
        if cp not in cells:
            continue
        c = cells[cp]
        i = c["_info"]
        print(f"\n### {label} {cp}: {int(c['_n']['games'])} games | margin SD {i['margin_sd_current']:.2f} -> "
              f"{i['margin_sd_candidate']:.2f} | real SD of (final - mean) {i['resid_sd_current']:.2f} -> "
              f"{i['resid_sd_candidate']:.2f}")
        if "total_mean_shift" in i:
            print(f"  mean shift (not scored): total {i['total_mean_shift']:+.3f} +- {i['total_mean_shift_se196']:.3f}"
                  f" | home margin {i['margin_mean_shift']:+.3f} +- {i['margin_mean_shift_se196']:.3f}")
        for metric in METRICS:
            m = c[metric]
            cell = f"{cp}:{metric}"
            tag = "  WORSE" if cell in worse else "  better" if cell in better else ""
            extra = (f" (coverage {m['current_coverage']:.3f} -> {m['candidate_coverage']:.3f})"
                     if "current_coverage" in m else "")
            z = fam.get("z", {}).get(cell)
            zs = f"  z {z:+.2f}" if z is not None else ""
            report_only = "  (reported, not flagged)" if flag_rule == "family" and cell in fam.get("report_only", ()) else ""
            print(f"  {metric:16s} {m['current']:.4f} -> {m['candidate']:.4f}  diff {m['diff']:+.4f} +- {m['se196']:.4f}"
                  f"{zs}{extra}{tag}{report_only}")
    if fam.get("critical_worse") is None:
        print(f"\n{label}: no cell scored")
    elif flag_rule == "family":
        print(f"\n{label}: family rule, critical z {fam['critical_worse']:+.2f} (worse) / {fam['critical_better']:+.2f} "
              f"(better), alpha {fam['alpha']} over {fam['n_cells']} cells ({', '.join(fam.get('metrics', []))})")
    else:
        print(f"\n{label}: per-cell rule (1.96 x SE per cell; the pre-2026-11-13 rule)")
    print(f"{label}: WORSE {worse or 'none'} | better {better or 'none'}")
    print(f"{label}: legacy (current salt 0 only, 1.96 per cell): WORSE {legacy['worse'] or 'none'} | "
          f"better {legacy['better'] or 'none'}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True)
    ap.add_argument("--candidate", help="the new value (JSON); '' means unset")
    ap.add_argument("--candidate-file", action="append", default=[],
                    help="a file holding a candidate value; repeat to score several against one shared current arm")
    ap.add_argument("--current", help="the value running now; default: read from the running role")
    ap.add_argument("--current-file")
    ap.add_argument("--current-from-role", action="store_true", default=None,
                    help="read the current value (and the switches) from the running role's environ (default when "
                         "--current is not given)")
    ap.add_argument("--dates", required=True, help="YYYY-MM-DD, comma list or A..B ranges, of the CURRENT season")
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", ""))
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--min-games", type=int, default=MIN_GAMES)
    ap.add_argument("--receipt-dir", default="", help="default: <main tree>/.syndicate/deploy/outcome_gate")
    ap.add_argument("--seed-salt", type=int, default=0,
                    help="re-seed every CANDIDATE arm (a candidate equal to current then is a noise check). The "
                         "receipt gets its own name and can never clear preflight. 0 = the gate's own seeds")
    ap.add_argument("--aa-salts", default="",
                    help="comma list: also score the CURRENT value against itself with these candidate salts (A/A "
                         "noise checks; their receipts never clear preflight)")
    ap.add_argument("--current-salts", type=int, default=DEFAULT_CURRENT_SALTS,
                    help=f"the current arm is the mean of this many seed-salted draws (default {DEFAULT_CURRENT_SALTS}: "
                         "one draw, production's seeds)")
    ap.add_argument("--flag-rule", choices=("family", "per-cell"), default=DEFAULT_FLAG_RULE,
                    help="per-cell = 1.96 x SE per cell (default); family = max-T family-wise (opt-in: it did not "
                         "refuse RC46 on 2026-11-13, see THE FLAG RULE)")
    ap.add_argument("--family-cells", choices=tuple(FAMILY_CELLS), default=DEFAULT_FAMILY_CELLS,
                    help="the family rule's cells: all 30, or the 20 smooth ones (coverage reported, never flagged; "
                         "opt-in, under confirmation in lane gate-smooth-family)")
    ap.add_argument("--family-alpha", type=float, default=FAMILY_ALPHA)
    ap.add_argument("--dump-arms", default="", help="write every arm's per-game features (JSON) here")
    args = ap.parse_args(argv)
    if args.seed_salt < 0:
        print("REFUSE: --seed-salt must be >= 0")
        return 2
    if args.current_salts < 1:
        print("REFUSE: --current-salts must be >= 1")
        return 2
    if not 0 < args.family_alpha < 0.5:
        print("REFUSE: --family-alpha must be in (0, 0.5)")
        return 2
    try:
        aa_salts = [int(s) for s in str(args.aa_salts or "").replace(" ", "").split(",") if s]
    except ValueError:
        print("REFUSE: --aa-salts is a comma list of integers")
        return 2
    cur_salts = current_salt_list(args.current_salts)
    if any(s <= 0 or s in cur_salts for s in aa_salts) or len(set(aa_salts)) != len(aa_salts):
        print(f"REFUSE: --aa-salts must be distinct, > 0 and outside the current arm's salts {cur_salts}")
        return 2

    league = args.league.lower()
    if league not in LEAGUES:
        print(f"REFUSE: no replay for league {league!r}; supported: {sorted(LEAGUES)}")
        return 2
    spec = LEAGUES[league]
    candidates: list[tuple[str, str, int]] = []  # (label, value, salt)
    if args.candidate is not None:
        candidates.append(("candidate", args.candidate, args.seed_salt))
    for i, path in enumerate(args.candidate_file):
        label = "candidate" if args.candidate is None and len(args.candidate_file) == 1 else f"cand{i + 1}"
        candidates.append((label, _read_value(None, path), args.seed_salt))
    if not candidates and not aa_salts:
        print("REFUSE: give --candidate, --candidate-file or --aa-salts")
        return 2
    current = _read_value(args.current, args.current_file)
    switches: dict[str, str] = {}
    if current is None or args.current_from_role:
        try:
            env = role_environ(spec["worker_script"], (spec["env_key"], *spec["switch_keys"]))
        except Exception as exc:  # noqa: BLE001
            print(f"REFUSE: cannot read the running {spec['role']} ({type(exc).__name__}: {exc})")
            return 2
        if current is None:
            current = env.get(spec["env_key"], "")
        switches = {k: env[k] for k in spec["switch_keys"] if k in env}
    candidates += [(f"aa{s}", current, s) for s in aa_salts]
    if not args.data_root:
        print("REFUSE: --data-root (or SYNDICATE_DATA_ROOT) is required: the fleet's data, never a checkout's mirror")
        return 2
    data_root = Path(args.data_root).expanduser()
    os.environ["SYNDICATE_DATA_ROOT"] = str(data_root)
    for key in spec["switch_keys"]:
        os.environ.pop(key, None)
    os.environ.update(switches)

    # Each value must parse to exactly its own fields: the parser turns ANY unknown field into {} (every mechanism
    # off), which would replay a different config than the one being loaded.
    sys.path.insert(0, str(REPO))
    from syndicate.features.ncaab import live_resim as lr

    for label, value in [("current", current)] + [(lab, val) for lab, val, _s in candidates]:
        try:
            want = json.loads(value) if canonical_value(value) else {}
        except ValueError:
            print(f"REFUSE: the {label} value is not JSON")
            return 2
        if not isinstance(want, dict):
            print(f"REFUSE: the {label} value is not a JSON object")
            return 2
        got = lr.live_mechanisms_from_env({spec["env_key"]: value})
        if len(got) != len(want):
            print(f"REFUSE: the {label} value parses to {len(got)} of its {len(want)} fields with this code")
            return 2
    for label, value, salt in candidates:
        if canonical_value(value) == canonical_value(current) and (not salt or salt in cur_salts):
            print(f"REFUSE: {label} is the current value with a salt the current arm uses ({salt}); there is no "
                  f"transition to score (an A/A noise check needs --aa-salts or --seed-salt outside {cur_salts})")
            return 2

    dates = expand_dates(args.dates)
    t0 = time.time()
    code = _git_head(REPO)
    rule = rule_id(args.flag_rule, args.current_salts, args.family_cells, args.family_alpha)
    opt_in = "" if rule == DEFAULT_RULE_ID else f" (OPT-IN: its receipts are named __rule-{rule} and never clear preflight)"
    print(f"league {league} key {spec['env_key']} dates {dates[0]}..{dates[-1]} ({len(dates)}) sims {args.sims} "
          f"switches {sorted(switches)} code {code[:9]} current arm = mean of {len(cur_salts)} draws {cur_salts} "
          f"flag rule {args.flag_rule} rule {rule}{opt_in}", flush=True)
    print(f"current   {canonical_value(current) or '(unset)'}", flush=True)
    for label, value, salt in candidates:
        noise = " (NOISE CHECK, not a gate reading)" if canonical_value(value) == canonical_value(current) else ""
        print(f"{label:9s} {canonical_value(value) or '(unset)'} salt {salt}{noise}", flush=True)
    arms = [(f"current@{s}", current, s) for s in cur_salts] + [(label, value, salt) for label, value, salt in candidates]
    by_arm, coverage = run_arms(league, arms, dates, data_root, args.sims, args.procs, log=lambda m: print(m, flush=True))
    cps = list(spec["checkpoints"])
    current_avg = average_arms([by_arm[f"current@{s}"] for s in cur_salts])
    if args.dump_arms:
        dump = {"league": league, "env_key": spec["env_key"], "dates": dates, "sims": args.sims, "code_commit": code,
                "current_hash": value_hash(current), "current_salts": cur_salts,
                "arms": {arm_id: {"value_hash": value_hash(value), "salt": salt, "games": by_arm[arm_id]}
                         for arm_id, value, salt in arms}}
        path = Path(args.dump_arms).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dump), encoding="utf-8")
        os.replace(tmp, path)
        print(f"ARMS {path}")
    rc = 0
    for label, value, salt in candidates:
        paired = pair(current_avg, by_arm[label])
        cells = score_cells(paired, cps)
        fam = family_flags(paired, cps, alpha=args.family_alpha, metrics=FAMILY_CELLS[args.family_cells])
        worse, better = (fam["worse"], fam["better"]) if args.flag_rule == "family" else flag_cells(cells)
        legacy_cells = score_cells(pair(by_arm["current@0"], by_arm[label]), cps)
        lw, lb = flag_cells(legacy_cells)
        legacy = {"current_salts": [0], "rule": "per-cell 1.96 x SE", "cells": legacy_cells, "worse": lw, "better": lb}
        _print_candidate(label, cps, cells, fam, args.flag_rule, worse, better, legacy)
        games = min((int(cells[cp]["_n"]["games"]) for cp in cells), default=0)
        if games < args.min_games or games < MIN_GAMES:
            print(f"{label}: NO RECEIPT: {games} games scored on every checkpoint, floor "
                  f"{max(args.min_games, MIN_GAMES)}. Widen --dates.")
            rc = 2
            continue
        payload = {
            "league": league, "env_key": spec["env_key"],
            "candidate_hash": value_hash(value), "current_hash": value_hash(current),
            "candidate": canonical_value(value), "current": canonical_value(current),
            "dates": dates, "games": games, "sims": args.sims, "checkpoints": spec["checkpoints"], "seed_salt": salt,
            "current_salts": cur_salts, "flag_rule": args.flag_rule, "family_cells": args.family_cells,
            "rule_id": rule,
            "family": {k: fam[k] for k in ("rule", "alpha", "draws", "critical_worse", "critical_better", "n_cells",
                                            "metrics", "report_only", "z", "worse", "better")},
            "legacy": legacy,
            "switches": {k: bool(str(v).strip()) for k, v in switches.items()},
            "code_commit": code, "data_root": str(data_root),
            "coverage": coverage, "cells": cells, "worse": worse, "better": better,
            "written_at": time.time(),
            "written_at_iso": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_seconds": round(time.time() - t0, 1),
        }
        path = write_receipt(Path(args.receipt_dir) if args.receipt_dir else receipt_dir(), payload)
        print(f"{label}: RECEIPT {path}")
        if worse and rc == 0:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
