from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def _extract_ps_function(content: str, function_name: str) -> str:
    marker = f"function {function_name} {{"
    start = content.index(marker)
    depth = 0
    for index in range(start, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    raise AssertionError(f"unbalanced braces extracting function {function_name}")


def _run_event_sim_decision(**kwargs: object) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "unified_daily_update.ps1"
    content = script_path.read_text(encoding="utf-8")

    functions = "\n".join(
        _extract_ps_function(content, name)
        for name in ("ConvertTo-NullableDateTimeOffset", "Get-EventSimExecutionDecision")
    )

    def _ps_literal(value: object) -> str:
        if value is None:
            return "$null"
        if isinstance(value, bool):
            return "$true" if value else "$false"
        if isinstance(value, int):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    args = " ".join(f"-{key} {_ps_literal(value)}" for key, value in kwargs.items())
    invocation = f"$result = Get-EventSimExecutionDecision {args}\nif ($null -eq $result) {{ 'null' }} else {{ $result.ToString() }}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        harness_path = Path(tmp_dir) / "harness.ps1"
        harness_path.write_text(functions + "\n" + invocation, encoding="utf-8")
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()


@unittest.skipUnless(shutil.which("powershell.exe") or shutil.which("powershell"), "powershell.exe not available")
class UnifiedDailyUpdateEventSimDecisionBehaviorTests(unittest.TestCase):
    def test_matching_fingerprint_with_existing_artifact_skips_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_path = Path(tmp_dir) / "artifact.json"
            artifact_path.write_text("{}", encoding="utf-8")

            result = _run_event_sim_decision(
                CurrentFingerprint="abc123",
                PreviousFingerprint="abc123",
                Fallback=None,
                CurrentTimeUtc=None,
                EventStartTimeUtc=None,
                ArtifactPath=str(artifact_path),
                ForceWithinMinutes=30,
            )

        self.assertEqual(result, "False")

    def test_mismatched_fingerprint_still_forces_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_path = Path(tmp_dir) / "artifact.json"
            artifact_path.write_text("{}", encoding="utf-8")

            result = _run_event_sim_decision(
                CurrentFingerprint="abc123",
                PreviousFingerprint="different",
                Fallback=None,
                CurrentTimeUtc=None,
                EventStartTimeUtc=None,
                ArtifactPath=str(artifact_path),
                ForceWithinMinutes=30,
            )

        self.assertEqual(result, "True")

    def test_missing_artifact_forces_rerun_even_with_matching_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_artifact_path = Path(tmp_dir) / "does_not_exist.json"

            result = _run_event_sim_decision(
                CurrentFingerprint="abc123",
                PreviousFingerprint="abc123",
                Fallback=None,
                CurrentTimeUtc=None,
                EventStartTimeUtc=None,
                ArtifactPath=str(missing_artifact_path),
                ForceWithinMinutes=30,
            )

        self.assertEqual(result, "True")


class UnifiedDailyUpdateEventSimFreshnessWindowTests(unittest.TestCase):
    def test_close_to_start_time_forces_event_sim_execution(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Get-Policy -Context $eventPolicyContext -PolicyConfig $eventSimPolicyConfig", content)
        self.assertIn("selectionMode = 'default'", content)
        self.assertIn("selectionMode = 'optimal'", content)
        self.assertIn("function Get-EventSimExecutionStartTimeUtc", content)
        # The decision call now also passes -ArtifactPath; pin the stable
        # leading arguments and the force-window argument separately so the
        # assertion survives argument-list evolution in between.
        self.assertIn(
            "Get-EventSimExecutionDecision -CurrentFingerprint $currentEventInputFingerprint -PreviousFingerprint $previousInputFingerprint",
            content,
        )
        self.assertIn("-ForceWithinMinutes $effectiveForceWindowMinutes", content)
        self.assertIn("$currentTimeOffset -ge $windowStartOffset -and $currentTimeOffset -le $eventStartOffset", content)
        self.assertIn("return $true", content)

    def test_far_from_start_time_keeps_fingerprint_skip_behavior(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ($currentFingerprintText -eq $previousFingerprintText) {", content)
        self.assertIn("return $false", content)

    def test_fingerprint_change_still_triggers_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ([string]::IsNullOrWhiteSpace($previousFingerprintText)) {", content)
        self.assertIn("return $true", content)
        self.assertIn("if ($eventDecision) {", content)

    def test_decision_call_site_wraps_artifact_path_cast_in_parens(self) -> None:
        # Regression guard: `-ArtifactPath [string]$eventPlan.artifactPath` (no
        # parens) is not a cast in PowerShell argument mode -- it stringifies
        # the literal text "[string]" plus the whole $eventPlan object plus
        # ".artifactPath", so Test-Path never finds that "path" and the
        # freshness/fingerprint skip below it (line ~2052) never fires.
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("-ArtifactPath ([string]$eventPlan.artifactPath)", content)
        self.assertNotIn("-ArtifactPath [string]$eventPlan.artifactPath", content)


if __name__ == "__main__":
    unittest.main()
