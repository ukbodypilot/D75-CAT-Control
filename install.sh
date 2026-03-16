#!/bin/bash
# D75 CAT Control — Headless server installer
# Installs dependencies and systemd service

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== D75 CAT Control — Headless Server Installer ==="

# Detect distro
if command -v pacman &>/dev/null; then
    DISTRO="arch"
elif command -v apt-get &>/dev/null; then
    DISTRO="debian"
else
    echo "Unsupported distro (need pacman or apt-get)"
    exit 1
fi
echo "Detected: $DISTRO"

# Install Python dependencies
echo "[1/3] Installing Python dependencies..."
pip3 install pyserial pyserial-asyncio --break-system-packages 2>/dev/null || \
    pip3 install pyserial pyserial-asyncio

# Create config if missing
echo "[2/3] Checking config..."
if [ ! -f "$SCRIPT_DIR/config.txt" ]; then
    cat > "$SCRIPT_DIR/config.txt" << 'EOF'
baud_rate=9600
device=
host=0.0.0.0
port=9750
password=
EOF
    echo "  Created config.txt — edit 'device' to set your serial port"
else
    echo "  config.txt exists"
fi

# Install systemd service
echo "[3/3] Installing systemd service..."
SERVICE_NAME="d75-cat"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CURRENT_USER=$(whoami)
PYTHON_PATH=$(which python3)

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=D75 CAT Control — Headless TCP Server
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/run-headless.sh
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
KillMode=control-group

# Environment for serial port access
Environment=HOME=/home/$CURRENT_USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
echo "  Service installed: $SERVICE_NAME"
echo "  Commands:"
echo "    sudo systemctl enable $SERVICE_NAME   # Start on boot"
echo "    sudo systemctl start $SERVICE_NAME    # Start now"
echo "    sudo systemctl status $SERVICE_NAME   # Check status"
echo "    journalctl -u $SERVICE_NAME -f        # Follow logs"

echo ""
echo "=== Installation complete ==="
echo "Edit config.txt to set your serial port, then:"
echo "  sudo systemctl start d75-cat"
