# -*- coding: utf-8 -*-
"""Create a version tag and push it to trigger the GitHub Release workflow.

Examples:
  powershell -ExecutionPolicy Bypass -File scripts\\release.ps1
  powershell -ExecutionPolicy Bypass -File scripts\\release.ps1 -Version 0.1.0
  powershell -ExecutionPolicy Bypass -File scripts\\release.ps1 -Version 0.1.1 -DryRun
"""

param(
    [string]$Version,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Get-CurrentVersion {
    $line = Get-Content "version.py" | Where-Object { $_ -match '__version__\s*=\s*"([^"]+)"' } | Select-Object -First 1
    if (-not $line) { throw "Could not parse __version__ from version.py" }
    return [regex]::Match($line, '"([^"]+)"').Groups[1].Value
}

function Set-Version([string]$NewVersion) {
    if ($NewVersion -notmatch '^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$') {
        throw "Version must look like 0.1.0 (got: $NewVersion)"
    }
    $content = Get-Content "version.py" -Raw
    $updated = [regex]::Replace($content, '__version__\s*=\s*"[^"]+"', "__version__ = `"$NewVersion`"")
    Set-Content -Path "version.py" -Value $updated -NoNewline
}

function Resolve-Gh {
    $cmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Join-Path ${env:ProgramFiles} "GitHub CLI\gh.exe"
    if (Test-Path $candidate) { return $candidate }
    throw "GitHub CLI (gh) not found. Install: winget install GitHub.cli"
}

$gh = Resolve-Gh

$status = git status --porcelain
if ($status -and -not $Force) {
    throw "Working tree is not clean. Commit/stash changes first, or pass -Force."
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main" -and $branch -ne "master" -and -not $Force) {
    throw "Current branch is '$branch'. Release from main/master, or pass -Force."
}

$current = Get-CurrentVersion
if (-not $Version) { $Version = $current }
if ($Version -ne $current) {
    Write-Host "Bumping version: $current -> $Version"
    Set-Version $Version
} else {
    Write-Host "Using version: $Version"
}

$tag = "v$Version"
$existing = git tag -l $tag
if ($existing) { throw "Tag already exists: $tag" }

$remote = (git remote | Select-Object -First 1)
if (-not $remote) {
    throw "No git remote configured. Create the GitHub repo first (see README)."
}

$commitMsg = "chore(release): v$Version"
if ($DryRun) {
    Write-Host "[DryRun] would commit version.py (if changed), tag $tag, push, and watch workflow"
    git status --short
    exit 0
}

if (git status --porcelain -- version.py) {
    git add version.py
    git commit -m $commitMsg
}

git tag -a $tag -m "Release $tag"
git push $remote HEAD
git push $remote $tag

Write-Host ""
Write-Host "Pushed $tag. Watching GitHub Actions..." -ForegroundColor Green
& $gh run watch --exit-status
Write-Host ""
Write-Host "Opening the release page..."
& $gh release view $tag --web
