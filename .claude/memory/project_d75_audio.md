---
name: D75 CAT Control - Full Feature Set
description: D75 CAT + BT audio bidirectional, gateway integration, automation, watchdog, web UI, memory scan, battery
type: project
---

**Status (2026-03-17):** Fully working. Bidirectional BT audio TX/RX. Connection watchdog with auto-recovery. Full web UI with memory channel scanner.

**Architecture:**
- D75_CAT.py: headless TCP server, BT audio (SCO bidirectional), CAT serial (RFCOMM), connection watchdog
- Gateway: D75CATClient (auto-reconnect) + D75AudioSource (bidirectional 8k↔48k)
- Web UI: /d75 page with dual-band controls, memory scanner, battery, tone display

**Connection Watchdog (2026-03-17):**
- Monitors serial + audio every 10s
- Auto-runs btstart on drop with increasing backoff (5s→30s max)
- Graceful shutdown: cancel watchdog, timeout disconnects at 3s
- Systemd: Restart=always, RestartSec=10, TimeoutStopSec=10
- run-headless.sh: skips rfcomm bind when bt_addr set (btstart handles order)

**TX Audio Path:**
- Gateway 48kHz → D75AudioSource.write_tx_audio() → downsample 8kHz → TCP 9751 → D75_CAT.py → SCO → radio
- PTT: !ptt on/off (explicit, NOT toggle)
- TX_RADIO config routes set_ptt_state() and audio output

**Web UI Features (/d75 page):**
- Edit locks on all controls (3-5s after interaction, prevents poll snap-back)
- Command feedback bar (green OK / red error, 3s)
- Tone/shift display on freq row: type+freq, shift+offset, cross-band
- TX red display on active band during PTT
- Battery level (BL command): Full/Med/Low/Empty, color-coded
- Memory scanner: ME 000-999, stops after 5 empty, shows freq/mode/tone/shift
  - A/B load buttons greyed based on single/dual mode
  - Cross-band detection (TX on different band = "Xband" in red)
- Power: 0=High, 1=Med, 2=Low, 3=EL
- Dual: DL 0=Dual, DL 1=Single

**D75 ME (Memory) Format:**
- 23 fields: ch_num, freq(10-digit Hz), tx_freq(10-digit Hz), step, tx_step, mode, ...
- Field 2 is TX frequency (NOT offset) — compare with field 1 to determine shift
- Fields 8/9/10: tone_on/ctcss_on/dcs_on; Fields 14/15/16: tone_idx/ctcss_idx/dcs_idx
- When tone_on=1 and tone_idx=0, use ctcss_idx instead (tone_idx=0 is often default/unset)
- Power not stored per-channel (D75 uses per-band power via PC command)

**Why:** Remote radio control + audio streaming + TX for radio-gateway Mumble bridge and automation.
**How to apply:** D75_CAT.py auto-connects on startup via watchdog. Gateway reconnects automatically. All controls have edit locks to prevent poll overwrite.
