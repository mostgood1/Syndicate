"""The daily-update run manifest must never carry a secret in clear.

MEASURED 2026-09-09, and this is why the file exists. The live `ODDS_API_KEY` was
sitting in FOUR tracked files on a PUBLIC repo:

    reports/daily_update/latest/unified_daily_update_latest.json
    reports/daily_update/<date>/<run>/unified_daily_update_run.json
    reports/intelligence/status_response_cache.json   (embeds the manifest)
    reports/ops_jobs.json                             (embeds it again)

at `.sourceSteps[].environmentOverrides.ODDS_API_KEY` and
`.sportRuns[].environmentOverrides.ODDS_API_KEY`, 33 occurrences in all.

**THE SHAPE OF THE BUG IS THE INTERESTING PART.** `unified_daily_update.ps1` has
redacted these values in its CONSOLE output since it was written -- the author
knew they were secret. The manifest writer did not, and the manifest is what gets
committed. A redacted log next to a plaintext artifact reads as safe at exactly
the moment it is not, so this pins BOTH paths to one predicate.

The blueprint fix that prompted this (`ODDS_API_KEY` -> `sync: false` in
render.yaml) does nothing here: this is a separate mechanism that would have
re-leaked the NEXT key regardless.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "unified_daily_update.ps1"

# A value no real environment would hold, so a hit is unambiguous.
SENTINEL = "SENTINEL_LIVE_SECRET_d0not_commit"

# Pull ONLY the two functions out of a 4,700-line orchestrator and run those.
# Dot-sourcing the script would execute its body; the AST parser does not.
_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$null, [ref]$null)
$wanted = @('Test-SecretEnvName', 'Protect-EnvironmentOverrides')
$fns = $ast.FindAll({{
    param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wanted -contains $n.Name
}}, $true)
if ($fns.Count -ne 2) {{ throw "expected 2 functions, found $($fns.Count)" }}
$fns | ForEach-Object {{ Invoke-Expression $_.Extent.Text }}

$live = @{{
    ODDS_API_KEY          = '{sentinel}'
    ANTHROPIC_API_KEY     = '{sentinel}'
    ADMIN_TOKEN           = '{sentinel}'
    DB_PASSWORD           = '{sentinel}'
    MLB_BETTING_DATA_ROOT = 'C:\data\mlb'
    SYNDICATE_DATA_ROOT   = '/opt/render/project/data'
}}

[ordered]@{{
    protected      = (Protect-EnvironmentOverrides $live)
    sourceUnmutated = ($live.ODDS_API_KEY -eq '{sentinel}')
    rawJson        = ($live | ConvertTo-Json -Depth 4)
    safeJson       = ((Protect-EnvironmentOverrides $live) | ConvertTo-Json -Depth 4)
}} | ConvertTo-Json -Depth 6
"""


def _powershell(snippet: str) -> dict:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", snippet],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"powershell failed rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def result() -> dict:
    if not SCRIPT.exists():
        pytest.skip("unified_daily_update.ps1 not present in this tree")
    return _powershell(_HARNESS.format(script=str(SCRIPT), sentinel=SENTINEL))


def test_secret_named_values_are_redacted(result: dict) -> None:
    """THE BUG. Every credential-shaped key is masked in the manifest copy."""
    protected = result["protected"]
    for key in ("ODDS_API_KEY", "ANTHROPIC_API_KEY", "ADMIN_TOKEN", "DB_PASSWORD"):
        assert protected[key] == "<redacted>", f"{key} was not redacted"


def test_ordinary_values_survive(result: dict) -> None:
    """The manifest is a debugging artifact. Redacting everything would buy
    safety by destroying the thing -- only credential-shaped keys go."""
    protected = result["protected"]
    assert protected["MLB_BETTING_DATA_ROOT"] == r"C:\data\mlb"
    assert protected["SYNDICATE_DATA_ROOT"] == "/opt/render/project/data"


def test_the_source_hashtable_is_not_mutated(result: dict) -> None:
    """Invoke-Step sets the REAL process environment from this hashtable. If
    redaction happened in place, every sport's job would run with the literal
    string '<redacted>' as its API key -- a working leak fix that breaks the
    entire daily update."""
    assert result["sourceUnmutated"] is True


def test_off_is_not_on(result: dict) -> None:
    """The unprotected hashtable DOES serialise the secret, so the assertions
    above are testing the fix rather than an artifact of the sentinel."""
    assert SENTINEL in result["rawJson"], "baseline is wrong: raw json has no secret"
    assert SENTINEL not in result["safeJson"], "protected json still carries the secret"


def test_every_manifest_site_is_wrapped() -> None:
    """STRUCTURAL, and the one that catches a NEW leak site.

    The behavioural tests above only prove the function works. This proves it is
    actually called at every point `environmentOverrides` enters a serialised
    object -- which is how the leak happened: the value was correct at the
    console and raw two lines later.
    """
    text = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assignments = re.findall(r"environmentOverrides\s*=\s*([^;\r\n}]+)", text)
    assert assignments, "no environmentOverrides assignment found -- did the field move?"
    unwrapped = [a.strip() for a in assignments if "Protect-EnvironmentOverrides" not in a]
    assert not unwrapped, (
        "environmentOverrides assigned without redaction at: "
        + "; ".join(unwrapped)
    )


def test_no_committed_report_carries_a_live_key() -> None:
    """The stale key was scrubbed from the four tracked reports. This keeps them
    scrubbed -- a regenerated report committed from a machine with the old
    behaviour would put it straight back.

    Matches on SHAPE, not on the one known value: any 32-hex value sitting under
    an `environmentOverrides` key is a credential in clear.
    """
    hex32 = re.compile(r'"[0-9a-f]{32}"')
    offenders = []
    for rel in (
        "reports/ops_jobs.json",
        "reports/intelligence/status_response_cache.json",
        "reports/daily_update/latest/unified_daily_update_latest.json",
    ):
        path = ROOT / rel
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r'"environmentOverrides"\s*:\s*\{[^}]*\}', raw):
            if hex32.search(match.group(0)):
                offenders.append(rel)
                break
    assert not offenders, f"a 32-hex credential is committed in clear in: {offenders}"
