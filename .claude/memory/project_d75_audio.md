---
name: D75 CAT Control - Bluetooth Audio
description: Bluetooth audio via HSP/SCO on D75 - full technical details and integration status
type: project
---

CAT control works on RFCOMM ch2 (/dev/rfcomm0). Audio works via HSP on RFCOMM ch1 + SCO.
Both run simultaneously over Bluetooth — no drop/reconnect needed.

D75 Bluetooth channels:
- RFCOMM ch1: Headset AG (HSP, UUID 0x1112) — send AT+CKPD=200 to activate audio routing
- RFCOMM ch2: Serial Port Profile (SPP, UUID 0x1101) — standard Kenwood CAT at 9600/8N1
- SCO: Outbound connect, CVSD decoded by BT controller → 8kHz 16-bit signed LE mono, 48-byte frames

D75 BT MAC: 90:CE:B8:D6:55:0A
Pi BT adapter: 9C:AD:EF:FE:13:BF (hci0) — CSR (Cambridge Silicon Radio) USB, vendor 6242:8202, HCI 2.1

**Adapter history:** RTL8761BU (00:E0:4C:23:99:87) has fatal SCO firmware bug — "unknown connection handle" on every SCO session, all 0xFF audio. Not fixable via force_scofix, alt settings, or module reload. Switched to CSR adapter on 2026-03-16 which works perfectly.

Key findings (2026-03-16):
- Do NOT send HFP AT commands (BRSF, CIND, CMER) — D75 returns ERROR and destabilizes link
- AT+CKPD=200 is the only recognized command (HSP button press, returns OK)
- SCO must be outbound connect (not listen) — AG-initiated SCO only survives 1 frame
- Audio verified: peak 1,036, RMS 38.0 with open squelch (CSR adapter)
- Simultaneous CAT+Audio confirmed working — freq changes, squelch, ID all work during audio
- RFCOMM ch1 must stay open during audio (closing it drops SCO)

**Correct BT startup sequence (implemented as !btstart):**
1. Bind rfcomm0 (sudo rfcomm bind 0 addr 2) — creates device node, may establish ACL
2. Connect audio: RFCOMM ch1 → SCO → AT+CKPD=200 (CKPD AFTER SCO, BEFORE serial)
3. Open serial on /dev/rfcomm0 via pyserial

**Critical: CKPD must be sent AFTER SCO connects but BEFORE serial opens.**

**Current status (2026-03-16, post CSR adapter switch):**
- bt_full_test.py passes: CAT + Audio simultaneous, peak=1036
- TCP CAT control fully working (port 9750, !command protocol verified)
- AudioManager + AudioTCPServer (port 9751) streams raw PCM to clients
- !btstart command does correct startup sequence
- Both servers have reuse_address=True to avoid port bind issues

**Next steps:**
1. Test !btstart end-to-end: TCP CAT + audio streaming via port 9751
2. Verify audio stream has real signal through TCP server
3. Build D75 CAT client for radio-gateway integration
4. Wire D75 audio into gateway via RemoteAudioSource (8k→48k resample)

**Why:** Remote audio streaming through headless TCP server for radio-gateway integration.
**How to apply:** Use !btstart for proper startup. Test scripts: bt_audio_test.py, bt_dual_test.py, bt_full_test.py.
