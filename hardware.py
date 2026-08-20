# Physical buttons and hold-to-toggle BLE handling.
import time
from machine import Pin
from DIYables_MicroPython_Button import Button
import ble_terminal
from config_hardware import *
from config_protocol import *


class Buttons:
    def __init__(self):
        self.btn_user = Button(Pin(PIN_BTN_USER, Pin.IN, Pin.PULL_UP))
        self.btn_1 = Button(Pin(PIN_BTN_1, Pin.IN, Pin.PULL_UP))
        self.btn_2 = Button(Pin(PIN_BTN_2, Pin.IN, Pin.PULL_UP))
        self.btn_3 = Button(Pin(PIN_BTN_3, Pin.IN, Pin.PULL_UP))
        self.btn_4 = Button(Pin(PIN_BTN_4, Pin.IN, Pin.PULL_UP))
        self.btn_5 = Button(Pin(PIN_BTN_5, Pin.IN, Pin.PULL_UP))
        self.btn_6 = Button(Pin(PIN_BTN_6, Pin.IN, Pin.PULL_UP))
        self._buttons = {
            "btn_user": self.btn_user,
            "btn_1": self.btn_1,
            "btn_2": self.btn_2,
            "btn_3": self.btn_3,
            "btn_4": self.btn_4,
            "btn_5": self.btn_5,
            "btn_6": self.btn_6,
        }
        self._ble_hold_start = None
        self._ble_hold_fired = False

    def loop(self):
        for btn in self._buttons.values():
            btn.loop()

    def check_buttons(self, device):
        self._check_ble_hold(device)
        for name, btn in self._buttons.items():
            if name == BLE_TOGGLE_BTN:
                continue  # short/long press handled in _check_ble_hold
            if btn.is_pressed():
                self.execute_button(device, name)

    def _check_ble_hold(self, device):
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
                self.execute_button(device, BLE_TOGGLE_BTN)
            self._ble_hold_start = None
            self._ble_hold_fired = False

    def execute_button(self, device, button_name):
        if button_name == "btn_user":
            print("User button pressed")
            return
        if button_name == "btn_1":
            device.set_state(confirmation=CONFIRMATION_YES)
        elif button_name == "btn_2":
            device.set_state(confirmation=CONFIRMATION_NO)
        elif button_name == "btn_3":
            device.clear_state()
            device.send_clear()
            return
        elif button_name == "btn_4":
            device.set_state(status=STATUS_FUEL)
        elif button_name == "btn_5":
            device.set_state(status=STATUS_PARKING)
        elif button_name == "btn_6":
            device.set_state(status=STATUS_EMERGENCY)
        else:
            print("Unknown button:", button_name)
            return
        device.send_state()
