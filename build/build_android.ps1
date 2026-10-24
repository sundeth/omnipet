# PowerShell script to build Android APK with Buildozer (cleaned)
param(
    [switch]$Clean = $false,
    [switch]$Release = $false,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

# The release version is src/core/version.py's unless -Version is given
# (build_all.ps1 passes it; the script used to have no such parameter, so
# build_all's Android step failed at once and was ignored).
if (-not $Version) {
    if ((Get-Content (Join-Path $PSScriptRoot "..\src\core\version.py") -Raw) -match 'VERSION\s*=\s*"([^"]+)"') {
        $Version = $matches[1]
    } else {
        Write-Host "[ERROR] No VERSION in src/core/version.py" -ForegroundColor Red
        exit 1
    }
}

Write-Host "=== Omnipet Android Build ===" -ForegroundColor Cyan

# Configuration
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$WSLBuildDir = "~/omnipet_build"
$BuildType = if ($Release) { "release" } else { "debug" }

Write-Host "[1/4] Preparing build directory..." -ForegroundColor Yellow
# Wipe stale top-level Python packages from prior layouts (older builds
# shipped a flat `core/`, `components/`, `scenes/` alongside the new
# `src/`).  Python's importer finds those FIRST on sys.path and runs
# stale .pyc bytecode that breaks under the current source layout
# (notably on Bluestacks where the import-resolution path differs from
# physical Android devices).  We keep `.buildozer/`, `bin/`, `src/` and
# the resource folders intact so incremental builds stay fast.
wsl bash -c "if [ -d $WSLBuildDir ]; then find $WSLBuildDir -maxdepth 1 -mindepth 1 \( -name '.buildozer' -o -name 'bin' -o -name 'src' -o -name 'assets' -o -name 'modules' -o -name 'save' -o -name '_python_bundle' \) -prune -o -exec rm -rf {} +; fi"
wsl bash -c "mkdir -p $WSLBuildDir/{src/core,src/models,src/ui,src/ui/components,src/ui/windows,src/ui/minigames,src/input,src/battle,src/battle/dcom,src/battle/sim,src/training,src/services,src/data,src/data/protocols,src/data/attack_patterns,src/utils,src/scenes,src/wificom,assets,modules,save}"

Write-Host "[2/4] Syncing files to WSL..." -ForegroundColor Yellow
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/core/ $WSLBuildDir/src/core/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/models/ $WSLBuildDir/src/models/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/ui/ $WSLBuildDir/src/ui/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/input/ $WSLBuildDir/src/input/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/battle/ $WSLBuildDir/src/battle/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/training/ $WSLBuildDir/src/training/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/services/ $WSLBuildDir/src/services/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/data/ $WSLBuildDir/src/data/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/utils/ $WSLBuildDir/src/utils/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/scenes/ $WSLBuildDir/src/scenes/"
wsl bash -c "rsync -avu --delete --exclude='__pycache__' --exclude='*.pyc' /mnt/e/Omnipet/src/wificom/ $WSLBuildDir/src/wificom/"
wsl bash -c "cp /mnt/e/Omnipet/src/vpet.py $WSLBuildDir/src/vpet.py"
wsl bash -c "cp /mnt/e/Omnipet/src/__init__.py $WSLBuildDir/src/__init__.py"
wsl bash -c "rsync -avu --delete /mnt/e/Omnipet/assets/ $WSLBuildDir/assets/"
# Ship an EMPTY modules/ folder — releases must not bundle the dev
# environment's installed modules.  --delete clears whatever may have
# been there from a previous run.
wsl bash -c "rm -rf $WSLBuildDir/modules && mkdir -p $WSLBuildDir/modules"
# config/ folder removed from the source tree (settings live in save/
# + core defaults); skip its rsync. Step 1 no longer keeps or recreates a
# config/ in the WSL build folder: the old one (ten 2025 JSON files the
# game no longer reads) went into every APK.
# Ship an EMPTY save/ folder — dev saves, configuration, and device_key
# must not leak into release APKs.  At runtime the app reads/writes saves
# from android.storage.app_storage_path()/save anyway, so a bundled save
# folder would never be used.
wsl bash -c "rm -rf $WSLBuildDir/save && mkdir -p $WSLBuildDir/save"
wsl bash -c "cp /mnt/e/Omnipet/main_android.py $WSLBuildDir/main.py"
wsl bash -c "rsync -avu --delete /mnt/e/Omnipet/android_src/ $WSLBuildDir/android_src/"
wsl bash -c "python3 /mnt/e/Omnipet/build/prepare_android_manifest.py $WSLBuildDir/android_src"
wsl bash -c "cp /mnt/e/Omnipet/buildozer.spec $WSLBuildDir/"

# Clean caches
Write-Host "[3/4] Cleaning Python bytecode cache..." -ForegroundColor Yellow
wsl bash -c "cd $WSLBuildDir && find . -type f -name '*.pyc' -delete && find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true"
if ($Clean) { wsl bash -c "cd $WSLBuildDir && rm -rf .buildozer bin" }

Write-Host "[4/4] Building APK ($BuildType)..." -ForegroundColor Yellow
# Wipe both WSL bin/ and the project bin/ so stale APKs from prior
# versions (e.g. omnipet-0.9.9-arm64-v8a-debug.apk) don't end up in the
# copy step alongside the current one.
wsl bash -c "rm -f $WSLBuildDir/bin/*.apk"
if (Test-Path "$ProjectRoot\bin") {
    Remove-Item "$ProjectRoot\bin\*.apk" -Force -ErrorAction SilentlyContinue
}
$buildCommand = if ($Release) { "cd $WSLBuildDir && buildozer android clean && buildozer android release" } else { "cd $WSLBuildDir && buildozer android clean && buildozer android debug" }
wsl bash -c $buildCommand

if ($LASTEXITCODE -eq 0) {
    Write-Host "=== Build Successful ===" -ForegroundColor Green
    # Native sources must be compiled into the dex files (classes*.dex: the APK has
    # several); no service payload remains.
    wsl bash -c "unzip -p $WSLBuildDir/bin/*.apk 'classes*.dex' | strings | grep -q 'org/omnipet/offline/PetAlarmReceiver'"
    if ($LASTEXITCODE -ne 0) {
        throw "PetAlarmReceiver is missing from the APK's native classes."
    }
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\bin" | Out-Null
    wsl bash -c "cp $WSLBuildDir/bin/*.apk /mnt/e/Omnipet/bin/"
    Get-ChildItem "$ProjectRoot\bin\*.apk" | ForEach-Object { Write-Host "  $($_.Name)" -ForegroundColor Cyan }
    # The release name build_all.ps1 looks for (Buildozer's own name stays in bin/)
    $apk = Get-ChildItem "$ProjectRoot\bin\*.apk" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\Release" | Out-Null
    Copy-Item $apk.FullName "$ProjectRoot\Release\Omnipet_Android_Ver_$Version.apk" -Force
    Write-Host "  Release\Omnipet_Android_Ver_$Version.apk" -ForegroundColor Cyan
} else {
    Write-Host "=== Build Failed ===" -ForegroundColor Red
    exit 1
}
