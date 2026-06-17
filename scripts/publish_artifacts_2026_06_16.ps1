param(
  [string]$Branch = $(if ($env:GITHUB_REF_NAME) { $env:GITHUB_REF_NAME } else { 'main' }),
  [string]$ArtifactsPath = 'data/mlb_source/source_artifacts/data/daily/2026-06-16'
)

Write-Host "Publish artifacts helper"
Write-Host "Branch: $Branch"
Write-Host "ArtifactsPath: $ArtifactsPath"

if (-not (Test-Path $ArtifactsPath)) {
  Write-Error "Artifacts path not found: $ArtifactsPath"
  Write-Host "Run this script in the workspace that contains the generated artifacts."
  exit 1
}

git --version | Out-Null

git config user.name 'artifact-publisher'
git config user.email 'artifact-publisher@local'

Write-Host 'Staging artifact files (force add)'
git add -f -- $ArtifactsPath

$status = git status --short
if ([string]::IsNullOrWhiteSpace($status)) {
  Write-Host 'No staged changes detected; nothing to commit.'
  exit 0
}

Write-Host 'Staged files:'
git --no-pager status --porcelain=v1

git commit -m "Publish mlb artifacts 2026-06-16" || Write-Host 'No commit created (possibly nothing changed)'

Write-Host 'Files in HEAD commit:'
git --no-pager show --name-only --pretty=format:'' HEAD

if ($env:GITHUB_TOKEN) {
  $repo = "${env:GITHUB_REPOSITORY}"
  if (-not $repo) {
    # Try to infer remote repo
    $remoteUrl = git remote get-url origin
    if ($remoteUrl -match 'github.com[:/](.+?)(?:\.git)?$') { $repo = $matches[1] }
  }
  if ($repo) {
    Write-Host 'Setting authenticated remote URL using GITHUB_TOKEN'
    git remote set-url origin "https://x-access-token:$env:GITHUB_TOKEN@github.com/$repo"
  } else {
    Write-Host 'GITHUB_REPOSITORY not set; pushing using existing origin remote'
  }
}

Write-Host "Pushing to origin/$Branch"
try {
  git push origin "HEAD:$Branch"
  Write-Host 'Push succeeded.'
} catch {
  Write-Error "Push failed: $_"
  Write-Host 'If push is blocked by branch protection, open a PR with the artifacts or push to an allowed branch then create a PR.'
  exit 1
}

Write-Host 'Done. After pushing, trigger a Render deploy (restart service) to bootstrap the data root.'
