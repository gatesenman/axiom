# Rebuild the Windows installer from the vendored caches. No network.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $Root "scripts\restore-electron-cache.ps1")
$env:ELECTRON_CACHE = Join-Path $Root "vendor\electron-cache"
$env:ELECTRON_BUILDER_CACHE = Join-Path $Root "vendor\electron-builder-cache"
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
Set-Location (Join-Path $Root "frontend")
npm ci --offline --cache (Join-Path $Root "vendor\npm-cache")
npm run dist:win
Write-Host "Installers are in frontend\release"
