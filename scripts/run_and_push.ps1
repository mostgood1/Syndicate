param(
    [string] $CommitMessage = "Add shared 30s live-odds refresh loop (cross-sport)",
    [string] $Branch = "main",
    [string] $Remote = "origin"
)

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
} catch {
    $scriptDir = Get-Location
}

#$RepoRoot is parent of the scripts folder
$RepoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $RepoRoot

Write-Host "Running live-refresh unit tests..." -ForegroundColor Cyan
# Ensure tests run with repo root on PYTHONPATH
$env:PYTHONPATH = (Get-Location).Path

$testCmd = "python -m pytest -q tests/test_live_refresh_loop.py"
Write-Host "$testCmd"
$proc = Start-Process -FilePath python -ArgumentList '-m','pytest','-q','tests/test_live_refresh_loop.py' -NoNewWindow -Wait -PassThru
$exitCode = $proc.ExitCode
if ($exitCode -ne 0) {
    Write-Host "Tests failed (exit code $exitCode). Aborting commit/push." -ForegroundColor Red
    exit $exitCode
}

Write-Host "Tests passed." -ForegroundColor Green

# Check for git changes
Write-Host "Checking git status..." -ForegroundColor Cyan
$porcelain = git status --porcelain
if ([string]::IsNullOrWhiteSpace($porcelain)) {
    Write-Host "No changes to commit." -ForegroundColor Yellow
} else {
    Write-Host "Staging changes..." -ForegroundColor Cyan
    git add -A
    Write-Host "Committing: $CommitMessage" -ForegroundColor Cyan
    git commit -m "$CommitMessage"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git commit failed (exit code $LASTEXITCODE). Aborting push." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "Pushing to $Remote/$Branch..." -ForegroundColor Cyan
git push $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "git push failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

$sha = git rev-parse HEAD
Write-Host "Pushed commit SHA: $sha" -ForegroundColor Green

Write-Host "Done. Triggered Render deploy if autoDeploy is configured." -ForegroundColor Green