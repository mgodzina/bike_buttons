Readme generated with help of AI

# Device schematic (PCB / Heltec buddy unit)

Wiring for the Heltec Wireless Stick Lite V3 buddy unit. Firmware pin map lives in `config_hardware.py` and matches this document.

## Onboard Heltec (not on PCB)

These are used by firmware but are **part of the module** — do not place discrete parts or header nets for them on the PCB:

| Function | GPIO | On module |
|----------|------|-----------|
| User / PRG | 0 | Built-in PRG button |
| Info LED | 35 | Built-in LED |

## Power

| Item | Detail |
|------|--------|
| Battery | Akyga **AKY0660**, **LP804050**, **3.7 V**, **1800 mAh**, ~**50 × 40 × 8 mm** |
| Heltec connector | On-module **SH1.25-2** battery jack (unchanged) |
| Power switch | DigiKey **2073-SWS045-030R22TSK-ND** — GCT **SWS045-030R22TSK**, right-angle THT slide, **DPDT**, 0.5 A / 50 V DC |
| Switch role | Interrupts **only the battery positive** lead |

### Battery positive cut (harness)

The pack still plugs into the Heltec battery connector. The **positive wire** of that lead is cut and both ends are soldered to PCB pads that go through the slide switch:

```text
  [ AKY0660 ]
       |+                         |-
       |                          |
    (cut + wire)                  |
       |                          |
       v                          |
   PCB pad BAT_FROM_PACK ----+    |
                             |    |
                    [ SW1 DPDT ]  |
                    (one pole used; other pole optional parallel)
                             |    |
   PCB pad BAT_TO_HELTEC <---+    |
       |                          |
       v                          v
   Heltec SH1.25 BAT+         Heltec SH1.25 BAT- / GND
```

- **Off:** battery positive open → module off (unless USB powered).
- **On:** pack + connected to Heltec BAT+.
- Ground / BAT− stays continuous (not switched).
- Use one DPDT pole for the + path; the second pole may be wired in parallel for lower resistance or left unused.

## External buttons (PCB)

Topology: `Heltec GPIO → tact switch → GND` (firmware internal pull-ups).

Classic **THT tact** switches (e.g. 6×6 mm — footprint TBD at layout).

| Function | GPIO | Heltec header |
|----------|------|----------------|
| YES | 5 | J3.19 |
| NO | 6 | J3.18 |
| CLEAR | 17 | J3.12 |
| FUEL | 18 | J3.9 |
| PARKING | 19 | J3.11 |
| EMERGENCY | 20 | J3.8 |

## External LEDs (PCB)

Topology: `Heltec GPIO → 150 Ω (0.25 W THT, flat) → LED anode → cathode → GND`.

Standard **5 mm THT** LEDs. Series resistors **150 Ω** for now (adjust later for brightness/Vf).

| Function | GPIO | Heltec header |
|----------|------|----------------|
| YES | 21 | J3.10 |
| NO | 1 | J2.18 |
| CLEAR | 2 | J2.19 |
| FUEL | 45 | J2.16 |
| PARKING | 46 | J2.17 |
| EMERGENCY | 3 | J2.20 |

**Note:** GPIO1 (NO LED) is also the Heltec VBAT ADC divider input. An LED load may affect battery-voltage readings if you use that feature later.

## Module mounting

- Heltec **Wireless Stick Lite V3** with **2.54 mm pin headers** soldered on the module.
- PCB has matching **female sockets** (DIP-style) so the module plugs in.
- Headers: **J2** and **J3** (20 pins each) per [Heltec datasheet Rev 1.1](https://resource.heltec.cn/download/Wireless_Stick_Lite_V3/HTIT-WSL_V3(Rev1.1).pdf).

## Block diagram

```text
  buttons (x6) --> | female sockets J2/J3 | --> LEDs (x6) via 150 Ω
                   |   Heltec WSL V3      |
                   |  (PRG + info LED     |
  pack+ --[SW1]--> |   onboard)           | <--> LoRa / WiFi antennas
  pack- ---------> |                      |
                   | USB-C (debug/charge) |
```

## BOM (electrical, current)

| Ref | DigiKey / MPN | Description |
|-----|---------------|-------------|
| U1 | Heltec WSL V3 | ESP32-S3 + SX1262 module (includes PRG + info LED) |
| BT1 | Akyga AKY0660 | 3.7 V 1800 mAh LP804050 |
| SW1 | **2073-SWS045-030R22TSK-ND** / SWS045-030R22TSK | RA THT slide DPDT |
| S1–S6 | TBD | THT tact (YES, NO, CLEAR, FUEL, PARKING, EMERGENCY) |
| R1–R6 | TBD | 150 Ω 0.25 W THT axial |
| D1–D6 | TBD | 5 mm THT LED (same six functions) |
| J_BAT pads | — | Two pads/holes for cut battery + wire |
| — | TBD | 2.54 mm female headers for J2/J3 |

## PCB later

- Exact tact footprint (6×6 vs other)
- LED colors / final resistor values
- Mechanical fit for battery and switch (RA actuator at board edge)
- Keep GPIOs in sync with `config_hardware.py`
