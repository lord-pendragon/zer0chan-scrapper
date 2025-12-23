<#  Shuffle-Zerochan.ps1
    - Randomize image filenames in "Zerochan", open folder, wait for Enter, then restore.
    - Restore is GLOBAL (searches other folders too) based on the per-run $token.
    - If restore name collides:
        * If contents match -> delete the shuffled file as redundant
        * Else -> restore with a suffix to avoid data loss
#>

[CmdletBinding()]
param(
  # If you want a fixed absolute path, set it here (e.g. 'D:\Pictures\Zerochan').
  # Leave blank to auto-use "<script folder>\Zerochan".
  [string]$Folder = '',

  # Shuffle recursion (include subfolders under $Folder)
  [switch]$Recurse,

  # Where to search for shuffled files during restore (global search).
  # If omitted, defaults to: $Folder, its parent, and "$env:USERPROFILE\Pictures"
  [string[]]$RestoreSearchRoots = @()
)

# --- robust base folder detection (works even if $PSScriptRoot is empty) ---
$scriptDir = if ($PSScriptRoot -and $PSScriptRoot.Trim()) {
  $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
  Split-Path -Path $MyInvocation.MyCommand.Path -Parent
} else {
  (Get-Location).Path
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

# Wait for user to finish viewing / moving files elsewhere
Write-Host ""
Read-Host "Press ENTER to strip _SHFL_<token>_ from filenames (GLOBAL) and exit"

# -----------------------------
# RESTORE (GLOBAL STRIP SEARCH)
# -----------------------------

# Default restore search roots if none provided: ALL FileSystem drives (global)
if (-not $RestoreSearchRoots -or $RestoreSearchRoots.Count -eq 0) {
  $RestoreSearchRoots =
    Get-PSDrive -PSProvider FileSystem |
    Where-Object { $_.Root -and (Test-Path -LiteralPath $_.Root) } |
    Select-Object -ExpandProperty Root |
    Sort-Object -Unique
} else {
  $RestoreSearchRoots = $RestoreSearchRoots |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Sort-Object -Unique
}

Write-Host ""
Write-Host "Stripping _SHFL_ prefix (search roots):" -ForegroundColor Cyan
$RestoreSearchRoots | ForEach-Object { Write-Host "  - $_" -ForegroundColor DarkCyan }

# Find all files starting with _SHFL_ anywhere under roots
$found = New-Object System.Collections.Generic.List[System.IO.FileInfo]

foreach ($root in $RestoreSearchRoots) {
  try {
    Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue -Filter "_SHFL_*" |
      ForEach-Object { $found.Add($_) }
  } catch {
    # Access denied / weird dirs: ignore safely
  }
}

if ($found.Count -eq 0) {
  Write-Host "No _SHFL_ files found under the chosen roots." -ForegroundColor Yellow
  exit 0
}

$cleaned = 0
$deletedAsDuplicate = 0
$keptWithSuffix = 0
$skippedNotMatchingPattern = 0
$failed = 0

# Regex: _SHFL_<32-hex-guid>_<rest-of-name>
# Example: _SHFL_bd2e...9d5a_00002_Artoria.jpg  -> keep "00002_Artoria.jpg"
$rx = '^_SHFL_[0-9a-fA-F]{32}_(.+)$'

foreach ($f in $found) {
  if ($f.Name -notmatch $rx) {
    $skippedNotMatchingPattern++
    continue
  }

  $desiredName = $Matches[1]
  $destPath = Join-Path $f.DirectoryName $desiredName

  try {
    if (Test-Path -LiteralPath $destPath) {
      # Name collision in that folder.
      # If same content -> delete shuffled one. Else -> keep with suffix.
      $existing = Get-Item -LiteralPath $destPath -ErrorAction Stop

      $same = $false
      if ($existing.Length -eq $f.Length) {
        $h1 = (Get-FileHash -LiteralPath $existing.FullName -Algorithm SHA256).Hash
        $h2 = (Get-FileHash -LiteralPath $f.FullName        -Algorithm SHA256).Hash
        if ($h1 -eq $h2) { $same = $true }
      }

      if ($same) {
        Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop
        $deletedAsDuplicate++
      } else {
        $base = [System.IO.Path]::GetFileNameWithoutExtension($desiredName)
        $ext  = [System.IO.Path]::GetExtension($desiredName)

        $n = 1
        do {
          $candidateName = "$base (cleaned $n)$ext"
          $candidatePath = Join-Path $f.DirectoryName $candidateName
          $n++
        } while (Test-Path -LiteralPath $candidatePath)

        Rename-Item -LiteralPath $f.FullName -NewName (Split-Path -Leaf $candidatePath) -ErrorAction Stop
        $keptWithSuffix++
      }
    } else {
      Rename-Item -LiteralPath $f.FullName -NewName $desiredName -ErrorAction Stop
      $cleaned++
    }
  } catch {
    $failed++
    Write-Host "  Clean failed: $($f.FullName)`n    $_" -ForegroundColor Yellow
  }
}

Write-Host ""
Write-Host "Global _SHFL_ cleanup summary:" -ForegroundColor Green
Write-Host "  Cleaned (renamed):      $cleaned" -ForegroundColor Green
Write-Host "  Deleted as duplicates:  $deletedAsDuplicate" -ForegroundColor Green
Write-Host "  Kept w/ suffix:         $keptWithSuffix" -ForegroundColor Green
Write-Host "  Skipped (non-matching): $skippedNotMatchingPattern" -ForegroundColor DarkYellow
Write-Host "  Failed ops:             $failed" -ForegroundColor DarkYellow

# Cleanup unused mapping file (since we restore by stripping prefix globally)
Remove-Item -LiteralPath $mapPath -Force -ErrorAction SilentlyContinue

Write-Host "Done. Goodbye!" -ForegroundColor Green
