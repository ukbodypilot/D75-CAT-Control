# CAT Command Rate Limits over Bluetooth

## Overview

The TH-D75's Bluetooth SPP (Serial Port Profile) on RFCOMM channel 2 has
significantly lower throughput than USB serial. CAT commands that work
reliably over USB can saturate the BT link and cause cascading failures
when sent too frequently.

This document covers empirically determined rate limits and failure modes
discovered during integration with a radio gateway that polls the D75
continuously for live dashboard updates.

## The Problem: S-Meter Polling Kills Bluetooth

The D75's `AI 1` (Auto-Info) mode pushes frequency, mode, TX/RX state,
and band changes automatically. However, **S-meter (`SM`) is NOT pushed
by AI 1** and must be polled explicitly.

### What Happens at High Poll Rates

With `SM 0` and `SM 1` polled every 0.5 seconds (4 serial round-trips/sec):

1. **Timeouts start**: SM queries take longer to respond, eventually
   exceeding the 2-second deadline
2. **Lock contention**: Each timed-out query holds the serial send lock
   for 2 seconds. Two back-to-back timeouts (SM 0 + SM 1) hold the lock
   for 4 seconds, blocking all user commands
3. **Command starvation**: User-initiated commands (frequency changes,
   power level, etc.) queue behind the SM poll lock and appear to fail
4. **Link death**: After sustained timeouts, the BT RFCOMM connection
   drops entirely with `[Errno 107] Transport endpoint is not connected`
5. **Radio unresponsive**: The D75 may need Bluetooth toggled off/on
   before it accepts new connections

### Timeline of a Typical Failure

```
00:00  SM 0 → response OK (50ms)
00:00  SM 1 → response OK (50ms)
00:50  SM 0 → response OK
00:50  SM 1 → response OK
...
05:30  SM 0 → no response (timeout 2s)     ← first sign of trouble
05:32  SM 1 → no response (timeout 2s)     ← lock held for 4s total
05:36  SM 0 → no response (timeout 2s)
05:38  User sends PC 0,1 — blocked behind SM lock
05:38  SM 1 → no response (timeout 2s)
05:42  [Errno 107] Transport endpoint is not connected
```

## Safe Polling Rates

| Command | Safe interval | Notes |
|---------|--------------|-------|
| `SM 0` + `SM 1` | 3 seconds | One round-trip per band |
| `FO 0` + `FO 1` | 15 seconds | Tone/shift/offset — rarely changes |
| `AI 1` streaming | Continuous | FQ/MD/TX/RX/BY/BC/DL/PC pushed automatically |

### Recommended: Poll SM at 3 Seconds with Backoff

```python
SM_POLL_INTERVAL = 3.0  # seconds between SM poll cycles
sm_fail_count = 0

# In your polling loop:
if time.time() - last_sm_poll >= SM_POLL_INTERVAL:
    last_sm_poll = time.time()
    ok = True

    r = send_raw("SM 0")
    if r:
        process(r)
    else:
        ok = False

    # Skip SM 1 if SM 0 failed — avoid 4s lock hold on double timeout
    if ok:
        r = send_raw("SM 1")
        if r:
            process(r)
        else:
            ok = False

    if not ok:
        sm_fail_count += 1
        # Exponential backoff: don't hammer a dying link
        if sm_fail_count >= 3:
            last_sm_poll += min(sm_fail_count * 2.0, 30.0)
    else:
        sm_fail_count = 0
```

### Key Design Rules

1. **Never poll SM faster than 3 seconds** over Bluetooth
2. **Skip the second band if the first times out** — if SM 0 fails,
   SM 1 will almost certainly fail too
3. **Back off exponentially** on repeated failures — 6s, 8s, 10s... up
   to 30s between attempts
4. **Use short timeouts for polls** (1-2s), longer for user commands (3-5s)
5. **AI 1 is free** — it pushes data asynchronously with no polling cost

## Other CAT Timing Considerations

### Command Response Time

Over Bluetooth, typical response times:

| Command | Typical | Worst case |
|---------|---------|------------|
| `SM` (S-meter) | 50-200ms | 2s+ (congested) |
| `FQ` (frequency) | 50-150ms | 500ms |
| `FO` (full options) | 100-300ms | 1s |
| `PC` (power) | 50-150ms | 500ms |
| `ID` (identification) | 100-500ms | 2s (initial query) |

### CKPD and Serial Ordering

When using simultaneous audio (RFCOMM ch1 + SCO) and CAT (RFCOMM ch2):

- `AT+CKPD=200` must be sent AFTER SCO connects but BEFORE CAT serial opens
- If CAT serial is already open, briefly disconnect it, send CKPD, reconnect
- See [bluetooth_audio.md](bluetooth_audio.md) for the full connection sequence

### btstart/btstop Timing

The `!btstart` command (connecting BT audio + serial) takes 3-8 seconds.
The `!btstop` command (disconnecting) takes 2-5 seconds. Both should use
timeouts of at least 15 seconds to avoid false failures.

## USB vs Bluetooth Comparison

| Aspect | USB Serial | Bluetooth SPP |
|--------|-----------|---------------|
| Throughput | High | Limited by RFCOMM |
| SM poll rate | 0.1s safe | 3s minimum |
| Command latency | <10ms | 50-500ms |
| Link stability | Excellent | Degrades under load |
| Concurrent users | N/A | Single RFCOMM client |
| Range | Cable length | ~10m typical |

## References

- Kenwood TH-D75 CAT command reference (via Hamlib `thd74.c`)
- LA3QMA Hamlib TH-D74/D75 implementation — 21-field FO format
- [bluetooth_audio.md](bluetooth_audio.md) — SCO audio architecture
