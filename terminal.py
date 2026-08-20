# USB / BLE character terminal for config and simulated button presses.
import sys
import select
import system_configurator as config
from config_protocol import *

class Terminal:
    BUTTON_MAP = {
        "0": "btn_user",
        "u": "btn_user",
        "1": "btn_1",
        "2": "btn_2",
        "3": "btn_3",
        "4": "btn_4",
        "5": "btn_5",
        "6": "btn_6",
    }

    def __init__(self, sender_id, devices, on_ble_toggle=None):
        self.sender_id = sender_id
        self.devices = list(devices)
        self.buddies = [i for i in self.devices if i != self.sender_id]
        self.on_ble_toggle = on_ble_toggle
        self._mode = None  # None | "d" | "i"
        self._line = None
        self._stdin_poll = select.poll()
        self._stdin_poll.register(sys.stdin, select.POLLIN)

    def print_help(self):
        print("Terminal: 0/u=user 1=YES 2=NO 3=CLEAR 4=FUEL 5=PARKING 6=EMERGENCY")
        print("          d=devices  |  i=sender id  |  b=toggle BLE")
        print("          one-shot: d1,2,3  or  i1")

    def poll(self, buttons, device, ble=None):
        events = self._stdin_poll.poll(0)
        if events:
            ch = sys.stdin.read(1)
            if ch:
                self._handle_char(ch, buttons, device)

        if ble is not None:
            while ble.any():
                raw = ble.read(1)
                if not raw:
                    break
                try:
                    ch = raw.decode()
                except UnicodeError:
                    continue
                self._handle_char(ch, buttons, device)

    def _parse_devices_line(self, line):
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

    def _apply_devices(self, devices, device):
        if 0 in devices:
            print("Device id 0 is not allowed in the buddy/devices list")
            return False
        if device.sender_id != 0 and device.sender_id not in devices:
            print("List must include this device id:", device.sender_id)
            return False
        config.save(device.sender_id, devices)
        self.devices = devices
        self.sender_id = device.sender_id
        self.buddies = [i for i in devices if i != device.sender_id]
        device.set_buddies(self.buddies)
        print("Devices:", self.devices, "buddies:", self.buddies)
        return True

    def _apply_sender_id(self, sender_id, device):
        sender_id = int(sender_id)
        if sender_id not in config.VALID_SENDER_IDS:
            print("Invalid sender id:", sender_id, "(use 0-4)")
            return False
        devices = [d for d in self.devices if d != 0]
        if sender_id != 0 and sender_id not in devices:
            devices.append(sender_id)
            devices.sort()
        config.save(sender_id, devices)
        self.sender_id = sender_id
        self.devices = devices
        device.sender_id = sender_id
        self.buddies = [i for i in devices if i != sender_id]
        device.set_buddies(self.buddies)
        print("Sender ID:", self.sender_id, "devices:", self.devices, "buddies:", self.buddies)
        if sender_id == 0:
            print("Device is not configured (id 0) — LoRa TX disabled")
        return True

    def _handle_char(self, ch, buttons, device):
        if not ch:
            return

        # ----- devices mode (d) -----
        # Android serial apps usually send '\n' with every Send, so empty Enter
        # after 'd' must NOT leave this mode (otherwise the next '123' is buttons).
        if self._mode == "d":
            if ch in ("\r", "\n"):
                line = self._line.strip()
                if not line:
                    print("Devices:", self.devices, "buddies:", device.buddies)
                    print("Still in devices mode — send e.g. 1,2,3  (or . to cancel)")
                    self._line = ""
                    return
                self._mode = None
                self._line = None
                devices = self._parse_devices_line(line)
                if devices is not None:
                    self._apply_devices(devices, device)
                return
            if ch in (".", "q", "\x1b"):
                self._mode = None
                self._line = None
                print("Devices mode cancelled")
                return
            if ch in ("\x08", "\x7f"):
                self._line = self._line[:-1]
                return
            self._line += ch
            return

        # ----- sender id mode (i) -----
        if self._mode == "i":
            if ch in ("\r", "\n"):
                line = self._line.strip()
                if not line:
                    print("Sender ID:", device.sender_id, "(0 = not configured)")
                    print("Still in id mode — send 0-4  (or . to cancel)")
                    self._line = ""
                    return
                self._mode = None
                self._line = None
                if len(line) == 1 and "0" <= line <= "4":
                    self._apply_sender_id(int(line), device)
                else:
                    print("Send a single id 0-4")
                return
            if ch in (".", "q", "\x1b"):
                self._mode = None
                self._line = None
                print("Id mode cancelled")
                return
            if ch in ("\x08", "\x7f"):
                self._line = self._line[:-1]
                return
            self._line += ch
            return

        if ch in ("\r", "\n", " "):
            return
        if ch in ("h", "?"):
            self.print_help()
            return
        if ch == "d":
            print("Devices mode (current", self.devices, ")")
            print("Send list e.g. 1,2,3 then Enter  (or . to cancel)")
            self._mode = "d"
            self._line = ""
            return
        if ch == "i":
            print("Sender id mode (current", device.sender_id, ", 0=not configured)")
            print("Send 0-4 then Enter  (or . to cancel)")
            self._mode = "i"
            self._line = ""
            return
        if ch == "b":
            if self.on_ble_toggle:
                self.on_ble_toggle()
            return
        name = self.BUTTON_MAP.get(ch)
        if name is None:
            print("Unknown key:", repr(ch), "(press h for help)")
            return
        print("Terminal ->", name)
        buttons.execute_button(device, name)


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