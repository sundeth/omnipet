# Main PowerShell build script for all Omnipet platforms
param(
    [string]$Platform = "all",
    [string]$Version = ""
)

# Pre-flight: ensure every sub-script we're about to dispatch is present.
# This folder shares its name with Nuitka's default intermediate output
# directory, and earlier cleanup code wiped it on every run.  If anything
# has gone missing, fail loudly and tell the user how to recover instead
# of silently producing a broken release.
$expectedScripts = @(
    "build_windows.ps1", "build_android.ps1", "build_python_desktop.ps1",
    "build_gamepi.ps1", "build_batocera.ps1",
    "build_nuitka_windows.ps1", "build_gamepi_nuitka.ps1"
)
$missing = $expectedScripts | Where-Object {
    -not (Test-Path (Join-Path $PSScriptRoot $_))
}
if ($missing.Count -gt 0) {
    Write-Host "[ABORT] Missing build scripts: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "        Run 'git restore build/' to recover, then retry." -ForegroundColor Red
    exit 1
}

# Color functions
function Write-Status {
    param([string]$Message)
    Write-Host "[BUILD] $Message" -ForegroundColor Yellow
}

function Write-Error-Message {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

# The release version is src/core/version.py's unless -Version is given
if (-not $Version) {
    $versionFile = Get-Content (Join-Path $PSScriptRoot "..\src\core\version.py") -Raw
    if ($versionFile -match 'VERSION\s*=\s*"([^"]+)"') {
        $Version = $matches[1]
        Write-Status "Extracted version: $Version"
    } else {
        Write-Host "[ERROR] No VERSION in src/core/version.py" -ForegroundColor Red
        exit 1
    }
}

# Create Release directory
$RELEASE_DIR = "..\Release"
if (-not (Test-Path $RELEASE_DIR)) {
    New-Item -ItemType Directory -Path $RELEASE_DIR | Out-Null
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Omnipet Virtual Pet Build Script v$Version" -ForegroundColor Cyan  
# Function to check if a release already exists
function Check-ReleaseExists {
    param(
        [string]$PlatformName,
        [string]$Version,
        [string]$Extension = "zip"
    )
    $buildName = "Omnipet_${PlatformName}_Ver_${Version}.${Extension}"
    if ($PlatformName -eq "Android") {
        $buildName = "Omnipet_Android_Ver_${Version}.apk"
    }
    if ($PlatformName -eq "Windows") {
        $buildName = "Omnipet_Windows_Ver_${Version}.zip"
    }
    if ($PlatformName -eq "GamePi_Nuitka_ARM") {
        $buildName = "Omnipet_GamePi_Nuitka_ARM_Ver_${Version}.zip"
    }
    if ($PlatformName -eq "Nuitka_Windows") {
        $buildName = "Omnipet_Nuitka_Windows_Ver_${Version}.zip"
    }
    
    $releasePath = Join-Path $RELEASE_DIR $buildName
    if (Test-Path $releasePath) {
        Write-Status "Release for $PlatformName v$Version already exists. Skipping."
        return $true
    }
    return $false
}

# Function to build Windows version
function Build-Windows {
    if (Check-ReleaseExists -PlatformName "Windows" -Version $Version) { return $true }
    Write-Status "Building Windows EXE..."
    try {
        powershell.exe -File ".\build_windows.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Windows build completed"
            return $true
        } else {
            Write-Error-Message "Windows build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run Windows build script: $_"
        return $false
    }
}

# Function to build Python Desktop version
function Build-PythonDesktop {
    if (Check-ReleaseExists -PlatformName "Python_Desktop" -Version $Version) { return $true }
    Write-Status "Building Python Desktop version..."
    try {
        powershell.exe -File ".\build_python_desktop.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Python Desktop build completed"
            return $true
        } else {
            Write-Error-Message "Python Desktop build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run Python Desktop build script: $_"
        return $false
    }
}

# Function to build GamePi version
function Build-GamePi {
    if (Check-ReleaseExists -PlatformName "GamePi" -Version $Version) { return $true }
    Write-Status "Building GamePi version..."
    try {
        powershell.exe -File ".\build_gamepi.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "GamePi build completed"
            return $true
        } else {
            Write-Error-Message "GamePi build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run GamePi build script: $_"
        return $false
    }
}

# Function to build GamePi Nuitka ARM version
function Build-GamePiNuitka {
    if (Check-ReleaseExists -PlatformName "GamePi_Nuitka_ARM" -Version $Version) { return $true }
    Write-Status "Building GamePi Nuitka ARM version..."
    try {
        powershell.exe -File ".\build_gamepi_nuitka.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "GamePi Nuitka ARM build completed"
            return $true
        } else {
            Write-Error-Message "GamePi Nuitka ARM build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run GamePi Nuitka ARM build script: $_"
        return $false
    }
}

# Function to build Windows Nuitka version
function Build-NuitkaWindows {
    if (Check-ReleaseExists -PlatformName "Nuitka_Windows" -Version $Version) { return $true }
    Write-Status "Building Windows Nuitka version..."
    try {
        powershell.exe -File ".\build_nuitka_windows.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Windows Nuitka build completed"
            return $true
        } else {
            Write-Error-Message "Windows Nuitka build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run Windows Nuitka build script: $_"
        return $false
    }
}

# Function to build Batocera version
function Build-Batocera {
    if (Check-ReleaseExists -PlatformName "Batocera" -Version $Version) { return $true }
    Write-Status "Building Batocera version..."
    try {
        powershell.exe -File ".\build_batocera.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Batocera build completed"
            return $true
        } else {
            Write-Error-Message "Batocera build failed"
            return $false
        }
    } catch {
        Write-Error-Message "Failed to run Batocera build script: $_"
        return $false
    }
}

# Function to build Android version
function Build-Android {
    if (Check-ReleaseExists -PlatformName "Android" -Version $Version -Extension "apk") { return $true }
    Write-Status "Building Android version..."
    try {
        powershell.exe -File ".\build_android.ps1" -Version $Version
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Android build completed"
            return $true
        } else {
            Write-Error-Message "Android build failed"
            # Ignoring Android build errors as requested
            return $true
        }
    } catch {
        Write-Error-Message "Failed to run Android build script: $_"
        # Ignoring Android build errors as requested
        return $true
    }
}

# Function to clean up temporary files
function Clean-Up {
    Write-Status "Cleaning up temporary build files..."
    $rootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    
    # IMPORTANT: do NOT remove "$rootDir\build" — that path is the folder
    # holding every PowerShell script we just dispatched.  Earlier
    # revisions wiped it here and obliterated the scripts on every run.
    # Only clean Nuitka's actual leak folders (source-name-derived).
    foreach ($leak in @("main_nuitka.build", "main_nuitka.dist", "main_nuitka.onefile-build")) {
        Remove-Item -Path (Join-Path $rootDir $leak) -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -Path (Join-Path $rootDir "dist") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $rootDir "temp_*") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $PSScriptRoot "temp_*") -Recurse -Force -ErrorAction SilentlyContinue
    
    # Clean up any compiled binaries from Nuitka builds
    Remove-Item -Path (Join-Path $rootDir "Omnipet.exe") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $rootDir "Omnipet") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $rootDir "main_nuitka.exe") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $rootDir "main_nuitka") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $rootDir "*.pyd") -Force -ErrorAction SilentlyContinue
    
    Write-Success "Cleanup complete."
}

# Main build logic
$success = $true
$platformsToBuild = @()

if ($Platform -eq "all") {
    $platformsToBuild = @("windows", "python_desktop", "gamepi", "batocera", "android")
} else {
    $platformsToBuild = @($Platform)
}

foreach ($p in $platformsToBuild) {
    $result = $false
    switch ($p) {
        "windows" { $result = Build-Windows }
        "python_desktop" { $result = Build-PythonDesktop }
        "gamepi" { $result = Build-GamePi }
        "gamepi_nuitka" { $result = Build-GamePiNuitka }
        "nuitka_windows" { $result = Build-NuitkaWindows }
        "batocera" { $result = Build-Batocera }
        "android" { $result = Build-Android }
        default {
            Write-Error-Message "Unknown platform: $p"
        }
    }
    if (-not $result) {
        $success = $false
        Write-Error-Message "Build for platform '$p' failed. Aborting further builds."
        break
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
if ($success) {
    Write-Success "All builds completed successfully!"
} else {
    Write-Error-Message "One or more builds failed."
}

Clean-Up

Write-Host "==========================================" -ForegroundColor Cyan
if ($success) {
    exit 0
} else {
    exit 1
}
