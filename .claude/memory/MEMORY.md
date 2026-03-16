# D75 CAT Control — Project Memory

## Project Overview
Headless TCP server for Kenwood D74/D75 radio CAT control. Forked from
[D75-CAT-Control](https://github.com/ukbodypilot/D75-CAT-Control/) (Ben Kozlowski, K7DMG).
Adapted to run without GUI, modeled after TH9800_CAT.py for radio-gateway integration.

**Main file:** `D75_CAT.py` (~680 lines, single file, no Qt dependency)
**Original GUI:** `d75_cat_control.py` + `Device.py` + `UI/` (PySide6, not used by headless)
**Config:** `config.txt` (baud=9600, port=9750, host=0.0.0.0)
**Service:** `d75-cat.service` (systemd, installed via install.sh)

## Architecture
- **asyncio** event loop (not threading like TH9800)
- **serial_asyncio** for serial I/O
- **TCP server** with `!command\n` protocol, password auth
- **Command queue** — D75 processes one command at a time, must wait for response
- **RadioState** class tracks all radio state, updated from parsed responses
- **GPS/ChannelFrequency** parsers copied from original code (no Qt deps)

## CAT Protocol — Text-Based
- Send: `CMD payload\r` (e.g., `FQ 0,0145500000\r`)
- Receive: `CMD data\r` or `?\r` (invalid) or `N\r` (rejected)
- 29 command codes (AE, AG, AI, BC, BE, BL, BT, BY, DL, DW, FO, FQ, FV, GP, ID, LC, MD, ME, MR, PC, PT, RX, SM, SQ, TN, TX, UP, VM)
- **FO responses can fragment** — need buffering until 72+ bytes received
- **AI 1** enables auto-feedback (radio pushes state changes)

## Serial Config
- 9600 baud, 8N1, **hardware flow control (RTS/CTS)**
- **CRITICAL:** RTS cannot be toggled — it's used for flow control. PTT via `TX`/`RX` CAT commands.
- DTR used for connection wake-up

## TCP Commands
`!pass`, `!exit`, `!cat`, `!freq`, `!vol`, `!squelch`, `!channel`, `!ptt on|off`,
`!meter`, `!power`, `!mode`, `!band`, `!dual`, `!gps`, `!bt`, `!info`, `!dtr`,
`!serial connect|disconnect|status`, `!status`

## Key Differences from TH9800_CAT.py
- Text protocol (not binary packets with framing/checksums)
- 9600 baud (not 19200)
- Hardware RTS/CTS flow control (no `!rts` command)
- PTT via CAT `TX`/`RX` (not binary command packet)
- Port 9750 (not 9800, avoids conflict)
- Single AF gain (no per-VFO volume)
- Pure asyncio (TH9800 uses threading + asyncio hybrid)

## Radio-Gateway Integration (TODO)
- RadioCATClient in radio_gateway.py connects to this TCP server
- Same auth flow (`!pass`) and command format (`!command data\n`)
- PTT: `!ptt on` / `!ptt off` (no RTS switching needed)
- Status: `!status` returns JSON
- Need new D75CATClient class or adapt existing RadioCATClient

## Status: 2026-03-15
- TCP server starts, auth works, commands dispatch correctly
- Serial protocol implemented but untested with actual D75 radio
- Systemd service template created
- Not yet integrated with radio-gateway
