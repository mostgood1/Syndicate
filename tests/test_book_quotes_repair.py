"""P3, lane book-quotes-splice-repair: remove splice fragments, and only them."""
from __future__ import annotations

import json

from syndicate.features.shared import book_quotes_repair as repair

INTACT = {"captured_at": "2026-09-03T04:00:00Z", "sport": "mlb", "market": "h2h", "selection": "home", "price": 340}


def _row(**over):
    return json.dumps({**INTACT, **over}, separators=(",", ":"))


def _shard(root, lines, sport="mlb", date="2026-09-03"):
    p = root / f"{sport}_source" / "tracking" / "book_quotes" / f"{date}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_a_dry_run_counts_and_writes_nothing(tmp_path):
    intact = _row()
    fragment = intact[intact.index('Z"'):]          # the headless tail of a real row
    orphan = "not json at all"
    p = _shard(tmp_path, [intact, fragment, _row(price=-110), orphan])
    before = p.read_bytes()
    result = repair.repair_shard(p)
    assert (result["lines"], result["bad_lines"], result["verified_fragments"], result["orphan_bad_lines"]) == (4, 2, 1, 1)
    assert p.read_bytes() == before


def test_apply_removes_only_the_verified_fragment(tmp_path):
    intact = _row()
    fragment = intact[intact.index('Z"'):]
    orphan = "not json at all"
    p = _shard(tmp_path, [intact, fragment, _row(price=-110), orphan])
    result = repair.repair_shard(p, apply=True)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert result["removed"] == 1
    assert fragment not in lines
    assert orphan in lines, "an unproven bad line is never deleted"
    assert [l for l in lines if l.startswith("{")] == [intact, _row(price=-110)]


def test_a_repeated_fragment_is_removed_every_time(tmp_path):
    intact = _row()
    fragment = intact[-20:]
    p = _shard(tmp_path, [intact, fragment, fragment])
    result = repair.repair_shard(p, apply=True)
    assert (result["verified_fragments"], result["removed"]) == (2, 2)
    assert p.read_text(encoding="utf-8").splitlines() == [intact]


def test_a_clean_shard_is_untouched(tmp_path):
    p = _shard(tmp_path, [_row(), _row(price=120)])
    before = p.read_bytes()
    result = repair.repair_shard(p, apply=True)
    assert result["bad_lines"] == 0 and "removed" not in result
    assert p.read_bytes() == before


def test_a_busy_lock_refuses_rather_than_racing_a_merge(tmp_path, monkeypatch):
    from syndicate.features.shared import artifact_merge

    p = _shard(tmp_path, [_row(), _row()[-10:]])
    monkeypatch.setattr(artifact_merge, "append_only_merge_lock", lambda path, wait_seconds=0.0: None)
    before = p.read_bytes()
    result = repair.repair_shard(p, apply=True)
    assert "lock_busy" in result["error"]
    assert p.read_bytes() == before


def _client(monkeypatch, tmp_path):
    from syndicate.app import create_app
    from syndicate.blueprints import ops

    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(ops, "data_root", lambda: tmp_path)
    spawned = []

    class _Child:
        pid = 4242

    monkeypatch.setattr(ops.subprocess, "Popen", lambda command, **kw: spawned.append(command) or _Child())
    app = create_app()
    app.testing = True
    return app.test_client(), spawned


def _post(client, body):
    return client.post("/api/ops/book-quotes/repair", json=body, headers={"Authorization": "Bearer secret-token"})


def test_the_endpoint_is_a_dry_run_unless_apply_is_exactly_true(monkeypatch, tmp_path):
    client, spawned = _client(monkeypatch, tmp_path)
    for body in ({"since": "2026-09-01"}, {"since": "2026-09-01", "apply": "true"}, {"since": "2026-09-01", "apply": 1}):
        response = _post(client, body)
        assert response.status_code == 200 and response.get_json()["apply"] is False
    assert all("--apply" not in command for command in spawned)

    response = _post(client, {"since": "2026-09-01", "apply": True, "sports": ["mlb"]})
    assert response.get_json()["apply"] is True
    command = spawned[-1]
    assert "--apply" in command
    assert command[command.index("--sports") + 1] == "mlb"
    assert command[command.index("--data-root") + 1] == str(tmp_path)


def test_the_endpoint_refuses_a_bad_date_or_sport(monkeypatch, tmp_path):
    client, spawned = _client(monkeypatch, tmp_path)
    assert _post(client, {"since": "yesterday"}).status_code == 400
    assert _post(client, {"since": "2026-09-01", "sports": ["../etc"]}).status_code == 400
    assert spawned == []


def test_a_glued_line_gives_back_its_complete_row(tmp_path):
    """ENOSPC tore a row head; the next append glued a whole row onto it."""
    torn = _row()[:40]
    whole = _row(price=-125, captured_at="2026-09-03T05:00:00Z")
    p = _shard(tmp_path, [_row(), torn + whole])
    dry = repair.repair_shard(p)
    assert (dry["glued_lines"], dry["salvaged_rows"], dry["orphan_bad_lines"], dry["verified_fragments"]) == (1, 1, 1, 0)
    result = repair.repair_shard(p, apply=True)
    assert (result["split_lines"], result["rows_written_from_glued"], result["removed"]) == (1, 1, 0)
    assert p.read_text(encoding="utf-8").splitlines() == [_row(), torn, whole], "the torn head is kept, never deleted"


def test_a_glued_row_already_intact_is_not_written_twice(tmp_path):
    torn = _row()[:40]
    p = _shard(tmp_path, [_row(), torn + _row()])
    dry = repair.repair_shard(p)
    assert (dry["glued_lines"], dry["salvaged_rows"]) == (1, 0)
    repair.repair_shard(p, apply=True)
    assert p.read_text(encoding="utf-8").splitlines() == [_row(), torn]


def test_the_scope_is_sport_and_since(tmp_path, capsys):
    _shard(tmp_path, [_row(), _row()[-10:]], date="2026-08-31")
    _shard(tmp_path, [_row(), _row()[-10:]], date="2026-09-03")
    _shard(tmp_path, [_row(), _row()[-10:]], sport="soccer", date="2026-09-03")
    totals = repair.repair_book_quotes_shards(tmp_path, sports=["mlb"], since="2026-09-01")
    out = capsys.readouterr().out
    assert totals["shards"] == 1 and totals["verified_fragments"] == 1 and totals["apply"] is False
    assert out.count("REPAIR_SHARD") == 1 and "REPAIR_DONE" in out
