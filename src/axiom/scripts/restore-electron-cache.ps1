# Join the vendored Electron zips. Each part is under the 100 MiB git limit.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Hash = "f71d58b9535ad2f1d90f09dd91a30fea648c4fe7e710e38a47d6983edd09e53f"
$Dest = Join-Path $Root "vendor\electron-cache\$Hash"
$Parts = Join-Path $Root "vendor\electron-cache\parts"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
foreach ($name in @("electron-v35.7.5-linux-x64.zip", "electron-v35.7.5-win32-x64.zip")) {
  $target = Join-Path $Dest $name
  if (Test-Path $target) { continue }
  $chunks = Get-ChildItem (Join-Path $Parts ($name + ".part-*")) | Sort-Object Name
  $fs = [System.IO.File]::Open($target, "Create")
  foreach ($chunk in $chunks) {
    $in = [System.IO.File]::OpenRead($chunk.FullName)
    $in.CopyTo($fs)
    $in.Close()
  }
  $fs.Close()
}
