#!/usr/bin/env python3
"""
bt_dual_test.py — Test CAT + Audio coexistence over Bluetooth.

Test 1: Try running CAT (rfcomm0/ch2) and audio (rfcomm ch1 + SCO) simultaneously.
Test 2: If that fails, test drop/reconnect pattern — tear down audio, do CAT, bring audio back.
"""

import socket
import struct
import time
import threading
import sys
import os

BTPROTO_RFCOMM = 3
BTPROTO_SCO = 2
SOL_BLUETOOTH = 274
BT_VOICE = 11
BT_VOICE_CVSD_16BIT = 0x0060
SOL_SCO = 17
SCO_OPTIONS = 1

D75_ADDR = "90:CE:B8:D6:55:0A"
D75_AG_CHANNEL = 1   # HSP audio
D75_CAT_CHANNEL = 2  # Serial Port / CAT


class D75Audio:
    """Manages SCO audio link to D75."""

    def __init__(self, addr):
        self.addr = addr
        self.rfcomm = None
        self.sco = None
        self.sco_mtu = 48
        self._running = False
        self._capture_buf = bytearray()
        self._read_thread = None
        self._frame_count = 0

    def connect(self):
        """Open RFCOMM ch1 + SCO."""
        # RFCOMM for HSP
        self.rfcomm = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
        self.rfcomm.settimeout(5.0)
        self.rfcomm.connect((self.addr, D75_AG_CHANNEL))
        time.sleep(0.3)

        # SCO for audio
        self.sco = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_SCO)
        opt = struct.pack("H", BT_VOICE_CVSD_16BIT)
        self.sco.setsockopt(SOL_BLUETOOTH, BT_VOICE, opt)
        self.sco.settimeout(5.0)
        self.sco.connect(self.addr)

        try:
            opt = self.sco.getsockopt(SOL_SCO, SCO_OPTIONS, 2)
            self.sco_mtu = struct.unpack('H', opt)[0]
        except:
            pass

        self._running = True
        self._frame_count = 0
        self._capture_buf.clear()
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        return True

    def disconnect(self):
        """Tear down audio."""
        self._running = False
        if self._read_thread:
            self._read_thread.join(timeout=2)
            self._read_thread = None
        if self.sco:
            try: self.sco.close()
            except: pass
            self.sco = None
        if self.rfcomm:
            try: self.rfcomm.close()
            except: pass
            self.rfcomm = None

    def _read_loop(self):
        while self._running and self.sco:
            try:
                data = self.sco.recv(self.sco_mtu)
                if not data:
                    break
                self._capture_buf.extend(data)
                self._frame_count += 1
            except socket.timeout:
                continue
            except Exception as e:
                print(f"  [Audio] Read error: {e}")
                break

    @property
    def is_alive(self):
        return self._running and self._read_thread and self._read_thread.is_alive()

    def get_stats(self):
        """Return (frame_count, buffer_bytes, peak_sample)."""
        buf = bytes(self._capture_buf)
        peak = 0
        if len(buf) >= 2:
            samples = struct.unpack(f'<{len(buf)//2}h', buf)
            peak = max(abs(s) for s in samples) if samples else 0
        return self._frame_count, len(buf), peak

    def flush(self):
        self._capture_buf.clear()


class D75CAT:
    """CAT control via RFCOMM ch2."""

    def __init__(self, addr):
        self.addr = addr
        self.sock = None

    def connect(self):
        """Open RFCOMM to CAT channel."""
        import serial
        # Use rfcomm device if available, otherwise raw socket
        if os.path.exists("/dev/rfcomm0"):
            self.sock = serial.Serial("/dev/rfcomm0", 9600, timeout=1,
                                      bytesize=serial.EIGHTBITS,
                                      parity=serial.PARITY_NONE,
                                      stopbits=serial.STOPBITS_ONE,
                                      rtscts=False)
            self.sock.dtr = True
            self._is_serial = True
        else:
            self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
            self.sock.settimeout(3.0)
            self.sock.connect((self.addr, D75_CAT_CHANNEL))
            self._is_serial = False
        time.sleep(0.3)
        return True

    def send(self, cmd):
        """Send CAT command, return response."""
        if self._is_serial:
            self.sock.write(f"{cmd}\r".encode())
            time.sleep(0.3)
            resp = self.sock.read(self.sock.in_waiting or 1)
            return resp.decode(errors='ignore').strip()
        else:
            self.sock.send(f"{cmd}\r".encode())
            time.sleep(0.3)
            try:
                resp = self.sock.recv(1024)
                return resp.decode(errors='ignore').strip()
            except socket.timeout:
                return "(timeout)"

    def disconnect(self):
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock = None


def main():
    print("=" * 60)
    print("D75 Bluetooth Dual Test — CAT + Audio")
    print("=" * 60)
    print()

    # ── Test 1: Simultaneous ──────────────────────────────────
    print("── Test 1: CAT and Audio simultaneously ──")
    print()

    audio = D75Audio(D75_ADDR)
    cat = D75CAT(D75_ADDR)

    # Start audio first
    print("[1] Starting audio...")
    try:
        audio.connect()
        print(f"  Audio connected (SCO MTU={audio.sco_mtu})")
    except Exception as e:
        print(f"  Audio connect failed: {e}")
        audio.disconnect()
        print("  Skipping to Test 2...")
        test1_passed = False
    else:
        time.sleep(1)
        audio.flush()
        fc1, _, _ = audio.get_stats()

        # Now try CAT while audio is running
        print("[1] Starting CAT while audio is active...")
        try:
            cat.connect()
            print("  CAT connected!")

            # Send some CAT commands
            resp = cat.send("ID")
            print(f"  ID -> {resp}")
            resp = cat.send("FQ 0")
            print(f"  FQ 0 -> {resp}")

            time.sleep(1)
            fc2, buf_bytes, peak = audio.get_stats()
            new_frames = fc2 - fc1
            print(f"  Audio during CAT: {new_frames} new frames, peak={peak}")

            test1_passed = (new_frames > 100 and audio.is_alive)
            if test1_passed:
                print("  ✓ Test 1 PASSED — simultaneous operation works!")
            else:
                print(f"  ✗ Test 1 FAILED — audio {'died' if not audio.is_alive else 'stalled'}")
        except Exception as e:
            print(f"  CAT connect failed while audio active: {e}")
            test1_passed = False

        cat.disconnect()
        audio.disconnect()

    print()

    # ── Test 2: Drop/Reconnect ────────────────────────────────
    print("── Test 2: Drop audio → CAT → Reconnect audio ──")
    print()

    audio = D75Audio(D75_ADDR)
    cat = D75CAT(D75_ADDR)

    # Start audio
    print("[2a] Starting audio...")
    try:
        audio.connect()
        print(f"  Audio connected")
        time.sleep(2)
        audio.flush()
        fc1, _, _ = audio.get_stats()
        time.sleep(1)
        fc2, buf_bytes, peak = audio.get_stats()
        print(f"  Audio baseline: {fc2-fc1} frames/sec, peak={peak}")
    except Exception as e:
        print(f"  Audio failed: {e}")
        return 1

    # Drop audio for CAT
    print("[2b] Dropping audio for CAT...")
    audio.disconnect()
    time.sleep(0.5)

    print("[2c] Doing CAT operations...")
    try:
        cat.connect()
        print("  CAT connected")

        resp = cat.send("ID")
        print(f"  ID -> {resp}")
        resp = cat.send("AE")
        print(f"  AE (serial#) -> {resp}")
        resp = cat.send("FQ 0")
        print(f"  FQ 0 -> {resp}")
        resp = cat.send("SQ 0")
        print(f"  SQ 0 -> {resp}")

        cat.disconnect()
        print("  CAT done, disconnected")
    except Exception as e:
        print(f"  CAT failed: {e}")
        cat.disconnect()

    time.sleep(0.5)

    # Bring audio back
    print("[2d] Reconnecting audio...")
    audio = D75Audio(D75_ADDR)
    try:
        audio.connect()
        print(f"  Audio reconnected")
        time.sleep(2)
        audio.flush()
        fc1, _, _ = audio.get_stats()
        time.sleep(1)
        fc2, buf_bytes, peak = audio.get_stats()
        new_frames = fc2 - fc1
        print(f"  Audio after reconnect: {new_frames} frames/sec, peak={peak}")

        if new_frames > 100 and audio.is_alive:
            print("  ✓ Test 2 PASSED — drop/reconnect works!")
        else:
            print(f"  ✗ Test 2 FAILED — audio {'died' if not audio.is_alive else 'stalled'}")
    except Exception as e:
        print(f"  Audio reconnect failed: {e}")
    finally:
        audio.disconnect()

    print()
    print("=" * 60)
    if test1_passed:
        print("Result: Simultaneous CAT+Audio works — no drop needed!")
    else:
        print("Result: Use drop/reconnect pattern for CAT operations")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
