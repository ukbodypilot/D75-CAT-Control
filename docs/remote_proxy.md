# Remote Bluetooth Proxy Architecture

## Overview

The TH-D75's Bluetooth range is limited (~10m). When the gateway or
controlling application runs on a different machine (or even a different
room), a remote proxy bridges the gap:

```
┌─────────┐    Bluetooth    ┌──────────────┐     TCP/IP      ┌─────────┐
│  TH-D75 │ ◄────────────► │  BT Proxy    │ ◄──────────────► │ Gateway │
│  Radio  │   RFCOMM + SCO │  (near radio) │   Ports 9750/51 │ (remote)│
└─────────┘                 └──────────────┘                  └─────────┘
```

The proxy machine sits near the radio with a Bluetooth adapter. The
gateway connects to the proxy over the local network via two TCP ports:

| Port | Protocol | Purpose |
|------|----------|---------|
| 9750 | Text (line-based) | CAT commands — compatible with D75_CAT.py |
| 9751 | Raw PCM stream | 8kHz 16-bit signed LE mono audio |

## Why Not Just Use Longer-Range Bluetooth?

- Class 1 BT adapters (100m range) exist but SCO audio quality degrades
  rapidly with distance
- BT repeaters/extenders don't support SCO audio
- USB-over-IP (USBIP) adds latency and requires kernel modules
- TCP proxy is simple, reliable, and works over any network

## Proxy Design

### Architecture

The proxy (`remote_bt_proxy.py`) has three managers:

1. **SerialManager** — RFCOMM ch2 (CAT control)
   - Raw Bluetooth socket (not /dev/rfcomm — avoids rfcomm bind issues)
   - `AI 1` streaming: reads pushed messages into a queue
   - `send_raw()`: sends a command, drains streaming messages, waits for
     matching response
   - Caches all radio state (frequency, mode, S-meter, tone, power, etc.)

2. **AudioManager** — RFCOMM ch1 + SCO (audio)
   - HSP connection sequence: RFCOMM ch1 → SCO → AT+CKPD=200
   - SCO read loop forwards raw PCM to TCP clients
   - Uses ctypes `libc.connect()` for SCO — Python's socket.connect()
     has inconsistent bdaddr parsing across distros

3. **CATServer** — TCP command interface
   - Accepts gateway connections on port 9750
   - Text protocol: `!command [args]\n` → `response\n`
   - `!status` returns cached state as JSON (no serial round-trip)
   - `!cat <raw>` passes commands to the radio via send_raw()
   - `!btstart` / `!btstop` manage the full BT lifecycle

### Command Protocol

```
Client → Proxy:
  !pass <password>\n        → "Login Successful" or "Login Failed"
  !status\n                 → JSON radio state
  !cat FQ 0\n               → "FQ 0,0146520000" (raw CAT passthrough)
  !btstart\n                → "btstart initiated" (async, poll !status)
  !btstop\n                 → "stopped"
  !ptt on\n                 → "TX"
  !ptt off\n                → "RX"
  !serial connect\n         → "connected" or "connect failed"
  !audio connect\n          → "connected" or "connect failed"
  !exit\n                   → (closes connection)
```

### State Caching

`!status` returns cached state — it does NOT send any commands to the
radio. This means the gateway can poll `!status` every 2 seconds without
adding any load to the Bluetooth link.

State is kept current by:
- **AI 1 streaming**: FQ, MD, TX, RX, BY, BC, DL, PC pushed automatically
- **SM polling**: S-meter polled every 3 seconds (see
  [cat_over_bluetooth.md](cat_over_bluetooth.md) for rate limits)
- **FO polling**: Tone/shift/offset polled every 15 seconds
- **User commands**: `!cat` responses update cached state

### btstart Sequence

`!btstart` is non-blocking — it returns immediately and runs the
connection in a background thread. The gateway polls `!status` to detect
when `serial_connected` becomes true.

```
1. Connect RFCOMM ch1 (audio control channel)
2. Connect SCO (audio transport)
3. Send AT+CKPD=200 (activate audio routing)
   ↑ Steps 1-3 done WITHOUT serial — if BT is unreachable, bail early
4. If serial was connected, briefly disconnect it
   (CKPD fails if serial is active — cross-channel interference)
5. Connect RFCOMM ch2 (serial/CAT)
6. Query ID, FV, AE, SM, FO, PC, DL, BC (initial state)
7. Enable AI 1 (auto-info streaming)
```

### Audio TCP Forwarding

The audio TCP server on port 9751 accepts multiple clients (though
typically only one gateway connects). Raw SCO PCM frames are forwarded
directly — no re-encoding, no buffering.

```
SCO socket (48 bytes/frame, ~331 fps)
  → AudioManager._read_loop()
    → sendall() to each connected TCP client
```

The gateway's `D75AudioSource` class connects to this port and feeds the
PCM into the audio mixer.

## Deployment

### Requirements

- Python 3.10+
- `pyserial` (for potential rfcomm fallback, though raw sockets are preferred)
- A CSR-based USB Bluetooth adapter (see
  [bluetooth_audio.md](bluetooth_audio.md) for adapter requirements)
- Bluetooth pairing completed (`bluetoothctl pair/trust`)

### Running

```bash
# On the BT proxy machine (near the radio):
python3 remote_bt_proxy.py

# On the gateway machine, set config:
#   D75_HOST = <proxy-machine-ip>
#   D75_PORT = 9750
#   D75_AUDIO_PORT = 9751
```

### Configuration

Edit the top of `remote_bt_proxy.py`:

```python
D75_MAC      = "90:CE:B8:D6:55:0A"   # Your radio's MAC
SERVER_HOST  = "0.0.0.0"              # Listen on all interfaces
CAT_PORT     = 9750
AUDIO_PORT   = 9751
PASSWORD     = ""                      # Match gateway's D75_CAT_PASSWORD
```

### No SSH Required

The proxy machine doesn't need SSH — deploy updates via `git pull` from
a local terminal or remote desktop session. The proxy has no dependencies
beyond Python stdlib + pyserial.

## Gateway Integration

### Connection Lifecycle

The gateway's `D75CATClient` manages the TCP connection to the proxy:

1. **Initial connect**: TCP to proxy port 9750, authenticate, start poll thread
2. **Poll thread**: sends `!status` every 2s, updates cached state
3. **Auto-reconnect**: if TCP drops, poll thread retries every 5s
4. **Auto-btstart**: after TCP reconnect, if serial is down and user hasn't
   explicitly stopped BT, sends `!btstart` automatically
5. **User commands**: `send_command()` pauses polling, drains buffer, sends
   command, resumes polling

### Connection State Model

```
                    ┌─────────────┐
          ┌────────►│ TCP Connected│◄───────┐
          │         │ BT Connected │        │
          │         └──────┬──────┘        │
          │                │ btstop        │ btstart
          │                ▼               │
          │         ┌─────────────┐        │
          │         │ TCP Connected│────────┘
          │         │ BT Down      │
          │         └──────┬──────┘
          │                │ proxy restart / TCP drop
          │                ▼
          │         ┌─────────────┐
          └─────────│ TCP Down     │
           reconnect│ Reconnecting │
                    └─────────────┘
```

### Key Implementation Details

- **`_connected` vs `_serial_connected`**: `_connected` = TCP to proxy,
  `_serial_connected` = proxy has BT serial to radio. Report "connected"
  to the user only when BOTH are true.

- **`_recv_line` must detect EOF**: When `recv()` returns `b''` (TCP
  close), set `_connected = False` immediately. Otherwise the poll thread
  loops forever getting None without triggering reconnect.

- **`close()` vs `_disconnect_for_reconnect()`**: `close()` sets
  `_stop = True` and kills the poll thread — use only for full shutdown.
  The poll thread's internal reconnect must only tear down the socket
  without setting `_stop`.

- **`send_command` guards**: Check `_sock` and `_connected` before
  accessing the socket. The socket can become None between the check and
  the use if the poll thread is reconnecting.

## Troubleshooting

### Proxy starts but gateway can't connect
- Check firewall: `sudo ufw allow 9750/tcp && sudo ufw allow 9751/tcp`
- Verify IP: `hostname -I` on the proxy machine
- Test: `nc -zv <proxy-ip> 9750`

### Gateway connects but btstart fails
- Check radio is powered on with Bluetooth enabled
- Check `bluetoothctl info <MAC>` shows Paired: yes, Trusted: yes
- Check BT adapter: `hciconfig hci0` should show UP RUNNING

### Audio connects but no sound
- SCO requires the BT adapter to be the one that paired with the radio
- Check `!audio status` returns "connected"
- Verify AT+CKPD=200 was sent (look for "CKPD sent" in proxy logs)

### Commands work but S-meter always 0
- SM is polled, not pushed — wait 3 seconds for first reading
- Open squelch to verify: `!cat SQ 0,0`
