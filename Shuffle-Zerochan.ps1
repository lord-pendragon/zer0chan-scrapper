<#  Shuffle-Zerochan.ps1
    - Randomize image filenames in "Zerochan", open folder, wait for Enter, then restore.
    - Default: no recursion (only that folder). Toggle $Recurse to $true if needed.
#>



[CmdletBinding()]
param(
  # If you want a fixed absolute path, set it here (e.g. 'D:\Pictures\Zerochan').
  # Leave blank to auto-use "<script folder>\Zerochan".
  [string]$Folder = ''
)

# --- robust base folder detection (works even if $PSScriptRoot is empty) ---
$scriptDir = if ($PSScriptRoot -and $PSScriptRoot.Trim()) {
  $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
  Split-Path -Path $MyInvocation.MyCommand.Path -Parent
} else {
  Get-Location | ForEach-Object Path
}

if (-not $Folder -or -not $Folder.Trim()) {
  $Folder = Join-Path $scriptDir 'Zerochan'
}

# --- config: image extensions you care about ---
$exts = @(
  'jpg','jpeg','png','gif','bmp','tif','tiff','webp',
  'heic','heif','cr2','arw','nef','rw2','orf','raf','dng'
)

if (-not (Test-Path -LiteralPath $Folder)) {
  Write-Host "Folder not found: $Folder" -ForegroundColor Red
  exit 1
}

# Get files
$files = Get-ChildItem -LiteralPath $Folder -File -ErrorAction SilentlyContinue -Recurse:$Recurse |
         Where-Object { $exts -contains $_.Extension.TrimStart('.').ToLower() }

if (-not $files -or $files.Count -eq 0) {
  Write-Host "No image files found in: $Folder" -ForegroundColor Yellow
  exit 0
}

# Session token to avoid any name clashes and to pair mapping with this run
$token = "_SHFL_" + ([guid]::NewGuid().ToString('N'))
$mapPath = Join-Path $Folder (".shuffle-map-$token.json")

# Shuffle files
$shuffled = $files | Get-Random -Count $files.Count

# Build mapping and rename
$idx = 1
$mapping = New-Object System.Collections.Generic.List[object]

Write-Host "Shuffling $($files.Count) files in `"$Folder`" ..." -ForegroundColor Cyan
foreach ($f in $shuffled) {
  $newBase = ("{0:00000}_{1}" -f $idx, $f.BaseName)
  $newName = "$token`_$newBase$($f.Extension.ToLower())"
  $newFull = Join-Path $f.DirectoryName $newName

  try {
    Rename-Item -LiteralPath $f.FullName -NewName $newName -ErrorAction Stop
    $mapping.Add([pscustomobject]@{
      OldPath = $f.FullName
      NewPath = $newFull
    })
    $idx++
  } catch {
    Write-Host "  Skipped (rename failed): $($f.FullName)`n    $_" -ForegroundColor Yellow
  }
}

# Persist the mapping so we can restore exactly
$mapping | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $mapPath -Encoding UTF8 -Force
Write-Host "Shuffle complete. Mapping saved: $mapPath" -ForegroundColor Green

# Open folder to view
Start-Process explorer.exe $Folder

# Wait for user to finish viewing
Write-Host ""
Read-Host "Press ENTER to restore original names and exit"

# Restore
if (-not (Test-Path -LiteralPath $mapPath)) {
  Write-Host "Mapping file missing; cannot restore automatically." -ForegroundColor Red
  exit 2
}

$restoreMap = Get-Content -LiteralPath $mapPath -Raw | ConvertFrom-Json
Write-Host "Restoring original names..." -ForegroundColor Cyan

foreach ($m in $restoreMap) {
  $old = [string]$m.OldPath
  $cur = [string]$m.NewPath

  if (-not (Test-Path -LiteralPath $cur)) {
    # File might have been moved/deleted; skip safely
    Write-Host "  Missing shuffled file (skip): $cur" -ForegroundColor Yellow
    continue
  }

  if ((Test-Path -LiteralPath $old) -and ((Resolve-Path -LiteralPath $old) -ne (Resolve-Path -LiteralPath $cur))) {
    # Destination already exists with that name (unexpected). Append a suffix to avoid clash.
    $dir  = Split-Path -LiteralPath $old -Parent
    $name = Split-Path -Leaf $old
    $base = [System.IO.Path]::GetFileNameWithoutExtension($name)
    $ext  = [System.IO.Path]::GetExtension($name)

    $n = 1
    do {
      $candidate = Join-Path $dir "$base (original $n)$ext"
      $n++
    } while (Test-Path -LiteralPath $candidate)

    Write-Host "  Name clash; restoring as: $(Split-Path -Leaf $candidate)" -ForegroundColor Yellow
    Rename-Item -LiteralPath $cur -NewName (Split-Path -Leaf $candidate)
  } else {
    # Normal restore
    Rename-Item -LiteralPath $cur -NewName (Split-Path -Leaf $old)
  }
}

# Cleanup
Remove-Item -LiteralPath $mapPath -Force -ErrorAction SilentlyContinue
Write-Host "Restore complete. Goodbye!" -ForegroundColor Green
