---
name: D75 Bluetooth audio protocol quirks
description: Critical protocol rules for D75 Bluetooth HSP audio - adapter selection, avoid HFP commands, use outbound SCO, correct startup order, stuck frame filter
type: feedback
---

**Adapter selection:** Use CSR (Cambridge Silicon Radio) or Broadcom USB BT adapter. Realtek adapters (RTL8761BU, RTL8851BU) have fatal SCO firmware bug. CSR works but drops ~48% of SCO packets — stuck frame filter in _read_loop handles this.

Do NOT send HFP AT commands to the D75 on the HSP channel (AT+BRSF, AT+CIND, AT+CMER). They all return ERROR and destabilize the connection.

AT+CKPD=200 activates audio routing. Must be sent AFTER SCO connects but BEFORE CAT serial opens.

SCO audio must use outbound connect (socket.connect), not listen/accept.

For CAT serial over Bluetooth: use pyserial on /dev/rfcomm0 (blocking, threaded read). Do NOT use serial_asyncio.

Correct BT startup order (!btstart):
1. RFCOMM ch1 connect → SCO connect → AT+CKPD=200 (MUST be before rfcomm bind)
2. Bind rfcomm0 (rfcomm bind to ch2 blocks D75 from accepting ch1)
3. Open serial on /dev/rfcomm0

Audio TCP streaming uses raw sockets, not asyncio StreamWriter. asyncio writer.write() via call_soon_threadsafe never reliably flushed.

D75CATClient in gateway: send_command() pauses polling thread to avoid race condition where poll response gets returned instead of command response. Buffer is flushed before each command.

D75AudioSource resampling: use streaming 6x linear interpolation with _prev_last boundary continuity. Do NOT use resampy (batch resampler causes chunk boundary artifacts).

**Connection modes:** D75_CONNECTION = 'bluetooth' or 'usb'. USB mode uses !serial connect (no btstart), audio via AIOC.

**Why:** Discovered through iterative testing on 2026-03-16.
**How to apply:** When modifying D75 code, always use pyserial for CAT, raw sockets for audio TCP, linear interp for resampling. Use CSR/Broadcom adapter. Manage gateway via systemd (never start manually or duplicates occur).
