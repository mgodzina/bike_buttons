# USB / BLE character terminal for config and simulated button presses.
import sys
import select
import system_configurator as config
from config_protocol import (
    STATUS_FUEL,
    STATUS_PARKING,
    STATUS_EMERGENCY,
    CONFIRMATION_YES,
    CONFIRMATION_NO,
)


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

    def poll(self, buttons, app, ble=None):
        events = self._stdin_poll.poll(0)
        if events:
            ch = sys.stdin.read(1)
            if ch:
                self._handle_char(ch, buttons, app)

        if ble is not None:
            while ble.any():
                raw = ble.read(1)
                if not raw:
                    break
                try:
                    ch = raw.decode()
                except UnicodeError:
                    continue
                self._handle_char(ch, buttons, app)

    def _parse_devices_line(self, line):
        devices = []
        for ch in line:
            if ch in (" ", ",", ";", "\t"):
                continue
            if ch < "1" or ch > "4":
                print(f"Invalid id character: {repr(ch)} (use 1-4; 0 not allowed in buddy list)")
                return None
            d = int(ch)
            if d not in devices:
                devices.append(d)
        return devices

    def _apply_devices(self, devices, app):
        if 0 in devices:
            print("Device id 0 is not allowed in the buddy/devices list")
            return False
        if app.sender_id != 0 and app.sender_id not in devices:
            print(f"List must include this device id: {app.sender_id}")
            return False
        config.save(app.sender_id, devices)
        self.devices = devices
        self.sender_id = app.sender_id
        self.buddies = [i for i in devices if i != app.sender_id]
        app.set_buddies(self.buddies)
        print(f"Devices: {self.devices}, buddies: {self.buddies}")
        return True

    def _apply_sender_id(self, sender_id, app):
        sender_id = int(sender_id)
        if sender_id not in config.VALID_SENDER_IDS:
            print(f"Invalid sender id: {sender_id} (use 0-4)")
            return False
        devices = [d for d in self.devices if d != 0]
        if sender_id != 0 and sender_id not in devices:
            devices.append(sender_id)
            devices.sort()
        config.save(sender_id, devices)
        self.sender_id = sender_id
        self.devices = devices
        app.sender_id = sender_id
        self.buddies = [i for i in devices if i != sender_id]
        app.set_buddies(self.buddies)
        print(f"Sender ID: {self.sender_id}, devices: {self.devices}, buddies: {self.buddies}")
        if sender_id == 0:
            print("Device is not configured (id 0) — LoRa TX disabled")
        return True

    def _handle_char(self, ch, buttons, app):
        if not ch:
            return

        # ----- devices mode (d) -----
        # Android serial apps usually send '\n' with every Send, so empty Enter
        # after 'd' must NOT leave this mode (otherwise the next '123' is buttons).
        if self._mode == "d":
            if ch in ("\r", "\n"):
                line = self._line.strip()
                if not line:
                    print(f"Devices: {self.devices}, buddies: {app.buddies}")
                    print("Still in devices mode — send e.g. 1,2,3  (or . to cancel)")
                    self._line = ""
                    return
                self._mode = None
                self._line = None
                devices = self._parse_devices_line(line)
                if devices is not None:
                    self._apply_devices(devices, app)
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
                    print(f"Sender ID: {app.sender_id} (0 = not configured)")
                    print("Still in id mode — send 0-4  (or . to cancel)")
                    self._line = ""
                    return
                self._mode = None
                self._line = None
                if len(line) == 1 and "0" <= line <= "4":
                    self._apply_sender_id(int(line), app)
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
            print(f"Devices mode (current {self.devices})")
            print("Send list e.g. 1,2,3 then Enter  (or . to cancel)")
            self._mode = "d"
            self._line = ""
            return
        if ch == "i":
            print(f"Sender id mode (current {app.sender_id}, 0=not configured)")
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
            print(f"Unknown key: {repr(ch)} (press h for help)")
            return
        print(f"Terminal -> {name}")
        buttons.execute_button(app, name)


# ----- State printer class -----

class StatePrinter:
    def __init__(self):
        self.prev_status = None
        self.prev_confirmation = None
        self.prev_waiting_for_ack_from = {}
        self.prev_communication_broken = None

    def print_state(self, app):
        changed = (
            self.prev_status != app.status
            or self.prev_confirmation != app.confirmation
            or self.prev_waiting_for_ack_from != app.waiting_for_ack_from
            or self.prev_communication_broken != app.communication_broken
        )

        if changed:
            status_map = {
                STATUS_FUEL: "FUEL",
                STATUS_PARKING: "PARKING",
                STATUS_EMERGENCY: "EMERGENCY",
                0x00: "NONE",
            }
            confirmation_map = {
                CONFIRMATION_YES: "YES",
                CONFIRMATION_NO: "NO",
                0x00: "NONE",
            }

            status_str = status_map.get(app.status, hex(app.status))
            confirmation_str = confirmation_map.get(app.confirmation, hex(app.confirmation))
            waiting_buddies = [
                str(buddy)
                for buddy, expected in app.waiting_for_ack_from.items()
                if expected is not None
            ]
            # Prepare lines of content
            lines = []
            lines.append(f"Status: {status_str}")
            lines.append(f"Confirmation: {confirmation_str}")
            if app.last_tx_seq is None:
                lines.append("Last Sequence: (none)")
            else:
                lines.append(f"Last Sequence: {app.last_tx_seq}")
            if app.waiting_for_ack():
                lines.append(f"Waiting for ACKs from: {', '.join(waiting_buddies)}")
            else:
                lines.append("Not waiting for any ACKs")
            if app.communication_broken:
                lines.append("COMMUNICATION BROKEN!")

            self.print_box("State Info", lines)
            print("")

        self.prev_status = app.status
        self.prev_confirmation = app.confirmation
        self.prev_waiting_for_ack_from = app.waiting_for_ack_from.copy()
        self.prev_communication_broken = app.communication_broken

    def print_box(self, caption, content):
        # Width matches content lines: ">" + pad + text + pad + "<"
        start_cap = f" START {caption} "
        end_cap = f" END {caption} "
        pad = 1
        content_width = max(len(line) for line in content) if content else 0
        inner = max(len(start_cap), len(end_cap), content_width)
        fill = inner + 2 * pad  # characters between the side markers

        def border(left, right, cap):
            left_dashes = (fill - len(cap)) // 2
            right_dashes = fill - len(cap) - left_dashes
            return f"{left}{'-' * left_dashes}{cap}{'-' * right_dashes}{right}"

        print(border("/", "\\", start_cap))
        for line in content:
            print(f">{' ' * pad}{line}{' ' * (inner - len(line))}{' ' * pad}<")
        print(border("\\", "/", end_cap))
