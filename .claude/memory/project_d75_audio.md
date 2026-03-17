---
name: D75 CAT Control - Bluetooth Audio & TX
description: D75 CAT + BT audio bidirectional (RX+TX), gateway integration, automation, auto-recovery
type: project
---

**Status (2026-03-17):** Fully working bidirectional BT audio. Gateway can PTT and transmit audio through D75 via Bluetooth SCO. Auto-connect/reconnect on startup.

**Architecture:**
- D75_CAT.py: headless TCP server, manages BT audio (SCO bidirectional) + CAT serial (RFCOMM)
- Gateway: D75CATClient (CAT over TCP, auto-reconnect) + D75AudioSource (audio over TCP, bidirectional: 8k→48k RX, 48k→8k TX)
- Web UI: /d75 page with full dual-band controls + PTT

**Connection modes:** D75_CONNECTION = 'bluetooth' or 'usb'

**TX Audio path (2026-03-17, verified working):**
- Gateway playback/TTS/announce → 48kHz PCM → D75AudioSource.write_tx_audio() → downsample to 8kHz (every 6th sample) → TCP port 9751 → D75_CAT.py AudioTCPServer._read_tx_audio() → AudioManager._write_blocking() → SCO socket → D75 radio → over the air
- PTT via D75CATClient.send_command("!ptt on"/"!ptt off") — explicit on/off, NOT toggle
- TX_RADIO config: 'th9800' (default) or 'd75' — routes set_ptt_state() and audio output
- RTS save/restore skipped when TX_RADIO=d75 (not applicable)

**Auto-startup (2026-03-17):**
- run-headless.sh: skips rfcomm bind when bt_addr is set (btstart handles correct order)
- D75_CAT.py: background task runs btstart automatically on startup (audio→rfcomm→serial)
- Gateway D75CATClient: auto-reconnect in poll thread on connection loss

**Auto-recovery:**
- btstart: HCI disconnect + rfcomm release before connecting, 3x retry with 3/6/9s backoff
- Gateway btstart runs in background thread (doesn't block startup)
- D75CATClient poll thread: detects OSError, marks connection dead, reconnects
- Systemd: Restart=always with 10s delay

**Automation engine (2026-03-17):**
- D75 FO command for atomic tuning: freq + step(5kHz) + mode + PL tone + offset in one command
- FO response parsing handles prefix stripping and multiline responses
- CTCSS tone lookup table (39 tones, index 0-38)
- Auto-calculates repeater offset: 600kHz for 2m, 5MHz for 70cm

**Web UI features (/d75 page):**
- Dual-band: frequency, mode, power, squelch, S-meter
- CTCSS/DCS tone selector, offset, shift direction
- VFO/Memory mode toggle, memory channel input
- PTT button, Volume slider, BT Start
- GPS panel, Battery level, BT state, TNC mode

**Why:** Remote radio control + audio streaming + TX for radio-gateway Mumble bridge and automation.
**How to apply:** Use systemd for both services. Auto-recovery handles BT hiccups. D75 BT toggle only needed if adapter hardware fails.
