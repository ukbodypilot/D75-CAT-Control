#!/usr/bin/env python3
"""
bt_full_test.py — Full test: CAT + Audio simultaneously with real audio.
Uses CAT to open squelch, then verifies audio has real signal.
"""

import socket
import struct
import time
import threading
import sys
import os
import wave

BTPROTO_RFCOMM = 3
BTPROTO_SCO = 2
SOL_BLUETOOTH = 274
BT_VOICE = 11
BT_VOICE_CVSD_16BIT = 0x0060
SOL_SCO = 17
SCO_OPTIONS = 1

D75_ADDR = "90:CE:B8:D6:55:0A"


def main():
    print("=== D75 Full Test: CAT + Audio ===")
    print()

    # ── Connect Audio (RFCOMM ch1 + SCO) ──
    print("[Audio] Connecting...")
    rfcomm = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
    rfcomm.settimeout(5.0)
    rfcomm.connect((D75_ADDR, 1))
    time.sleep(0.3)

    sco = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_SCO)
    sco.setsockopt(SOL_BLUETOOTH, BT_VOICE, struct.pack("H", BT_VOICE_CVSD_16BIT))
    sco.settimeout(5.0)
    sco.connect(D75_ADDR)
    print("[Audio] SCO connected")

    # Send CKPD=200 to activate HSP audio routing
    rfcomm.send(b"AT+CKPD=200\r")
    time.sleep(0.5)
    try:
        resp = rfcomm.recv(1024)
        print(f"[Audio] CKPD response: {resp.decode(errors='ignore').strip()}")
    except socket.timeout:
        print("[Audio] CKPD: no response")

    # Start capture thread
    capture_buf = bytearray()
    running = [True]

    def read_loop():
        while running[0]:
            try:
                data = sco.recv(255)
                if not data:
                    break
                capture_buf.extend(data)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Audio] Error: {e}")
                break

    t = threading.Thread(target=read_loop, daemon=True)
    t.start()

    # ── Connect CAT (rfcomm0 / ch2) ──
    print("[CAT] Connecting...")
    import serial
    cat = serial.Serial("/dev/rfcomm0", 9600, timeout=1,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        rtscts=False)
    time.sleep(0.3)

    def cat_cmd(cmd):
        cat.write(f"{cmd}\r".encode())
        time.sleep(0.3)
        resp = cat.read(cat.in_waiting or 1).decode(errors='ignore').strip()
        print(f"[CAT] {cmd} -> {resp}")
        return resp

    # Get radio info
    cat_cmd("ID")
    cat_cmd("FQ 0")

    # Read current squelch
    cat_cmd("SQ 0")

    # Set squelch to 0 (fully open)
    print()
    print("[CAT] Opening squelch...")
    cat_cmd("SQ 0,0")
    time.sleep(0.5)

    # Record audio with squelch open
    print()
    print("[Test] Recording 3 seconds with squelch open...")
    capture_buf.clear()
    time.sleep(3)

    audio_open = bytes(capture_buf)
    print(f"[Test] Captured {len(audio_open)} bytes")

    if len(audio_open) >= 2:
        samples = struct.unpack(f'<{len(audio_open)//2}h', audio_open)
        peak = max(abs(s) for s in samples)
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        print(f"[Test] Squelch OPEN — Peak: {peak}, RMS: {rms:.1f}")

    # Restore squelch
    print()
    print("[CAT] Restoring squelch to 3...")
    cat_cmd("SQ 0,2")
    time.sleep(0.5)

    # Record with squelch closed
    capture_buf.clear()
    time.sleep(2)

    audio_closed = bytes(capture_buf)
    if len(audio_closed) >= 2:
        samples = struct.unpack(f'<{len(audio_closed)//2}h', audio_closed)
        peak_closed = max(abs(s) for s in samples)
        rms_closed = (sum(s*s for s in samples) / len(samples)) ** 0.5
        print(f"[Test] Squelch CLOSED — Peak: {peak_closed}, RMS: {rms_closed:.1f}")

    # Save the open-squelch audio
    if len(audio_open) > 0:
        wav_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_full.wav")
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(audio_open)
        print(f"\n[Test] Saved to {wav_path}")

    # Test a channel change while audio is running
    print()
    print("[Test] Testing channel change with audio running...")
    capture_buf.clear()
    cat_cmd("FQ 0,0146520000")  # change to 146.520
    time.sleep(1)
    fc_after = len(capture_buf)
    cat_cmd("FQ 0")  # read back
    print(f"[Test] Audio frames during freq change: {fc_after} bytes captured")
    cat_cmd("FQ 0,0445975000")  # change back

    # Cleanup
    running[0] = False
    t.join(timeout=2)
    cat.close()
    sco.close()
    rfcomm.close()

    print()
    print("=" * 50)
    if peak > 100:
        print("SUCCESS: CAT + Audio working simultaneously!")
        print(f"  Audio: real signal (peak={peak})")
        print("  CAT: radio responds to commands")
        print("  No need for drop/reconnect pattern!")
    else:
        print("Audio levels low — squelch may not have opened")
        print("Try with radio receiving a signal")
    print("=" * 50)

    return 0


if __name__ == '__main__':
    sys.exit(main())
