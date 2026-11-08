# Build the desktop client into a single windowed exe (no console).
# Requires: a build venv with pyinstaller (see docs/CLIENT.md).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".buildvenv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "creating .buildvenv ..."
    python -m venv .buildvenv
    & (Join-Path $root ".buildvenv\Scripts\pip.exe") install pyinstaller
}

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name XiaoxiSinger --distpath dist --workpath build\tmp --specpath build `
    client\desktop.py

Write-Host "done -> $root\dist\XiaoxiSinger.exe"
