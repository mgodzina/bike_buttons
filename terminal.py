"""
USB / BLE character terminal for config and simulated button presses.

Also provides ``StatePrinter`` for boxed status dumps when app state changes.
"""
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
    """
    Line/char UI over USB stdin and optional BLE UART.

    Supports button simulation keys, devices list mode (``d``), sender id mode
    (``i``), and BLE toggle (``b``).
    """

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
        """
        Create a terminal with initial identity from flash config.

        :param sender_id: This device id (0 = not configured).
        :type sender_id: int
        :param devices: Full device list including self when configured.
        :type devices: list
        :param on_ble_toggle: Callable invoked for key ``b``, or None.
        :type on_ble_toggle: callable or None
        """
        self.sender_id = sender_id
        self.devices = list(devices)
        self.buddies = [i for i in self.devices if i != self.sender_id]
        self.on_ble_toggle = on_ble_toggle
        self._mode = None  # None | "d" | "i"
        self._line = None
        self._stdin_poll = select.poll()
        self._stdin_poll.register(sys.stdin, select.POLLIN)

    def print_help(self):
        """
        Print the short keybinding help text to the console.
        """
        print("Terminal: 0/u=user 1=YES 2=NO 3=CLEAR 4=FUEL 5=PARKING 6=EMERGENCY")
        print("          d=devices  |  i=sender id  |  b=toggle BLE")
        print("          one-shot: d1,2,3  or  i1")

    def poll(self, buttons, app, ble=None):
        """
        Non-blocking read of USB and optional BLE input characters.

        :param buttons: Button handler used for simulated presses.
        :type buttons: hardware.Buttons
        :param app: Application instance for config and state actions.
        :type app: app.App
        :param ble: Active ``BleTerminal`` session, or None if BLE is off.
        :type ble: ble_terminal.BleTerminal or None
        """
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
        """
        Parse a devices-mode line into a list of unique ids 1-4.

        :param line: Raw input such as ``"1,2,3"`` or ``"123"``.
        :type line: str
        :return: Device id list, or None if the line is invalid.
        :rtype: list or None
        """
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
        """
        Validate, persist, and apply a new devices list.

        :param devices: Proposed device ids (must not include 0).
        :type devices: list
        :param app: Application instance to update buddies on.
        :type app: app.App
        :return: True if saved and applied.
        :rtype: bool
        """
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
        """
        Validate, persist, and apply a new sender id.

        :param sender_id: New id in ``VALID_SENDER_IDS`` (0 disables TX).
        :type sender_id: int
        :param app: Application instance whose ``sender_id`` is updated.
        :type app: app.App
        :return: True if saved and applied.
        :rtype: bool
        """
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
        """
        Handle one input character in normal or config modes.

        :param ch: Single character from USB or BLE.
        :type ch: str
        :param buttons: Button handler for simulated presses.
        :type buttons: hardware.Buttons
        :param app: Application instance for config and actions.
        :type app: app.App
        """
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


class StatePrinter:
    """
    Print a boxed status summary when application state changes.
    """

    def __init__(self):
        """
        Initialize previous-state snapshots used for change detection.
        """
        self.prev_status = None
        self.prev_confirmation = None
        self.prev_waiting_for_ack_from = {}
        self.prev_communication_broken = None

    def print_state(self, app):
        """
        If relevant fields changed, print a boxed state summary.

        :param app: Application instance to read state from.
        :type app: app.App
        """
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
        """
        Print ``content`` lines inside a dashed box with start/end captions.

        Width matches content lines: ``>`` + pad + text + pad + ``<``.

        :param caption: Short title used in START/END border lines.
        :type caption: str
        :param content: Text lines to show inside the box.
        :type content: list
        """
        start_cap = f" START {caption} "
        end_cap = f" END {caption} "
        pad = 1
        content_width = max(len(line) for line in content) if content else 0
        inner = max(len(start_cap), len(end_cap), content_width)
        fill = inner + 2 * pad  # characters between the side markers

        def border(left, right, cap):
            """
            Build one horizontal border line with a centered caption.

            :param left: Left corner character (e.g. ``/`` or ``\\``).
            :type left: str
            :param right: Right corner character.
            :type right: str
            :param cap: Caption text including surrounding spaces.
            :type cap: str
            :return: Complete border line.
            :rtype: str
            """
            left_dashes = (fill - len(cap)) // 2
            right_dashes = fill - len(cap) - left_dashes
            return f"{left}{'-' * left_dashes}{cap}{'-' * right_dashes}{right}"

        print(border("/", "\\", start_cap))
        for line in content:
            print(f">{' ' * pad}{line}{' ' * (inner - len(line))}{' ' * pad}<")
        print(border("\\", "/", end_cap))
