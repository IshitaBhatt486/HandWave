$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

function Write-ReleaseStage([string] $message) {
    Write-Host "`n==> $message" -ForegroundColor Cyan
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run scripts\setup.cmd dev first."
}

Write-ReleaseStage "Validating release prerequisites"
& $python -c "import sys; assert sys.version_info[:2] == (3, 11), f'HandWave requires Python 3.11; found {sys.version}'"
if ($LASTEXITCODE -ne 0) { throw "Unsupported Python version." }
& $python -c "import importlib; import importlib.metadata as m; modules={'PyInstaller':'PyInstaller','PyQt6':'PyQt6','mediapipe':'mediapipe','numpy':'numpy','opencv-python':'cv2','sounddevice':'sounddevice'}; [importlib.import_module(module) for module in modules.values()]; print('Dependencies:', ', '.join(f'{name}={m.version(name)}' for name in modules))"
if ($LASTEXITCODE -ne 0) { throw "Required build dependency is missing or cannot be imported. Run scripts\setup.cmd dev." }
foreach ($file in @('packaging\HandWave.spec', 'packaging\HandWave.nsi', 'packaging\version_info.txt', 'handwave\assets\handwave.ico')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $file))) { throw "Required release input is missing: $file" }
}

Write-ReleaseStage "Running test and coverage gate"
& ".\scripts\run_tests.cmd" -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; release build stopped." }

Write-ReleaseStage "Building executable with PyInstaller"
# A separate work directory makes every release clean and avoids stale/locked
# files under the developer's ordinary build directory. Do not retry a failed
# clean build without --clean: that hides the failure and can ship stale code.
$pyInstallerWork = Join-Path $projectRoot ".build-release"
& $python -m PyInstaller --noconfirm --clean --workpath $pyInstallerWork "packaging\HandWave.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$release = Join-Path $projectRoot "dist\HandWave.exe"
if (-not (Test-Path -LiteralPath $release)) { throw "Release executable was not created." }

$nsisCandidates = @(
    $env:NSIS_MAKENSIS,
    (Get-Command "makensis.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Program Files (x86)\NSIS\makensis.exe",
    "C:\Program Files\NSIS\makensis.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$makensis = $nsisCandidates | Select-Object -First 1
if (-not $makensis) {
    throw "NSIS was not found. Install it with: winget install --id NSIS.NSIS -e"
}

Write-ReleaseStage "Building NSIS installer"
$version = & $python -c "from handwave.version import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Unable to read HandWave version." }

& $makensis "/DPRODUCT_VERSION=$version" "packaging\HandWave.nsi"
if ($LASTEXITCODE -ne 0) { throw "NSIS installer build failed." }

$installer = Join-Path $projectRoot "dist\HandWave-$version-Setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer was not created." }

$checksums = @($release, $installer) | ForEach-Object {
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($_))"
}
$checksums | Set-Content -Encoding ascii -LiteralPath (Join-Path $projectRoot "dist\SHA256SUMS.txt")

Write-Host "Portable executable: $release"
Write-Host "Installer: $installer"
Write-Host "Checksums: $(Join-Path $projectRoot 'dist\SHA256SUMS.txt')"
