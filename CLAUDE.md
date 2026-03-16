# Claude Instructions — D75 CAT Control

## Memory
At the end of every session, update the memory files:
- `.claude/memory/MEMORY.md` — project overview and key details

Also sync to the Claude Code auto-memory path after cloning:
```
mkdir -p ~/.claude/projects/-home-user-D75-CAT-Control/memory/
cp .claude/memory/* ~/.claude/projects/-home-user-D75-CAT-Control/memory/
```

## Project Rules
- Only commit when the user explicitly asks
- Never auto-push
- `config.txt` should NOT contain passwords when committed
- The headless server (`D75_CAT.py`) must never depend on PySide6/Qt
- Serial uses hardware RTS/CTS flow control on USB — never toggle RTS manually
- Bluetooth RFCOMM does NOT support RTS/CTS — auto-detect via /dev/rfcomm* prefix

## Bluetooth Audio Rules
- D75 BT MAC: 90:CE:B8:D6:55:0A
- RFCOMM ch1 = Headset AG (audio), RFCOMM ch2 = SPP (CAT)
- Only send AT+CKPD=200 on HSP channel — all HFP AT commands return ERROR
- SCO must be outbound connect (not listen/accept)
- CAT and audio work simultaneously — no need to drop audio for CAT ops
- Audio format: 8kHz 16-bit signed LE mono, 48-byte frames via SCO
- See `docs/bluetooth_audio.md` for full technical reference
