"""
Board wiring and low-level hardware constants (Heltec Wireless Stick Lite V3).

Defines GPIO pin numbers, the ``leds`` Pin map, blink timing, and which button
toggles BLE on long press. Instantiating this module creates LED output pins.

Pin map matches the final PCB (socketed Heltec headers). USER (GPIO0) and
info LED (GPIO35) are the Heltec onboard PRG button and LED — not PCB parts.
"""
from machine import Pin

# ----- Pin assignments (final PCB / breadboard) -----
PIN_LED_INFO = 35   # Heltec onboard LED
PIN_BTN_USER = 0    # also Heltec PRG; hold at reset may enter download mode
PIN_BTN_1 = 5       # YES
PIN_BTN_2 = 6       # NO
PIN_BTN_3 = 17      # CLEAR
PIN_BTN_4 = 18      # FUEL
PIN_BTN_5 = 19      # PARKING
PIN_BTN_6 = 20      # EMERGENCY
PIN_LED_1 = 21      # yes
PIN_LED_2 = 1       # no
PIN_LED_3 = 2       # clear
PIN_LED_4 = 45      # fuel
PIN_LED_5 = 46      # parking
PIN_LED_6 = 3       # emergency

# ----- LEDs -----
leds = {
    "info": Pin(PIN_LED_INFO, Pin.OUT),
    "yes": Pin(PIN_LED_1, Pin.OUT),
    "no": Pin(PIN_LED_2, Pin.OUT),
    "clear": Pin(PIN_LED_3, Pin.OUT),
    "fuel": Pin(PIN_LED_4, Pin.OUT),
    "parking": Pin(PIN_LED_5, Pin.OUT),
    "emergency": Pin(PIN_LED_6, Pin.OUT),
}

BLINK_SLOW_MS = 500    # waiting for ACK
BLINK_FAST_MS = 150    # communication broken
LED_NOTIFY_MS = 120    # half-period for led_notify() flashes
LED_MODE_STATIC = 0
LED_MODE_BLINK_SLOW = 1
LED_MODE_BLINK_FAST = 2
BLINK_INTERVAL_MS = {
    LED_MODE_BLINK_SLOW: BLINK_SLOW_MS,
    LED_MODE_BLINK_FAST: BLINK_FAST_MS,
}

# ----- BLE toggle (hold button) -----
# Change BLE_TOGGLE_BTN to "btn_1" … "btn_6" to use a different key.
BLE_TOGGLE_BTN = "btn_1"
BLE_TOGGLE_HOLD_MS = 5000
