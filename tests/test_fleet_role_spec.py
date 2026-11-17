"""The fleet builds every role's env without Render's files (lane `render-config-retirement`,
todo #766 reopened 2026-11-17, user: "we should not depend on render at all").

Three things are pinned here:

1. `scripts/fleet_role_spec.json` is, key for key and in order, what `render.yaml` declared
   (parsed below with the launcher's retired parser, kept in THIS test only), and every
   declared value expands to exactly what the retired `/opt/render` rewrite produced. So the
   spec layer of every role's env is identical to the render.yaml layer it replaced.
2. The launcher never OPENS `render.yaml` or anything under `<home>/render_env/` while it
   builds env (`cmd_env` for every role, `template_text`, the `up` path up to the first
   process it would start) -- caught by a CPython audit hook on every `open`, with a poisoned
   `render_env/` present beside a good `fleet_env/`. Plus a static check of its string
   constants.
3. `up` refuses to start a role that has no `fleet_env/<role>.json` (absent is not off: the
   snapshot holds the venue keys and the `*_AUTORUN` switches), unless the operator passes
   `--allow-missing-env-snapshot`.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from scripts import local_production as lp

REPO = Path(__file__).resolve().parents[1]
RENDER_YAML = REPO / "render.yaml"


# --- the retired parser and rewrite, kept ONLY to prove equivalence ---------------------

_SERVICE_TO_ROLE = {"syndicate": "web", "refresh-worker": "refresh-worker", "live-odds-worker": "live-odds-worker"}
_RENDER_DATA_PREFIX = "/opt/render/project/data"
_RENDER_SRC_PREFIX = "/opt/render/project/src"


def _legacy_blueprint(path: Path) -> dict[str, list[tuple[str, str | None, str]]]:
    """`local_production.load_blueprint` as it was at origin/main 3179b1ff1."""
    import yaml

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, str | None, str]]] = {}
    for service in doc.get("services") or []:
        role = _SERVICE_TO_ROLE.get(str(service.get("name") or ""))
        if role is None:
            continue
        keys = []
        for entry in service.get("envVars") or []:
            name = str(entry.get("key") or "").strip()
            if not name:
                continue
            if "value" in entry:
                keys.append((name, str(entry["value"]), "value"))
            elif entry.get("generateValue"):
                keys.append((name, None, "generate"))
            elif isinstance(entry.get("fromService"), dict):
                kind = "keyvalue" if str(entry["fromService"].get("type")) == "keyvalue" else "from_web"
                keys.append((name, None, kind))
            elif entry.get("sync") is False:
                keys.append((name, None, "sync_false"))
        out[role] = keys
    return out


def _legacy_rewrite(value: str, *, data_root: Path) -> str:
    if value == _RENDER_DATA_PREFIX or value.startswith(_RENDER_DATA_PREFIX + "/"):
        tail = value[len(_RENDER_DATA_PREFIX):].lstrip("/")
        return str(data_root.joinpath(*tail.split("/")) if tail else data_root)
    if value == _RENDER_SRC_PREFIX or value.startswith(_RENDER_SRC_PREFIX + "/"):
        tail = value[len(_RENDER_SRC_PREFIX):].lstrip("/")
        return str(lp.REPO_ROOT.joinpath(*tail.split("/")) if tail else lp.REPO_ROOT)
    return value


# --- 1. the spec is render.yaml's declaration, key for key ----------------------------

@pytest.mark.skipif(not RENDER_YAML.is_file(), reason="render.yaml is gone; the spec is the only record now")
def test_spec_is_render_yaml_key_for_key_and_values_expand_identically(tmp_path: Path) -> None:
    legacy = _legacy_blueprint(RENDER_YAML)
    spec = lp.load_role_spec()
    data_root = tmp_path / "home" / "data"
    assert list(spec) == list(lp.ROLE_ORDER)
    for role in lp.ROLE_ORDER:
        assert [(k.key, k.source) for k in spec[role]] == [(k, s) for k, _, s in legacy[role]], role
        for item, (name, value, source) in zip(spec[role], legacy[role]):
            if source != "value":
                assert item.value is None
                continue
            assert lp.expand_path(item.value, data_root=data_root) == _legacy_rewrite(value, data_root=data_root), name
    # Sizes measured 2026-11-17 at origin/main 3179b1ff1.
    assert {r: len(spec[r]) for r in lp.ROLE_ORDER} == {"web": 52, "refresh-worker": 84, "live-odds-worker": 76}


def test_spec_carries_no_render_disk_path() -> None:
    text = lp.ROLE_SPEC_PATH.read_text(encoding="utf-8")
    assert "/opt/render" not in text
    assert "{data_root}" in text


def test_spec_refuses_a_malformed_file(tmp_path: Path) -> None:
    good = json.loads(lp.ROLE_SPEC_PATH.read_text(encoding="utf-8"))
    for broken in (
        {"roles": {}},
        {"roles": {**good["roles"], "web": [{"key": "X", "source": "nonsense"}]}},
        {"roles": {**good["roles"], "web": [{"key": "X", "source": "value"}]}},  # no value
    ):
        path = tmp_path / "spec.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(SystemExit):
            lp.load_role_spec(path)


def test_worker_start_commands_are_the_fleet_s_own(tmp_path: Path) -> None:
    settings = lp.Settings(home=tmp_path)
    assert lp.role_command("refresh-worker", {}, settings) == ([sys.executable, "scripts/run_refresh_worker.py"], "python")
    assert lp.role_command("live-odds-worker", {}, settings) == (
        [sys.executable, "scripts/run_live_odds_refresh_worker.py"], "python")


# --- 2. the launcher never opens a Render file ------------------------------------------

_OPENED: list[str] = []
_RECORDING = {"on": False}


def _audit(event: str, args: tuple) -> None:
    if _RECORDING["on"] and event in {"open", "os.listdir", "os.scandir"} and args:
        _OPENED.append(str(args[0]))


sys.addaudithook(_audit)


def _render_files_opened() -> list[str]:
    return [p for p in _OPENED if "render.yaml" in p or "render_env" in p.replace("\\", "/")]


def _fleet_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "fleet_env").mkdir(parents=True)
    (home / "render_env").mkdir(parents=True)
    for role in lp.ROLE_ORDER:
        (home / "fleet_env" / f"{role}.json").write_text(json.dumps(
            {"role": role, "values": {"SYNDICATE_DATA_ROOT": "{data_root}", "FROM_SNAPSHOT": "fleet"}}), encoding="utf-8")
        # Poison: if anything reads this, FROM_SNAPSHOT says so.
        (home / "render_env" / f"{role}.json").write_text(json.dumps(
            {"values": {"FROM_SNAPSHOT": "render", "SYNDICATE_DATA_ROOT": "/opt/render/project/data"}}), encoding="utf-8")
    (home / "local_production.env").write_text("ADMIN_TOKEN=t\n", encoding="utf-8")
    return home


def test_env_build_never_opens_render_yaml_or_render_env(tmp_path: Path, capsys) -> None:
    home = _fleet_home(tmp_path)
    _OPENED.clear()
    _RECORDING["on"] = True
    try:
        for role in lp.ROLE_ORDER:
            assert lp.main(["--home", str(home), "env", "--role", role, "--unmask"]) == 0
        spec = lp.load_role_spec()
        lp.template_text(spec)
        settings = lp.Settings(home=home)
        for role in lp.ROLE_ORDER:
            env, _ = lp.derive_role_env(role, spec, {}, settings, snapshot=lp.load_env_snapshot(settings, role), base_env={})
            assert env["FROM_SNAPSHOT"] == "fleet"
            assert env["SYNDICATE_DATA_ROOT"] == str(home / "data")
    finally:
        _RECORDING["on"] = False
    out = capsys.readouterr().out
    assert "FROM_SNAPSHOT=fleet" in out and "FROM_SNAPSHOT=render" not in out
    assert any(p.endswith("fleet_role_spec.json") for p in _OPENED)  # the hook does see opens
    assert any("fleet_env" in p.replace("\\", "/") for p in _OPENED)
    assert _render_files_opened() == []


def test_up_never_opens_render_files_before_its_first_process(tmp_path: Path, monkeypatch) -> None:
    home = _fleet_home(tmp_path)

    class Reached(Exception):
        pass

    def _stop(*_a, **_k):
        raise Reached

    monkeypatch.setattr(lp, "start_local_redis", _stop)
    _OPENED.clear()
    _RECORDING["on"] = True
    try:
        with pytest.raises(Reached):
            lp.main(["--home", str(home), "up", "--skip-bootstrap", "--no-jobs"])
    finally:
        _RECORDING["on"] = False
    assert _render_files_opened() == []


def test_launcher_source_names_no_render_file_outside_prose() -> None:
    """Every string constant that is not a docstring or a comment -- the strings code USES."""
    tree = ast.parse(Path(lp.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    used = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    offenders = [s for s in used if "render.yaml" in s or "render_env" in s or "/opt/render" in s]
    # The only survivors are operator-facing messages that name the OLD directory so a
    # restore from a pre-2026-11-17 backup knows to migrate it. None is a path the code opens.
    assert all("migrate" in s or "backup" in s for s in offenders), offenders


# --- 3. up fails closed without the snapshot --------------------------------------------

def test_up_refuses_a_role_without_its_snapshot(tmp_path: Path, monkeypatch) -> None:
    home = _fleet_home(tmp_path)
    (home / "fleet_env" / "refresh-worker.json").unlink()
    started = []
    monkeypatch.setattr(lp, "start_local_redis", lambda *a, **k: started.append(1))
    with pytest.raises(SystemExit) as exc:
        lp.main(["--home", str(home), "up", "--skip-bootstrap", "--no-jobs"])
    assert "refresh-worker" in str(exc.value) and "fleet_env" in str(exc.value)
    assert started == []  # refused before anything ran


def test_up_with_the_override_gets_past_the_snapshot_check(tmp_path: Path, monkeypatch) -> None:
    home = _fleet_home(tmp_path)
    (home / "fleet_env" / "refresh-worker.json").unlink()

    class Reached(Exception):
        pass

    def _stop(*_a, **_k):
        raise Reached

    monkeypatch.setattr(lp, "start_local_redis", _stop)
    with pytest.raises(Reached):
        lp.main(["--home", str(home), "up", "--skip-bootstrap", "--no-jobs", "--allow-missing-env-snapshot"])


def test_up_scoped_to_roles_that_have_snapshots_starts(tmp_path: Path, monkeypatch) -> None:
    home = _fleet_home(tmp_path)
    (home / "fleet_env" / "refresh-worker.json").unlink()

    class Reached(Exception):
        pass

    def _stop(*_a, **_k):
        raise Reached

    monkeypatch.setattr(lp, "start_local_redis", _stop)
    with pytest.raises(Reached):
        lp.main(["--home", str(home), "up", "--skip-bootstrap", "--no-jobs", "--roles", "web"])
