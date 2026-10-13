"""WNBA recon tools are Syndicate's own (lane nba-source-cli-native, 2026-10-13).

`refresh_wnba_oddsapi_props._build_local_optional_player_recon_artifacts` loads two tools by path. They used to be the
vendored `vendor/wnba_betting_repo/tools/{build_recon_players,build_live_player_lens_tuning}.py`; they are now
`syndicate/features/wnba/recon_tools/`, the vendored bytes below a comment-only header (a leading UTF-8 BOM, which
the lens-tuning tool has, moves above the header so Python still parses it). Pinned here:
  * each copy's body is byte-identical (LF) to the vendored file while the vendor tree exists;
  * the refresh resolves both tools under syndicate/, never vendor/, and the builders it calls exist.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "syndicate" / "features" / "wnba" / "recon_tools"
TOOLS = ("build_recon_players", "build_live_player_lens_tuning")
BOM = b"\xef\xbb\xbf"


def _blob(path: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, cwd=ROOT)
    return r.stdout if r.returncode == 0 else None


@pytest.mark.parametrize("name", TOOLS)
def test_copy_body_is_the_vendored_file(name):
    ours = (TOOLS_DIR / f"{name}.py").read_bytes().replace(b"\r\n", b"\n")
    had_bom = ours.startswith(BOM)
    header, _, body = ours.removeprefix(BOM).partition(b"tests/test_wnba_recon_tools_native.py pins the body.\n")
    assert header.startswith(b"# Syndicate copy of vendor/wnba_betting_repo/tools/") and body
    assert all(line.startswith(b"#") for line in (header + b"#").split(b"\n") if line)
    vendored = _blob(f"vendor/wnba_betting_repo/tools/{name}.py")
    if vendored is None:
        pytest.skip("vendor tree removed")
    assert had_bom == vendored.startswith(BOM)
    assert body == vendored.removeprefix(BOM)


def test_refresh_loads_the_syndicate_copies(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("refresh_wnba_probe_recon", ROOT / "scripts" / "refresh_wnba_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    loaded = []

    def fake_load(name, path):
        loaded.append(Path(path))
        return type("M", (), {"build_recon_players": lambda d: __import__("pandas").DataFrame({"a": [1]}),
                              "build_live_player_lens_tuning": lambda d: __import__("pandas").DataFrame({"b": [2]})})

    monkeypatch.setattr(mod, "_materialize_local_boxscore_cache_for_player_artifacts", lambda **kw: 1)
    monkeypatch.setattr(mod, "_load_module_from_path", fake_load)
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    out = mod._build_local_optional_player_recon_artifacts(processed_root=processed, date_str="2026-10-17")
    assert [p.name for p in loaded] == [f"{t}.py" for t in TOOLS]
    assert all("vendor" not in p.relative_to(ROOT).parts and p.is_file() for p in loaded)
    assert set(out) == {"recon_players_path", "live_player_lens_tuning_path"}
    for name in TOOLS:  # the real copies expose the builders the refresh calls
        spec2 = importlib.util.spec_from_file_location(f"probe_wnba_{name}", TOOLS_DIR / f"{name}.py")
        m = importlib.util.module_from_spec(spec2)
        sys.modules[f"probe_wnba_{name}"] = m  # the tools define dataclasses, as the refresh's loader allows for
        spec2.loader.exec_module(m)
        assert callable(getattr(m, name))
