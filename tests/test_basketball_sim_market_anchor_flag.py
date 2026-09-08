"""P3 (pricing plane v1, step 2): the basketball sim's pre-simulation market
anchoring is a FLAGGED, RECORDED mechanism.

`SYNDICATE_BASKETBALL_SIM_MARKET_ANCHOR` = on (default, bit-identical to the
pre-flag code) | off (no blend at all) | weights:<tw>,<mw>.

The tests here are about REACHABILITY as much as output: under `off` the blend
function must never execute (wrapper port AND the vendor fallback), and the
artifact must carry the raw model means in every state so a row can be
de-anchored post hoc.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import syndicate.features.shared.basketball_props_smart_sim as smart_sim

FLAG = smart_sim._MARKET_ANCHOR_ENV_LOCAL


def _game_inputs(*, market_total: float | None = 165.5, market_home_spread: float | None = -3.5):
    return smart_sim.GameInputsLocal(
        date="2026-07-22",
        home=smart_sim.TeamContextLocal(team="LVA", pace=79.5, off_rating=105.0, def_rating=99.0),
        away=smart_sim.TeamContextLocal(team="NYL", pace=79.5, off_rating=103.0, def_rating=101.0),
        market_total=market_total,
        market_home_spread=market_home_spread,
    )


def _simulate(tmp_path: Path, *, seed: int = 123, inp=None, n_samples: int = 1000):
    np.random.seed(seed)
    return smart_sim._simulate_quarters_local(
        processed_root=tmp_path,
        inp=inp if inp is not None else _game_inputs(),
        league=smart_sim._WNBA_LEAGUE_LOCAL,
        n_samples=n_samples,
    )


def _pre_flag_blend(home_mu: float, away_mu: float, market_total, market_home_spread, w_total: float, w_margin: float, min_team_pts: float):
    """The blend as it stood in `_simulate_quarters_local` before the flag, verbatim.

    Kept so `on` is checked against what it replaced, not against a restatement
    of the new code.
    """
    if market_total is not None:
        mt = float(market_total)
        cur_total_mu = home_mu + away_mu
        blend_total = w_total * mt + (1.0 - w_total) * cur_total_mu
        scale = blend_total / max(1e-6, cur_total_mu)
        home_mu *= scale
        away_mu *= scale
    cur_total_mu = home_mu + away_mu
    margin_mu = home_mu - away_mu
    if market_home_spread is not None:
        ms = float(market_home_spread)
        target_margin_mu = w_margin * (-ms) + (1.0 - w_margin) * margin_mu
        home_mu = 0.5 * (cur_total_mu + target_margin_mu)
        away_mu = 0.5 * (cur_total_mu - target_margin_mu)
        if home_mu < min_team_pts:
            home_mu = min_team_pts
            away_mu = cur_total_mu - home_mu
        if away_mu < min_team_pts:
            away_mu = min_team_pts
            home_mu = cur_total_mu - away_mu
    return home_mu, away_mu


def _summary_tuple(qsum):
    return (
        [(q.q, q.home_pts_mu, q.home_pts_sigma, q.away_pts_mu, q.away_pts_sigma, q.corr) for q in qsum.quarters],
        qsum.final_total_mu,
        qsum.final_total_sigma,
        qsum.final_margin_mu,
        qsum.final_margin_sigma,
        dict(qsum.probs),
        dict(qsum.evs),
    )


# --- flag parsing --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, state, total_w, margin_w",
    [
        (None, "on", None, None),
        ("", "on", None, None),
        ("on", "on", None, None),
        ("ON", "on", None, None),
        ("off", "off", None, None),
        ("weights:0.5,0.5", "weights", 0.5, 0.5),
        ("weights: 0.25 , 1.0", "weights", 0.25, 1.0),
        ("weights:1.5,-1", "weights", 1.0, 0.0),  # clamped, like the vendor
    ],
)
def test_policy_parse(raw, state, total_w, margin_w):
    policy = smart_sim._market_anchor_policy_local(raw)
    assert policy.state == state
    assert policy.total_w == total_w
    assert policy.margin_w == margin_w


@pytest.mark.parametrize("raw", ["weights:0.5", "weights:a,b", "weights:", "sideways", "0.7"])
def test_malformed_flag_falls_back_to_on_and_says_so(raw, capsys):
    policy = smart_sim._market_anchor_policy_local(raw)
    assert policy.state == "on"
    assert policy.enabled
    out = capsys.readouterr().out
    assert FLAG in out and "falling back to 'on'" in out


def test_policy_reads_environment(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    assert smart_sim._market_anchor_policy_local().state == "on"
    monkeypatch.setenv(FLAG, "off")
    assert smart_sim._market_anchor_policy_local().state == "off"
    monkeypatch.setenv(FLAG, "weights:0.3,0.9")
    policy = smart_sim._market_anchor_policy_local()
    assert (policy.state, policy.total_w, policy.margin_w) == ("weights", 0.3, 0.9)


# --- flag absent == on == pre-flag arithmetic, bit for bit -----------------------


def test_flag_absent_is_bit_identical_to_on_and_to_pre_flag_arithmetic(tmp_path, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    absent = _simulate(tmp_path)
    monkeypatch.setenv(FLAG, "on")
    explicit_on = _simulate(tmp_path)

    assert _summary_tuple(absent) == _summary_tuple(explicit_on)

    rec = absent.market_anchor
    assert rec["state"] == "on"
    assert (rec["total_w"], rec["margin_w"]) == (0.7, 0.95)  # no quarters_blend_weights.json in tmp
    assert (rec["market_total"], rec["market_spread"]) == (165.5, -3.5)

    # Recover the raw team means from the record (total/margin pin them
    # uniquely) and push them through the VERBATIM pre-flag blend.
    raw_home = 0.5 * (rec["model_total_raw"] + rec["model_margin_raw"])
    raw_away = 0.5 * (rec["model_total_raw"] - rec["model_margin_raw"])
    exp_home, exp_away = _pre_flag_blend(raw_home, raw_away, 165.5, -3.5, 0.7, 0.95, float(smart_sim._WNBA_LEAGUE_LOCAL.min_team_points))
    assert rec["anchored_total"] == pytest.approx(exp_home + exp_away, abs=1e-9)
    assert rec["anchored_margin"] == pytest.approx(exp_home - exp_away, abs=1e-9)
    # ...and the anchor really moved the means (the raw model is NOT at market).
    assert rec["anchored_total"] != pytest.approx(rec["model_total_raw"], abs=1e-6)
    assert rec["anchored_margin"] == pytest.approx(0.95 * 3.5 + 0.05 * (rec["model_margin_raw"] * (rec["anchored_total"] / rec["model_total_raw"])), abs=1e-9)


def test_on_calls_the_blend_function_exactly_once(tmp_path, monkeypatch):
    """Positive control for the `off` reachability test below."""
    monkeypatch.setenv(FLAG, "on")
    calls: list[dict] = []
    real = smart_sim._apply_market_anchor_local

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(smart_sim, "_apply_market_anchor_local", spy)
    _simulate(tmp_path)
    assert len(calls) == 1
    assert (calls[0]["w_total"], calls[0]["w_margin"]) == (0.7, 0.95)


# --- off: unreachable blend, means equal the raw model ---------------------------


def test_off_never_reaches_the_blend_and_means_equal_raw_model(tmp_path, monkeypatch):
    monkeypatch.setenv(FLAG, "off")

    def boom(**kwargs):
        raise AssertionError("pre-sim market anchor executed under off")

    monkeypatch.setattr(smart_sim, "_apply_market_anchor_local", boom)
    monkeypatch.setattr(smart_sim, "_blend_weights_local", lambda **kwargs: (_ for _ in ()).throw(AssertionError("blend weights resolved under off")))

    qsum = _simulate(tmp_path)
    rec = qsum.market_anchor
    assert rec["state"] == "off"
    assert rec["total_w"] is None and rec["margin_w"] is None
    assert rec["anchored_total"] == rec["model_total_raw"]
    assert rec["anchored_margin"] == rec["model_margin_raw"]
    # The market is still RECORDED (so the row can be re-anchored post hoc)...
    assert (rec["market_total"], rec["market_spread"]) == (165.5, -3.5)
    # ...and still used for the cover/over probabilities, which are about the
    # market and not the means.
    assert "p_home_cover" in qsum.probs and "p_total_over" in qsum.probs
    # The quarter means sum to the raw model total (the post-blend quarter
    # rescale is clamped to [0.95, 1.05] of the target total).
    quarter_total = sum(q.home_pts_mu + q.away_pts_mu for q in qsum.quarters)
    assert quarter_total == pytest.approx(rec["model_total_raw"], rel=0.051)


def test_off_differs_from_on_on_the_same_seed(tmp_path, monkeypatch):
    monkeypatch.setenv(FLAG, "on")
    on = _simulate(tmp_path)
    monkeypatch.setenv(FLAG, "off")
    off = _simulate(tmp_path)
    assert on.market_anchor["model_total_raw"] == off.market_anchor["model_total_raw"]
    assert on.market_anchor["model_margin_raw"] == off.market_anchor["model_margin_raw"]
    assert on.market_anchor["anchored_margin"] != off.market_anchor["anchored_margin"]
    assert on.final_margin_mu != off.final_margin_mu


def test_no_market_lines_means_on_and_off_agree(tmp_path, monkeypatch):
    inp = _game_inputs(market_total=None, market_home_spread=None)
    monkeypatch.setenv(FLAG, "on")
    on = _simulate(tmp_path, inp=inp)
    monkeypatch.setenv(FLAG, "off")
    off = _simulate(tmp_path, inp=inp)
    assert _summary_tuple(on) == _summary_tuple(off)
    assert on.market_anchor["anchored_total"] == on.market_anchor["model_total_raw"]
    assert on.market_anchor["market_total"] is None and on.market_anchor["market_spread"] is None


# --- explicit weights ------------------------------------------------------------


def test_weights_flag_arithmetic(tmp_path, monkeypatch):
    monkeypatch.setenv(FLAG, "weights:0.5,0.5")
    inp = _game_inputs(market_total=170.0, market_home_spread=-4.0)
    qsum = _simulate(tmp_path, inp=inp)
    rec = qsum.market_anchor
    assert rec["state"] == "weights"
    assert (rec["total_w"], rec["margin_w"]) == (0.5, 0.5)
    raw_total = rec["model_total_raw"]
    raw_margin = rec["model_margin_raw"]
    expected_total = 0.5 * 170.0 + 0.5 * raw_total
    assert rec["anchored_total"] == pytest.approx(expected_total, abs=1e-9)
    # The total blend rescales both means, so the margin fed into the margin
    # blend is raw_margin * scale, exactly as before the flag.
    scale = expected_total / raw_total
    assert rec["anchored_margin"] == pytest.approx(0.5 * 4.0 + 0.5 * (raw_margin * scale), abs=1e-9)


def test_weights_flag_overrides_quarters_blend_weights_file(tmp_path, monkeypatch):
    (tmp_path / "quarters_blend_weights.json").write_text(json.dumps({"total_w": 0.1, "margin_w": 0.2}), encoding="utf-8")
    smart_sim._DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL.pop(str(tmp_path), None)
    monkeypatch.setenv(FLAG, "on")
    on = _simulate(tmp_path)
    assert (on.market_anchor["total_w"], on.market_anchor["margin_w"]) == (0.1, 0.2)
    monkeypatch.setenv(FLAG, "weights:0.6,0.4")
    explicit = _simulate(tmp_path)
    assert (explicit.market_anchor["total_w"], explicit.market_anchor["margin_w"]) == (0.6, 0.4)


# --- the VENDOR blend is unreachable behind the flag ---------------------------------


def _vendor_inputs(vendor_quarters):
    return vendor_quarters.GameInputs(
        date="2026-07-22",
        home=vendor_quarters.TeamContext(team="LVA", pace=79.5, off_rating=105.0, def_rating=99.0),
        away=vendor_quarters.TeamContext(team="NYL", pace=79.5, off_rating=103.0, def_rating=101.0),
        market_total=165.5,
        market_home_spread=-3.5,
    )


@pytest.mark.parametrize("package", ["nba_betting", "wnba_betting"])
def test_vendor_quarters_fallback_is_routed_through_the_local_port(package, tmp_path, monkeypatch):
    """The vendored `simulate_smart_game` calls its own `simulate_quarters` when
    the caller passes `quarters=None`. Prove that (a) the vendor blend IS live
    when called directly (positive control), and (b) inside the wrapper's
    monkeypatch scope it is never reached under `off`, and even under `on` the
    blend that runs is the wrapper's, not the vendor's.
    """
    import importlib

    real_module = smart_sim._import_real_smart_sim_module_local(package_name=package)
    if real_module is None:
        pytest.skip(f"vendor package {package} not importable here")
    vendor_quarters = importlib.import_module(f"{package}.sim.quarters")
    original_vendor_simulate_quarters = vendor_quarters.simulate_quarters
    league_code = "wnba" if package == "wnba_betting" else "nba"

    vendor_blend_calls: list[object] = []
    real_vendor_blend = vendor_quarters._blend_weights

    def vendor_blend_spy(inp):
        vendor_blend_calls.append(inp)
        return real_vendor_blend(inp)

    monkeypatch.setattr(vendor_quarters, "_blend_weights", vendor_blend_spy)

    # (a) positive control: the sentinel is live on the vendor's own path.
    np.random.seed(1)
    original_vendor_simulate_quarters(_vendor_inputs(vendor_quarters), n_samples=1000)
    assert len(vendor_blend_calls) == 1
    vendor_blend_calls.clear()

    # (b) inside the wrapper scope, the vendor's `quarters is None` fallback
    # resolves `simulate_quarters` from the module namespace -- exactly what a
    # fake simulate_smart_game does here.
    captured: dict[str, object] = {}

    def fake_simulate_smart_game(**kwargs):
        captured["simulate_quarters"] = real_module.simulate_quarters
        captured["result"] = real_module.simulate_quarters(_vendor_inputs(vendor_quarters), n_samples=1000)
        return {"ok": True}

    monkeypatch.setattr(real_module, "simulate_smart_game", fake_simulate_smart_game)

    local_blend_calls: list[dict] = []
    real_local_blend = smart_sim._apply_market_anchor_local

    def local_blend_spy(**kwargs):
        local_blend_calls.append(kwargs)
        return real_local_blend(**kwargs)

    monkeypatch.setattr(smart_sim, "_apply_market_anchor_local", local_blend_spy)

    for state, expect_local_calls in (("off", 0), ("on", 1)):
        monkeypatch.setenv(FLAG, state)
        local_blend_calls.clear()
        vendor_blend_calls.clear()
        captured.clear()
        np.random.seed(1)
        out = smart_sim._call_source_simulate_smart_game_local(
            smart_sim_module=real_module,
            processed_root=tmp_path,
            league_code=league_code,
            kwargs={"date_str": "2026-07-22", "home_tri": "LVA", "away_tri": "NYL", "quarters": None},
        )
        assert out == {"ok": True}
        assert captured["simulate_quarters"] is not original_vendor_simulate_quarters, "vendor simulate_quarters was not replaced"
        assert vendor_blend_calls == [], f"vendor blend reached under {state}"
        assert len(local_blend_calls) == expect_local_calls
        result = captured["result"]
        assert isinstance(result, smart_sim.QuarterSummaryLocal)
        assert result.market_anchor["state"] == state
        assert len(result.quarters) == 4
        # vendor consumers read these attributes off each quarter
        assert all(hasattr(q, "home_pts_mu") and hasattr(q, "away_pts_sigma") and hasattr(q, "corr") for q in result.quarters)

    # The monkeypatch scope restored the vendor's own function afterwards.
    assert real_module.simulate_quarters is original_vendor_simulate_quarters


def test_replacements_cover_simulate_quarters_by_name(tmp_path):
    """Name-level guard: the replacement dict must keep targeting the vendor's
    module-level import `simulate_quarters` (smart_sim.py: `from .quarters import
    ... simulate_quarters`). A rename on either side would silently re-enable
    the vendor blend behind the flag."""
    seen: dict[str, object] = {}

    def fake_simulate_smart_game(**kwargs):
        seen["simulate_quarters"] = module.simulate_quarters
        return {}

    module = SimpleNamespace(simulate_smart_game=fake_simulate_smart_game)
    smart_sim._call_source_simulate_smart_game_local(smart_sim_module=module, processed_root=tmp_path, league_code="nba", kwargs={})
    assert callable(seen["simulate_quarters"])
    # The wrapper restores every replaced name to `getattr(module, name, None)`
    # afterwards (pre-existing behaviour for all ~20 replacements), so an
    # attribute that did not exist before comes back as None, not absent.
    assert module.simulate_quarters is None


# --- the artifact carries market_anchor in every state ----------------------------


def _seed_props(processed_root: Path, date_str: str) -> Path:
    props_path = processed_root / f"props_predictions_{date_str}.csv"
    props_path.write_text(
        "player_name,team,opponent,mean_pts,mean_reb,mean_ast,mean_threes,pred_min\n"
        "A One,LVA,NYL,20,6,4,2,32\n"
        "A Two,LVA,NYL,14,5,3,1,28\n"
        "B One,NYL,LVA,18,7,5,2,31\n"
        "B Two,NYL,LVA,12,4,2,1,26\n",
        encoding="utf-8",
    )
    return props_path


@pytest.mark.parametrize("state", ["on", "off", "weights:0.5,0.5"])
def test_worker_artifact_carries_market_anchor(state, tmp_path, monkeypatch):
    monkeypatch.setenv(FLAG, state)
    processed_root = tmp_path / "data" / "processed"
    processed_root.mkdir(parents=True)
    date_str = "2026-07-22"
    props_path = _seed_props(processed_root, date_str)

    # Use the flat local stub instead of the vendored engine: the artifact
    # plumbing under test is the wrapper's, and the stub needs no data root.
    def stub_module(*, processed_root, league_code):
        return SimpleNamespace(simulate_smart_game=smart_sim._simulate_smart_game_local, paths=SimpleNamespace(data_processed=processed_root, root=processed_root.parent))

    monkeypatch.setattr(smart_sim, "_build_local_smart_sim_module", stub_module)
    smart_sim._smart_sim_worker_init_local(date_str, 10, 1, False, str(props_path), "historical", "wnba", {}, {}, {}, {}, {})
    out_path = processed_root / f"smart_sim_{date_str}_LVA_NYL.json"
    np.random.seed(5)
    result = smart_sim._smart_sim_worker_run_local(
        {
            "date_str": date_str,
            "home_tri": "LVA",
            "away_tri": "NYL",
            "out_path": str(out_path),
            "market_total": 165.5,
            "home_spread": -3.5,
            "home_pace": 79.5,
            "away_pace": 79.5,
            "home_off_rtg": 105.0,
            "away_off_rtg": 103.0,
            "home_def_rtg": 99.0,
            "away_def_rtg": 101.0,
        }
    )
    assert result["status"] == "wrote", result
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    rec = payload["market_anchor"]
    expected_state = "weights" if state.startswith("weights") else state
    assert rec["state"] == expected_state
    assert rec["flag"] == FLAG
    for key in ("total_w", "margin_w", "market_total", "market_spread", "model_total_raw", "model_margin_raw", "anchored_total", "anchored_margin"):
        assert key in rec, key
    assert (rec["market_total"], rec["market_spread"]) == (165.5, -3.5)
    assert rec["market_total_source"] == "job"
    assert rec["model_total_raw"] > 0
    if expected_state == "off":
        assert rec["anchored_total"] == rec["model_total_raw"]
        assert rec["anchored_margin"] == rec["model_margin_raw"]
        assert rec["total_w"] is None
    elif expected_state == "on":
        assert (rec["total_w"], rec["margin_w"]) == (0.7, 0.95)
        assert rec["anchored_total"] != rec["model_total_raw"]
    else:
        assert (rec["total_w"], rec["margin_w"]) == (0.5, 0.5)
    # The quarters handed to the engine are the anchored ones (the same object
    # the vendor sums into target_home_points / target_away_points).
    quarters = payload["quarters"]
    assert len(quarters) == 4
    quarter_total = sum(float(q["home_pts_mu"]) + float(q["away_pts_mu"]) for q in quarters)
    assert quarter_total == pytest.approx(rec["anchored_total"], rel=0.051)


def test_served_sim_blocks_carry_market_anchor():
    """The record must survive into what the web service serves, for both
    leagues, or the artifact field is write-only."""
    from syndicate.features.wnba import cards as wnba_cards

    rec = {"state": "on", "total_w": 0.7, "margin_w": 0.95, "market_total": 160.0, "market_spread": -2.0, "model_total_raw": 158.0, "model_margin_raw": 1.0, "anchored_total": 159.4, "anchored_margin": 1.95}
    served = wnba_cards._source_sim_payload("g1", {"sim": {"market_anchor": rec, "players": {"home": [], "away": []}}}, {"home_spread": "-2", "total": "160"})
    assert served["market_anchor"] == rec
    assert wnba_cards._source_sim_payload("g1", {"sim": {}}, {})["market_anchor"] is None

    merged = wnba_cards._merge_sim_indexes(
        {("NYL", "LVA"): {"away_tri": "NYL", "home_tri": "LVA", "sim": {"players": {}}}},
        {("NYL", "LVA"): {"away_tri": "NYL", "home_tri": "LVA", "sim": {"market_anchor": rec}}},
    )
    assert merged[("NYL", "LVA")]["sim"]["market_anchor"] == rec

    import importlib.util

    for script_name in ("refresh_nba_oddsapi_props", "refresh_wnba_oddsapi_props"):
        script_path = Path(smart_sim.repo_root_from(smart_sim.__file__)) / "scripts" / f"{script_name}.py"
        source = script_path.read_text(encoding="utf-8")
        assert '"market_anchor": payload.get("market_anchor")' in source, f"{script_name} cards_sim_detail builder drops market_anchor"
    nba_cards_path = Path(smart_sim.repo_root_from(smart_sim.__file__)) / "syndicate" / "features" / "nba" / "cards.py"
    assert '"market_anchor": sim_payload.get("market_anchor")' in nba_cards_path.read_text(encoding="utf-8")


# --- harness ---------------------------------------------------------------------


def test_harness_refuses_without_local_data_and_names_the_files(tmp_path, capsys):
    import importlib.util

    script = Path(smart_sim.repo_root_from(smart_sim.__file__)) / "scripts" / "ab_basketball_sim_anchor.py"
    spec = importlib.util.spec_from_file_location("ab_basketball_sim_anchor", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rc = module.main(["--date", "2026-07-22", "--league", "wnba", "--data-root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "REFUSING TO RUN" in err
    assert "predictions_2026-07-22.csv" in err and "props_predictions_2026-07-22.csv" in err
    assert "game_odds_2026-07-22.csv" in err


def test_harness_runs_both_arms_on_a_synthetic_slate(tmp_path, monkeypatch, capsys):
    """End to end through `_smart_sim_run_date_local` with the flat stub engine:
    two arms, identical seeds, per-game rows, and the on-arm shift is the anchor."""
    import importlib.util

    script = Path(smart_sim.repo_root_from(smart_sim.__file__)) / "scripts" / "ab_basketball_sim_anchor.py"
    spec = importlib.util.spec_from_file_location("ab_basketball_sim_anchor_run", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data_root = tmp_path / "wnba_source"
    processed_root = data_root / "data" / "processed"
    processed_root.mkdir(parents=True)
    date_str = "2026-07-22"
    (processed_root / f"predictions_{date_str}.csv").write_text("home_team,visitor_team,totals,spread_margin\nLVA,NYL,160,4\n", encoding="utf-8")
    (processed_root / f"game_odds_{date_str}.csv").write_text("home_team,visitor_team,total,home_spread\nLVA,NYL,165.5,-3.5\n", encoding="utf-8")
    _seed_props(processed_root, date_str)

    def stub_module(*, processed_root, league_code):
        return SimpleNamespace(simulate_smart_game=smart_sim._simulate_smart_game_local, paths=SimpleNamespace(data_processed=processed_root, root=processed_root.parent))

    monkeypatch.setattr(smart_sim, "_build_local_smart_sim_module", stub_module)
    monkeypatch.delenv(FLAG, raising=False)

    report = module.run_ab(data_root=data_root, date=date_str, league="wnba", n_sims=10, seed=3, max_games=None, keep=False)
    assert report["runs"]["on"]["wrote"] == 1 and report["runs"]["off"]["wrote"] == 1
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert (row["home"], row["away"]) == ("LVA", "NYL")
    assert (row["state_on"], row["state_off"]) == ("on", "off")
    assert (row["market_total"], row["market_spread"]) == (165.5, -3.5)
    assert row["anchored_total"] != row["model_total_raw"]
    assert row["anchored_total"] == pytest.approx(0.7 * 165.5 + 0.3 * row["model_total_raw"], abs=1e-9)
    assert report["summary"]["mean_abs_anchor_shift_margin"] > 0
    assert not list(processed_root.glob("ab_anchor_*"))  # cleaned up
    assert FLAG not in __import__("os").environ  # restored
    module._print_report(report)
    out = capsys.readouterr().out
    assert "NYL@LVA" in out and "arm=on" in out and "arm=off" in out
