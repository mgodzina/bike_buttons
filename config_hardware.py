"""
Board wiring and low-level hardware constants (Heltec Wireless Stick Lite V3).

Defines GPIO pin numbers, the ``leds`` Pin map, blink timing, and which button
toggles BLE on long press. Instantiating this module creates LED output pins.
"""
from machine import Pin

# ----- Pin assignments -----
# Breadboard / temporary mapping (override final board wiring here).
PIN_LED_INFO = 2
PIN_BTN_USER = 17
PIN_BTN_1 = 5
PIN_BTN_2 = 6
PIN_BTN_3 = 0
PIN_BTN_4 = 18
PIN_BTN_5 = 19
PIN_BTN_6 = 20
PIN_LED_1 = 21   # yes
PIN_LED_2 = 1    # no
PIN_LED_3 = 35   # clear (onboard LED for now)
PIN_LED_4 = 45   # fuel
PIN_LED_5 = 46   # parking
PIN_LED_6 = 3    # emergency

# Final board targets (for reference when leaving breadboard):
# PIN_LED_INFO = 35
# PIN_BTN_USER = 0
# PIN_BTN_3 = 17
# PIN_LED_3 = 2

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
BLE_TOGGLE_BTN = "btn_user"
BLE_TOGGLE_HOLD_MS = 5000
