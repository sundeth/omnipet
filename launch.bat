@echo off
REM Launch script for Omnipet Virtual Pet Game on Windows
REM Display, sound and button settings are in the game's Settings menu

REM Run from the game's own folder (assets, modules and save are found there),
REM whatever folder this was started from
cd /d "%~dp0"

echo Starting Omnipet Virtual Pet Game...
echo Note: display, sound and button settings are in the game's Settings menu

REM Set environment variables for better compatibility
set SDL_VIDEO_CENTERED=1

REM Check if fullscreen was requested
if "%1"=="--fullscreen" set OMNIPET_FULLSCREEN=1
if "%1"=="-f" set OMNIPET_FULLSCREEN=1

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found
    echo Please install Python 3 from https://python.org
    pause
    exit /b 1
)

REM Check for pygame
python -c "import pygame" >nul 2>&1
if errorlevel 1 (
    echo Error: pygame not installed
    echo Install with: pip install pygame
    pause
    exit /b 1
)

REM Run the game
python main.py %*

REM Keep window open if there was an error
if errorlevel 1 pause
