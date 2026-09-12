# Omnipet Virtual Pet Game - Build Requirements

This document outlines the requirements for building Omnipet Virtual Pet Game across different platforms and build systems.

## Table of Contents
- [General Requirements](#general-requirements)
- [Platform-Specific Builds](#platform-specific-builds)
- [Build Tools Setup](#build-tools-setup)
- [Troubleshooting](#troubleshooting)

## General Requirements

### Python Version
- **Required**: Python 3.8 - 3.11
- **Recommended**: Python 3.10
- **Not Supported**: Python 3.12+ (due to some build tool compatibility issues)

### Core Dependencies
```
pygame>=2.0.0
psutil>=5.8.0
```

### Optional Dependencies (Platform-specific)
```
# For the WiFiCom feature (all platforms)
paho-mqtt>=1.6.0

# For GPIO support on Raspberry Pi
RPi.GPIO>=0.7.0 (Raspberry Pi only)

# For Android builds
buildozer>=1.4.0
python-for-android>=2023.06.21

# For standalone executables
nuitka>=1.8.0
pyinstaller>=5.0
```

## Platform-Specific Builds

### 1. Python Desktop Build (`build_python_desktop.ps1`)

**Target**: Cross-platform Python distribution requiring Python installation

**Requirements**:
- Python 3.8-3.11
- pygame >= 2.0.0
- psutil >= 5.8.0

**Platform Support**:
- Windows 7+
- Linux (Ubuntu 18.04+, Debian 10+)
- macOS 10.14+

**Build Output**: ZIP archive with Python source files
**Runtime Requirements**: Python + pygame + psutil installed on target system

---

### 2. Windows Executable Build (`build_windows.ps1`)

**Target**: Windows standalone executable using PyInstaller

**Requirements**:
- Windows 10+ (build system)
- Python 3.8-3.11
- PyInstaller >= 5.0
- pygame >= 2.0.0
- psutil >= 5.8.0
- UPX (optional, for compression)

**Installation**:
```powershell
pip install pyinstaller>=5.0 pygame>=2.0.0 psutil>=5.8.0
```

**Build Output**: `Omnipet.exe` (standalone executable)
**Runtime Requirements**: None (includes Python runtime)

---

### 3. Nuitka Windows Build (`build_nuitka_windows.ps1`)

**Target**: Optimized Windows standalone executable using Nuitka

**Requirements**:
- Windows 10+ (build system)
- Python 3.8-3.11
- Nuitka >= 1.8.0
- pygame >= 2.0.0
- psutil >= 5.8.0
- Visual Studio Build Tools or MinGW-w64
- UPX (optional, for compression)

**Installation**:
```powershell
pip install nuitka>=1.8.0 pygame>=2.0.0 psutil>=5.8.0
```

**Build Output**: `omnipet.exe` (optimized standalone executable)
**Runtime Requirements**: None (includes Python runtime)
**Advantages**: Better performance, smaller file size than PyInstaller

---

### 4. GamePi Build (`build_gamepi.ps1`)

**Target**: Raspberry Pi (GamePi Zero 2W) distribution

**Requirements**:
- Cross-compilation: Windows/Linux build system
- Target: Raspberry Pi OS Lite (Bullseye/Bookworm)
- Python 3.9+ (on target Pi)
- pygame >= 2.0.0
- psutil >= 5.8.0
- RPi.GPIO >= 0.7.0 (for hardware controls)

**Target Pi Setup**:
```bash
sudo apt update
sudo apt install python3-pygame python3-psutil python3-rpi.gpio
```

**Build Output**: ZIP archive optimized for Pi
**Runtime Requirements**: Python + dependencies on Raspberry Pi

---

### 5. GamePi Nuitka Build (`build_gamepi_nuitka.ps1`)

**Target**: Compiled executable for Raspberry Pi

**Requirements**:
- **Cross-compilation Setup**: ARM GCC toolchain
- Windows/Linux build system
- Python 3.8-3.11
- Nuitka >= 1.8.0
- ARM cross-compilation tools

**Cross-compilation Setup** (Advanced):
```bash
# On Ubuntu/Debian build system
sudo apt install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

**Current Limitation**: Requires proper ARM toolchain setup for cross-compilation
**Alternative**: Build directly on Raspberry Pi

---

### 6. Batocera Build (`build_batocera.ps1`)

**Target**: Batocera Linux gaming distribution

**Requirements**:
- Batocera v37+ (target system)
- Python 3.9+ (usually pre-installed on Batocera)
- pygame >= 2.0.0

**Build Output**: `.pygame` package for Batocera
**Runtime Requirements**: Batocera system with Python support

---

### 7. Android APK Build (`build_android_apk.ps1`)

**Target**: Android devices (ARM/ARM64)

**Requirements**:
- Linux build system (Ubuntu 20.04+ recommended)
- Python 3.8-3.11
- Buildozer >= 1.4.0
- python-for-android >= 2023.06.21
- plyer >= 2.0.0 (for accelerometer support)
- Android SDK/NDK (auto-downloaded by Buildozer)
- Java JDK 8 or 11

**Installation**:
```bash
pip install buildozer python-for-android plyer
```

**System Dependencies** (Ubuntu):
```bash
sudo apt install -y git zip unzip openjdk-8-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
```

**Buildozer Spec Requirements**:
```ini
# Add to buildozer.spec
requirements = python3, pygame, plyer
android.permissions = INTERNET

# Accelerometer support (automatically included with plyer)
# No additional permissions needed for accelerometer
```

**Android-Specific Features**:
- **Accelerometer Shake Detection**: Uses `plyer.accelerometer` for shake events
- **App Storage**: Uses `android.storage.app_storage_path()` for save files
- **Touch Input**: Full touch and drag gesture support

**Build Output**: `omnipet.apk`
**Runtime Requirements**: Android 5.0+ (API level 21+)

## Quick Setup Commands

### Core Dependencies (All Platforms)
```bash
# Install core game dependencies
pip install pygame>=2.0.0 psutil>=5.8.0
```

### Windows Build Tools
```powershell
# For PyInstaller builds
pip install pyinstaller>=5.0 pygame>=2.0.0 psutil>=5.8.0

# For Nuitka builds (recommended for performance)
pip install nuitka>=1.8.0 pygame>=2.0.0 psutil>=5.8.0

# All Windows build tools
pip install pyinstaller>=5.0 nuitka>=1.8.0 pygame>=2.0.0 psutil>=5.8.0
```

### Linux/macOS Build Tools
```bash
# For standard builds
pip install pygame>=2.0.0 psutil>=5.8.0

# For Android builds (Linux only)
pip install buildozer>=1.4.0 python-for-android>=2023.06.21 pygame>=2.0.0 psutil>=5.8.0

# For Nuitka builds
pip install nuitka>=1.8.0 pygame>=2.0.0 psutil>=5.8.0
```

### Raspberry Pi Dependencies
```bash
# On Raspberry Pi OS
sudo apt update
sudo apt install python3-pygame python3-psutil python3-rpi.gpio

# Or via pip
pip install pygame>=2.0.0 psutil>=5.8.0 RPi.GPIO>=0.7.0
```

### Development Environment (All Tools)
```bash
# Install everything for complete development setup
pip install pygame>=2.0.0 psutil>=5.8.0 pyinstaller>=5.0 nuitka>=1.8.0 buildozer>=1.4.0 python-for-android>=2023.06.21
```

## Git Configuration

### Line Ending Handling
The project includes a `.gitattributes` file that automatically handles line endings:
- **Shell scripts** (`.sh`): Always use LF (Unix-style) line endings
- **Windows scripts** (`.bat`, `.cmd`, `.ps1`): Always use CRLF (Windows-style) line endings
- **Source code and configs**: Use LF line endings for cross-platform compatibility

### Recommended Git Settings
```bash
# Set up Git to handle line endings properly
git config --global core.autocrlf input    # Linux/macOS
git config --global core.autocrlf true     # Windows

# Ensure .gitattributes is respected
git config --global core.eol lf
```

### Fixing Existing Line Ending Issues
If you encounter shell script execution errors:
```bash
# Convert CRLF to LF for shell scripts
dos2unix launch.sh utilities/setup.sh

# Or use Git to normalize line endings
git add --renormalize .
git commit -m "Normalize line endings"
```

## Build Tools Setup

### PyInstaller Setup
```powershell
pip install pyinstaller>=5.0
# Optional: Install UPX for smaller executables
# Download UPX from https://upx.github.io/
```

### Nuitka Setup
```powershell
pip install nuitka>=1.8.0

# Windows: Install Visual Studio Build Tools
# Or install MinGW-w64: https://www.mingw-w64.org/downloads/

# Verify installation
python -m nuitka --version
```

### Buildozer Setup (Linux only)
```bash
pip install buildozer python-for-android

# Install system dependencies
sudo apt install -y git zip unzip openjdk-8-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

# Initialize buildozer (creates buildozer.spec)
buildozer init
```

## File Structure Requirements

The following files must be present in the project root for builds to work:

```
Omnipet/
├── .gitattributes         # Git line ending configuration (IMPORTANT)
├── main.py                # Standard Python entry point
├── main_nuitka.py         # Nuitka-optimized entry point
├── launch.sh              # Unix/Linux/macOS launch script
├── fix-line-endings.sh    # Quick fix for line ending issues
├── pyinstall.spec         # PyInstaller configuration
├── omnipet.pygame         # Batocera package metadata
├── assets/                # Game assets (sprites, sounds)
├── modules/               # Game modules (DMC, etc.)
├── config/                # Configuration files
├── game/                  # Python game source code
├── utilities/             # Platform-specific utilities
└── build/                 # Build scripts
```

## Build Script Usage

All build scripts accept a version parameter:

```powershell
# Build with default version (0.9.8)
.\build_windows.ps1

# Build with custom version
.\build_windows.ps1 -Version "1.0.0"

# Build all platforms
.\build_all.ps1 -Version "1.0.0"
```

## Performance Recommendations

### Build Performance:
1. **Nuitka**: Best performance, moderate build time
2. **PyInstaller**: Good compatibility, slower runtime than Nuitka
3. **Python**: Fastest build, requires Python on target system

### File Size Comparison:
- **Python Distribution**: ~50MB (source + assets)
- **PyInstaller Executable**: ~80-120MB
- **Nuitka Executable**: ~60-90MB
- **Android APK**: ~30-50MB

## Troubleshooting

### Common Issues:

**1. Nuitka Build Fails**:
- Install Visual Studio Build Tools (Windows)
- Check Python version compatibility (3.8-3.11)
- Ensure all assets are included in `--include-data-dir`

**2. PyInstaller Executable Won't Run**:
- Check `hiddenimports` in `pyinstall.spec`
- Verify asset paths are included in `datas`
- Test on clean system without Python installed

**3. Android Build Fails**:
- Use Linux build system (WSL2 on Windows)
- Install all required system dependencies
- Check Java version (JDK 8 or 11 only)

**4. GamePi GPIO Not Working**:
- Install `python3-rpi.gpio` on target Pi
- Ensure user is in `gpio` group: `sudo usermod -a -G gpio $USER`

**5. Cross-compilation Issues**:
- Use native compilation on target platform when possible
- For ARM: Build directly on Raspberry Pi for best compatibility

**6. Shell Script Line Ending Issues (Linux/macOS)**:
- **Error**: `bash: ./launch.sh: cannot execute: required file not found`
- **Error**: `-bash: ./launch.sh: /bin/bash^M: bad interpreter: No such file or directory`
- **Cause**: Windows CRLF line endings in shell scripts
- **Quick Fix**: Run `./fix-line-endings.sh` in project root
- **Manual Fix**: Convert line endings using `dos2unix launch.sh` or text editor
- **Prevention**: Project includes `.gitattributes` to enforce LF line endings

### Debug Mode:

Enable debug mode in any build by modifying the respective main file:
```python
# In main.py or main_nuitka.py
DEBUG_MODE = True
```

This will show console output and additional logging information.

## Version Compatibility Matrix

| Platform | Python 3.8 | Python 3.9 | Python 3.10 | Python 3.11 | Python 3.12+ |
|----------|-------------|-------------|--------------|--------------|---------------|
| Windows  | ✅          | ✅          | ✅           | ✅           | ❌            |
| Linux    | ✅          | ✅          | ✅           | ✅           | ❌            |
| macOS    | ✅          | ✅          | ✅           | ✅           | ❌            |
| Raspberry Pi | ✅      | ✅          | ✅           | ✅           | ⚠️            |
| Android  | ✅          | ✅          | ✅           | ❌           | ❌            |
| Batocera | ✅          | ✅          | ✅           | ✅           | ⚠️            |

**Legend**:
- ✅ Fully Supported
- ⚠️ Limited Support / Testing Required
- ❌ Not Supported

## Support

For build issues, check:
1. This requirements document
2. Build script logs and error messages
3. Platform-specific documentation
4. GitHub Issues for known problems

Last updated: August 31, 2025
Game Version: 0.9.8

## NFC reader + battery gauge dependencies

The NFC card reading service (`src/services/nfc_service.py`) and the battery
gauge (`src/input/i2c_utils.py`) use optional, platform-specific packages.
Everything degrades gracefully when a package is missing (NFC Read button
disabled / battery icon neutral), but ship them for full functionality:

- **Windows / desktop**: `pip install pyscard` (PC/SC readers such as the
  ACR122U). The PyInstaller specs list the `smartcard.*` hidden imports.
- **Raspberry Pi**: `pip install adafruit-circuitpython-pn532 adafruit-blinka`
  for the PN532 I2C NFC reader; `smbus` + `RPi.GPIO` for the UPS-Lite V1.3
  battery hat (MAX17040 fuel gauge on I2C 0x36, external-power sense on
  GPIO4). Enable I2C in raspi-config.
- **Android**: battery uses `plyer` with a `pyjnius` fallback (both in
  buildozer requirements). Phone NFC reading is not implemented yet.

## WiFiCom dependencies

`src/wificom/` is wificom-lib vendored into the game, so Omnipet can present
itself to wificom.dev as a WiFiCom rather than needing one. See
`src/wificom/UPSTREAM.md`.

Its only added dependency is **paho-mqtt**, which stands in for the
CircuitPython `adafruit_minimqtt` upstream uses:

```bash
pip install paho-mqtt
```

It degrades the same way the NFC and serial features do — without it,
`wificom.is_available()` is False and the feature is off; nothing else in the
game is affected.

Build coverage, since a new `src/` package has to be added in every pipeline
by hand:

- **PyInstaller** (`Omnipet.spec`, `pyinstall.spec`): `src/wificom` in
  `datas`, and `paho.mqtt.client` in `hiddenimports` — it is imported inside
  a `try`/`except`, which the analysis does not follow.
- **Nuitka** (`build_nuitka_windows.ps1`, `build_gamepi_nuitka.ps1`):
  `--include-package="src.wificom"` and `--include-module="paho.mqtt.client"`.
- **Python/Batocera/GamePi** (`build_python_desktop.ps1`,
  `build_batocera.ps1`, `build_gamepi.ps1`): a robocopy block for
  `src\wificom`.
- **Android** (`build_android.ps1`, `buildozer.spec`): `src/wificom` in the
  WSL mkdir and rsync lists, and `paho-mqtt` in buildozer `requirements`
  (pure Python, so p4a needs no recipe). `source.include_patterns` already
  covers it through `src/**`.
