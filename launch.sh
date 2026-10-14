#!/bin/bash
# Launch script for Omnipet Virtual Pet Game
# Works on Ubuntu, Batocera, other Linux distributions, and macOS
# Display and other settings are in the game's Settings menu

# Set environment variables for better compatibility
export SDL_VIDEO_CENTERED=1

# Detect the environment
if [ -f "/usr/bin/batocera-info" ]; then
    echo "Detected Batocera system"
    export OMNIPET_FULLSCREEN=1
    export SDL_VIDEODRIVER=kmsdrm
elif [ -n "$WAYLAND_DISPLAY" ]; then
    echo "Detected Wayland environment"
    export SDL_VIDEODRIVER=wayland
elif [ -n "$DISPLAY" ]; then
    echo "Detected X11 environment"
    export SDL_VIDEODRIVER=x11
elif [ -d "/Library/Apple" ]; then
    echo "Detected macOS environment"
    export SDL_VIDEODRIVER=cocoa
else
    echo "No display server detected, using the console (KMS/DRM)"
    # SDL2 (pygame 2) has no fbcon driver; kmsdrm is its console driver
    export SDL_VIDEODRIVER=kmsdrm
fi

# Check if fullscreen was requested
if [ "$1" = "--fullscreen" ] || [ "$1" = "-f" ]; then
    export OMNIPET_FULLSCREEN=1
fi

# Find Python: the game needs 3.10 or newer with pygame. The system python3
# can be older (Raspberry Pi OS Bullseye: 3.9), so a newer build is looked for
# first: one bundled in the game folder, then python3.NN on the PATH (the
# GamePi image's /usr/local/bin/python3.10), then python3 and python.
GAME_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_CMD=""
for candidate in "$GAME_DIR"/Python-3*/python "$GAME_DIR"/Python-3*/bin/python3 \
                 "$GAME_DIR"/Python-3*/bin/python3.[0-9][0-9] \
                 python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    resolved="$(command -v "$candidate" 2>/dev/null)" || continue
    if "$resolved" -c 'import sys, pygame; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PYTHON_CMD="$resolved"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "Error: no Python 3.10 or newer with pygame found"
    echo "Install Python 3.10+ and pygame (pip install pygame)"
    exit 1
fi

# Change to the directory where the script is located
cd "$(dirname "$0")"

# Run the game
echo "Starting Omnipet Virtual Pet Game..."
echo "Note: display settings are in the game's Settings menu"
"$PYTHON_CMD" main.py "$@"
