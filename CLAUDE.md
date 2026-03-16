# Claude Instructions — D75 CAT Control

## Memory
At the end of every session, update the memory files:
- `.claude/memory/MEMORY.md` — project overview and key details

Also sync to the Claude Code auto-memory path after cloning:
```
mkdir -p ~/.claude/projects/-home-user-Downloads-D75-CAT-Control/memory/
cp .claude/memory/* ~/.claude/projects/-home-user-Downloads-D75-CAT-Control/memory/
```

## Project Rules
- Only commit when the user explicitly asks
- Never auto-push
- `config.txt` should NOT contain passwords when committed
- The headless server (`D75_CAT.py`) must never depend on PySide6/Qt
- Serial uses hardware RTS/CTS flow control — never toggle RTS manually
