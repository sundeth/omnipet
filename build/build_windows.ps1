# PowerShell Windows build script for Omnipet Virtual Pet Game
# Creates a Windows executable using PyInstaller

param(
    [string]$Version = ""
)

# The release version is src/core/version.py's unless -Version is given
if (-not $Version) {
    if ((Get-Content (Join-Path $PSScriptRoot "..\src\core\version.py") -Raw) -match 'VERSION\s*=\s*"([^"]+)"') {
        $Version = $matches[1]
    } else {
        Write-Host "[ERROR] No VERSION in src/core/version.py" -ForegroundColor Red
        exit 1
    }
}

$RELEASE_DIR = "..\Release"
$BUILD_NAME = "Omnipet_Windows_Ver_$Version"
$TEMP_DIR = "..\temp_windows_build"

function Write-Status {
    param([string]$Message)
    Write-Host "[WINDOWS] $Message" -ForegroundColor Yellow
}

function Write-Error-Message {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

# Check if required files exist
if (-not (Test-Path "..\main.py")) {
    Write-Error-Message "main.py not found"
    exit 1
}

if (-not (Test-Path "..\pyinstall.spec")) {
    Write-Error-Message "pyinstall.spec not found"
    exit 1
}

Write-Status "Building Windows executable version..."

# Clean previous builds. PyInstaller's work folder is build\pyinstall (its
# default "build" beside the spec, named after it); "..\build" itself is the
# folder holding these scripts and must never be removed.
Write-Status "Cleaning previous builds..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }
if (Test-Path "..\build\pyinstall") { Remove-Item -Recurse -Force "..\build\pyinstall" }
if (Test-Path "..\dist") { Remove-Item -Recurse -Force "..\dist" }

# Install pygame if needed and run PyInstaller
Write-Status "Running PyInstaller on pyinstall.spec..."
try {
    Push-Location ".."
    
    # Ensure pygame is installed
    & python -m pip install pygame
    
    # Run PyInstaller
    & pyinstaller pyinstall.spec
    $exitCode = $LASTEXITCODE
    Pop-Location
    
    if ($exitCode -ne 0) {
        throw "PyInstaller failed"
    }
} catch {
    Pop-Location
    Write-Error-Message "PyInstaller failed: $_"
    exit 1
}

# Check if executable was created
if (-not (Test-Path "..\dist\Omnipet.exe")) {
    Write-Error-Message "Omnipet.exe was not created"
    exit 1
}

Write-Success "Windows executable created successfully"

# Create temporary build directory
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME" -Force | Out-Null

# Copy assets
Write-Status "Copying assets..."
Copy-Item -Recurse "..\assets" "$TEMP_DIR\$BUILD_NAME\"

# Settings live in the save (GameConfiguration): the config/ folder
# these builds used to copy was removed in 1.0 (e09369e8).

# Copy documentation
Write-Status "Copying documentation..."
Copy-Item -Recurse "..\Documentation" "$TEMP_DIR\$BUILD_NAME\"

# Copy the Module Editor: its own repository's Release build (beside this
# repository); an older checkout kept a copy in "Module Editor" here.
Write-Status "Copying Module Editor..."
$editorSrc = @("..\Module Editor", "..\..\Omnipet Module Editor\OmnipetModuleEditor\bin\Release") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($editorSrc) {
    New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\Module Editor" -Force | Out-Null
    Get-ChildItem $editorSrc | Where-Object { $_.Name -ne "Source" } | ForEach-Object {
        Copy-Item -Recurse $_.FullName "$TEMP_DIR\$BUILD_NAME\Module Editor\"
    }
} else {
    Write-Host "[WARNING] No Module Editor build found (build it in Release first); shipping without it" -ForegroundColor Yellow
}

# Ship an EMPTY modules/ folder - releases must not include the dev
# environment's installed modules.  The runtime handles the empty
# folder (load_modules() returns an empty dict).
Write-Status "Creating empty modules/ folder..."
New-Item -ItemType Directory -Force -Path "$TEMP_DIR\$BUILD_NAME\modules" | Out-Null

# Create empty save folder
Write-Status "Creating save directory..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\save" -Force | Out-Null

# Copy executable and other files
Write-Status "Copying executable and additional files..."
Copy-Item "..\dist\Omnipet.exe" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\LICENSE.txt" "$TEMP_DIR\$BUILD_NAME\"

# Create the ZIP file
Write-Status "Creating ZIP archive..."
if (-not (Test-Path $RELEASE_DIR)) {
    New-Item -ItemType Directory -Path $RELEASE_DIR | Out-Null
}

# Remove existing ZIP file if it exists
$zipPath = "$RELEASE_DIR\$BUILD_NAME.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

try {
    Add-Type -AssemblyName "System.IO.Compression.FileSystem"
    $sourcePath = (Resolve-Path "$TEMP_DIR\$BUILD_NAME").Path
    $zipPath = (Resolve-Path $RELEASE_DIR).Path + "\$BUILD_NAME.zip"
    # Forward slashes and Unix permissions (scripts executable, folders
    # writable): .NET's ZipFile wrote backslashes and no modes, which Linux
    # unzip and Python's zipfile mis-extract (build/make_zip.py).
    python (Join-Path $PSScriptRoot "make_zip.py") $sourcePath $zipPath
    if ($LASTEXITCODE -ne 0) { throw "make_zip.py failed with exit code $LASTEXITCODE" }
} catch {
    Write-Error-Message "Failed to create ZIP file: $_"
    exit 1
}

# Clean up
Write-Status "Cleaning up temporary files..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }
if (Test-Path "..\build\pyinstall") { Remove-Item -Recurse -Force "..\build\pyinstall" }
if (Test-Path "..\dist") { Remove-Item -Recurse -Force "..\dist" }

if (Test-Path "$RELEASE_DIR\$BUILD_NAME.zip") {
    Write-Success "Windows build completed: $BUILD_NAME"
    Get-ChildItem "$RELEASE_DIR\$BUILD_NAME.zip" | Format-Table Name, Length, LastWriteTime
} else {
    Write-Error-Message "Failed to create release archive"
    exit 1
}
