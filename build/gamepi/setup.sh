#!/bin/bash

echo "🚀 Starting Omnipet Virtual Pet Game setup..."
echo "This script works on Raspberry Pi, Ubuntu, Debian, and other Linux distributions"

# Detect the distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    echo "Detected distribution: $PRETTY_NAME"
else
    echo "Cannot detect distribution, assuming Debian-based"
    DISTRO="debian"
fi

# Update system packages
echo "📦 Updating system packages..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update && sudo apt-get upgrade -y
elif command -v dnf &> /dev/null; then
    sudo dnf update -y
elif command -v pacman &> /dev/null; then
    sudo pacman -Syu --noconfirm
else
    echo "⚠️  Unknown package manager, please install dependencies manually"
fi

# Install necessary dependencies
echo "📦 Installing Python and dependencies..."
if command -v apt-get &> /dev/null; then
    # Debian/Ubuntu/Raspberry Pi
    sudo apt-get install -y python3 python3-pip git
    
    # For Raspberry Pi I2C support
    if [ -f "/usr/bin/raspi-config" ]; then
        echo "Raspberry Pi detected, installing I2C support..."
        sudo apt-get install -y python3-smbus i2c-tools
    fi
    
    # Install Pygame dependencies
    sudo apt-get install -y libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0
    sudo apt-get install -y python3-dev python3-pip python3-setuptools \
        python3-wheel build-essential \
        libfreetype6-dev libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev \
        libsdl2-ttf-dev libportmidi-dev libjpeg-dev libtiff-dev

elif command -v dnf &> /dev/null; then
    # Fedora/CentOS/RHEL
    sudo dnf install -y python3 python3-pip git
    sudo dnf install -y SDL2-devel SDL2_image-devel SDL2_mixer-devel SDL2_ttf-devel
    sudo dnf install -y freetype-devel libjpeg-devel
    
elif command -v pacman &> /dev/null; then
    # Arch Linux
    sudo pacman -S --noconfirm python python-pip git
    sudo pacman -S --noconfirm sdl2 sdl2_image sdl2_mixer sdl2_ttf
fi

# The game needs Python 3.10 or newer; launch.sh looks for python3.NN before python3
PYTHON_CMD=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &> /dev/null && \
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2> /dev/null; then
        PYTHON_CMD="$candidate"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "❌ The game needs Python 3.10 or newer; this system has $(python3 --version 2>&1)"
    echo "   Install Python 3.10+ (or use the GamePi image), then run setup again"
    exit 1
fi

# Install Python packages
echo "🐍 Installing Python packages for $PYTHON_CMD..."
"$PYTHON_CMD" -m pip install --user pygame psutil || \
    echo "⚠️  pip refused; install pygame and psutil for $PYTHON_CMD with your package manager"

# Test if pygame works
echo "🧪 Testing pygame installation..."
"$PYTHON_CMD" -c "import pygame; print('Pygame version:', pygame.version.ver)" || {
    echo "❌ Pygame installation failed"
    exit 1
}

# Make launch script executable
chmod +x launch.sh

# Create desktop shortcut if we're on a desktop environment
if [ -n "$XDG_CURRENT_DESKTOP" ] && [ -d "$HOME/Desktop" ]; then
    echo "🖥️  Creating desktop shortcut..."
    cat > "$HOME/Desktop/Omnipet.desktop" << EOF
[Desktop Entry]
Name=Omnipet Virtual Pet
Comment=Virtual Pet Game
Exec=$(pwd)/launch.sh
Icon=$(pwd)/assets/icon.png
Terminal=false
Type=Application
Categories=Game;
Path=$(pwd)
EOF
    chmod +x "$HOME/Desktop/Omnipet.desktop"
fi

# Optional: Create systemd service for auto-start (Raspberry Pi/embedded systems)
if [ "$1" = "--service" ] && [ -f "/usr/bin/raspi-config" ]; then
    echo "🚀 Creating systemd service for auto-start..."
    sudo tee /etc/systemd/system/omnipet.service > /dev/null << EOF
[Unit]
Description=Omnipet Virtual Pet Game
After=graphical-session.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/launch.sh
Restart=always
Environment="DISPLAY=:0"

[Install]
WantedBy=graphical-session.target
EOF
    
    sudo systemctl daemon-reload
    sudo systemctl enable omnipet.service
    echo "Service created. Game will start automatically after reboot."
fi

echo "✅ Setup complete!"
echo "🎮 Run './launch.sh' to start the game"
echo "⚙️  Settings (display, sound, buttons) are in the game's Settings menu"
echo "🔄 To update, copy a new release's files over this folder"
