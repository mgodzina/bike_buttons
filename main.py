# required: mpremote mip install lora-sx126x lora-sync
import sys
import select
import time
from machine import Pin
from DIYables_MicroPython_Button import Button
import lora_msg
import config
import ble_terminal
# We are importing mostly constants, so import * is fine here.
from hardware import *
from protocol import *

# ----- Identity / network (config.json on flash) -----
_cfg = config.load()
SENDER_ID = _cfg["sender_id"]
ALL_DEVICE_IDS = _cfg["devices"]
buddies = [i for i in ALL_DEVICE_IDS if i != SENDER_ID]
print(f"Sender ID: {SENDER_ID}, devices: {ALL_DEVICE_IDS}, buddies: {buddies}")
if SENDER_ID == 0:
    print("Sender ID is 0 (not configured). Set with terminal: i then 1-4")
elif SENDER_ID not in ALL_DEVICE_IDS:
    print(f"Warning: sender_id {SENDER_ID} is not in devices {ALL_DEVICE_IDS}")

# ----- Terminal button handling -----
TERMINAL_BUTTONS = {
    "0": "btn_user",
    "u": "btn_user",
    "1": "btn_1",
    "2": "btn_2",
    "3": "btn_3",
    "4": "btn_4",
    "5": "btn_5",
    "6": "btn_6",
}

_stdin_poll = select.poll()
_stdin_poll.register(sys.stdin, select.POLLIN)
_term_mode = None  # None | "d" (devices) | "i" (sender id)
_term_line = None


def parse_devices_line(line):
    """Parse '1,2,3' or '1 2 3' or '123' into a list of device ids (1-4 only)."""
    devices = []
    for ch in line:
        if ch in (" ", ",", ";", "\t"):
            continue
        if ch < "1" or ch > "4":
            print("Invalid id character:", repr(ch), "(use 1-4; 0 not allowed in buddy list)")
            return None
        d = int(ch)
        if d not in devices:
            devices.append(d)
    return devices


def apply_devices(devices, device):
    global ALL_DEVICE_IDS, buddies, SENDER_ID
    if 0 in devices:
        print("Device id 0 is not allowed in the buddy/devices list")
        return False
    if device.sender_id != 0 and device.sender_id not in devices:
        print("List must include this device id:", device.sender_id)
        return False
    config.save(device.sender_id, devices)
    ALL_DEVICE_IDS = devices
    SENDER_ID = device.sender_id
    buddies = [i for i in devices if i != device.sender_id]
    device.set_buddies(buddies)
    print("Devices:", ALL_DEVICE_IDS, "buddies:", buddies)
    return True


def apply_sender_id(sender_id, device):
    global SENDER_ID, ALL_DEVICE_IDS, buddies
    sender_id = int(sender_id)
    if sender_id not in config.VALID_SENDER_IDS:
        print("Invalid sender id:", sender_id, "(use 0-4)")
        return False
    devices = list(ALL_DEVICE_IDS)
    # Never keep 0 in the devices list
    devices = [d for d in devices if d != 0]
    if sender_id != 0 and sender_id not in devices:
        devices.append(sender_id)
        devices.sort()
    config.save(sender_id, devices)
    SENDER_ID = sender_id
    ALL_DEVICE_IDS = devices
    device.sender_id = sender_id
    buddies = [i for i in devices if i != sender_id]
    device.set_buddies(buddies)
    print("Sender ID:", SENDER_ID, "devices:", ALL_DEVICE_IDS, "buddies:", buddies)
    if sender_id == 0:
        print("Device is not configured (id 0) — LoRa TX disabled")
    return True


def handle_terminal_char(ch, buttons, device):
    global _term_mode, _term_line
    if not ch:
        return

    # ----- devices mode (d) -----
    # Android serial apps usually send '\n' with every Send, so empty Enter
    # after 'd' must NOT leave this mode (otherwise the next '123' is buttons).
    if _term_mode == "d":
        if ch in ("\r", "\n"):
            line = _term_line.strip()
            if not line:
                print("Devices:", ALL_DEVICE_IDS, "buddies:", device.buddies)
                print("Still in devices mode — send e.g. 1,2,3  (or . to cancel)")
                _term_line = ""
                return
            _term_mode = None
            _term_line = None
            devices = parse_devices_line(line)
            if devices is not None:
                apply_devices(devices, device)
            return
        if ch in (".", "q", "\x1b"):
            _term_mode = None
            _term_line = None
            print("Devices mode cancelled")
            return
        if ch in ("\x08", "\x7f"):
            _term_line = _term_line[:-1]
            return
        _term_line += ch
        return

    # ----- sender id mode (i) -----
    if _term_mode == "i":
        if ch in ("\r", "\n"):
            line = _term_line.strip()
            if not line:
                print("Sender ID:", device.sender_id, "(0 = not configured)")
                print("Still in id mode — send 0-4  (or . to cancel)")
                _term_line = ""
                return
            _term_mode = None
            _term_line = None
            if len(line) == 1 and "0" <= line <= "4":
                apply_sender_id(int(line), device)
            else:
                print("Send a single id 0-4")
            return
        if ch in (".", "q", "\x1b"):
            _term_mode = None
            _term_line = None
            print("Id mode cancelled")
            return
        if ch in ("\x08", "\x7f"):
            _term_line = _term_line[:-1]
            return
        _term_line += ch
        return

    if ch in ("\r", "\n", " "):
        return
    if ch in ("h", "?"):
        print("Terminal: 0/u=user 1=YES 2=NO 3=CLEAR 4=FUEL 5=PARKING 6=EMERGENCY")
        print("          d=devices  |  i=sender id  |  b=toggle BLE")
        print("          one-shot: d1,2,3  or  i1")
        return
    if ch == "d":
        print("Devices mode (current", ALL_DEVICE_IDS, ")")
        print("Send list e.g. 1,2,3 then Enter  (or . to cancel)")
        _term_mode = "d"
        _term_line = ""
        return
    if ch == "i":
        print("Sender id mode (current", device.sender_id, ", 0=not configured)")
        print("Send 0-4 then Enter  (or . to cancel)")
        _term_mode = "i"
        _term_line = ""
        return
    if ch == "b":
        ble_toggle()
        return
    name = TERMINAL_BUTTONS.get(ch)
    if name is None:
        print("Unknown key:", repr(ch), "(press h for help)")
        return
    print("Terminal ->", name)
    buttons.execute_button(device, name)


def check_terminal(buttons, device, ble=None):
    events = _stdin_poll.poll(0)
    if events:
        ch = sys.stdin.read(1)
        if ch:
            handle_terminal_char(ch, buttons, device)

    if ble is not None:
        while ble.any():
            raw = ble.read(1)
            if not raw:
                break
            try:
                ch = raw.decode()
            except UnicodeError:
                continue
            handle_terminal_char(ch, buttons, device)


# ----- Buttons class -----

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
                ble_toggle()
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


def ble_start():
    global ble
    if ble is not None:
        return
    ble = ble_terminal.start(name="lora-{}".format(SENDER_ID))
    print("BLE on (lora-{})".format(SENDER_ID))
    device.led_notify(3)


def ble_stop():
    global ble
    if ble is None:
        return
    ble.close()
    ble = None
    print("BLE off")
    device.led_notify(2)

def ble_toggle():
    if ble is None:
        ble_start()
    else:
        ble_stop()

# ----- State printer class -----

class StatePrinter:
    def __init__(self):
        self.prev_status = None
        self.prev_confirmation = None
        self.prev_waiting_for_ack_from = {}
        self.prev_communication_broken = None

    def print_state(self, device):
        changed = False
        # Check if status or confirmation changed
        if (
            self.prev_status != device.status
            or self.prev_confirmation != device.confirmation
            or self.prev_waiting_for_ack_from != device.waiting_for_ack_from
            or self.prev_communication_broken != device.is_communication_broken
        ):
            changed = True

        if changed:
            status_map = {
                STATUS_FUEL: "FUEL",
                STATUS_PARKING: "PARKING",
                STATUS_EMERGENCY: "EMERGENCY",
                0x00: "NONE"
            }
            confirmation_map = {
                CONFIRMATION_YES: "YES",
                CONFIRMATION_NO: "NO",
                0x00: "NONE"
            }

            status_str = status_map.get(device.status, hex(device.status))
            confirmation_str = confirmation_map.get(device.confirmation, hex(device.confirmation))
            waiting_buddies = [hex(buddy) for buddy, waiting in device.waiting_for_ack_from.items() if waiting]
            print("\\/\\/\\/------ State Info ------\\/\\/\\/")
            print("Status:", status_str)
            print("Confirmation:", confirmation_str)
            print("Last Sequence:", device.seq - 1)
            if device.waiting_for_ack():
                print("Waiting for ACKs from:", ", ".join(waiting_buddies))
            else:
                print("Not waiting for any ACKs")
            if device.is_communication_broken:
                print("COMMUNICATION BROKEN!")
            print("/\\/\\/\\------ END State ------/\\/\\/\\")
            print("")

        # Update previous state
        self.prev_status = device.status
        self.prev_confirmation = device.confirmation
        self.prev_waiting_for_ack_from = device.waiting_for_ack_from.copy()
        self.prev_communication_broken = device.is_communication_broken


# ----- Device class -----
class Device:
    def __init__(self, sender_id, buddies):
        self.sender_id = sender_id
        self.buddies = buddies
        self.status = 0x00
        self.confirmation = 0x00
        self.seq = 1
        self.rx_active = False
        self.is_communication_broken = False
        self.ack_timeout = ACK_TIMEOUT_MS
        self.reset_ack_timeout()
        self.waiting_for_ack_from = {}
        self.reset_waiting_for_ack_from()
        self.waiting_for_clear_ack = False
        self.last_rx_seq = {}  # buddy_id -> last processed seq
        self._pending_tx = None  # reliable STATE/CLEAR retransmit state
        self.led_states = {
            name: {"on": False, "mode": LED_MODE_STATIC, "blink_on": False, "last_toggle": 0}
            for name in leds
        }
        self._led_notify = None  # non-blocking flash sequence

    # --------- Protocol helpers ---------
    @staticmethod
    def seq_is_newer(new, old):
        """True if new should be processed (never seen, or ahead with wraparound)."""
        if old is None:
            return True
        if new == old:
            return False
        return ((new - old) & SEQ_MAX) < SEQ_HALF

    def next_seq(self):
        self.seq = 1 if self.seq >= SEQ_MAX else self.seq + 1

    # --------- Protocol functions ---------
    def reset_waiting_for_ack_from(self):
        self.waiting_for_ack_from = {buddy: False for buddy in self.buddies}
        self.reset_ack_timeout()
        self._pending_tx = None

    def set_buddies(self, buddies):
        self.buddies = buddies
        self.reset_waiting_for_ack_from()

    def waiting_for_ack(self):
        for buddy in self.waiting_for_ack_from:
            if self.waiting_for_ack_from[buddy]:
                return True
        return False

    def set_ack_timeout(self):
        self.ack_timeout_at = time.ticks_add(time.ticks_ms(), self.ack_timeout)

    def reset_ack_timeout(self):
        self.ack_timeout_at = False

    def start_listening(self):
        if not self.rx_active:
            modem.start_recv(continuous=True)
            self.rx_active = True

    def check_rx(self):
        if not self.rx_active:
            return
        result = modem.poll_recv()
        if result and result is not True:
            parsed = lora_msg.unpack(result)
            if parsed:
                buddy_id, sequence, message_type, data = parsed
                print(f"RX from={buddy_id} seq={sequence} type={lora_msg.MSG_TYPE_NAMES.get(message_type)} data={hex(data)} RSSI={result.rssi}")
                if message_type == lora_msg.MSG_TYPE_ACK:
                    self.process_incoming_ack(buddy_id, sequence, data)
                else:
                    self.communication_broken(False)
                    last = self.last_rx_seq.get(buddy_id)
                    if self.seq_is_newer(sequence, last):
                        self.last_rx_seq[buddy_id] = sequence
                        self.process_incoming_message(buddy_id, sequence, message_type, data)
                    else:
                        print(f"Duplicate/old seq={sequence} from={buddy_id} (last={last}) — ACK only")
                    self.send_ACK(sequence)

    def process_incoming_ack(self, buddy_id, sequence, data=0):
        if buddy_id not in self.waiting_for_ack_from:
            return
        expected = self.waiting_for_ack_from[buddy_id]
        # False means already ACKed; anything else must match seq
        if expected is False or expected != sequence:
            return
        self.waiting_for_ack_from[buddy_id] = False
        print(f"ACK received from={buddy_id} seq={sequence} attempt={data}")
        if not self.waiting_for_ack():
            self._pending_tx = None
    def process_incoming_message(self, buddy_id, sequence, message_type, data):
        if message_type == lora_msg.MSG_TYPE_STATE:
            self.set_state(byte=data)
            return
        elif message_type == lora_msg.MSG_TYPE_CLEAR:
            self.clear_state()
            return
        print(f"Unknown message type: {message_type}, ACK send, but message not processed")

    def is_configured(self):
        return self.sender_id != 0

    def _send_packet(self, msg_type, seq, data):
        self.rx_active = False
        msg = lora_msg.pack(self.sender_id, seq, msg_type, data)
        modem.send(msg)

    def _begin_reliable_tx(self, msg_type, data, clear_ack=False):
        """Send STATE/CLEAR and schedule retransmits until ACKed or timeout."""
        if not self.is_configured():
            print("Cannot TX: sender_id is 0 (not configured)")
            return
        self.communication_broken(False)
        seq = self.seq
        self._send_packet(msg_type, seq, data)
        type_name = lora_msg.MSG_TYPE_NAMES.get(msg_type, hex(msg_type))
        print(f"TX seq={seq} type={type_name} data={data:02x} (1/{TX_ATTEMPTS})")
        self.waiting_for_clear_ack = clear_ack
        self.expect_ack(seq)
        interval = max(1, self.ack_timeout // TX_ATTEMPTS)
        self._pending_tx = {
            "msg_type": msg_type,
            "seq": seq,
            "data": data,
            "sends_left": TX_ATTEMPTS - 1,
            "attempt": 1,
            "next_send_at": time.ticks_add(time.ticks_ms(), interval),
            "interval": interval,
        }
        self.next_seq()

    def send_state(self):
        self._begin_reliable_tx(
            lora_msg.MSG_TYPE_STATE,
            self.status | self.confirmation,
            clear_ack=False,
        )

    def send_clear(self):
        self._begin_reliable_tx(
            lora_msg.MSG_TYPE_CLEAR,
            0,
            clear_ack=True,
        )

    def send_ACK(self, received_seq):
        if not self.is_configured():
            print("Cannot ACK: sender_id is 0 (not configured)")
            return
        for attempt in range(1, ACK_ATTEMPTS + 1):
            self._send_packet(lora_msg.MSG_TYPE_ACK, received_seq, attempt)
            print(f"TX type=ACK seq={received_seq} attempt={attempt}/{ACK_ATTEMPTS}")

    def expect_ack(self, seq):
        self.waiting_for_ack_from = {buddy: seq for buddy in self.buddies}
        self.set_ack_timeout()

    def check_retransmit(self):
        """Resend pending STATE/CLEAR while still waiting for ACKs."""
        p = self._pending_tx
        if p is None or not self.waiting_for_ack():
            return
        if p["sends_left"] <= 0:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, p["next_send_at"]) < 0:
            return
        p["attempt"] += 1
        p["sends_left"] -= 1
        self._send_packet(p["msg_type"], p["seq"], p["data"])
        type_name = lora_msg.MSG_TYPE_NAMES.get(p["msg_type"], hex(p["msg_type"]))
        print(f"TX seq={p['seq']} type={type_name} data={p['data']:02x} (retry {p['attempt']}/{TX_ATTEMPTS})")
        p["next_send_at"] = time.ticks_add(now, p["interval"])

    # --------- LED functions ---------
    def led_notify(self, n=3, ms=None):
        """Flash all LEDs n times (non-blocking). Call anytime, e.g. on BLE toggle."""
        if n <= 0:
            return
        interval = LED_NOTIFY_MS if ms is None else ms
        self._led_notify = {
            "left": n * 2,  # on + off per flash
            "lit": False,
            "next_at": time.ticks_ms(),
            "interval": interval,
        }

    def set_led_on(self, led_name):
        self.led_states[led_name]["on"] = True

    def set_led_off(self, led_name):
        self.led_states[led_name]["on"] = False

    def set_all_leds_off(self):
        for name in leds:
            self.set_led_off(name)

    def set_all_leds_on(self):
        for name in leds:
            self.set_led_on(name)

    def update_led_mode(self, led_name):
        if self.is_communication_broken:
            self.led_states[led_name]["mode"] = LED_MODE_BLINK_FAST
        elif self.waiting_for_ack():
            self.led_states[led_name]["mode"] = LED_MODE_BLINK_SLOW
        else:
            self.led_states[led_name]["mode"] = LED_MODE_STATIC

    def update_leds_mode(self):
        for name in leds:
            self.update_led_mode(name)

    def apply_leds(self):
        now = time.ticks_ms()
        # Priority: one-shot notify flash overrides normal LED rendering
        if self._led_notify is not None:
            n = self._led_notify
            if time.ticks_diff(now, n["next_at"]) >= 0:
                n["lit"] = not n["lit"]
                n["left"] -= 1
                n["next_at"] = time.ticks_add(now, n["interval"])
                if n["left"] <= 0:
                    self._led_notify = None
            lit = self._led_notify is not None and self._led_notify["lit"]
            for pin in leds.values():
                pin.on() if lit else pin.off()
            return

        # Shared phase so all LEDs with the same blink speed stay in sync
        blink_lit = {
            mode: ((now // interval) % 2) == 0
            for mode, interval in BLINK_INTERVAL_MS.items()
        }

        for name, pin in leds.items():
            state = self.led_states[name]
            if not state["on"]:
                pin.off()
                continue
            if state["mode"] == LED_MODE_STATIC:
                pin.on()
                continue
            pin.on() if blink_lit.get(state["mode"], False) else pin.off()
    def update_leds_state(self):
        if self._led_notify is not None:
            return
        if self.is_communication_broken:
            return
        self.set_all_leds_off()
        if self.waiting_for_clear_ack:
            self.set_led_on("clear")
            return
        if self.confirmation == CONFIRMATION_YES:
            self.set_led_on("yes")
        elif self.confirmation == CONFIRMATION_NO:
            self.set_led_on("no")
        if self.status == STATUS_FUEL:
            self.set_led_on("fuel")
            self.set_led_on("info")
        elif self.status == STATUS_PARKING:
            self.set_led_on("parking")
        elif self.status == STATUS_EMERGENCY:
            self.set_led_on("emergency")
    # --------- Timer functions ---------
    def check_timers(self):
        if self.waiting_for_ack():
            self.check_retransmit()
            if self.ack_timeout_at and time.ticks_diff(time.ticks_ms(), self.ack_timeout_at) > 0:
                self.clear_state()
                self.communication_broken(True)
                self.reset_waiting_for_ack_from()
                print("Timeout waiting for ACKs")
        elif self.ack_timeout_at:
            # all ACKs received before timeout
            self.reset_ack_timeout()
            self.waiting_for_clear_ack = False
            self._pending_tx = None
            self.communication_broken(False)

    # --------- State functions ---------
    def clear_state(self):
        self.status = 0x00
        self.confirmation = 0x00
        self.waiting_for_clear_ack = False

    def state_byte(self):
        return self.status | self.confirmation

    def set_state(self, status=None, confirmation=None, byte=None):
        if byte is not None:
            self.status = byte & 0x0F
            self.confirmation = byte & 0xF0
            return
        if status is not None:
            self.status = status
        if confirmation is not None:
            self.confirmation = confirmation

    def communication_broken(self, broken=None):
        if broken is None:
            return self.is_communication_broken
        if self.is_communication_broken == broken:
            return
        print(f"Communication broken: {broken}")
        self.is_communication_broken = broken
        if broken:
            self.set_all_leds_on()


# Initialization
print("Initializing LoRa...")
modem = lora_msg.create_modem()
print("LoRa ready")
device = Device(SENDER_ID, buddies)
device.set_all_leds_off()
buttons = Buttons()
ble = None  # started by holding BLE_TOGGLE_BTN

state_printer = StatePrinter()
print("Terminal: 0/u=user 1=YES 2=NO 3=CLEAR 4=FUEL 5=PARKING 6=EMERGENCY")
print("          d=devices  |  i=sender id (0=not configured)  |  e.g. i1  d1,2,3")
print("BLE: hold", BLE_TOGGLE_BTN, "for", BLE_TOGGLE_HOLD_MS // 1000, "s to toggle")

# Main part of the program

while True:
    buttons.loop()
    buttons.check_buttons(device)
    check_terminal(buttons, device, ble)
    device.start_listening()
    device.check_rx()
    device.check_timers()
    device.update_leds_state()
    device.update_leds_mode()
    device.apply_leds()
    state_printer.print_state(device)
    if ble is not None:
        ble.poll_tx()
