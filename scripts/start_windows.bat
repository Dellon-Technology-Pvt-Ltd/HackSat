@echo off
REM Cross-Platform Satellite Ground Station Startup Script for Windows
REM This script handles all Windows-specific setup and launches the application

echo 🛰️ Cross-Platform Satellite Ground Station - Windows Startup
echo ==========================================================

REM Get script directory
cd /d "%~dp0"

REM Check Python installation
echo 🐍 Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed or not in PATH
    echo    Please install Python 3.8+ from https://python.org
    echo    Make sure to add Python to PATH during installation
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✅ Found Python %PYTHON_VERSION%

REM Check if virtual environment exists
if not exist "venv" (
    echo 📦 Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ❌ Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo 🔄 Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies if needed
if exist "requirements.txt" (
    echo 📦 Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Check serial ports
echo 🔌 Checking serial ports...
python -c "import serial.tools.list_ports; ports=serial.tools.list_ports.comports(); [print(f'✅ Found: {p.device} - {p.description}') for p in ports] if ports else print('⚠️ No serial ports found')"

REM Display system information
echo 📊 System Information:
echo    OS: %OS%
echo    Platform: %PROCESSOR_ARCHITECTURE%
echo    Python: %PYTHON_VERSION%
echo    Working Directory: %CD%

REM Check if cross-platform app exists
if not exist "app_cross_platform.py" (
    echo ❌ Cross-platform app not found: app_cross_platform.py
    pause
    exit /b 1
)

REM Start application
echo.
echo 🚀 Starting Cross-Platform Satellite Ground Station...
echo 🌐 Web Dashboard: http://localhost:5000
echo 🔧 Modbus TCP: localhost:502
echo 📡 Serial Port: Auto-detecting...
echo.
echo Press Ctrl+C to stop the application
echo ==========================================================

REM Set environment variables for better performance
set PYTHONUNBUFFERED=1
set EVENTLET_HUB=poll

REM Run cross-platform application
python app_cross_platform.py

REM Cleanup on exit
echo.
echo 🛑 Application stopped
echo ✅ Cleanup complete
pause
