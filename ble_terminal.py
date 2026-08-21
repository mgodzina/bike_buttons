"""
Nordic UART Service (BLE) for phone terminal access.

Session API: ``configure`` / ``start`` / ``stop`` / ``toggle`` / ``get``.
Mirrors ``print`` output to connected centrals when a session is active.
"""

import os
import struct
import bluetooth
from micropython import const

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_WRITE = const(0x0008)
_FLAG_WRITE_NO_RESPONSE = const(0x0004)
_FLAG_NOTIFY = const(0x0010)

_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (
    bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"),
    _FLAG_NOTIFY,
)
_UART_RX = (
    bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"),
    _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE,
)
_UART_SERVICE = (
    _UART_UUID,
    (_UART_TX, _UART_RX),
)

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_APPEARANCE_GENERIC_COMPUTER = const(128)
_ADV_TYPE_APPEARANCE = const(0x19)

# Default ATT MTU is 23 → 20 bytes of payload per notify
_NOTIFY_CHUNK = const(20)
_TX_BUFFER_MAX = const(1024)


def _advertising_payload(name):
    """
    Build a BLE advertising payload including flags, name, and appearance.

    :param name: Device name string (must fit in the 31-byte adv limit).
    :type name: str
    :return: Advertising payload bytes.
    :rtype: bytearray
    :raises ValueError: If the packed payload exceeds 31 bytes.
    """
    payload = bytearray()

    def append(adv_type, value):
        """
        Append one AD structure to the payload.

        :param adv_type: GAP advertising data type byte.
        :type adv_type: int
        :param value: Raw value bytes for this AD field.
        :type value: bytes
        """
        nonlocal payload
        payload += struct.pack("BB", len(value) + 1, adv_type) + value

    append(_ADV_TYPE_FLAGS, struct.pack("B", 0x06))
    if name:
        append(_ADV_TYPE_NAME, name.encode())
    append(_ADV_TYPE_APPEARANCE, struct.pack("<h", _ADV_APPEARANCE_GENERIC_COMPUTER))
    if len(payload) > 31:
        raise ValueError("BLE advertising name too long")
    return payload


class BleTerminal:
    """
    Nordic UART BLE peripheral with RX buffer and queued TX notifies.
    """

    def __init__(self, name="lora-cfg", rxbuf=128):
        """
        Activate BLE, register the UART service, and start advertising.

        :param name: Advertising / device name.
        :type name: str
        :param rxbuf: GATTS write buffer size for the RX characteristic.
        :type rxbuf: int
        """
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)
        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._ble.gatts_set_buffer(self._rx_handle, rxbuf, True)
        self._connections = set()
        self._rx_buffer = bytearray()
        self._tx_buffer = bytearray()
        self._payload = _advertising_payload(name)
        self._name = name
        self._stdout_attached = False
        self._orig_print = None
        self._advertise()
        print("BLE UART advertising as:", name)

    def _irq(self, event, data):
        """
        BLE IRQ handler for connect, disconnect, and GATTS writes.

        :param event: IRQ event code.
        :type event: int
        :param data: Event-specific tuple from the bluetooth stack.
        :type data: tuple
        """
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            print("BLE connected")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.discard(conn_handle)
            self._tx_buffer = bytearray()
            print("BLE disconnected")
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if conn_handle in self._connections and value_handle == self._rx_handle:
                self._rx_buffer += self._ble.gatts_read(self._rx_handle)

    def _advertise(self, interval_us=500000):
        """
        Start or restart GAP advertising with the stored payload.

        :param interval_us: Advertising interval in microseconds.
        :type interval_us: int
        """
        self._ble.gap_advertise(interval_us, adv_data=self._payload)

    def any(self):
        """
        Number of bytes waiting in the RX buffer.

        :return: Pending RX byte count.
        :rtype: int
        """
        return len(self._rx_buffer)

    def read(self, n=None):
        """
        Consume up to ``n`` bytes from the RX buffer.

        :param n: Max bytes to read, or None for the whole buffer.
        :type n: int or None
        :return: Bytes read (may be empty).
        :rtype: bytes
        """
        if n is None:
            n = len(self._rx_buffer)
        if n <= 0:
            return b""
        data = bytes(self._rx_buffer[:n])
        self._rx_buffer = self._rx_buffer[n:]
        return data

    def readinto(self, buf):
        """
        dupterm stream API stub: BLE does not feed REPL input here.

        :param buf: Destination buffer (unused).
        :type buf: bytearray
        :return: Always None (no data).
        :rtype: None
        """
        return None

    def write(self, data):
        """
        Queue text for BLE notify (flushed by ``poll_tx`` from the main loop).

        :param data: String or bytes to send to connected centrals.
        :type data: str or bytes
        :return: Number of bytes accepted (0 if nothing to write).
        :rtype: int
        """
        if not self._connections:
            return len(data) if data else 0
        if isinstance(data, str):
            data = data.encode()
        self._tx_buffer += data
        if len(self._tx_buffer) > _TX_BUFFER_MAX:
            self._tx_buffer = self._tx_buffer[-(_TX_BUFFER_MAX // 2) :]
        return len(data)

    def poll_tx(self):
        """
        Send queued stdout chunks over BLE. Call from the main loop.
        """
        if not self._connections or not self._tx_buffer:
            return
        sent = 0
        while self._tx_buffer and sent < 8:
            chunk = bytes(self._tx_buffer[:_NOTIFY_CHUNK])
            self._tx_buffer = self._tx_buffer[_NOTIFY_CHUNK:]
            for conn_handle in self._connections:
                try:
                    self._ble.gatts_notify(conn_handle, self._tx_handle, chunk)
                except OSError:
                    pass
            sent += 1

    def attach_stdout(self):
        """
        Mirror ``print()`` to BLE without replacing the USB console.

        Prefers a second ``dupterm`` slot; falls back to wrapping ``builtins.print``.
        """
        if self._stdout_attached:
            return
        # Prefer a second dupterm slot so USB (slot 0) stays intact.
        try:
            os.dupterm(self, 1)
            self._stdout_attached = True
            return
        except (TypeError, OSError, AttributeError, ValueError):
            pass
        # Fallback: wrap builtins.print (this port has only one dupterm slot)
        import builtins
        ble = self
        self._orig_print = builtins.print

        def hooked_print(*args, sep=" ", end="\n"):
            """
            Print to the original console and queue the same text for BLE.

            :param args: Values to print.
            :param sep: Separator between values.
            :type sep: str
            :param end: Line ending.
            :type end: str
            """
            self._orig_print(*args, sep=sep, end=end)
            try:
                parts = [str(a) for a in args]
                ble.write(sep.join(parts) + end)
            except Exception:
                pass

        builtins.print = hooked_print
        self._stdout_attached = True

    def close(self):
        """
        Detach stdout mirroring, disconnect centrals, and deactivate BLE.
        """
        if self._stdout_attached:
            try:
                os.dupterm(None, 1)
            except (TypeError, OSError, AttributeError, ValueError):
                pass
            if self._orig_print is not None:
                import builtins
                builtins.print = self._orig_print
        for conn_handle in list(self._connections):
            try:
                self._ble.gap_disconnect(conn_handle)
            except OSError:
                pass
        self._connections.clear()
        self._ble.active(False)


# ----- Session helpers (used by main / hardware / terminal) -----
_instance = None
_name = "lora-cfg"
_on_start = None
_on_stop = None


def configure(name=None, on_start=None, on_stop=None):
    """
    Set advertising name (str or callable) and optional start/stop hooks.

    :param name: Fixed name, or callable returning a name at start time.
    :type name: str or callable or None
    :param on_start: Called after a successful ``start()``, or None.
    :type on_start: callable or None
    :param on_stop: Called after ``stop()``, or None.
    :type on_stop: callable or None
    """
    global _name, _on_start, _on_stop
    if name is not None:
        _name = name
    if on_start is not None:
        _on_start = on_start
    if on_stop is not None:
        _on_stop = on_stop


def _resolve_name(name=None):
    """
    Resolve the advertising name from an override or configured value.

    :param name: Explicit name override, or None to use configured name.
    :type name: str or None
    :return: Advertising name string.
    :rtype: str
    """
    if name is not None:
        return name
    return _name() if callable(_name) else _name


def get():
    """
    Return the active BLE session instance, if any.

    :return: Current ``BleTerminal``, or None if BLE is off.
    :rtype: BleTerminal or None
    """
    return _instance


def start(name=None, mirror_stdout=True):
    """
    Start a BLE UART session if one is not already running.

    :param name: Optional advertising name override.
    :type name: str or None
    :param mirror_stdout: If True, attach print mirroring to BLE.
    :type mirror_stdout: bool
    :return: The active ``BleTerminal`` instance.
    :rtype: BleTerminal
    """
    global _instance
    if _instance is not None:
        return _instance
    use_name = _resolve_name(name)
    _instance = BleTerminal(name=use_name)
    if mirror_stdout:
        _instance.attach_stdout()
    print(f"BLE on ({use_name})")
    if _on_start:
        _on_start()
    return _instance


def stop():
    """
    Stop the active BLE session and run the configured stop hook.
    """
    global _instance
    if _instance is None:
        return
    _instance.close()
    _instance = None
    print("BLE off")
    if _on_stop:
        _on_stop()


def toggle():
    """
    Start BLE if off, otherwise stop it.
    """
    if _instance is None:
        start()
    else:
        stop()
