---
name: D75 CAT Control - Bluetooth Audio
description: Bluetooth audio via HSP/SCO on D75 - full technical details and integration status
type: project
---

CAT control works on RFCOMM ch2 (/dev/rfcomm0). Audio works via HSP on RFCOMM ch1 + SCO.
Both run simultaneously over Bluetooth — no drop/reconnect needed.

D75 BT MAC: 90:CE:B8:D6:55:0A
Pi BT adapter: 9C:AD:EF:FE:13:BF (hci0) — CSR (Cambridge Silicon Radio) USB, vendor 6242:8202

**Adapter history:** RTL8761BU has fatal SCO firmware bug. CSR adapter works but has ~48% SCO frame loss (stuck frames). Fixed with stuck frame filter in _read_loop.

**Correct BT startup sequence (implemented as !btstart):**
1. Connect audio: RFCOMM ch1 → SCO → AT+CKPD=200 (must be FIRST — rfcomm bind blocks ch1)
2. Bind rfcomm0 (sudo rfcomm bind 0 addr 2) — after audio is established
3. Open serial on /dev/rfcomm0 via pyserial

**Audio TCP streaming:** Raw socket forwarding (not asyncio). AudioTCPServer uses threading accept loop, _forward_audio uses sock.sendall() from SCO read thread. Port 9751.

**SCO stuck frame filter:** CSR adapter repeats last sample for all 24 positions in dropped packets. _read_loop detects stuck frames (unique values <= 2) and replaces with faded copy of last good frame. Reduces stuck rate from 48% to ~4%.

**Gateway integration (2026-03-16, fully working):**
- D75AudioSource: TCP client to port 9751, 6x linear interpolation (8kHz→48kHz) with boundary continuity (_prev_last), queues for mixer
- D75CATClient: TCP client to port 9750, text !command protocol, polls !status every 2s, send_command() pauses polling to avoid race condition
- Config: ENABLE_D75, D75_HOST, D75_PORT, D75_AUDIO_PORT, D75_PASSWORD, D75_AUDIO_BOOST, etc.
- Web UI: /d75 control page (dual-band freq/squelch/mode/power), /d75status + /d75cmd endpoints
- Dashboard: D75 orange audio level bar, connection status, mute indicator
- Nav links conditional on ENABLE flags (ENABLE_TH9800, ENABLE_D75)
- Keyboard 'w' mutes D75 audio
- Systemd service manages gateway (don't start manually or you get duplicates!)

**D75 BT quirk:** D75 goes unresponsive after rapid connect/disconnect cycles. Must toggle BT off/on on radio to recover. Avoid killing D75 server unnecessarily.

**Why:** Remote audio streaming + CAT control through headless TCP server for radio-gateway integration.
**How to apply:** Use systemd to manage gateway. D75_CAT.py runs separately. !btstart handles full connection sequence.
