# Physical buttons and hold-to-toggle BLE handling.
import time
from machine import Pin
from DIYables_MicroPython_Button import Button
import ble_terminal
from config_hardware import (
    PIN_BTN_USER,
    PIN_BTN_1,
    PIN_BTN_2,
    PIN_BTN_3,
    PIN_BTN_4,
    PIN_BTN_5,
    PIN_BTN_6,
    BLE_TOGGLE_BTN,
    BLE_TOGGLE_HOLD_MS,
)
from config_protocol import (
    CONFIRMATION_YES,
    CONFIRMATION_NO,
    STATUS_FUEL,
    STATUS_PARKING,
    STATUS_EMERGENCY,
)

_BTN_PINS = (
    ("btn_user", PIN_BTN_USER),
    ("btn_1", PIN_BTN_1),
    ("btn_2", PIN_BTN_2),
    ("btn_3", PIN_BTN_3),
    ("btn_4", PIN_BTN_4),
    ("btn_5", PIN_BTN_5),
    ("btn_6", PIN_BTN_6),
)

# Maps button name -> kwargs for App.set_state(**kwargs); btn_3 is CLEAR (special).
_BUTTON_STATE = {
    "btn_1": {"confirmation": CONFIRMATION_YES},
    "btn_2": {"confirmation": CONFIRMATION_NO},
    "btn_4": {"status": STATUS_FUEL},
    "btn_5": {"status": STATUS_PARKING},
    "btn_6": {"status": STATUS_EMERGENCY},
}


class Buttons:
    def __init__(self):
        self._buttons = {
            name: Button(Pin(pin, Pin.IN, Pin.PULL_UP))
            for name, pin in _BTN_PINS
        }
        self._ble_hold_start = None
        self._ble_hold_fired = False

    def loop(self):
        for btn in self._buttons.values():
            btn.loop()

    def check_buttons(self, app):
        self._check_ble_hold(app)
        for name, btn in self._buttons.items():
            if name == BLE_TOGGLE_BTN:
                continue  # short/long press handled in _check_ble_hold
            if btn.is_pressed():
                self.execute_button(app, name)

    def _check_ble_hold(self, app):
        btn = self._buttons[BLE_TOGGLE_BTN]
        pressed = btn.get_state() == btn.pressed_state
        now = time.ticks_ms()
        if pressed:
            if self._ble_hold_start is None:
                self._ble_hold_start = now
                self._ble_hold_fired = False
            elif (
                not self._ble_hold_fired
                and time.ticks_diff(now, self._ble_hold_start) >= BLE_TOGGLE_HOLD_MS
            ):
                ble_terminal.toggle()
                self._ble_hold_fired = True
        else:
            if self._ble_hold_start is not None and not self._ble_hold_fired:
                self.execute_button(app, BLE_TOGGLE_BTN)
            self._ble_hold_start = None
            self._ble_hold_fired = False

    def execute_button(self, app, button_name):
        if button_name == "btn_user":
            print("User button pressed")
            return
        if button_name == "btn_3":
            app.clear_state()
            app.send_clear()
            return
        kwargs = _BUTTON_STATE.get(button_name)
        if kwargs is None:
            print(f"Unknown button: {button_name}")
            return
        app.set_state(**kwargs)
        app.send_state()
