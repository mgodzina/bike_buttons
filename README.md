Readme generated with help of AI

# ESP32 LoRa buddy messenger

Firmware for **Heltec Wireless Stick Lite V3** (ESP32-S3 + SX1262) boards that exchange short LoRa messages between paired “buddy” devices.

Made as personal project to help group motorbike trips without using intercoms.
Proceed at your own risk.

Each unit shows shared **status** (fuel / parking / emergency) and **confirmation** (yes / no) on LEDs, with reliable delivery (ACK + retransmit). Configuration and button simulation work over USB serial or optional BLE UART.

## Features

- LoRa STATE / CLEAR / ACK messaging between devices with ids `1`–`4`
- Physical buttons + matching terminal keys
- LED indication (static, slow blink while waiting for ACK, fast blink on timeout)
- Persistent identity in `config.json` on flash
- BLE Nordic UART for phone setup (hold YES button 5 s, or terminal `b`)

## Hardware

See [schematic.md](schematic.md) for wiring, power, and GPIO map.

**Required now:** Heltec Wireless Stick Lite V3 + Akyga AKY0660 battery (and your breadboard buttons/LEDs). Specific LED/button part numbers come later for PCB design.

## Flash / upload

1. Install [MicroPython](https://micropython.org/download/) for ESP32-S3 on the Heltec.
2. Copy this project to the board (e.g. MicroPython workbench, `mpremote cp -r . :`).
3. Include `lib/` (vendored `lora` driver + button library). No separate `mip install` is required for LoRa.

On first boot, missing `config.json` is created with `sender_id: 0` (not configured).

## Configuration

Identity lives in flash as `config.json`:

```json
{"sender_id": 1, "devices": [1, 2]}
```

| Field | Meaning |
|--------|---------|
| `sender_id` | This device (`1`–`4`). `0` = not configured (LoRa TX disabled). |
| `devices` | All nodes in the group (must include this device when configured). Buddies = everyone except self. |

### Serial port (USB)

The Heltec exposes a USB serial port (ESP32-S3 USB-CDC). Use it for the REPL, logs, and the config terminal.

| Setting | Value |
|---------|--------|
| Baud rate | **115200** (default MicroPython REPL; CDC often ignores baud, but set this anyway) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |
| Line ending | LF (`\n`) or CRLF (`\r\n`) — both work |

Examples:

```bash
mpremote connect /dev/ttyUSB0   # or /dev/ttyACM0 on some hosts
# or: screen /dev/ttyUSB0 115200
# or: picocom -b 115200 /dev/ttyUSB0
```

On Windows, pick the COM port shown in Device Manager; same **115200 8N1**, no flow control.

### Terminal keys (USB or BLE)

Connect over USB serial (above), or enable BLE and use a Nordic UART app. Advertising name is `lora-<sender_id>`.

| Key | Action |
|-----|--------|
| `h` / `?` | Help |
| `1`–`6` / `0`/`u` | Simulate buttons (YES, NO, CLEAR, FUEL, PARKING, EMERGENCY, user) |
| `d` then `1,2,3` + Enter | Set devices list (ids `1`–`4` only; `0` not allowed) |
| `i` then `1` + Enter | Set sender id (`0`–`4`) |
| `b` | Toggle BLE |
| `.` / `q` | Cancel devices/id mode |

One-shot examples (send as one line): `d1,2,3` or `i1`.

Empty Enter while in `d` / `i` mode stays in that mode (useful for Android serial apps).

### Typical first-time setup (two boards)

1. On device A: `i` → `1` → Enter, then `d` → `1,2` → Enter
2. On device B: `i` → `2` → Enter, then `d` → `1,2` → Enter
3. Press YES/NO/status buttons on one board; the other should update LEDs and exchange ACKs.

Pins and BLE hold button are defined in `config_hardware.py` (breadboard map today; final board targets are commented there).

## Project layout

| File / dir | Role |
|------------|------|
| `main.py` | Boot wiring + main loop |
| `app.py` | LoRa protocol, ACK/retransmit, LEDs |
| `hardware.py` | Buttons |
| `terminal.py` | USB/BLE config UI + state printer |
| `ble_terminal.py` | BLE UART session |
| `lora_msg.py` | Packet format + modem factory |
| `system_configurator.py` | `config.json` load/save |
| `config_hardware.py` / `config_protocol.py` | Pins and protocol constants |
| `lib/` | Vendored LoRa + button libraries |

## AI Disclamer

This project was made using help of LLMs (AIs). In fact I used the oportunity to use LLM
as much as possible to learn it. Project was made for my private use, and quality
of the code can be tragic.

## License / third-party

LoRa drivers under `lib/lora/` come from [micropython-lib](https://github.com/micropython/micropython-lib) (`lora`, `lora-sync`, `lora-sx126x`). Button handling uses DIYables MicroPython Button under `lib/DIYables_MicroPython_Button/`.
