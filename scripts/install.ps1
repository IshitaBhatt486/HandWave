<#
.SYNOPSIS
    Download HandWave from GitHub Releases, verify it, and install it for the current user.

.EXAMPLE
    irm https://raw.githubusercontent.com/IshitaBhatt486/HandWave/main/scripts/install.ps1 | iex

.EXAMPLE
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/IshitaBhatt486/HandWave/main/scripts/install.ps1))) -Version 1.1.0 -Desktop

.EXAMPLE
    .\scripts\install.ps1 -Uninstall
#>
param(
    [string]$Version = "latest",   # e.g. 1.1.0; "latest" is the newest non-pre-release
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\HandWave",
    [switch]$Desktop,              # also create a desktop shortcut
    [switch]$Uninstall,
    [string]$BaseUrl               # download from this folder URL instead of GitHub (mirrors, testing)
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar on
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = "https://github.com/IshitaBhatt486/HandWave"
$exe = Join-Path $InstallDir "HandWave.exe"
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "HandWave.lnk"
$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "HandWave.lnk"

if ($Uninstall) {
    Get-Process HandWave -ErrorAction SilentlyContinue | Stop-Process -Force
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $InstallDir, $startMenu, $desktopLink
    Write-Host "HandWave removed. Your settings are still in $env:APPDATA\HandWave; delete that folder to remove them."
    return
}

$base = if ($BaseUrl) { $BaseUrl.TrimEnd("/") } elseif ($Version -eq "latest") { "$repo/releases/latest/download" } else { "$repo/releases/download/v$($Version.TrimStart('v'))" }
$temp = Join-Path ([IO.Path]::GetTempPath()) ("handwave-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    Write-Host "Downloading HandWave ($Version)..."
    Invoke-WebRequest "$base/HandWave.exe" -OutFile "$temp\HandWave.exe" -UseBasicParsing

    $sums = "$temp\SHA256SUMS.txt"
    try { Invoke-WebRequest "$base/SHA256SUMS.txt" -OutFile $sums -UseBasicParsing } catch { $sums = $null }
    if ($sums) {
        $expected = (Select-String -Path $sums -Pattern "HandWave\.exe$").Line.Split(" ")[0]
        $actual = (Get-FileHash -Algorithm SHA256 "$temp\HandWave.exe").Hash
        if ($expected -ine $actual) { throw "Checksum mismatch: expected $expected, got $actual. Nothing was installed." }
        Write-Host "Checksum OK ($actual)"
    } else {
        Write-Warning "This release has no SHA256SUMS.txt, so the download could not be verified."
    }

    Get-Process HandWave -ErrorAction SilentlyContinue | Stop-Process -Force
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Move-Item -Force "$temp\HandWave.exe" $exe
    foreach ($extra in "THIRD_PARTY_LICENSES.txt") {
        try { Invoke-WebRequest "$base/$extra" -OutFile (Join-Path $InstallDir $extra) -UseBasicParsing } catch { }
    }

    $shell = New-Object -ComObject WScript.Shell
    $links = @($startMenu) + $(if ($Desktop) { @($desktopLink) } else { @() })
    foreach ($path in $links) {
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = $exe
        $link.WorkingDirectory = $InstallDir
        $link.Save()
    }
    Write-Host "Installed to $exe. Start it from the Start Menu, or run: & `"$exe`""
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $temp
}
