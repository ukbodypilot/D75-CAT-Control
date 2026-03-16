---
name: D75 CAT Control - Bluetooth Audio
description: Bluetooth audio via HSP/SCO on D75 - full technical details, gateway integration, reliability
type: project
---

**Status (2026-03-16):** Fully working with auto-recovery. Gateway integration complete. Web UI has all radio controls. BT reconnect with HCI cleanup + 3x retry handles unclean disconnects without manual radio intervention.

**Architecture:**
- D75_CAT.py: headless TCP server, manages BT audio (SCO) + CAT serial (RFCOMM)
- Gateway: D75CATClient (CAT over TCP) + D75AudioSource (audio over TCP, 8k→48k resample)
- Web UI: /d75 page with full dual-band controls

**Connection modes:** D75_CONNECTION = 'bluetooth' or 'usb'

**Auto-recovery (verified working 2026-03-16):**
- btstart: HCI disconnect + rfcomm release before connecting, 3x retry with 3/6/9s backoff
- Gateway btstart runs in background thread (doesn't block startup)
- Serial reconnect: rfcomm release + rebind on timeout, max 3 attempts
- Command writer: detects OSError, marks connection dead, unblocks waiters
- Systemd: Restart=always with 10s delay

**Web UI features (/d75 page):**
- Dual-band: frequency, mode, power, squelch, S-meter
- CTCSS/DCS tone selector, offset, shift direction
- VFO/Memory mode toggle, memory channel input
- Active band (A/B), dual/single band
- Up/Down dial buttons
- Volume slider, BT Start, PTT
- GPS panel (lat/lon/alt/speed/sats)
- Battery level, BT state, TNC mode, beacon type
- Dashboard: D75 orange level bar + connection status

**Why:** Remote radio control + audio streaming for radio-gateway Mumble bridge.
**How to apply:** Use systemd for both services. Auto-recovery handles BT hiccups. D75 BT toggle only needed if adapter hardware fails.
