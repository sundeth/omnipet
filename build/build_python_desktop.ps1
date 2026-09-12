# PowerShell Python Desktop build script for Omnipet Virtual Pet Game
# Creates a Python desktop version for Windows and Linux

param(
    [string]$Version = "0.9.8"
)

$RELEASE_DIR = "..\Release"
$BUILD_NAME = "Omnipet_Python_Desktop_Ver_$Version"
$TEMP_DIR = "..\temp_python_desktop_build"

function Write-Status {
    param([string]$Message)
    Write-Host "[PYTHON] $Message" -ForegroundColor Yellow
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

Write-Status "Building Python Desktop version..."

# Clean previous builds
Write-Status "Cleaning previous builds..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }

# Create temporary build directory
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME" -Force | Out-Null

# Copy assets
Write-Status "Copying assets..."
Copy-Item -Recurse "..\assets" "$TEMP_DIR\$BUILD_NAME\"

# Copy and rename config files
Write-Status "Copying configuration files..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\config" -Force | Out-Null
Copy-Item "..\config\config_python_desktop.json" "$TEMP_DIR\$BUILD_NAME\config\config.json"
Copy-Item "..\config\input_config_python_desktop.json" "$TEMP_DIR\$BUILD_NAME\config\input_config.json"

# Copy documentation
Write-Status "Copying documentation..."
Copy-Item -Recurse "..\Documentation" "$TEMP_DIR\$BUILD_NAME\"

# Copy core directory (excluding __pycache__ folders)
Write-Status "Copying core directory..."
$coreSource = (Resolve-Path "..\src\core").Path
$coreDestination = "$TEMP_DIR\$BUILD_NAME\src\core"
robocopy $coreSource $coreDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy core directory"
    exit 1
}

# Copy models directory
Write-Status "Copying models directory..."
$modelsSource = (Resolve-Path "..\src\models").Path
$modelsDestination = "$TEMP_DIR\$BUILD_NAME\src\models"
robocopy $modelsSource $modelsDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy models directory"
    exit 1
}

# Copy ui directory
Write-Status "Copying ui directory..."
$uiSource = (Resolve-Path "..\src\ui").Path
$uiDestination = "$TEMP_DIR\$BUILD_NAME\src\ui"
robocopy $uiSource $uiDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy ui directory"
    exit 1
}

# Copy input directory
Write-Status "Copying input directory..."
$inputSource = (Resolve-Path "..\src\input").Path
$inputDestination = "$TEMP_DIR\$BUILD_NAME\src\input"
robocopy $inputSource $inputDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy input directory"
    exit 1
}

# Copy battle directory
Write-Status "Copying battle directory..."
$battleSource = (Resolve-Path "..\src\battle").Path
$battleDestination = "$TEMP_DIR\$BUILD_NAME\src\battle"
robocopy $battleSource $battleDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy battle directory"
    exit 1
}

# Copy training directory
Write-Status "Copying training directory..."
$trainingSource = (Resolve-Path "..\src\training").Path
$trainingDestination = "$TEMP_DIR\$BUILD_NAME\src\training"
robocopy $trainingSource $trainingDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy training directory"
    exit 1
}

# Copy services directory
Write-Status "Copying services directory..."
$servicesSource = (Resolve-Path "..\src\services").Path
$servicesDestination = "$TEMP_DIR\$BUILD_NAME\src\services"
robocopy $servicesSource $servicesDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy services directory"
    exit 1
}

# Copy data directory
Write-Status "Copying data directory..."
$dataSource = (Resolve-Path "..\src\data").Path
$dataDestination = "$TEMP_DIR\$BUILD_NAME\src\data"
robocopy $dataSource $dataDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy data directory"
    exit 1
}

# Copy utils directory
Write-Status "Copying utils directory..."
$utilsSource = (Resolve-Path "..\src\utils").Path
$utilsDestination = "$TEMP_DIR\$BUILD_NAME\src\utils"
robocopy $utilsSource $utilsDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy utils directory"
    exit 1
}

# Copy scenes directory
Write-Status "Copying scenes directory..."
$scenesSource = (Resolve-Path "..\src\scenes").Path
$scenesDestination = "$TEMP_DIR\$BUILD_NAME\src\scenes"
robocopy $scenesSource $scenesDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy scenes directory"
    exit 1
}

# Copy wificom directory
Write-Status "Copying wificom directory..."
$wificomSource = (Resolve-Path "..\src\wificom").Path
$wificomDestination = "$TEMP_DIR\$BUILD_NAME\src\wificom"
robocopy $wificomSource $wificomDestination /E /XD "__pycache__" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error-Message "Failed to copy wificom directory"
    exit 1
}

# Copy vpet.py and src __init__.py
Write-Status "Copying vpet.py..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\src" -Force | Out-Null
Copy-Item "..\src\vpet.py" "$TEMP_DIR\$BUILD_NAME\src\"
Copy-Item "..\src\__init__.py" "$TEMP_DIR\$BUILD_NAME\src\"

# Copy Module Editor (excluding Source folder)
Write-Status "Copying Module Editor..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\Module Editor" -Force | Out-Null
Get-ChildItem "..\Module Editor" | Where-Object { $_.Name -ne "Source" } | ForEach-Object {
    Copy-Item -Recurse $_.FullName "$TEMP_DIR\$BUILD_NAME\Module Editor\"
}

# Ship an EMPTY modules/ folder - releases must not include the dev
# environment's installed modules.  The runtime handles the empty
# folder (load_modules() returns an empty dict).
Write-Status "Creating empty modules/ folder..."
New-Item -ItemType Directory -Force -Path "$TEMP_DIR\$BUILD_NAME\modules" | Out-Null

# Create empty save folder
Write-Status "Creating save directory..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\save" -Force | Out-Null

# Copy Python files and scripts
Write-Status "Copying Python files and launch scripts..."
Copy-Item "..\__init__.py" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\launch.bat" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\launch.sh" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\LICENSE.txt" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\main.py" "$TEMP_DIR\$BUILD_NAME\"
Copy-Item "..\ModuleEditor.bat" "$TEMP_DIR\$BUILD_NAME\"

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
    [System.IO.Compression.ZipFile]::CreateFromDirectory($sourcePath, $zipPath)
} catch {
    Write-Error-Message "Failed to create ZIP file: $_"
    exit 1
}

# Clean up
Write-Status "Cleaning up temporary files..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }

if (Test-Path "$RELEASE_DIR\$BUILD_NAME.zip") {
    Write-Success "Python Desktop build completed: $BUILD_NAME"
    Get-ChildItem "$RELEASE_DIR\$BUILD_NAME.zip" | Format-Table Name, Length, LastWriteTime
} else {
    Write-Error-Message "Failed to create release archive"
    exit 1
}
