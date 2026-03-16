# D75 CAT Control — Headless TCP Server

Headless TCP server for remote control of the Kenwood TH-D75 (and TH-D74) via CAT commands, with optional Bluetooth SCO audio streaming. Designed to run on a Raspberry Pi as a systemd service and integrate with [radio-gateway](https://github.com/ukbodypilot/radio-gateway).

Forked from [xbenkozx/D75-CAT-Control](https://github.com/xbenkozx/D75-CAT-Control) (GUI version). This fork replaces the Qt GUI with an asyncio TCP server and adds Bluetooth audio support.

## Features

- TCP server for remote CAT control (port 9750)
- Bluetooth HSP/SCO audio streaming (port 9751) — 8kHz 16-bit mono PCM
- USB cable serial connection (CAT only, audio via AIOC)
- Simultaneous CAT + audio over Bluetooth
- Stuck SCO frame filtering for clean audio on CSR adapters
- Systemd service for headless operation
- Web control UI when used with radio-gateway (`/d75` page)
- No GUI or PySide6 dependency

## Connection Modes

The D75 can connect via **Bluetooth** or **USB cable**:

| | Bluetooth | USB Cable |
|---|---|---|
| CAT Control | RFCOMM ch2 via BT | `/dev/ttyUSB0` direct serial |
| Audio | SCO via BT → TCP port 9751 | AIOC (analog audio interface) |
| Config | `bt_addr=<MAC>`, `device=/dev/rfcomm0` | `bt_addr=` (empty), `device=/dev/ttyUSB0` |
| Startup | `!btstart` (audio → rfcomm → serial) | `!serial connect` |
| BT Adapter | CSR or Broadcom required | Not needed |

## Hardware Requirements

- Kenwood TH-D75 (or TH-D74)
- Raspberry Pi (tested on Pi 5 with Linux 6.12, ARM64)

### For Bluetooth mode:
- **USB Bluetooth adapter: CSR (Cambridge Silicon Radio) or Broadcom (e.g., ASUS USB-BT400)**

> **Do NOT use Realtek BT adapters** (RTL8761BU, RTL8851BU, etc.) for audio.
> They have a fatal SCO firmware bug — invalid connection handles cause silent
> audio on every session. See [docs/bluetooth_audio.md](docs/bluetooth_audio.md).

> **CSR adapter note:** CSR adapters may drop ~48% of SCO packets. The server
> includes a stuck frame filter that detects and replaces dropped frames,
> producing clean audio output.

### For USB mode:
- USB cable to D75
- AIOC (All-In-One-Cable) or similar analog audio interface for audio

## Quick Start

```bash
# Install dependencies
pip3 install pyserial pyserial-asyncio --break-system-packages

# USB serial (CAT only)
python3 D75_CAT.py -c /dev/ttyUSB0 -d

# Bluetooth (edit config.txt first)
python3 D75_CAT.py -d
```

### USB Setup

1. Connect D75 via USB cable
2. Edit `config.txt`:
   ```
   device=/dev/ttyUSB0
   bt_addr=
   ```
3. Start the server: `python3 D75_CAT.py -d`
4. Connect via TCP and run `!serial connect`

### Bluetooth Setup

1. Pair the D75 with your CSR adapter via `bluetoothctl`
2. Edit `config.txt`:
   ```
   device=/dev/rfcomm0
   bt_addr=90:CE:B8:D6:55:0A    # Your D75's BT MAC
   ```
3. Start the server: `python3 D75_CAT.py -d`
4. Connect via TCP and run `!btstart`

`!btstart` handles the full connection sequence: audio (RFCOMM ch1 + SCO + CKPD), rfcomm bind, then serial open.

## radio-gateway Integration

This server integrates with [radio-gateway](https://github.com/ukbodypilot/radio-gateway) for Mumble bridging, web control, and multi-radio management.

### Gateway config (`gateway_config.txt`):
```ini
[d75]
ENABLE_D75 = true
D75_CONNECTION = bluetooth    # 'bluetooth' or 'usb'
D75_HOST = 127.0.0.1         # D75_CAT.py server IP
D75_PORT = 9750
D75_AUDIO_PORT = 9751         # Bluetooth mode only
D75_PASSWORD =
```

### Gateway features:
- **`/d75` web page** — Dual-band frequency display, squelch/mode/power controls, S-meter, volume
- **D75AudioSource** — TCP client to port 9751, resamples 8kHz→48kHz (linear interpolation), feeds mixer
- **D75CATClient** — TCP client to port 9750, polls radio state, sends commands from web UI
- **Dashboard** — D75 audio level bar, connection status, mute control ('w' key)

### Connection modes in gateway:
- **Bluetooth**: `!btstart` → D75AudioSource for audio
- **USB**: `!serial connect` → audio via AIOC (existing radio source)

## TCP Protocol

Connect to port 9750. Commands use `!command [args]\n` format. Authenticate first with `!pass`.

### Connection & Control

| Command | Description |
|---------|-------------|
| `!pass <password>` | Authenticate (required first) |
| `!btstart` | Full BT startup: audio + CAT serial |
| `!serial connect` | Connect CAT serial only (USB mode) |
| `!serial disconnect` | Disconnect serial |
| `!serial status` | Connection status |
| `!audio connect` | Connect BT audio only |
| `!audio disconnect` | Disconnect audio |
| `!audio status` | Audio connection status (JSON) |
| `!audio stream` | Stream audio to this TCP client |
| `!exit` | Disconnect |

### Radio Commands

| Command | Description |
|---------|-------------|
| `!cat <CMD> [payload]` | Raw CAT command (e.g., `!cat FQ 0`) |
| `!freq [band] [freq]` | Get/set frequency |
| `!vol [level]` | Get/set AF gain (0-255) |
| `!squelch <band> [level]` | Get/set squelch |
| `!channel <band> [ch]` | Get/set memory channel |
| `!ptt on\|off` | Transmit/receive |
| `!meter [band]` | Read S-meter |
| `!power <band> [level]` | Get/set output power |
| `!mode <band> [mode]` | Get/set mode |
| `!band [idx]` | Get/set active band (0=A, 1=B) |
| `!dual [0\|1]` | Dual/single band |
| `!gps [on\|off]` | GPS control |
| `!bt [on\|off]` | Bluetooth control |
| `!info` | Radio model, S/N, firmware |
| `!status` | Full radio state (JSON) |

## Audio Streaming

When Bluetooth is configured (`bt_addr` is set), audio is available via:

1. **TCP port 9751** — Connect and receive raw PCM (8kHz, 16-bit signed LE, mono)

Audio format: 8,000 Hz sample rate, 16-bit signed little-endian, mono. 48-byte SCO frames (24 samples each, ~331 frames/sec). CVSD decoding is handled in hardware by the BT controller.

The server filters stuck SCO frames (dropped packets where the BT controller repeats the last sample). These are replaced with faded copies of the last good frame, reducing artifacts from ~48% to ~4%.

See [docs/bluetooth_audio.md](docs/bluetooth_audio.md) for full technical details including adapter selection, connection sequence, and troubleshooting.

## Configuration

`config.txt` in the project directory:

| Key | Default | Description |
|-----|---------|-------------|
| `baud_rate` | `9600` | Serial baud rate |
| `device` | *(empty)* | Serial port (`/dev/ttyUSB0` for USB, `/dev/rfcomm0` for BT) |
| `host` | `0.0.0.0` | TCP bind address |
| `port` | `9750` | CAT TCP port |
| `password` | *(empty)* | TCP auth password (blank = still requires `!pass`) |
| `bt_addr` | *(empty)* | D75 Bluetooth MAC — enables BT audio features. Leave empty for USB mode. |
| `audio_port` | `9751` | Audio streaming TCP port (BT mode only) |

## Systemd Service

```bash
./install.sh                          # Install deps + service
sudo systemctl enable d75-cat         # Start on boot
sudo systemctl start d75-cat          # Start now
sudo systemctl status d75-cat         # Check status
journalctl -u d75-cat -f              # Follow logs
```

## Project Structure

| File | Description |
|------|-------------|
| `D75_CAT.py` | Headless TCP server — CAT, audio, and BT management |
| `config.txt` | Server configuration |
| `run-headless.sh` | Startup script (reads config, finds serial port) |
| `install.sh` | Installs dependencies + systemd service |
| `bt_full_test.py` | Integration test — CAT + audio simultaneous |
| `bt_audio_test.py` | Basic SCO audio capture test |
| `bt_dual_test.py` | CAT + audio dual test |
| `docs/bluetooth_audio.md` | Full BT audio technical reference |
| `d75_cat_control.py` | Original GUI application (upstream, not used) |
| `CATControlServer.py` | Original GUI server (upstream, not used) |

## Bluetooth Connection Sequence

The `!btstart` command executes this sequence:

1. **Audio first** — RFCOMM ch1 (HSP) + SCO connect + AT+CKPD=200
2. **Bind rfcomm0** — `rfcomm bind 0 <MAC> 2` for CAT serial
3. **Open serial** — pyserial on `/dev/rfcomm0` at 9600 baud

Order matters: rfcomm bind to ch2 blocks the D75 from accepting ch1, so audio must connect first. CKPD must be sent after SCO but before serial opens.

## Known Issues

- **D75 BT unresponsive after disconnect**: The D75 goes unresponsive after rapid BT connect/disconnect cycles. Toggle Bluetooth off/on on the radio to recover.
- **CSR SCO packet loss**: CSR adapters drop ~48% of SCO packets. The stuck frame filter handles this, but audio quality is limited to what SCO provides (~8kHz voice bandwidth).
- **Realtek BT adapters**: Fatal SCO firmware bug. Do not use for audio.

## License

GNU General Public License v3.0. See [LICENSE](https://www.gnu.org/licenses/gpl-3.0.html).

Based on [D75-CAT-Control](https://github.com/xbenkozx/D75-CAT-Control) by Ben Kozlowski (K7DMG).
