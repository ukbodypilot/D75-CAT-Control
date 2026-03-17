#!/bin/bash
# D75 CAT Control — Headless server launcher
# Reads config.txt for defaults, starts TCP server

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/config.txt"

# Read config
BAUD="9600"
DEVICE=""
HOST="0.0.0.0"
PORT="9750"
PASSWORD=""

if [ -f "$CONFIG" ]; then
    while IFS='=' read -r key value; do
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        case "$key" in
            baud_rate) BAUD="$value" ;;
            device) DEVICE="$value" ;;
            host) HOST="$value" ;;
            port) PORT="$value" ;;
            password) PASSWORD="$value" ;;
        esac
    done < "$CONFIG"
fi

# Find serial port by device description if not an absolute path
if [ -n "$DEVICE" ] && [ ! -e "$DEVICE" ]; then
    COMPORT=$(python3 -c "
import serial.tools.list_ports
for p in serial.tools.list_ports.comports():
    if '$DEVICE' in p.description:
        print(p.device)
        break
" 2>/dev/null)
else
    COMPORT="$DEVICE"
fi

# If device is rfcomm, check if bt_addr is configured
# When bt_addr is set, D75_CAT.py handles BT connect via !btstart
# (rfcomm bind must happen AFTER audio SCO connects — see btstart order)
# So we skip the serial port check and let D75_CAT.py manage everything
BT_ADDR=""
if [ -f "$CONFIG" ]; then
    BT_ADDR=$(grep -m1 "^bt_addr" "$CONFIG" | cut -d= -f2 | xargs)
fi

if [ -z "$COMPORT" ] && [ -n "$BT_ADDR" ]; then
    # BT mode — don't bind rfcomm here, btstart will handle it
    COMPORT="$DEVICE"
    echo "Bluetooth mode: $BT_ADDR — serial will be connected via btstart"
fi

if [ -z "$COMPORT" ]; then
    echo "Error: No serial port found for device '$DEVICE'"
    echo "Available ports:"
    python3 -c "
import serial.tools.list_ports
for p in serial.tools.list_ports.comports():
    print(f'  {p.device}: {p.description}')
"
    exit 1
fi

echo "Starting D75 CAT server on $HOST:$PORT (serial: $COMPORT @ $BAUD)"

exec python3 "$SCRIPT_DIR/D75_CAT.py" \
    -c "$COMPORT" \
    -b "$BAUD" \
    --start-server \
    -sH "$HOST" \
    -sP "$PORT" \
    -p "$PASSWORD"
