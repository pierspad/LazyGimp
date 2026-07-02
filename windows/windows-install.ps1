#Requires -Version 5.1
<#
.SYNOPSIS
    LazyGimp for Windows — latest stable GIMP + PhotoGIMP, one script.

.DESCRIPTION
    Downloads the official GIMP installer published by gimp.org (version and
    SHA-256 taken from gimp.org's own metadata, never hardcoded), installs it
    silently, then applies the PhotoGIMP configuration layer to the config
    directory matching the installed GIMP version.

    A full backup of any existing configuration is created before anything
    is written, and every file the layer installs is recorded in a manifest.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File windows-install.ps1

.NOTES
    Why a script instead of an MSI? See docs/ARCHITECTURE.md in the repo:
    unsigned installers fight SmartScreen, and wrapping the upstream
    installer adds nothing but maintenance burden.
#>
[CmdletBinding()]
param(
    [switch]$SkipGimpInstall,
    [switch]$SkipPhotoGimp
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$VersionsUrl = 'https://www.gimp.org/gimp_versions.json'
$Mirror      = 'https://download.gimp.org/gimp'
$PhotoGimpRepo = 'Diolinux/PhotoGIMP'
# renovate: datasource=github-releases depName=Diolinux/PhotoGIMP
$PhotoGimpTag  = '3.0'
$GmicPage    = 'https://gmic.eu/download.html'
$StateDir    = Join-Path $env:LOCALAPPDATA 'LazyGimp'
$ManifestName = '.lazygimp-photogimp.manifest'

function Write-Info($Message) { Write-Host "[info] $Message" -ForegroundColor Cyan }
function Write-Ok($Message)   { Write-Host "[ ok ] $Message" -ForegroundColor Green }

# Latest stable GIMP release for Windows, straight from gimp.org metadata.
function Get-LatestStableGimp {
    $data = Invoke-RestMethod -Uri $VersionsUrl
    $release = $data.STABLE | Select-Object -First 1
    $win = $release.windows | Select-Object -First 1
    if (-not $win) { throw 'no Windows installer found in gimp.org metadata' }
    [pscustomobject]@{
        Version  = [string]$release.version
        Series   = ([string]$release.version -replace '^(\d+\.\d+).*', '$1')
        FileName = [string]$win.filename
        Sha256   = [string]$win.sha256
    }
}

function Install-Gimp([pscustomobject]$Gimp) {
    $url = "$Mirror/v$($Gimp.Series)/windows/$($Gimp.FileName)"
    $installer = Join-Path $env:TEMP $Gimp.FileName

    Write-Info "downloading GIMP $($Gimp.Version) from $url"
    Invoke-WebRequest -Uri $url -OutFile $installer

    $actual = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Gimp.Sha256.ToLowerInvariant()) {
        throw "checksum mismatch for $($Gimp.FileName): expected $($Gimp.Sha256), got $actual"
    }
    Write-Info 'checksum verified'

    Write-Info 'running the official installer silently (this can take a few minutes)'
    Start-Process -FilePath $installer -ArgumentList '/VERYSILENT', '/NORESTART' -Wait
    Remove-Item $installer -Force
    Write-Ok "GIMP $($Gimp.Version) installed"
}

# Resolve the config directory the layer must target: the series we just
# installed, or the newest existing X.Y directory as a fallback.
function Get-GimpConfigDir([string]$Series) {
    $base = Join-Path $env:APPDATA 'GIMP'
    if ($Series) { return (Join-Path $base $Series) }
    $existing = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } |
        Select-Object -Last 1
    if (-not $existing) { throw "no GIMP config directory found under $base — launch GIMP once, then re-run" }
    return $existing.FullName
}

function Install-PhotoGimp([string]$TargetDir) {
    $zipUrl = "https://github.com/$PhotoGimpRepo/releases/download/$PhotoGimpTag/PhotoGIMP.zip"
    $tmp = Join-Path $env:TEMP "lazygimp-$([guid]::NewGuid().ToString('n'))"
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'PhotoGIMP.zip'
        Write-Info "downloading PhotoGIMP ($PhotoGimpTag)"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'extracted') -Force

        # Newest .config/GIMP/X.Y payload inside the archive, version-agnostic.
        $payload = Get-ChildItem -Path (Join-Path $tmp 'extracted') -Recurse -Directory |
            Where-Object { $_.FullName -match '\.config[\\/]GIMP[\\/]\d+\.\d+$' } |
            Sort-Object { [version]$_.Name } |
            Select-Object -Last 1
        if (-not $payload) { throw 'no GIMP payload (.config/GIMP/X.Y) found in the PhotoGIMP archive' }

        # Backup before touching anything.
        if (Test-Path $TargetDir) {
            $backupDir = Join-Path $StateDir 'backups'
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $backup = Join-Path $backupDir ("gimp-config-" + (Split-Path $TargetDir -Leaf) + "-$stamp.zip")
            Compress-Archive -Path (Join-Path $TargetDir '*') -DestinationPath $backup -Force
            Write-Info "existing configuration backed up to $backup"
        }
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

        # Copy file-by-file, recording everything in a manifest so the layer
        # can be removed cleanly. User files are never deleted.
        $manifest = Join-Path $TargetDir $ManifestName
        Set-Content -Path $manifest -Value @()
        Get-ChildItem -Path $payload.FullName -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($payload.FullName.Length).TrimStart('\', '/')
            $dest = Join-Path $TargetDir $rel
            New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
            Copy-Item -Path $_.FullName -Destination $dest -Force
            Add-Content -Path $manifest -Value $rel
        }
        $count = (Get-Content $manifest | Measure-Object -Line).Lines
        Write-Ok "PhotoGIMP layer installed ($count files) into $TargetDir"
    }
    finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ------------------------------- main flow --------------------------------
$gimp = Get-LatestStableGimp

if (-not $SkipGimpInstall) {
    Install-Gimp $gimp
}

if (-not $SkipPhotoGimp) {
    Install-PhotoGimp (Get-GimpConfigDir $gimp.Series)
}

Write-Warning "G'MIC ships its own Windows installer for GIMP — grab it from $GmicPage"
Write-Ok 'all done — launch GIMP from the Start menu'
