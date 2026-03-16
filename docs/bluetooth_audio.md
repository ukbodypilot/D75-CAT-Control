# D75 Bluetooth Audio — Technical Documentation

## Overview

The Kenwood TH-D75 exposes two Bluetooth services:

| RFCOMM Channel | Service | UUID | Purpose |
|---|---|---|---|
| 1 | Headset Audio Gateway (HSP) | 0x1112 | Audio control + SCO audio |
| 2 | Serial Port Profile (SPP) | 0x1101 | CAT control |

Both services can be used simultaneously. CAT commands on channel 2 and
audio on channel 1 + SCO do not interfere with each other.

## Hardware Setup

### Bluetooth Pairing

Pair the D75 via `bluetoothctl` or the desktop Bluetooth GUI:

```bash
bluetoothctl
  scan on
  pair 90:CE:B8:D6:55:0A    # Replace with your D75's MAC
  trust 90:CE:B8:D6:55:0A
  scan off
  quit
```

### Discovering RFCOMM Channels

```bash
sdptool browse 90:CE:B8:D6:55:0A
```

Output will show:
- Channel 1: "Headset Audio Gateway" (0x1112) + "Generic Audio" (0x1203)
- Channel 2: "Serial Port" (0x1101)

### Binding RFCOMM Devices

```bash
sudo rfcomm bind 0 90:CE:B8:D6:55:0A 2   # /dev/rfcomm0 → CAT (ch2)
sudo rfcomm bind 1 90:CE:B8:D6:55:0A 1   # /dev/rfcomm1 → Audio (ch1)
```

### Persistent Configuration

Create `/etc/bluetooth/rfcomm.conf`:

```
rfcomm0 {
    bind yes;
    device 90:CE:B8:D6:55:0A;
    channel 2;
    comment "TH-D75 CAT Control";
}

rfcomm1 {
    bind yes;
    device 90:CE:B8:D6:55:0A;
    channel 1;
    comment "TH-D75 Audio (Headset AG)";
}
```

### WirePlumber HFP Configuration

To enable the Pi as an HFP Hands-Free unit, create
`~/.config/wireplumber/wireplumber.conf.d/50-bluez-hsp.conf`:

```
monitor.bluez.properties = {
  bluez5.headset-roles = [ hsp_hs hsp_ag hfp_hf hfp_ag ]
  bluez5.hfphsp-backend = "native"
}
```

> **Note:** PipeWire/WirePlumber's standard Bluetooth audio path does NOT work
> for the D75's audio because the radio advertises as AG (Audio Gateway) and
> the `audio-gateway` profile creates 0 sinks/0 sources. We use direct SCO
> sockets instead.

## Audio Architecture

### Connection Sequence

1. **RFCOMM ch1** — Open a raw Bluetooth RFCOMM socket to the D75's channel 1
   (Headset AG). This establishes the HSP service-level connection.

2. **AT+CKPD=200** — Send this HSP "button press" command over RFCOMM to
   activate audio routing on the radio. The D75 responds with `OK`.

3. **SCO socket** — Open an outbound SCO (Synchronous Connection-Oriented)
   socket to the D75. This creates the audio transport.

4. **Audio flows** — The BT controller decodes CVSD in hardware and delivers
   8kHz 16-bit signed little-endian mono PCM via the SCO socket.

### Important Notes

- **Do NOT send HFP AT commands** (AT+BRSF, AT+CIND, AT+CMER, etc.) — the D75
  returns ERROR for all of them, which can destabilize the connection.
- **Only AT+CKPD=200 is recognized** by the D75 on the HSP channel.
- **SCO must be outbound** (we connect to the radio, not listen). When using
  CKPD=200 to trigger AG-initiated SCO, the connection only survives 1 frame.
- **RFCOMM ch1 must stay open** during audio — closing it drops the SCO link.

### PCM Audio Format

| Parameter | Value |
|---|---|
| Sample rate | 8,000 Hz |
| Bit depth | 16-bit signed |
| Byte order | Little-endian |
| Channels | 1 (mono) |
| Frame size | 48 bytes (24 samples) |
| Frame rate | ~331 frames/sec |
| SCO MTU | 255 bytes |
| Encoding | CVSD (decoded by BT controller hardware) |

### Audio Quality

With squelch open on an active channel:
- Peak amplitude: ~16,000 (out of 32,767)
- RMS: ~4,000
- Suitable for voice communications and digital mode decoding

Some zero-filled frames (dropped SCO packets) are normal for Bluetooth audio
and should be handled gracefully.

## Simultaneous CAT + Audio

CAT control via `/dev/rfcomm0` (RFCOMM ch2) and audio via RFCOMM ch1 + SCO
operate simultaneously without interference.

### Verified Operations During Audio

- `ID` — Radio identification
- `FQ` — Frequency read/set (including band changes)
- `SQ` — Squelch read/set
- `AE` — Serial number query
- `MR` — Memory channel selection
- All standard CAT commands

### Drop/Reconnect (Optional)

If needed (e.g., for TNC mode switching), audio can be torn down and
reconnected:

1. Close SCO socket
2. Close RFCOMM ch1
3. Perform CAT operations
4. Reconnect RFCOMM ch1
5. Reconnect SCO
6. Send AT+CKPD=200

This is NOT required for normal CAT operations — they work simultaneously.

## Python Implementation

### Minimal Audio Connection

```python
import socket
import struct

BTPROTO_RFCOMM = 3
BTPROTO_SCO = 2
SOL_BLUETOOTH = 274
BT_VOICE = 11
BT_VOICE_CVSD_16BIT = 0x0060

D75_ADDR = "90:CE:B8:D6:55:0A"

# 1. RFCOMM to HSP channel
rfcomm = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
rfcomm.settimeout(5.0)
rfcomm.connect((D75_ADDR, 1))  # Channel 1 = Headset AG

# 2. Activate audio routing
rfcomm.send(b"AT+CKPD=200\r")
time.sleep(0.5)
rfcomm.recv(1024)  # Read OK response

# 3. SCO for audio
sco = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_SCO)
sco.setsockopt(SOL_BLUETOOTH, BT_VOICE, struct.pack("H", BT_VOICE_CVSD_16BIT))
sco.settimeout(5.0)
sco.connect(D75_ADDR)

# 4. Read audio frames (48 bytes = 24 samples of 16-bit PCM)
while True:
    data = sco.recv(255)
    # data is 8kHz 16-bit signed LE mono PCM
    samples = struct.unpack(f'<{len(data)//2}h', data)
```

### CAT Serial (Simultaneous)

```python
import serial

cat = serial.Serial("/dev/rfcomm0", 9600, timeout=1,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    rtscts=False)  # RFCOMM has no hardware flow control

cat.write(b"FQ 0\r")
response = cat.read(cat.in_waiting or 1)
```

## Test Scripts

| Script | Purpose |
|---|---|
| `bt_audio_test.py` | Basic SCO audio capture test — records 5s to WAV |
| `bt_dual_test.py` | Tests CAT + Audio simultaneously and drop/reconnect |
| `bt_full_test.py` | Full integration test — CAT opens squelch + records audio |

## Troubleshooting

### RFCOMM connect times out
- Disconnect via `bluetoothctl disconnect <MAC>`, wait 2 seconds, retry
- The D75 may need Bluetooth restarted (Menu → Bluetooth → Off/On)

### SCO connect fails with "Invalid argument"
- Ensure RFCOMM ch1 is connected first (SCO needs an active ACL link)
- Check BT_VOICE socket option is set before connect

### Audio is all zeros/silence
- Squelch is closed — open it via CAT (`SQ 0,0`) or physically on the radio
- On quiet UHF frequencies, there may be genuinely no noise
- Verify AT+CKPD=200 returned OK (activates audio routing)

### "Device or resource busy" on /dev/rfcomm1
- PipeWire/BlueZ may have claimed the device via profile connection
- Disconnect the BlueZ profile: `busctl call org.bluez /org/bluez/hci0/dev_XX_XX... org.bluez.Device1 DisconnectProfile s "00001112-..."`
- Use raw sockets instead of /dev/rfcomm1 for audio

### Connection drops after AT commands
- The D75 returns ERROR for all HFP AT commands (AT+BRSF, AT+CIND, etc.)
- Only send AT+CKPD=200 on the HSP channel
- Multiple ERRORs can destabilize the connection
