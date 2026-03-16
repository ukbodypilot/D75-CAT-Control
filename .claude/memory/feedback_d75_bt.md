---
name: D75 Bluetooth audio protocol quirks
description: Critical protocol rules for D75 Bluetooth HSP audio - adapter selection, avoid HFP commands, use outbound SCO, correct startup order
type: feedback
---

**Adapter selection:** Use a CSR (Cambridge Silicon Radio) or Broadcom USB BT adapter. Realtek adapters (RTL8761BU, RTL8851BU, etc.) have a fatal SCO firmware bug — invalid connection handles cause all-0xFF audio on every session. Not fixable in software.

Do NOT send HFP AT commands to the D75 on the HSP channel (AT+BRSF, AT+CIND, AT+CMER). They all return ERROR and destabilize the connection.

AT+CKPD=200 activates audio routing. Must be sent AFTER SCO connects but BEFORE CAT serial opens. When CAT is active on rfcomm0, CKPD causes cross-channel errors that break SCO.

SCO audio must use outbound connect (socket.connect), not listen/accept.

For CAT serial over Bluetooth: use pyserial on /dev/rfcomm0 (blocking, threaded read). Do NOT use serial_asyncio — it conflicts with SCO audio causing EBUSY errors. Raw BT RFCOMM sockets in non-blocking mode also conflict with SCO.

Correct BT startup order (!btstart):
1. RFCOMM ch1 connect → SCO connect → AT+CKPD=200 (MUST be before rfcomm bind)
2. Bind rfcomm0 (rfcomm bind to ch2 blocks D75 from accepting ch1)
3. Open serial on /dev/rfcomm0

AudioManager._connect_blocking: always use threaded SCO read loop (not asyncio). The asyncio approach fails because _connect_blocking runs in an executor thread where asyncio.get_event_loop().create_task() doesn't work.

**Why:** Discovered through iterative testing on 2026-03-16. RTL8761BU SCO bug confirmed fatal after testing force_scofix, USB alt settings, module reload. CSR adapter verified working same day. serial_asyncio and non-blocking BT sockets interfere with kernel BT stack SCO handling.
**How to apply:** When modifying D75_CAT.py Bluetooth code, always use pyserial (not serial_asyncio or raw non-blocking sockets) for CAT. Use !btstart sequence for proper startup. Never send CKPD when CAT is active. Use CSR/Broadcom adapter, never Realtek.
