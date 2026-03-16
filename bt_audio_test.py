#!/usr/bin/env python3
"""
bt_audio_test.py — Test Bluetooth HFP audio with TH-D75.

The D75 acts as AG (Audio Gateway). The Pi acts as HF (Hands-Free).
We establish the HFP Service Level Connection via AT commands on RFCOMM,
then open an SCO socket for bidirectional 8kHz 16-bit mono PCM audio.

Usage: python3 bt_audio_test.py
"""

import socket
import struct
import time
import threading
import sys
import wave
import os

# Bluetooth constants
BTPROTO_RFCOMM = 3
BTPROTO_SCO = 2
SOL_BLUETOOTH = 274
BT_VOICE = 11
BT_VOICE_CVSD_16BIT = 0x0060
BT_VOICE_TRANSPARENT = 0x0003
SOL_SCO = 17
SCO_OPTIONS = 1

D75_ADDR = "90:CE:B8:D6:55:0A"
D75_AG_CHANNEL = 1  # Headset AG is on RFCOMM channel 1

class D75Audio:
    """Connect to TH-D75 as HFP Hands-Free unit and stream SCO audio."""

    def __init__(self, addr, ag_channel=1):
        self.addr = addr
        self.ag_channel = ag_channel
        self.rfcomm = None
        self.sco = None
        self.sco_mtu = 48  # default, will be updated after connect
        self.connected = False
        self._capture_buf = bytearray()
        self._read_thread = None
        self._running = False

    def connect(self):
        """Establish HFP Service Level Connection, then open SCO audio."""
        print(f"[BT] Connecting RFCOMM to {self.addr} channel {self.ag_channel}...")
        self.rfcomm = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
        self.rfcomm.settimeout(5.0)
        self.rfcomm.connect((self.addr, self.ag_channel))
        print("[BT] RFCOMM connected")

        # D75 HSP: just keep RFCOMM open, connect SCO outbound
        # (Don't send AT commands - they cause ERRORs and break the link)
        time.sleep(0.5)
        print("[BT] RFCOMM established, connecting SCO directly...")
        time.sleep(0.5)

        # Now open SCO for audio
        self._connect_sco()
        return self.connected

    def open_cat_serial(self, port="/dev/rfcomm0", baudrate=9600):
        """Open CAT serial connection to send radio commands."""
        import serial
        self.cat = serial.Serial(port, baudrate, timeout=1,
                                 bytesize=serial.EIGHTBITS,
                                 parity=serial.PARITY_NONE,
                                 stopbits=serial.STOPBITS_ONE,
                                 rtscts=False)  # RFCOMM, no hw flow
        self.cat.dtr = True
        time.sleep(0.5)
        # Enable auto-feedback
        self.cat.write(b"AI 1\r")
        time.sleep(0.2)
        resp = self.cat.read(self.cat.in_waiting or 1)
        print(f"[CAT] Connected, AI response: {resp}")
        return True

    def cat_command(self, cmd):
        """Send a CAT command and read response."""
        if not hasattr(self, 'cat') or not self.cat:
            return None
        self.cat.write(f"{cmd}\r".encode())
        time.sleep(0.3)
        resp = self.cat.read(self.cat.in_waiting or 1)
        text = resp.decode(errors='ignore').strip()
        print(f"[CAT] {cmd} -> {text}")
        return text
        return self.connected

    def _at_command(self, cmd):
        """Send AT command and read response."""
        print(f"[AT] TX: {cmd.decode().strip()}")
        self.rfcomm.send(cmd)
        time.sleep(0.3)

        response = b""
        while True:
            try:
                data = self.rfcomm.recv(1024)
                if not data:
                    break
                response += data
                # Check if we got OK or ERROR
                if b"OK" in response or b"ERROR" in response:
                    break
            except socket.timeout:
                break

        for line in response.decode(errors='ignore').strip().split('\r\n'):
            line = line.strip()
            if line:
                print(f"[AT] RX: {line}")
        return response

    def _connect_sco(self):
        """Open SCO socket for audio — outbound connect."""
        print("[BT] Opening SCO audio connection...")
        self.sco = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_SCO)

        # Set voice setting for CVSD 16-bit
        opt = struct.pack("H", BT_VOICE_CVSD_16BIT)
        self.sco.setsockopt(SOL_BLUETOOTH, BT_VOICE, opt)

        self.sco.settimeout(5.0)
        try:
            self.sco.connect(self.addr)
            print(f"[BT] SCO connected to {self.addr}")
        except Exception as e:
            print(f"[BT] SCO connect failed: {e}")
            self.sco.close()
            self.sco = None
            return

        # Get MTU
        try:
            opt = self.sco.getsockopt(SOL_SCO, SCO_OPTIONS, 2)
            mtu = struct.unpack('H', opt)[0]
            self.sco_mtu = mtu
            print(f"[BT] SCO MTU: {mtu}")
        except Exception as e:
            print(f"[BT] Could not get SCO MTU: {e}, using default {self.sco_mtu}")

        self.connected = True
        self._running = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

    def _read_loop(self):
        """Continuously read SCO audio frames."""
        print("[Audio] Read loop started")
        frame_count = 0
        while self._running and self.sco:
            try:
                data = self.sco.recv(self.sco_mtu)
                if not data:
                    break
                self._capture_buf.extend(data)
                frame_count += 1
                if frame_count <= 10:
                    # Show both hex and decoded PCM samples
                    samples = struct.unpack(f'<{len(data)//2}h', data) if len(data) >= 2 else ()
                    print(f"[Audio] Frame {frame_count}: {len(data)} bytes, "
                          f"samples[0:4]={samples[:4]}, "
                          f"hex: {data[:16].hex()}")
                elif frame_count == 11:
                    print("[Audio] (further frames suppressed)")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Audio] Read error: {e}")
                break
        print(f"[Audio] Read loop ended, {frame_count} frames captured")

    def read_audio(self, nbytes=0):
        """Read captured audio from buffer."""
        if nbytes <= 0 or nbytes >= len(self._capture_buf):
            data = bytes(self._capture_buf)
            self._capture_buf.clear()
            return data
        data = bytes(self._capture_buf[:nbytes])
        del self._capture_buf[:nbytes]
        return data

    def write_audio(self, data):
        """Send audio data to D75 via SCO."""
        if not self.sco:
            return False
        try:
            sent = 0
            while sent < len(data):
                chunk = data[sent:sent + self.sco_mtu]
                # Pad if needed
                if len(chunk) < self.sco_mtu:
                    chunk = chunk + b'\x00' * (self.sco_mtu - len(chunk))
                sent += self.sco.send(chunk)
            return True
        except Exception as e:
            print(f"[Audio] Write error: {e}")
            return False

    def close(self):
        """Clean up connections."""
        self._running = False
        if self._read_thread:
            self._read_thread.join(timeout=2)
        if self.sco:
            self.sco.close()
            self.sco = None
        if self.rfcomm:
            self.rfcomm.close()
            self.rfcomm = None
        self.connected = False
        print("[BT] Closed")


def main():
    print("=== D75 Bluetooth Audio Test ===")
    print(f"Target: {D75_ADDR}, AG channel: {D75_AG_CHANNEL}")
    print()

    print("[NOTE] Please open squelch manually on the radio for audio test")
    print()

    # Establish Bluetooth audio
    d75 = D75Audio(D75_ADDR, D75_AG_CHANNEL)

    try:
        if not d75.connect():
            print("Failed to connect")
            return 1

        print()
        print("[Test] Recording 5 seconds of audio...")
        d75.read_audio()  # flush buffer
        time.sleep(5)

        audio_data = d75.read_audio()
        print(f"[Test] Captured {len(audio_data)} bytes of audio")

        if len(audio_data) > 0:
            # Save as WAV file
            wav_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_audio.wav")
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(8000)
                wf.writeframes(audio_data)
            print(f"[Test] Saved to {wav_path}")

            # Quick level analysis
            if len(audio_data) >= 2:
                samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
                peak = max(abs(s) for s in samples)
                rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
                print(f"[Test] Peak: {peak}, RMS: {rms:.1f}")
                if peak == 0:
                    print("[Test] WARNING: All silence — radio may not be receiving")
                elif peak < 100:
                    print("[Test] Very low audio level")
                else:
                    print("[Test] Audio captured successfully!")

        return 0

    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        d75.close()

    return 1


if __name__ == '__main__':
    sys.exit(main())
