#!/usr/bin/env python3
"""
D75_CAT.py — Headless TCP server for Kenwood D74/D75 CAT control.

Adapted from D75-CAT-Control (Ben Kozlowski, K7DMG) and modeled after
TH9800_CAT.py. Provides a TCP interface for remote CAT control, designed
to integrate with radio-gateway.

Protocol: Text-based. Commands sent as "!command data\n" over TCP.
CAT: Kenwood text protocol — "CMD payload\r" at 9600/8N1/RTS-CTS.

License: GNU GPL v3
"""

import asyncio
import argparse
import datetime
import json
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time

try:
    import serial
    import serial.tools.list_ports
    import serial_asyncio
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip3 install pyserial pyserial-asyncio --break-system-packages")
    sys.exit(1)

# ============================================================================
# CONSTANTS
# ============================================================================

VERSION = "1.1.0"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
CONFIG_DEFAULTS = {
    "baud_rate": "9600",
    "device": "",
    "host": "0.0.0.0",
    "port": "9750",
    "password": "",
    "bt_addr": "",
    "audio_port": "9751",
}

# Kenwood D74/D75 CAT command codes
class CAT:
    SerialNumber    = "AE"
    AFGain          = "AG"
    RealTimeFB      = "AI"
    BandControl     = "BC"
    Beacon          = "BE"
    BatteryLevel    = "BL"
    Bluetooth       = "BT"
    SquelchOpen     = "BY"
    DualSingleBand  = "DL"
    BtnDown         = "DW"
    FrequencyInfo   = "FO"
    Frequency       = "FQ"
    FWVersion       = "FV"
    GPS             = "GP"
    ModelID         = "ID"
    Backlight       = "LC"
    BandMode        = "MD"
    MemChannelFreq  = "ME"
    MemChannel      = "MR"
    OutputPower     = "PC"
    BeaconType      = "PT"
    RX              = "RX"
    S_Meter         = "SM"
    Squelch         = "SQ"
    TNC             = "TN"
    TX              = "TX"
    BtnUp           = "UP"
    MemoryMode      = "VM"

CTCSS_TONES = [
    "67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5",
    "91.5", "94.8", "97.4", "100.0", "103.5", "107.2", "110.9", "114.8",
    "118.8", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2", "151.4",
    "156.7", "162.2", "167.9", "173.8", "179.9", "186.2", "192.8", "203.5",
    "210.7", "218.1", "225.7", "233.6", "241.8", "250.3"
]

DCS_TONES = [
    "023", "025", "026", "031", "032", "036", "043", "047", "051", "053", "054",
    "065", "071", "072", "073", "074", "114", "115", "116", "122", "125", "131",
    "132", "134", "143", "145", "152", "155", "156", "162", "165", "172", "174",
    "205", "212", "223", "225", "226", "243", "244", "245", "246", "251", "252",
    "255", "261", "263", "265", "266", "271", "274", "306", "311", "315", "325",
    "331", "332", "343", "346", "351", "356", "364", "365", "371", "411", "412",
    "413", "423", "431", "432", "445", "446", "452", "454", "455", "462", "464",
    "465", "466", "503", "506", "516", "523", "526", "532", "546", "565", "606",
    "612", "624", "627", "631", "632", "654", "662", "664", "703", "712", "723",
    "731", "732", "734", "743", "754"
]

GPS_SENTENCES = ['$GPRMC', '$GPGGA']

# ============================================================================
# GPS DATA PARSER
# ============================================================================

class GPSData:
    """Parse NMEA GPS sentences from the D74/D75 radio."""

    def __init__(self):
        self.utc_time = ''
        self.pos_status = ''
        self.lat = ''
        self.lat_dir = ''
        self.lon = ''
        self.lon_dir = ''
        self.speed = ''
        self.track = ''
        self.date = ''
        self.mag_var = ''
        self.var_dir = ''
        self.mode_ind = ''
        self.quality = ''
        self.sat_num = ''
        self.hdop = ''
        self.alt = ''
        self.a_units = ''
        self.undulation = ''
        self.u_units = ''
        self.age = ''
        self.station_id = ''

    def parse(self, data):
        gps_arr = data.split(',')
        sentence = gps_arr[0]
        gps_data = gps_arr[1:]

        if sentence == '$GPRMC' and len(gps_data) >= 12:
            self.utc_time = gps_data[0]
            self.pos_status = gps_data[1]
            self.lat = gps_data[2]
            self.lat_dir = gps_data[3]
            self.lon = gps_data[4]
            self.lon_dir = gps_data[5]
            self.speed = gps_data[6]
            self.track = gps_data[7]
            self.date = gps_data[8]
            self.mag_var = gps_data[9]
            self.var_dir = gps_data[10]
            self.mode_ind = gps_data[11].split('*')[0]

        elif sentence == '$GPGGA' and len(gps_data) >= 14:
            self.utc_time = gps_data[0]
            self.lat = gps_data[1]
            self.lat_dir = gps_data[2]
            self.lon = gps_data[3]
            self.lon_dir = gps_data[4]
            self.quality = gps_data[5]
            self.sat_num = gps_data[6]
            self.hdop = gps_data[7]
            self.alt = gps_data[8]
            self.a_units = gps_data[9]
            self.undulation = gps_data[10]
            self.u_units = gps_data[11]
            self.age = gps_data[12]
            self.station_id = gps_data[13].split('*')[0]

    def is_valid(self):
        return self.pos_status == 'A'

    def to_dict(self):
        return {
            'valid': self.is_valid(),
            'lat': self.lat, 'lat_dir': self.lat_dir,
            'lon': self.lon, 'lon_dir': self.lon_dir,
            'alt': self.alt, 'speed': self.speed,
            'sat_num': self.sat_num, 'utc_time': self.utc_time,
        }

# ============================================================================
# CHANNEL FREQUENCY INFO
# ============================================================================

class ChannelFrequency:
    """Parse/serialize the 21-field FO (FrequencyInfo) response."""

    def __init__(self, data):
        self.band = int(data[0])
        self.frequency = str(int(data[1][:4])) + '.' + data[1][4:7]
        self.offset = str(int(data[2][:4])) + '.' + data[2][4:7]
        self.step = data[3]
        self.tx_step = data[4]
        self.mode = data[5]
        self.fine_mode = data[6]
        self.fine_step_size = data[7]
        self.tone_status = data[8] == '1'
        self.ctcss_status = data[9] == '1'
        self.dcs_status = data[10] == '1'
        self.ctcss_dcs_status = data[11] == '1'
        self.reversed = data[12]
        self.shift_direction = data[13]
        self.tone_freq = int(data[14])
        self.ctcss_freq = int(data[15])
        self.dcs_freq = int(data[16])
        try:
            self.cross_encode = int(data[17])
        except (ValueError, IndexError):
            self.cross_encode = 0
        self.urcall = data[18] if len(data) > 18 else ''
        self.dstar_sq_type = data[19] if len(data) > 19 and data[17] != 'D' else ''
        self.dstar_sq_code = data[20] if len(data) > 20 and data[17] != 'D' else ''

    def to_dict(self):
        return {
            'band': self.band, 'frequency': self.frequency,
            'offset': self.offset, 'step': self.step,
            'mode': self.mode, 'tone_status': self.tone_status,
            'ctcss_status': self.ctcss_status, 'dcs_status': self.dcs_status,
            'shift_direction': self.shift_direction,
            'tone_freq': self.tone_freq, 'ctcss_freq': self.ctcss_freq,
            'dcs_freq': self.dcs_freq,
        }

    def to_radio(self):
        data = [''] * 21
        data[0] = str(self.band)
        data[1] = self.frequency.split('.')[0].rjust(4, '0') + self.frequency.split('.')[1].ljust(6, '0')
        data[2] = self.offset.split('.')[0].rjust(4, '0') + self.offset.split('.')[1].ljust(6, '0')
        data[3] = self.step
        data[4] = self.tx_step
        data[5] = self.mode
        data[6] = self.fine_mode
        data[7] = self.fine_step_size
        data[8] = '1' if self.tone_status else '0'
        data[9] = '1' if self.ctcss_status else '0'
        data[10] = '1' if self.dcs_status else '0'
        data[11] = '1' if self.ctcss_dcs_status else '0'
        data[12] = self.reversed
        data[13] = self.shift_direction
        data[14] = str(self.tone_freq).rjust(2, '0')
        data[15] = str(self.ctcss_freq).rjust(2, '0')
        data[16] = str(self.dcs_freq).rjust(3, '0')
        data[17] = str(self.cross_encode)
        data[18] = self.urcall
        data[19] = self.dstar_sq_type
        data[20] = self.dstar_sq_code
        return ','.join(data)

# ============================================================================
# CONFIG MANAGEMENT
# ============================================================================

def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(CONFIG_DEFAULTS)
        return dict(CONFIG_DEFAULTS)
    settings = dict(CONFIG_DEFAULTS)
    with open(CONFIG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key in settings:
                    settings[key] = value.strip()
    return settings

def save_config(settings):
    with open(CONFIG_PATH, "w") as f:
        for key in CONFIG_DEFAULTS:
            f.write(f"{key}={settings.get(key, '')}\n")

# ============================================================================
# RADIO STATE
# ============================================================================

class RadioState:
    """Tracks the current state of the radio, updated from CAT responses."""

    def __init__(self):
        self.serial_number = ''
        self.radio_type = ''
        self.model_id = ''
        self.fw_version = ''
        self.active_band = 0
        self.dual_band = 0
        self.af_gain = 0
        self.backlight = 0
        self.bluetooth = False
        self.gps = [False, False]  # [enabled, pc_output]
        self.transmitting = False
        self.memory_mode = 0
        self.tnc = [0, 0]  # [mode, band]
        self.beacon_type = 0
        self.gps_data = GPSData()
        self.band = {
            0: {'frequency': '', 'mode': 0, 'memory_mode': 0, 'channel': '',
                'squelch': 0, 'power': 0, 's_meter': 0, 'freq_info': None},
            1: {'frequency': '', 'mode': 0, 'memory_mode': 0, 'channel': '',
                'squelch': 0, 'power': 0, 's_meter': 0, 'freq_info': None},
        }

    def to_dict(self):
        d = {
            'serial_number': self.serial_number,
            'radio_type': self.radio_type,
            'model_id': self.model_id,
            'fw_version': self.fw_version,
            'active_band': self.active_band,
            'dual_band': self.dual_band,
            'af_gain': self.af_gain,
            'backlight': self.backlight,
            'bluetooth': self.bluetooth,
            'gps': self.gps,
            'transmitting': self.transmitting,
            'tnc': self.tnc,
            'beacon_type': self.beacon_type,
        }
        for b in (0, 1):
            bd = dict(self.band[b])
            fi = bd.pop('freq_info', None)
            bd['freq_info'] = fi.to_dict() if fi else None
            d[f'band_{b}'] = bd
        if self.gps_data:
            d['gps_data'] = self.gps_data.to_dict()
        return d

# ============================================================================
# SERIAL PROTOCOL
# ============================================================================

class D75Serial:
    """Async serial connection to the D74/D75 radio.

    Supports two connection modes:
      - USB: serial_asyncio on /dev/ttyUSB* with RTS/CTS
      - Bluetooth: raw RFCOMM socket (avoids /dev/rfcomm* which conflicts with SCO audio)
    """

    def __init__(self, verbose=False):
        self.transport = None
        self.protocol = None
        self.verbose = verbose
        self.state = RadioState()
        self._buffer = b''
        self._fo_buffer = b''  # FO responses can arrive fragmented
        self._command_queue = asyncio.Queue()
        self._response_event = asyncio.Event()
        self._last_response = None
        self._connected = False
        self._write_task = None
        self._read_task = None
        self._tcp_clients = []  # list of (reader, writer) for forwarding
        self._last_radio_rx = 0
        self._bt_serial = None  # pyserial on /dev/rfcomm0 (Bluetooth mode)
        self._read_thread = None
        self._loop = None

    async def connect(self, port, baudrate=9600, bt_addr=None):
        """Open serial connection to the radio.

        If bt_addr is provided, uses raw RFCOMM socket to channel 2 instead
        of opening /dev/rfcomm*. This avoids conflicts with SCO audio.
        """
        if bt_addr:
            return await self._connect_bluetooth(bt_addr)
        return await self._connect_serial(port, baudrate)

    async def _connect_serial(self, port, baudrate):
        """Connect via USB serial port."""
        try:
            use_rtscts = not port.startswith('/dev/rfcomm')
            self.transport, self.protocol = await serial_asyncio.create_serial_connection(
                asyncio.get_event_loop(),
                lambda: _SerialProtocol(self),
                port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                rtscts=use_rtscts,
            )
            self._connected = True
            if use_rtscts:
                self.transport.serial.dtr = True
            fc = "RTS/CTS" if use_rtscts else "none (RFCOMM)"
            print(f"[Serial] Connected to {port} @ {baudrate} (8N1, flow={fc})")

            self._write_task = asyncio.create_task(self._command_writer())
            await self._init_radio()
            return True
        except Exception as e:
            print(f"[Serial] Connection failed: {e}")
            return False

    async def bind_rfcomm(self, bt_addr):
        """Bind /dev/rfcomm0 to the BT address without opening serial.

        This establishes the ACL link so audio can connect before serial opens.
        """
        import subprocess
        subprocess.run(['sudo', 'rfcomm', 'bind', '0', bt_addr, '2'],
                       capture_output=True, timeout=5)
        print(f"[Serial] rfcomm0 bound to {bt_addr} ch2")

    async def _connect_bluetooth(self, bt_addr):
        """Connect via pyserial on /dev/rfcomm0 bound to the BT address.

        Uses synchronous pyserial (not serial_asyncio) to avoid conflicts
        with SCO audio. Read loop runs in a thread.
        Call bind_rfcomm() first if audio needs to connect before serial.
        """
        loop = asyncio.get_event_loop()

        # Ensure rfcomm0 is bound (no-op if already bound)
        import subprocess
        subprocess.run(['sudo', 'rfcomm', 'bind', '0', bt_addr, '2'],
                       capture_output=True, timeout=5)

        port = '/dev/rfcomm0'

        def _do_connect():
            import serial as pyserial
            s = pyserial.Serial(port, 9600, timeout=1,
                                bytesize=pyserial.EIGHTBITS,
                                parity=pyserial.PARITY_NONE,
                                stopbits=pyserial.STOPBITS_ONE,
                                rtscts=False)
            return s

        try:
            self._bt_serial = await loop.run_in_executor(None, _do_connect)
            self._connected = True
            self._loop = loop
            self._bt_addr_used = bt_addr
            print(f"[Serial] Connected via Bluetooth {port} to {bt_addr} ch2")

            # Read loop in thread, command writer in asyncio
            self._read_thread = threading.Thread(target=self._bt_serial_read_loop, daemon=True)
            self._read_thread.start()
            self._write_task = asyncio.create_task(self._command_writer())
            await self._init_radio()
            return True
        except Exception as e:
            print(f"[Serial] Bluetooth connection failed: {e}")
            return False

    def _bt_serial_read_loop(self):
        """Read from pyserial BT connection in a thread."""
        while self._connected and self._bt_serial:
            try:
                data = self._bt_serial.read(self._bt_serial.in_waiting or 1)
                if data:
                    # Schedule data processing on the event loop
                    if self._loop:
                        self._loop.call_soon_threadsafe(self._data_received, data)
                    else:
                        self._data_received(data)
            except Exception:
                break

    async def disconnect(self):
        """Close serial connection."""
        self._connected = False
        if self._write_task:
            self._write_task.cancel()
            self._write_task = None
        if self._bt_serial:
            self._bt_serial.close()
            self._bt_serial = None
            if self._read_thread:
                self._read_thread.join(timeout=2)
                self._read_thread = None
        elif self.transport and not self.transport.is_closing():
            try:
                self.transport.serial.dtr = False
            except Exception:
                pass
            self.transport.close()
        self._connected = False
        self._buffer = b''
        self._fo_buffer = b''
        print("[Serial] Disconnected")

    @property
    def connected(self):
        if self._bt_serial:
            return self._connected and self._bt_serial.is_open
        return self._connected and self.transport and not self.transport.is_closing()

    async def send_command(self, cmd, payload=None):
        """Send a CAT command and wait for the response."""
        if not self.connected:
            return None

        if payload is not None:
            data = f"{cmd} {payload}\r".encode('utf-8')
        else:
            data = f"{cmd}\r".encode('utf-8')

        # Queue the command and wait for response
        self._response_event.clear()
        self._last_response = None
        await self._command_queue.put(data)

        # Wait up to 3 seconds for response
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            if self.verbose:
                print(f"[Serial] Timeout waiting for response to: {cmd}")
            return None

        return self._last_response

    async def send_raw(self, text):
        """Send raw text to the radio (no queuing, for simple commands)."""
        if not self.connected:
            return None
        data = f"{text}\r".encode('utf-8')
        self._response_event.clear()
        self._last_response = None
        await self._command_queue.put(data)
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            return None
        return self._last_response

    async def _command_writer(self):
        """Process command queue — sends one command at a time, waits for response."""
        while True:
            try:
                data = await self._command_queue.get()
                if self.verbose:
                    print(f"[Serial] TX: {data}")
                if self._bt_serial:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._bt_serial.write, data)
                else:
                    self.transport.write(data)
                # Wait for response before sending next command
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    if self.verbose:
                        print(f"[Serial] No response for: {data}")
                await asyncio.sleep(0.05)  # small gap between commands
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[Serial] Writer error: {e}")

    def _data_received(self, data):
        """Called by serial protocol when data arrives."""
        self._last_radio_rx = time.monotonic()
        self._buffer += data

        # Process complete lines (terminated by \r)
        while b'\r' in self._buffer:
            line, _, self._buffer = self._buffer.partition(b'\r')
            line = line.strip()
            if not line:
                continue

            # Handle FO response fragmentation (can be < 72 bytes)
            if line.startswith(b'FO') and len(line) < 72:
                self._fo_buffer = line
                continue
            if self._fo_buffer:
                if len(self._fo_buffer) + len(line) <= 80:
                    line = self._fo_buffer + line
                    self._fo_buffer = b''
                else:
                    self._fo_buffer = b''

            try:
                text = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                continue

            if self.verbose:
                print(f"[Serial] RX: {text}")

            # Parse the response and update state
            self._parse_response(text)

            # Signal that a response was received
            self._last_response = text
            self._response_event.set()

            # Forward to TCP clients
            for writer in list(self._tcp_clients):
                try:
                    writer.write(f"{text}\n".encode('utf-8'))
                except Exception:
                    pass

    def _parse_response(self, text):
        """Parse a CAT response and update radio state."""
        # GPS NMEA sentences
        if text.startswith('$'):
            self.state.gps_data.parse(text)
            return

        # Error responses
        if text == '?':
            return  # Invalid command
        if text == 'N':
            return  # Command rejected

        parts = text.split(None, 1)
        cmd = parts[0] if parts else ''
        cmd_data = parts[1].split(',') if len(parts) > 1 else []

        if cmd == CAT.SerialNumber and len(cmd_data) >= 2:
            self.state.serial_number = cmd_data[0]
            self.state.radio_type = cmd_data[1]

        elif cmd == CAT.FWVersion and cmd_data:
            self.state.fw_version = cmd_data[0]

        elif cmd == CAT.ModelID and cmd_data:
            self.state.model_id = cmd_data[0]

        elif cmd == CAT.RealTimeFB and cmd_data:
            pass  # AI response, just acknowledge

        elif cmd == CAT.BandControl and cmd_data:
            self.state.active_band = int(cmd_data[0])

        elif cmd == CAT.BandMode and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            self.state.band[band]['mode'] = int(cmd_data[1])

        elif cmd == CAT.Frequency and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            freq_raw = cmd_data[1]
            freq = str(int(freq_raw[:4])) + "." + freq_raw[4:7]
            self.state.band[band]['frequency'] = freq

        elif cmd == CAT.FrequencyInfo and cmd_data:
            try:
                fi = ChannelFrequency(cmd_data)
                self.state.band[fi.band]['freq_info'] = fi
                freq = fi.frequency
                self.state.band[fi.band]['frequency'] = freq
            except Exception as e:
                if self.verbose:
                    print(f"[Serial] FO parse error: {e}")

        elif cmd == CAT.MemoryMode and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            self.state.band[band]['memory_mode'] = int(cmd_data[1])
            self.state.memory_mode = int(cmd_data[1])

        elif cmd == CAT.TX:
            self.state.transmitting = True

        elif cmd == CAT.RX:
            self.state.transmitting = False

        elif cmd == CAT.S_Meter and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            self.state.band[band]['s_meter'] = int(cmd_data[1])

        elif cmd == CAT.AFGain and cmd_data:
            self.state.af_gain = int(cmd_data[0])

        elif cmd == CAT.MemChannel and cmd_data:
            if len(cmd_data) == 1:
                self.state.band[self.state.active_band]['channel'] = cmd_data[0]
            elif len(cmd_data) >= 2:
                band = int(cmd_data[0])
                self.state.band[band]['channel'] = cmd_data[1] if len(cmd_data) > 1 else ''

        elif cmd == CAT.DualSingleBand and cmd_data:
            self.state.dual_band = int(cmd_data[0])

        elif cmd == CAT.Backlight and cmd_data:
            self.state.backlight = int(cmd_data[0])

        elif cmd == CAT.Bluetooth and cmd_data:
            self.state.bluetooth = int(cmd_data[0]) == 1

        elif cmd == CAT.GPS and len(cmd_data) >= 2:
            self.state.gps = [int(cmd_data[0]) == 1, int(cmd_data[1]) == 1]

        elif cmd == CAT.Squelch and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            self.state.band[band]['squelch'] = int(cmd_data[1])

        elif cmd == CAT.TNC and len(cmd_data) >= 2:
            self.state.tnc = [int(cmd_data[0]), int(cmd_data[1])]

        elif cmd == CAT.BeaconType and cmd_data:
            self.state.beacon_type = int(cmd_data[0])

        elif cmd == CAT.OutputPower and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            self.state.band[band]['power'] = int(cmd_data[1])

        elif cmd == CAT.SquelchOpen and len(cmd_data) >= 2:
            band = int(cmd_data[0])
            if int(cmd_data[1]) == 0:
                self.state.band[band]['s_meter'] = 0

    async def _init_radio(self):
        """Send initialization sequence to query radio state."""
        print("[Serial] Initializing radio...")
        await self.send_command(CAT.SerialNumber)
        await self.send_command(CAT.FWVersion)
        await self.send_command(CAT.ModelID)
        await self.send_command(CAT.RealTimeFB, "1")  # Enable auto-feedback
        await self.send_command(CAT.DualSingleBand)
        await self.send_command(CAT.BandControl)
        await self.send_command(CAT.AFGain)
        await self.send_command(CAT.Backlight)
        await self.send_command(CAT.Bluetooth)
        await self.send_command(CAT.GPS)
        await self.send_command(CAT.TNC)
        await self.send_command(CAT.BeaconType)

        # Per-band queries
        for band in (0, 1):
            b = str(band)
            await self.send_command(CAT.MemoryMode, b)
            await self.send_command(CAT.BandMode, b)
            await self.send_command(CAT.S_Meter, b)
            await self.send_command(CAT.Squelch, b)
            await self.send_command(CAT.OutputPower, b)
            await self.send_command(CAT.FrequencyInfo, b)

        s = self.state
        print(f"[Serial] Radio: {s.model_id} S/N:{s.serial_number} FW:{s.fw_version}")
        for b in (0, 1):
            bd = s.band[b]
            print(f"[Serial]   Band {'A' if b == 0 else 'B'}: {bd['frequency']} MHz, "
                  f"mode={bd['mode']}, sq={bd['squelch']}, pwr={bd['power']}")


class _SerialProtocol(asyncio.Protocol):
    """asyncio Protocol adapter for serial port."""

    def __init__(self, d75serial):
        self._d75 = d75serial

    def connection_made(self, transport):
        self._d75.transport = transport

    def data_received(self, data):
        self._d75._data_received(data)

    def connection_lost(self, exc):
        self._d75._connected = False
        if exc:
            print(f"[Serial] Connection lost: {exc}")
        else:
            print("[Serial] Connection closed")

# ============================================================================
# BLUETOOTH AUDIO
# ============================================================================

# Bluetooth socket constants
BTPROTO_RFCOMM = 3
BTPROTO_SCO = 2
SOL_BLUETOOTH = 274
BT_VOICE = 11
BT_VOICE_CVSD_16BIT = 0x0060
SOL_SCO = 17
SCO_OPTIONS = 1

AUDIO_SAMPLE_RATE = 8000
AUDIO_SAMPLE_WIDTH = 2  # 16-bit
AUDIO_CHANNELS = 1
AUDIO_FRAME_SIZE = 48  # bytes per SCO frame


class AudioManager:
    """Manages Bluetooth HSP audio connection to the D75.

    The D75 exposes two Bluetooth services:
      - RFCOMM ch1: Headset Audio Gateway (HSP) — audio control
      - RFCOMM ch2: Serial Port Profile (SPP) — CAT control (handled by D75Serial)

    Audio flows via SCO (Synchronous Connection-Oriented) link.
    CVSD decoding is done in hardware by the BT controller.
    Result: 8kHz, 16-bit signed LE, mono PCM.
    """

    def __init__(self, bt_addr, verbose=False):
        self.bt_addr = bt_addr
        self.verbose = verbose
        self._rfcomm = None
        self._sco = None
        self._running = False
        self._read_thread = None
        self._capture_buf = bytearray()
        self._buf_lock = threading.Lock()
        self._audio_clients = []  # list of asyncio StreamWriters for audio streaming
        self._loop = None  # asyncio event loop for scheduling from threads
        self._connected = False
        self._frame_count = 0
        self._read_task = None  # asyncio task for SCO read
        self._ckpd_sent = False  # whether AT+CKPD=200 has been sent to activate audio routing

    @property
    def connected(self):
        return self._connected and self._sco is not None

    async def connect(self, send_ckpd=True):
        """Establish HSP RFCOMM + SCO audio link.

        send_ckpd: If True, send AT+CKPD=200 to activate audio routing.
                   Set False if CAT serial is already open (causes cross-channel errors).
        """
        if not self.bt_addr:
            print("[Audio] No Bluetooth address configured")
            return False

        try:
            # Run blocking BT socket ops in executor
            loop = asyncio.get_event_loop()
            self._loop = loop
            ok = await loop.run_in_executor(None, self._connect_blocking, send_ckpd)
            if ok:
                ckpd_status = " (CKPD sent)" if self._ckpd_sent else " (no CKPD)"
                print(f"[Audio] Connected to {self.bt_addr}{ckpd_status}")
            return ok
        except Exception as e:
            print(f"[Audio] Connect failed: {e}")
            return False

    def _connect_blocking(self, send_ckpd=True):
        """Blocking connect — runs in executor thread."""
        # RFCOMM to HSP channel 1
        self._rfcomm = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
        self._rfcomm.settimeout(5.0)
        try:
            self._rfcomm.connect((self.bt_addr, 1))
        except Exception as e:
            print(f"[Audio] RFCOMM connect failed: {e}")
            self._rfcomm.close()
            self._rfcomm = None
            return False

        time.sleep(0.3)

        # SCO must be connected BEFORE sending CKPD (matches working bt_full_test.py order)
        # SCO for audio
        self._sco = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_SCO)
        opt = struct.pack("H", BT_VOICE_CVSD_16BIT)
        self._sco.setsockopt(SOL_BLUETOOTH, BT_VOICE, opt)
        self._sco.settimeout(5.0)

        try:
            self._sco.connect(self.bt_addr)
        except Exception as e:
            print(f"[Audio] SCO connect failed: {e}")
            self._sco.close()
            self._sco = None
            self._rfcomm.close()
            self._rfcomm = None
            return False

        # Get MTU
        try:
            opt = self._sco.getsockopt(SOL_SCO, SCO_OPTIONS, 2)
            mtu = struct.unpack('H', opt)[0]
            if self.verbose:
                print(f"[Audio] SCO MTU: {mtu}")
        except Exception:
            pass

        # AT+CKPD=200 activates audio routing on the D75.
        # Must be sent AFTER SCO is connected. MUST NOT be sent when CAT serial
        # is open — causes cross-channel errors.
        if send_ckpd:
            try:
                self._rfcomm.sendall(b'AT+CKPD=200\r')
                time.sleep(0.5)
                resp = self._rfcomm.recv(256)
                resp_text = resp.decode('utf-8', errors='ignore').strip()
                if self.verbose:
                    print(f"[Audio] CKPD response: {resp_text}")
                self._ckpd_sent = 'OK' in resp_text
                if not self._ckpd_sent:
                    print(f"[Audio] CKPD unexpected response: {resp_text}")
            except Exception as e:
                print(f"[Audio] CKPD failed: {e}")
                self._ckpd_sent = False
        else:
            self._ckpd_sent = False

        self._connected = True
        self._frame_count = 0
        self._running = True

        # Start read loop — threaded (avoids asyncio issues from executor thread)
        self._sco.settimeout(1.0)
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        return True

    async def disconnect(self):
        """Tear down audio connection."""
        self._running = False
        self._connected = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
            self._read_task = None

        if self._read_thread:
            self._read_thread.join(timeout=2)
            self._read_thread = None

        if self._sco:
            try:
                self._sco.close()
            except Exception:
                pass
            self._sco = None

        if self._rfcomm:
            try:
                self._rfcomm.close()
            except Exception:
                pass
            self._rfcomm = None

        # Close audio streaming clients
        for writer in list(self._audio_clients):
            try:
                writer.close()
            except Exception:
                pass
        self._audio_clients.clear()

        print("[Audio] Disconnected")

    def _read_loop(self):
        """Continuously read SCO audio frames (runs in thread)."""
        if self.verbose:
            print("[Audio] Read loop started")

        while self._running and self._sco:
            try:
                data = self._sco.recv(255)
                if not data:
                    break

                self._frame_count += 1

                # Buffer for polling reads
                with self._buf_lock:
                    # Cap buffer at 1MB (~62 seconds of audio)
                    if len(self._capture_buf) > 1_000_000:
                        self._capture_buf = self._capture_buf[-500_000:]
                    self._capture_buf.extend(data)

                # Forward to streaming clients
                if self._audio_clients and self._loop:
                    self._loop.call_soon_threadsafe(
                        self._forward_audio, bytes(data))

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[Audio] Read error: {e}")
                break

        self._connected = False
        if self.verbose:
            print(f"[Audio] Read loop ended ({self._frame_count} frames)")

    async def _async_read_loop(self):
        """Read SCO audio frames via asyncio (non-blocking socket)."""
        if self.verbose:
            print("[Audio] Async read loop started")
        loop = asyncio.get_event_loop()
        while self._running and self._sco:
            try:
                data = await loop.sock_recv(self._sco, 255)
                if not data:
                    break
                self._frame_count += 1
                with self._buf_lock:
                    if len(self._capture_buf) > 1_000_000:
                        self._capture_buf = self._capture_buf[-500_000:]
                    self._capture_buf.extend(data)
                if self._audio_clients:
                    self._forward_audio(bytes(data))
            except (OSError, asyncio.CancelledError):
                break
        self._connected = False
        if self.verbose:
            print(f"[Audio] Async read loop ended ({self._frame_count} frames)")

    def _forward_audio(self, data):
        """Forward audio data to all streaming TCP clients (called from event loop)."""
        for writer in list(self._audio_clients):
            try:
                writer.write(data)
            except Exception:
                self._audio_clients.remove(writer)

    def read_audio(self, nbytes=0):
        """Read buffered audio data. Returns bytes."""
        with self._buf_lock:
            if nbytes <= 0 or nbytes >= len(self._capture_buf):
                data = bytes(self._capture_buf)
                self._capture_buf.clear()
            else:
                data = bytes(self._capture_buf[:nbytes])
                del self._capture_buf[:nbytes]
        return data

    def flush(self):
        """Clear audio buffer."""
        with self._buf_lock:
            self._capture_buf.clear()

    def add_stream_client(self, writer):
        """Add a TCP writer to receive raw audio stream."""
        if writer not in self._audio_clients:
            self._audio_clients.append(writer)

    def remove_stream_client(self, writer):
        """Remove a TCP writer from audio stream."""
        if writer in self._audio_clients:
            self._audio_clients.remove(writer)

    async def write_audio(self, data):
        """Send audio data to the radio via SCO (for TX)."""
        if not self._sco:
            return False
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._write_blocking, data)
            return True
        except Exception as e:
            print(f"[Audio] Write error: {e}")
            return False

    def _write_blocking(self, data):
        """Blocking SCO write — runs in executor."""
        sent = 0
        while sent < len(data):
            chunk = data[sent:sent + AUDIO_FRAME_SIZE]
            if len(chunk) < AUDIO_FRAME_SIZE:
                chunk = chunk + b'\x00' * (AUDIO_FRAME_SIZE - len(chunk))
            sent += self._sco.send(chunk)

    def to_dict(self):
        """Return audio state as dict."""
        buf_len = len(self._capture_buf)
        return {
            'connected': self.connected,
            'bt_addr': self.bt_addr,
            'frame_count': self._frame_count,
            'buffer_bytes': buf_len,
            'buffer_seconds': round(buf_len / (AUDIO_SAMPLE_RATE * AUDIO_SAMPLE_WIDTH), 2),
            'stream_clients': len(self._audio_clients),
            'format': {
                'sample_rate': AUDIO_SAMPLE_RATE,
                'sample_width': AUDIO_SAMPLE_WIDTH,
                'channels': AUDIO_CHANNELS,
                'encoding': 'signed16le',
            },
        }


# ============================================================================
# AUDIO TCP SERVER
# ============================================================================

class AudioTCPServer:
    """Dedicated TCP server for raw audio streaming.

    Clients connect and receive a continuous stream of raw PCM audio
    (8kHz, 16-bit signed LE, mono). No protocol framing — just raw bytes.
    This allows direct piping to aplay, ffmpeg, Mumble, etc.
    """

    def __init__(self, audio_mgr, verbose=False):
        self.audio = audio_mgr
        self.verbose = verbose
        self.server = None

    async def start(self, host='0.0.0.0', port=9751):
        self.server = await asyncio.start_server(
            self._handle_client, host, port,
            reuse_address=True)
        addr = self.server.sockets[0].getsockname()
        print(f"[AudioTCP] Streaming server on {addr[0]}:{addr[1]}")

    async def _handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"[AudioTCP] Client connected: {addr}")

        if not self.audio.connected:
            writer.write(b"ERROR: audio not connected\n")
            await writer.drain()
            writer.close()
            return

        self.audio.add_stream_client(writer)
        try:
            # Keep connection alive until client disconnects
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.audio.remove_stream_client(writer)
            print(f"[AudioTCP] Client disconnected: {addr}")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# ============================================================================
# TCP SERVER
# ============================================================================

class TCPServer:
    """TCP server for remote CAT control."""

    def __init__(self, d75serial, password='', verbose=False, audio=None):
        self.serial = d75serial
        self.audio = audio
        self.password = password
        self.verbose = verbose
        self.server = None
        self.ready = False

    async def start(self, host='0.0.0.0', port=9750):
        self.server = await asyncio.start_server(
            self._handle_client, host, port,
            reuse_address=True)
        addr = self.server.sockets[0].getsockname()
        print(f"[TCP] Server running on {addr[0]}:{addr[1]}")
        self.ready = True
        async with self.server:
            await self.server.serve_forever()

    async def _handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"[TCP] Client connected: {addr}")

        # Per-connection auth state
        logged_in = False
        login_attempts = 0

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break  # Connection closed

                line = data.decode('utf-8', errors='ignore').strip()
                if not line:
                    continue

                # Parse !command format
                if not line.startswith('!'):
                    writer.write(b"Error: commands must start with !\n")
                    await writer.drain()
                    continue

                parts = line[1:].split(None, 1)
                cmd = parts[0].lower() if parts else ''
                cmd_data = parts[1] if len(parts) > 1 else ''

                # Auth check
                if cmd not in ('pass', 'exit') and not logged_in:
                    writer.write(b"Unauthorized\n")
                    await writer.drain()
                    continue

                # Process command
                response = await self._process_cmd(
                    cmd, cmd_data, writer, logged_in, login_attempts)

                if isinstance(response, tuple):
                    # Auth state update
                    response, logged_in, login_attempts = response

                if response == '__close__':
                    break

                if response is not None:
                    writer.write(f"{response}\n".encode('utf-8'))
                    await writer.drain()

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"[TCP] Client error: {e}")
        finally:
            # Remove from forwarding list
            if writer in self.serial._tcp_clients:
                self.serial._tcp_clients.remove(writer)
            print(f"[TCP] Client disconnected: {addr}")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_cmd(self, cmd, data, writer, logged_in, login_attempts):
        """Process a TCP command. Returns response string or (response, logged_in, login_attempts)."""

        if cmd == 'pass':
            if login_attempts > 3:
                return ('Too many login attempts', logged_in, login_attempts)
            if data == self.password:
                # Add to forwarding list so this client gets serial responses
                if writer not in self.serial._tcp_clients:
                    self.serial._tcp_clients.append(writer)
                return ('Login Successful', True, 0)
            else:
                return ('Login Failed', False, login_attempts + 1)

        elif cmd == 'exit':
            return '__close__'

        elif cmd == 'cat':
            # Raw CAT command: !cat FQ 0 or !cat AG
            if not self.serial.connected:
                return 'serial not connected'
            resp = await self.serial.send_raw(data)
            return resp or 'no response'

        elif cmd == 'freq':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) == 2:
                band, freq = parts[0], parts[1]
                # Format frequency: "145.500" -> "0145500000"
                f_arr = freq.split('.')
                freq_str = f_arr[0].rjust(4, '0') + (f_arr[1] if len(f_arr) > 1 else '').ljust(6, '0')
                resp = await self.serial.send_command(CAT.Frequency, f"{band},{freq_str}")
                return resp or 'ok'
            elif len(parts) == 1:
                resp = await self.serial.send_command(CAT.Frequency, parts[0])
                return resp or 'no response'
            else:
                return f"Band A: {self.serial.state.band[0]['frequency']}, Band B: {self.serial.state.band[1]['frequency']}"

        elif cmd == 'vol':
            if not self.serial.connected:
                return 'serial not connected'
            if data:
                level = str(int(data)).rjust(3, '0')
                resp = await self.serial.send_command(CAT.AFGain, level)
                return resp or 'ok'
            else:
                return str(self.serial.state.af_gain)

        elif cmd == 'squelch':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) == 2:
                resp = await self.serial.send_command(CAT.Squelch, f"{parts[0]},{parts[1]}")
                return resp or 'ok'
            elif len(parts) == 1:
                resp = await self.serial.send_command(CAT.Squelch, parts[0])
                return resp or 'no response'
            else:
                return f"A:{self.serial.state.band[0]['squelch']} B:{self.serial.state.band[1]['squelch']}"

        elif cmd == 'channel':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) == 2:
                ch = str(parts[1]).ljust(3, '0')
                resp = await self.serial.send_command(CAT.MemChannel, f"{parts[0]},{ch}")
                return resp or 'ok'
            elif len(parts) == 1:
                resp = await self.serial.send_command(CAT.MemChannel, parts[0])
                return resp or 'no response'
            else:
                return f"A:{self.serial.state.band[0]['channel']} B:{self.serial.state.band[1]['channel']}"

        elif cmd == 'ptt':
            if not self.serial.connected:
                return 'serial not connected'
            action = data.strip().lower() if data else ''
            if action in ('on', 'true', '1'):
                resp = await self.serial.send_command(CAT.TX)
                return resp or 'TX'
            elif action in ('off', 'false', '0'):
                resp = await self.serial.send_command(CAT.RX)
                return resp or 'RX'
            else:
                return 'TX' if self.serial.state.transmitting else 'RX'

        elif cmd == 'meter':
            if not self.serial.connected:
                return 'serial not connected'
            band = data.strip() if data else str(self.serial.state.active_band)
            resp = await self.serial.send_command(CAT.S_Meter, band)
            return resp or 'no response'

        elif cmd == 'power':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) == 2:
                resp = await self.serial.send_command(CAT.OutputPower, f"{parts[0]},{parts[1]}")
                return resp or 'ok'
            elif len(parts) == 1:
                resp = await self.serial.send_command(CAT.OutputPower, parts[0])
                return resp or 'no response'
            else:
                return f"A:{self.serial.state.band[0]['power']} B:{self.serial.state.band[1]['power']}"

        elif cmd == 'mode':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) == 2:
                resp = await self.serial.send_command(CAT.BandMode, f"{parts[0]},{parts[1]}")
                return resp or 'ok'
            elif len(parts) == 1:
                resp = await self.serial.send_command(CAT.BandMode, parts[0])
                return resp or 'no response'
            else:
                return f"A:{self.serial.state.band[0]['mode']} B:{self.serial.state.band[1]['mode']}"

        elif cmd == 'band':
            if not self.serial.connected:
                return 'serial not connected'
            if data:
                resp = await self.serial.send_command(CAT.BandControl, data.strip())
                return resp or 'ok'
            else:
                return str(self.serial.state.active_band)

        elif cmd == 'dual':
            if not self.serial.connected:
                return 'serial not connected'
            if data:
                resp = await self.serial.send_command(CAT.DualSingleBand, data.strip())
                return resp or 'ok'
            else:
                return str(self.serial.state.dual_band)

        elif cmd == 'gps':
            if not self.serial.connected:
                return 'serial not connected'
            parts = data.split() if data else []
            if len(parts) >= 1:
                enabled = '1' if parts[0].lower() in ('on', 'true', '1') else '0'
                pc_out = '1' if len(parts) > 1 and parts[1].lower() in ('on', 'true', '1') else '0'
                resp = await self.serial.send_command(CAT.GPS, f"{enabled},{pc_out}")
                return resp or 'ok'
            else:
                return json.dumps(self.serial.state.gps_data.to_dict())

        elif cmd == 'bt':
            if not self.serial.connected:
                return 'serial not connected'
            if data:
                val = '1' if data.strip().lower() in ('on', 'true', '1') else '0'
                resp = await self.serial.send_command(CAT.Bluetooth, val)
                return resp or 'ok'
            else:
                return str(self.serial.state.bluetooth)

        elif cmd == 'info':
            if not self.serial.connected:
                return 'serial not connected'
            await self.serial.send_command(CAT.ModelID)
            await self.serial.send_command(CAT.SerialNumber)
            await self.serial.send_command(CAT.FWVersion)
            s = self.serial.state
            return f"Model:{s.model_id} S/N:{s.serial_number} FW:{s.fw_version} Type:{s.radio_type}"

        elif cmd == 'dtr':
            if not self.serial.connected:
                return 'serial not connected'
            if data:
                val = data.strip().lower() in ('on', 'true', '1')
                self.serial.transport.serial.dtr = val
                return str(val)
            else:
                return str(self.serial.transport.serial.dtr)

        elif cmd == 'serial':
            action = (data or '').strip().lower()
            if action == 'connect':
                if self.serial.connected:
                    return 'already connected'
                port = getattr(self.serial, '_comport', None)
                baud = getattr(self.serial, '_baudrate', 9600)
                bt = getattr(self.serial, '_bt_addr', '')
                if not port and not bt:
                    return 'no comport or bt_addr configured'
                ok = await self.serial.connect(port, baud, bt_addr=bt or None)
                return 'connected' if ok else 'connect failed'
            elif action == 'disconnect':
                await self.serial.disconnect()
                return 'disconnected'
            elif action == 'status':
                return 'connected' if self.serial.connected else 'disconnected'
            else:
                return 'usage: !serial connect|disconnect|status'

        elif cmd == 'status':
            state = self.serial.state.to_dict()
            if self.audio:
                state['audio'] = self.audio.to_dict()
            return json.dumps(state)

        elif cmd == 'audio':
            if not self.audio:
                return 'audio not configured (set bt_addr in config.txt)'
            action = (data or '').strip().lower()
            if action == 'connect':
                if self.audio.connected:
                    return 'already connected'
                # Send CKPD only when CAT serial is NOT open
                send_ckpd = not self.serial.connected
                ok = await self.audio.connect(send_ckpd=send_ckpd)
                return 'audio connected' if ok else 'audio connect failed'
            elif action == 'disconnect':
                await self.audio.disconnect()
                return 'audio disconnected'
            elif action == 'status':
                return json.dumps(self.audio.to_dict())
            elif action == 'flush':
                self.audio.flush()
                return 'buffer flushed'
            elif action == 'stream':
                # Add this TCP client to raw audio stream
                if not self.audio.connected:
                    return 'audio not connected'
                self.audio.add_stream_client(writer)
                return 'streaming started (raw PCM: 8kHz/16-bit/mono)'
            elif action == 'stop':
                self.audio.remove_stream_client(writer)
                return 'streaming stopped'
            else:
                return 'usage: !audio connect|disconnect|status|flush|stream|stop'

        elif cmd == 'btstart':
            # Full Bluetooth startup: audio+CKPD → bind rfcomm → serial
            # Audio (RFCOMM ch1 + SCO) must connect BEFORE rfcomm bind,
            # because rfcomm bind to ch2 blocks D75 from accepting ch1.
            if not self.audio:
                return 'audio not configured (set bt_addr in config.txt)'
            bt = getattr(self.serial, '_bt_addr', '')
            if not bt:
                return 'no bt_addr configured'
            if self.serial.connected and self.audio.connected:
                return 'already connected (serial + audio)'

            steps = []

            # Step 1: Connect audio with CKPD (must be before rfcomm bind)
            if not self.audio.connected:
                ok = await self.audio.connect(send_ckpd=True)
                steps.append('audio+CKPD' if ok else 'audio FAILED')
                if not ok:
                    return f"btstart partial: {', '.join(steps)}"
                await asyncio.sleep(0.5)

            # Step 2: Bind rfcomm0 (after audio is established)
            await self.serial.bind_rfcomm(bt)
            steps.append('rfcomm bound')
            await asyncio.sleep(0.5)

            # Step 3: Open serial on /dev/rfcomm0
            if not self.serial.connected:
                port = getattr(self.serial, '_comport', '/dev/rfcomm0')
                baud = getattr(self.serial, '_baudrate', 9600)
                ok = await self.serial.connect(port, baud, bt_addr=bt)
                steps.append('serial' if ok else 'serial FAILED')
                if not ok:
                    return f"btstart partial: {', '.join(steps)}"

            return f"btstart OK: {', '.join(steps)}"

        else:
            return f"Unknown command: {cmd}"

# ============================================================================
# MAIN
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description='D75 CAT Control — Headless TCP Server')
    parser.add_argument('-c', '--comport', type=str, help='Serial port (e.g., /dev/ttyUSB0)')
    parser.add_argument('-b', '--baudrate', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('-s', '--start-server', action='store_true', help='Start TCP server')
    parser.add_argument('-p', '--server-password', type=str, default='', help='Server password')
    parser.add_argument('-sH', '--server-host-ip', type=str, default='0.0.0.0', help='Server host')
    parser.add_argument('-sP', '--server-port', type=int, default=9750, help='Server port')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable verbose output')
    parser.add_argument('-l', '--list-comports', action='store_true', help='List available COM ports')
    args = parser.parse_args()

    if args.list_comports:
        for port in serial.tools.list_ports.comports():
            print(f"  {port.device}: {port.description}")
        return

    # Load config for defaults
    settings = load_config()

    comport = args.comport or settings.get('device', '')
    baudrate = args.baudrate or int(settings.get('baud_rate', '9600'))
    host = args.server_host_ip or settings.get('host', '0.0.0.0')
    port = args.server_port or int(settings.get('port', '9750'))
    password = args.server_password or settings.get('password', '')
    verbose = args.debug

    if args.start_server or settings.get('auto_start_server', '').lower() != 'false':
        if not comport:
            print("Error: No serial port specified. Use -c /dev/ttyUSBx or set 'device' in config.txt")
            # List available ports to help
            ports = serial.tools.list_ports.comports()
            if ports:
                print("Available ports:")
                for p in ports:
                    print(f"  {p.device}: {p.description}")
            return

        bt_addr = settings.get('bt_addr', '')
        audio_port = int(settings.get('audio_port', '9751'))

        print(f"D75 CAT Control Server v{VERSION}")
        print(f"  Serial: {comport} @ {baudrate}")
        print(f"  TCP: {host}:{port}")
        if bt_addr:
            print(f"  Bluetooth: {bt_addr}")
            print(f"  Audio TCP: {host}:{audio_port}")

        # Create serial handler
        d75 = D75Serial(verbose=verbose)
        d75._comport = comport
        d75._baudrate = baudrate
        d75._bt_addr = bt_addr  # Use raw BT socket if set

        # Create audio manager (if Bluetooth configured)
        audio = None
        audio_tcp = None
        if bt_addr:
            audio = AudioManager(bt_addr, verbose=verbose)
            audio_tcp = AudioTCPServer(audio, verbose=verbose)

        # Create TCP server
        tcp = TCPServer(d75, password=password, verbose=verbose, audio=audio)

        # Start TCP server task
        tcp_task = asyncio.create_task(tcp.start(host, port))

        # Start audio TCP server if configured
        if audio_tcp:
            await audio_tcp.start(host, audio_port)

        # Wait for TCP server to be ready
        for _ in range(50):
            if tcp.ready:
                break
            await asyncio.sleep(0.1)

        # Don't auto-connect serial — let user connect via !serial connect
        # (avoids init command storm on restart)
        print(f"[TCP] Ready — waiting for !serial connect")
        print(f"  Serial device: {comport} @ {baudrate}")
        if bt_addr:
            print(f"  Audio: !audio connect (or connect to port {audio_port} for raw stream)")

        # SIGTERM handler for clean shutdown
        shutdown_event = asyncio.Event()

        def sigterm_handler(signum, frame):
            print("\nShutdown signal received...")
            shutdown_event.set()

        signal.signal(signal.SIGTERM, sigterm_handler)
        signal.signal(signal.SIGINT, sigterm_handler)

        try:
            await shutdown_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            print("Shutting down...")
            if audio and audio.connected:
                await audio.disconnect()
            if d75.connected:
                if d75.transport:
                    try:
                        d75.transport.serial.dtr = False
                    except Exception:
                        pass
                await d75.disconnect()
            if audio_tcp and audio_tcp.server:
                audio_tcp.server.close()
            if tcp.server:
                tcp.server.close()
            print("Goodbye.")
    else:
        print("Use --start-server to launch the TCP server")
        print("  Example: python3 D75_CAT.py -c /dev/ttyUSB0 --start-server")


if __name__ == '__main__':
    asyncio.run(main())
