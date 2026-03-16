# D74/75 CAT Control Software

<p align="center">
<img src="./icon.png" />
</p>

This software is for controlling the Kenwood D74/75 via CAT commands from your PC, Mac, or Linux computer.

## How to use
You can connect to your radio either via USB or through Bluetooth. If you plan on using the internal KISS TNC, make sure to set your Interface opposite of your CAT connection. For example, if you are using USB for CAT control, set your KISS interface to Bluetooth, otherwise CAT Control will disconnect from the radio.

The KISS interface can be changed via Menu [983].

## Memory Channels
Memory channels are defaulted in the CAT control software to just the numbers. If you would like add names to your channels, use the additional <i>mnd.py</i> file with the 
argument -p [COMPORT]. This will dump your memory channel names to <i>channel_memory.json</i> and will load next time you start the CAT Control software.

The file can be located in the D75 CAT Control folder in your HOME directory.

You will need to dump the memory channel names if there is any addition, removal, or name change of the channel.

<i>Note: The way that the radio reports the current channel over serial, it is not possible to preload both bands current channel. Once you switch bands, it will load the current band into the CAT Control software.</i>

## Config
Some additional settings can be set in the config.cfg file. The config file can be located in the D75 CAT Control folder in your HOME directory.

| Section | Variable    | Default      | Description |
|---------|-------------|--------------|-------------|
| SERIAL  | port        | <i>empty</i> | Defines the serial COM port.<br/>Autosaved based on your previous connection. |
| SERIAL  | autoconnect | False        | Can be set to <i>True</i> if you wish to attempt a<br/>connection to your last COM port on startup. |
| GPS     | alt_format  | I            | I = Imperial, M = Metric |
| GPS     | spd_format  | I            | I = Imperial, M = Metric |
| DEBUG   | verbose     | False        | Set to True if you want all data sent and received<br/>to print to console. |
|||||

# Compiling an EXE
For Windows users, you can compile a single file EXE. You can build it by running the following command from the main project directory. 

    pyinstaller -y d75_cat_control.spec

Once complete, you will find your EXE in the <i>dist</i> folder.


## Headless TCP Server (D75_CAT.py)

A standalone headless TCP server for remote CAT control, designed to integrate with
[radio-gateway](https://github.com/ukbodypilot/radio-gateway). No GUI or PySide6 required.

### Quick Start

```bash
# Install dependencies
pip3 install pyserial pyserial-asyncio --break-system-packages

# Start the server
python3 D75_CAT.py -c /dev/ttyUSB0 --start-server

# Or install as a systemd service
./install.sh
# Edit config.txt to set your serial port, then:
sudo systemctl start d75-cat
```

### TCP Protocol

Connect to port 9750 (default). Commands use `!command data\n` format:

```
!pass <password>          # Authenticate
!serial connect           # Connect to radio serial port
!serial disconnect        # Disconnect serial
!serial status            # Check serial connection
!cat <CMD> [payload]      # Send raw CAT command (e.g., !cat FQ 0)
!freq [band] [freq]       # Get/set frequency (e.g., !freq 0 145.500)
!vol [level]              # Get/set AF gain (0-255)
!squelch <band> [level]   # Get/set squelch
!channel <band> [ch]      # Get/set memory channel
!ptt on|off               # Transmit/receive (uses TX/RX CAT commands)
!meter [band]             # Read S-meter
!power <band> [level]     # Get/set output power
!mode <band> [mode]       # Get/set band mode
!band [idx]               # Get/set active band (0=A, 1=B)
!dual [0|1]               # Dual/single band mode
!gps [on|off] [pcout]     # GPS control
!bt [on|off]              # Bluetooth control
!info                     # Radio model, serial number, firmware
!dtr [on|off]             # Toggle DTR line
!status                   # Full radio state (JSON)
!exit                     # Disconnect
```

### Configuration (config.txt)

```
baud_rate=9600
device=                   # Serial port or device description
host=0.0.0.0              # TCP bind address
port=9750                 # TCP port (default 9750, avoids conflict with TH9800 on 9800)
password=                 # TCP auth password (blank = no password)
```

### Key Differences from GUI Version

- No PySide6/Qt dependency — pure Python asyncio
- TCP server for remote control (not just local serial)
- Runs headless as a systemd service
- Serial uses hardware flow control (RTS/CTS) — RTS is NOT toggled for PTT
- PTT uses CAT `TX`/`RX` commands directly
- Command queuing ensures one-at-a-time serial communication

### Files

| File | Description |
|------|-------------|
| `D75_CAT.py` | Headless TCP server (main) |
| `config.txt` | Server configuration |
| `run-headless.sh` | Startup script (reads config) |
| `install.sh` | Installs deps + systemd service |
| `requirements-headless.txt` | Python dependencies |

### Systemd Service

```bash
sudo systemctl enable d75-cat    # Start on boot
sudo systemctl start d75-cat     # Start now
sudo systemctl status d75-cat    # Check status
journalctl -u d75-cat -f         # Follow logs
```

## Future Development
As this program is in beta stage of development, there is always room for improvement.

If you come across any issues or wish to have features added, please let me know at <a href="mailto:k7dmg@protonmail.com">k7dmg@protonmail.com</a>.

## License

D75 CAT Control is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

D75 CAT Control is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with D75 CAT Control. If not, see <https://www.gnu.org/licenses/>.