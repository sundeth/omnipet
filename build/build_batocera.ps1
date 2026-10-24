# PowerShell Batocera build script for Omnipet Virtual Pet Game
# Creates a Batocera version

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
$BUILD_NAME = "Omnipet_Batocera_Ver_$Version"
$TEMP_DIR = "..\temp_batocera_build"

function Write-Status {
    param([string]$Message)
    Write-Host "[BATOCERA] $Message" -ForegroundColor Yellow
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

if (-not (Test-Path "..\omnipet.pygame")) {
    Write-Error-Message "omnipet.pygame not found"
    exit 1
}

if (-not (Test-Path "batocera\input_test")) {
    Write-Error-Message "build\batocera\input_test folder not found"
    exit 1
}

Write-Status "Building Batocera version..."

# Clean previous builds
Write-Status "Cleaning previous builds..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }

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

# Copy core directory (excluding __pycache__ folders)
Write-Status "Copying core directory..."
$coreSource = (Resolve-Path "..\src\core").Path
$coreDestination = "$TEMP_DIR\$BUILD_NAME\src\core"
robocopy $coreSource $coreDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy models directory
Write-Status "Copying models directory..."
$modelsSource = (Resolve-Path "..\src\models").Path
$modelsDestination = "$TEMP_DIR\$BUILD_NAME\src\models"
robocopy $modelsSource $modelsDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy ui directory
Write-Status "Copying ui directory..."
$uiSource = (Resolve-Path "..\src\ui").Path
$uiDestination = "$TEMP_DIR\$BUILD_NAME\src\ui"
robocopy $uiSource $uiDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy input directory
Write-Status "Copying input directory..."
$inputSource = (Resolve-Path "..\src\input").Path
$inputDestination = "$TEMP_DIR\$BUILD_NAME\src\input"
robocopy $inputSource $inputDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy battle directory
Write-Status "Copying battle directory..."
$battleSource = (Resolve-Path "..\src\battle").Path
$battleDestination = "$TEMP_DIR\$BUILD_NAME\src\battle"
robocopy $battleSource $battleDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy training directory
Write-Status "Copying training directory..."
$trainingSource = (Resolve-Path "..\src\training").Path
$trainingDestination = "$TEMP_DIR\$BUILD_NAME\src\training"
robocopy $trainingSource $trainingDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy services directory
Write-Status "Copying services directory..."
$servicesSource = (Resolve-Path "..\src\services").Path
$servicesDestination = "$TEMP_DIR\$BUILD_NAME\src\services"
robocopy $servicesSource $servicesDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy data directory
Write-Status "Copying data directory..."
$dataSource = (Resolve-Path "..\src\data").Path
$dataDestination = "$TEMP_DIR\$BUILD_NAME\src\data"
robocopy $dataSource $dataDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy utils directory
Write-Status "Copying utils directory..."
$utilsSource = (Resolve-Path "..\src\utils").Path
$utilsDestination = "$TEMP_DIR\$BUILD_NAME\src\utils"
robocopy $utilsSource $utilsDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy scenes directory
Write-Status "Copying scenes directory..."
$scenesSource = (Resolve-Path "..\src\scenes").Path
$scenesDestination = "$TEMP_DIR\$BUILD_NAME\src\scenes"
robocopy $scenesSource $scenesDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy wificom directory
Write-Status "Copying wificom directory..."
$wificomSource = (Resolve-Path "..\src\wificom").Path
$wificomDestination = "$TEMP_DIR\$BUILD_NAME\src\wificom"
robocopy $wificomSource $wificomDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

# Copy vpet.py and src __init__.py
Write-Status "Copying vpet.py..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\src" -Force | Out-Null
Copy-Item "..\src\vpet.py" "$TEMP_DIR\$BUILD_NAME\src\"
Copy-Item "..\src\__init__.py" "$TEMP_DIR\$BUILD_NAME\src\"

# Ship an EMPTY modules/ folder - releases must not include the dev
# environment's installed modules.  The runtime handles the empty
# folder (load_modules() returns an empty dict).
Write-Status "Creating empty modules/ folder..."
New-Item -ItemType Directory -Force -Path "$TEMP_DIR\$BUILD_NAME\modules" | Out-Null

# Create empty save folder
Write-Status "Creating save directory..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\save" -Force | Out-Null

# Copy Python files and scripts
Write-Status "Copying Python files and configuration..."
Copy-Item "..\__init__.py" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\LICENSE.txt" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\main.py" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\omnipet.pygame" "$TEMP_DIR\$BUILD_NAME\"

# Copy the input test (versioned in build/batocera/)
Write-Status "Copying input test utilities..."
Copy-Item -Recurse "batocera\input_test" "$TEMP_DIR\$BUILD_NAME\"

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

if (Test-Path "$RELEASE_DIR\$BUILD_NAME.zip") {
    Write-Success "Batocera build completed: $BUILD_NAME"
    Get-ChildItem "$RELEASE_DIR\$BUILD_NAME.zip" | Format-Table Name, Length, LastWriteTime
} else {
    Write-Error-Message "Failed to create release archive"
    exit 1
}
