#!/bin/bash

# Cross-Platform Satellite Ground Station Startup Script for Linux
# This script handles all Linux-specific setup and launches the application

echo "🛰️  Cross-Platform Satellite Ground Station - Linux Startup"
echo "=========================================================="

# Check if running as root for permissions
if [[ $EUID -eq 0 ]]; then
   echo "⚠️  Running as root - this is OK for serial port access"
else
   echo "ℹ️  Running as user - checking serial port permissions..."
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Check Python version
echo "🐍 Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+"
    echo "   sudo apt update && sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Found Python $PYTHON_VERSION"

# Check if virtual environment exists
if [ ! -d "../venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv ../venv
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source ../venv/bin/activate

# Install dependencies if needed
if [ -f "requirements.txt" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install dependencies"
        exit 1
    fi
fi

# Check serial port permissions
echo "🔌 Checking serial port permissions..."
SERIAL_PORTS=("/dev/ttyUSB0" "/dev/ttyACM0" "/dev/ttyUSB1" "/dev/ttyACM1")
PORT_FOUND=false

for port in "${SERIAL_PORTS[@]}"; do
    if [ -e "$port" ]; then
        echo "✅ Found serial port: $port"
        
        # Check permissions
        if [ -r "$port" ] && [ -w "$port" ]; then
            echo "✅ Port $port is accessible"
            PORT_FOUND=true
        else
            echo "⚠️  Port $port exists but permissions issue detected"
            echo "   Try: sudo chmod 666 $port"
            echo "   Or add user to dialout group: sudo usermod -a -G dialout \$USER"
            echo "   Then logout and login again"
        fi
    fi
done

if [ "$PORT_FOUND" = false ]; then
    echo "⚠️  No serial ports found. ESP32 may not be connected."
    echo "   Connect ESP32 and run this script again."
fi

# Check if ESP32 is connected (optional)
echo "🔍 Scanning for USB devices..."
if command -v lsusb &> /dev/null; then
    lsusb | grep -i "silicon\|cp210\|ftdi\|ch340" || echo "   No common USB-Serial chips detected"
fi

# Display system information
echo "📊 System Information:"
echo "   OS: $(uname -s) $(uname -r)"
echo "   Platform: $(python3 -c 'import platform; print(platform.platform())')"
echo "   Python: $(python3 --version)"
echo "   Working Directory: $(pwd)"

# Check if cross-platform app exists
if [ ! -f "app_cross_platform.py" ]; then
    echo "❌ Cross-platform app not found: app_cross_platform.py"
    exit 1
fi

# Start the application
echo ""
echo "🚀 Starting Cross-Platform Satellite Ground Station..."
echo "🌐 Web Dashboard: http://localhost:5000"
echo "🔧 Modbus TCP: localhost:502"
echo "📡 Serial Port: Auto-detecting..."
echo ""
echo "Press Ctrl+C to stop the application"
echo "=========================================================="

# Set environment variables for better performance
export PYTHONUNBUFFERED=1
export EVENTLET_HUB=poll

# Run the cross-platform application
python3 app_cross_platform.py

# Cleanup on exit
echo ""
echo "🛑 Application stopped"
echo "✅ Cleanup complete"
