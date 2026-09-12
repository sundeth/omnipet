# PowerShell Windows Nuitka build script for Omnipet Virtual Pet Game
# Uses Nuitka for packaging and performance optimization
# Windows testing/production version

param(
    [string]$Version = "0.9.8"
)

# Use absolute paths to avoid confusion
$SCRIPT_DIR = $PSScriptRoot
$PROJECT_ROOT = Split-Path $SCRIPT_DIR -Parent
$RELEASE_DIR = Join-Path $PROJECT_ROOT "Release"
$BUILD_NAME = "Omnipet_Nuitka_Windows_Ver_$Version"
$TEMP_DIR = Join-Path $PROJECT_ROOT "temp_nuitka_windows_build"

function Write-Status {
    param([string]$Message)
    Write-Host "[NUITKA-WINDOWS] $Message" -ForegroundColor Yellow
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
if (-not (Test-Path (Join-Path $PROJECT_ROOT "main_nuitka.py"))) {
    Write-Error-Message "main_nuitka.py not found"
    exit 1
}

Write-Status "Building Nuitka Windows version..."

# Clean previous builds
Write-Status "Cleaning previous builds..."
if (Test-Path $TEMP_DIR) { Remove-Item -Recurse -Force $TEMP_DIR }
# IMPORTANT: do NOT wipe $PROJECT_ROOT\build — that's the folder these
# scripts live in.  Nuitka writes its intermediates to $TEMP_DIR (set
# via --output-dir) and to source-name-derived sibling folders at the
# project root (main_nuitka.build / .dist / .onefile-build).  Clean
# only those, never the generic "build" name.
foreach ($leak in @("main_nuitka.build", "main_nuitka.dist", "main_nuitka.onefile-build")) {
    $leakPath = Join-Path $PROJECT_ROOT $leak
    if (Test-Path $leakPath) { Remove-Item -Recurse -Force $leakPath }
}
if (Test-Path (Join-Path $PROJECT_ROOT "dist")) { Remove-Item -Recurse -Force (Join-Path $PROJECT_ROOT "dist") }

# Check if Nuitka is installed
Write-Status "Checking for Nuitka..."
try {
    $nuitkaVersion = python -m nuitka --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Nuitka not found. Installing Nuitka..."
        python -m pip install nuitka
        if ($LASTEXITCODE -ne 0) {
            Write-Error-Message "Failed to install Nuitka"
            exit 1
        }
    } else {
        Write-Status "Nuitka found: $nuitkaVersion"
    }
} catch {
    Write-Error-Message "Failed to check/install Nuitka: $_"
    exit 1
}

# Create temporary build directory
New-Item -ItemType Directory -Path "$TEMP_DIR" -Force | Out-Null

# Build with Nuitka for modular compilation
Write-Status "Building with Nuitka for modular Windows compilation..."
Write-Status "Creating separate compiled modules (.pyd files) for debugging..."

try {
    Push-Location $PROJECT_ROOT
    
    # Set PYTHONPATH for Nuitka compilation
    $env:PYTHONPATH = "$PROJECT_ROOT;$PROJECT_ROOT\src"
    Write-Status "Temporarily setting PYTHONPATH for Nuitka: $env:PYTHONPATH"

    # Nuitka build command for Windows
    python -m nuitka `
        --output-dir="$TEMP_DIR" `
        --output-filename="omnipet" `
        --include-package="src" `
        --include-package="src.core" `
        --include-package="src.models" `
        --include-package="src.ui" `
        --include-package="src.ui.components" `
        --include-package="src.ui.windows" `
        --include-package="src.ui.minigames" `
        --include-package="src.input" `
        --include-package="src.battle" `
        --include-package="src.battle.dcom" `
        --include-package="src.battle.sim" `
        --include-package="src.training" `
        --include-package="src.services" `
        --include-package="src.data" `
        --include-package="src.utils" `
        --include-package="src.scenes" `
        --include-package="src.wificom" `
        --include-package-data="src" `
        --include-module="json" `
        --include-module="psutil" `
        --include-module="paho.mqtt.client" `
        --include-module="platform" `
        --include-module="os" `
        --include-module="sys" `
        --nofollow-import-to="pygame.tests" `
        --nofollow-import-to="pygame.examples" `
        --nofollow-import-to="pygame.docs" `
        --follow-imports `
        --assume-yes-for-downloads `
        --show-progress `
        --python-flag="no_site" `
        --python-flag="no_docstrings" `
        --python-flag="no_asserts" `
        main_nuitka.py
    
    $exitCode = $LASTEXITCODE
    
    # Unset PYTHONPATH
    if (Test-Path Env:PYTHONPATH) {
        Remove-Item Env:PYTHONPATH
        Write-Status "PYTHONPATH restored"
    }
    
    Pop-Location
    
    if ($exitCode -ne 0) {
        throw "Nuitka compilation failed with exit code $exitCode"
    }
    
    Write-Success "Nuitka compilation completed successfully"
    
    # Check if the compiled Windows binary exists
    $binaryPath = "$PROJECT_ROOT\omnipet.exe"
    if (-not (Test-Path $binaryPath)) {
        # Try alternative locations
        $binaryPath = "$PROJECT_ROOT\main_nuitka.exe" 
        if (-not (Test-Path $binaryPath)) {
            $binaryPath = "$TEMP_DIR\omnipet.exe"
            if (-not (Test-Path $binaryPath)) {
                $binaryPath = "$TEMP_DIR\main_nuitka.exe" 
                if (-not (Test-Path $binaryPath)) {
                    throw "Compiled Windows binary not found at expected locations"
                }
            }
        }
    }
    
    Write-Status "Found compiled binary at: $binaryPath"
    
} catch {
    # Unset PYTHONPATH in case of failure
    if (Test-Path Env:PYTHONPATH) {
        Remove-Item Env:PYTHONPATH
        Write-Status "PYTHONPATH restored after error"
    }
    Pop-Location -ErrorAction SilentlyContinue
    Write-Error-Message "Nuitka build failed: $_"
    exit 1
}

# Create the final package directory
Write-Status "Creating final package..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME" -Force | Out-Null

# Copy the compiled Nuitka distribution
Write-Status "Copying compiled binary and dependencies..."

# Copy the main Windows executable
Copy-Item $binaryPath "$TEMP_DIR\$BUILD_NAME\omnipet.exe" -Force
Write-Status "Copied main executable from: $binaryPath"

# Copy any .pyd files (compiled modules) from temp dir
if (Test-Path "$TEMP_DIR\*.pyd") {
    Copy-Item "$TEMP_DIR\*.pyd" "$TEMP_DIR\$BUILD_NAME\" -Force
    Write-Status "Copied compiled module files (.pyd) from temp directory"
}

# Copy any .pyd files from project root
if (Test-Path "$PROJECT_ROOT\*.pyd") {
    Copy-Item "$PROJECT_ROOT\*.pyd" "$TEMP_DIR\$BUILD_NAME\" -Force
    Write-Status "Copied compiled module files (.pyd) from project root"
}

# Copy any additional compiled files and dependencies from temp dir
Get-ChildItem "$TEMP_DIR" -Include "*.dll", "*.pyd", "*.so" -Recurse | ForEach-Object {
    $relativePath = $_.FullName.Replace("$TEMP_DIR\", "")
    $destPath = Join-Path "$TEMP_DIR\$BUILD_NAME" $relativePath
    $destDir = Split-Path $destPath -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item $_.FullName $destPath -Force
}

# Copy any additional compiled files from project root
Get-ChildItem "$PROJECT_ROOT" -Include "*.dll", "*.pyd", "*.so" | ForEach-Object {
    Copy-Item $_.FullName "$TEMP_DIR\$BUILD_NAME\" -Force
}

Write-Status "Copied all compiled dependencies"

# Copy additional assets and files
Write-Status "Copying additional assets..."
Copy-Item (Join-Path $PROJECT_ROOT "assets") "$TEMP_DIR\$BUILD_NAME\" -Recurse

# Copy Windows configuration files with correct names
Write-Status "Copying Windows configuration files..."
try {
    $configDestDir = Join-Path $TEMP_DIR\$BUILD_NAME "config"
    if (-not (Test-Path $configDestDir)) {
        New-Item -ItemType Directory -Path $configDestDir | Out-Null
    }
    Copy-Item (Join-Path $PROJECT_ROOT "config\config_windows.json") (Join-Path $configDestDir "config.json")
    Copy-Item (Join-Path $PROJECT_ROOT "config\input_config_windows.json") (Join-Path $configDestDir "input_config.json")
} catch {
    Write-Error-Message "Failed to copy configuration files: $_"
    exit 1
}

# Copy documentation
Write-Status "Copying documentation..."
Copy-Item -Recurse (Join-Path $PROJECT_ROOT "Documentation") "$TEMP_DIR\$BUILD_NAME\" -Force

# Copy modules
# Ship an EMPTY modules/ folder (see legacy build scripts for rationale).
Write-Status "Creating empty modules/ folder..."
New-Item -ItemType Directory -Force -Path "$TEMP_DIR\$BUILD_NAME\modules" | Out-Null


# Copy Module Editor (without Source folder)
Write-Status "Copying Module Editor..."
$moduleEditorSrc = Join-Path $PROJECT_ROOT "Module Editor"
$moduleEditorDest = Join-Path "$TEMP_DIR\$BUILD_NAME" "Module Editor"
if (Test-Path $moduleEditorSrc) {
    # Copy Module Editor directory but exclude Source folder
    $moduleEditorFiles = Get-ChildItem $moduleEditorSrc -Recurse | Where-Object { $_.FullName -notlike "*\Source\*" -and $_.Name -ne "Source" }
    foreach ($file in $moduleEditorFiles) {
        $relativePath = $file.FullName.Replace($moduleEditorSrc, "").TrimStart('\')
        $destPath = Join-Path $moduleEditorDest $relativePath
        $destDir = Split-Path $destPath -Parent
        
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        
        if (-not $file.PSIsContainer) {
            Copy-Item $file.FullName $destPath -Force
        }
    }
    Write-Status "Copied Module Editor (excluding Source folder)"
}

# Copy Module Editor launch script
Write-Status "Copying Module Editor launch script..."
if (Test-Path (Join-Path $PROJECT_ROOT "ModuleEditor.bat")) {
    Copy-Item (Join-Path $PROJECT_ROOT "ModuleEditor.bat") "$TEMP_DIR\$BUILD_NAME\" -Force
}

# Create empty save folder
Write-Status "Creating save directory..."
New-Item -ItemType Directory -Path "$TEMP_DIR\$BUILD_NAME\save" -Force | Out-Null

# Copy LICENSE only
Write-Status "Copying LICENSE..."
Copy-Item (Join-Path $PROJECT_ROOT "LICENSE.txt") "$TEMP_DIR\$BUILD_NAME\" -Force

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
    Write-Success "Nuitka Windows build completed: $BUILD_NAME"
    Get-ChildItem "$RELEASE_DIR\$BUILD_NAME.zip" | Format-Table Name, Length, LastWriteTime
} else {
    Write-Error-Message "Failed to create release archive"
    exit 1
}
