param(
    [switch]$SkipFfmpeg,
    [switch]$SkipInstall,
    [string]$Python = ".\\.venv\\Scripts\\python.exe"
)

<#
.SYNOPSIS
  Build Windows onedir package with PyInstaller.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -SkipFfmpeg
#>

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path $Python)) {
    Write-Step "Creating virtual environment"
    python -m venv .venv
    $Python = ".\\.venv\\Scripts\\python.exe"
}

if (-not $SkipInstall) {
    Write-Step "Installing runtime + build dependencies (CPU torch)"
    & $Python -m pip install --upgrade pip
    # Prefer CPU wheels for redistributable size / portability
    & $Python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org `
        --index-url https://download.pytorch.org/whl/cpu `
        --extra-index-url https://pypi.org/simple `
        torch torchaudio
    & $Python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org `
        -r requirements.txt -r requirements-build.txt
}

$ffmpegDir = Join-Path $PWD "third_party\\ffmpeg"
$ffmpegExe = Join-Path $ffmpegDir "ffmpeg.exe"
if (-not $SkipFfmpeg -and -not (Test-Path $ffmpegExe)) {
    Write-Step "Downloading ffmpeg essentials (GPL/LGPL build from gyan.dev)"
    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
    $zipPath = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    $extractRoot = Join-Path $env:TEMP "ffmpeg-extract"
    if (Test-Path $extractRoot) { Remove-Item $extractRoot -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
    $found = Get-ChildItem -Path $extractRoot -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $found) { throw "ffmpeg.exe not found in archive" }
    Copy-Item $found.FullName $ffmpegExe -Force
    Write-Host "Bundled: $ffmpegExe"
} elseif (Test-Path $ffmpegExe) {
    Write-Host "Using existing ffmpeg: $ffmpegExe"
} else {
    Write-Host "Skipping ffmpeg bundle (mp3 etc. will need system ffmpeg on PATH)"
}

Write-Step "Building manual PDF from Markdown"
& $Python scripts\build_manual_pdf.py
if ($LASTEXITCODE -ne 0) { throw "manual PDF build failed with exit code $LASTEXITCODE" }

Write-Step "Cleaning previous build outputs"
foreach ($dir in @("build", "dist")) {
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
}

Write-Step "Running PyInstaller"
& $Python -m PyInstaller --noconfirm --clean piano_transcription_gui.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$outDir = Join-Path $PWD "dist\\PianoTranscriptionGUI"
if (-not (Test-Path (Join-Path $outDir "PianoTranscriptionGUI.exe"))) {
    throw "Expected exe not found under $outDir"
}

# Copy license/notice/manual next to the app for redistribution
Copy-Item "LICENSE" $outDir -Force -ErrorAction SilentlyContinue
Copy-Item "NOTICE" $outDir -Force -ErrorAction SilentlyContinue
Copy-Item "README.md" $outDir -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Join-Path $outDir "docs") | Out-Null
Copy-Item "docs\manual.md" (Join-Path $outDir "docs\manual.md") -Force
Copy-Item "docs\manual.pdf" (Join-Path $outDir "docs\manual.pdf") -Force

Write-Step "Creating zip archive"
$version = (& $Python -c "from version import __version__; print(__version__)").Trim()
$zipName = "PianoTranscriptionGUI-windows-x64-v$version.zip"
$zipPath = Join-Path (Join-Path $PWD "dist") $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "  App: $outDir\\PianoTranscriptionGUI.exe"
Write-Host "  Zip: $zipPath"
Write-Host ""
Write-Host "Note: First run downloads the ~165MB model checkpoint to the user profile."
