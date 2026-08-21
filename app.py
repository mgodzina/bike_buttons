"""
LoRa application state machine: reliable messaging, ACK/retransmit, and LEDs.

Owns the buddy protocol on top of ``lora_msg`` and drives LED indication from
status, confirmation, ACK wait, and communication-broken flags.
"""
import time
import lora_msg
from config_hardware import (
    leds,
    LED_NOTIFY_MS,
    LED_MODE_STATIC,
    LED_MODE_BLINK_SLOW,
    LED_MODE_BLINK_FAST,
    BLINK_INTERVAL_MS,
)
from config_protocol import (
    CONFIRMATION_YES,
    CONFIRMATION_NO,
    STATUS_FUEL,
    STATUS_PARKING,
    STATUS_EMERGENCY,
    ACK_TIMEOUT_MS,
    TX_ATTEMPTS,
    ACK_ATTEMPTS,
    SEQ_MAX,
    SEQ_HALF,
)


class App:
    """
    Application node: LoRa TX/RX protocol plus LED rendering.

    Tracks local status/confirmation, sequence numbers, pending reliable TX,
    and per-buddy ACK expectations.
    """

    def __init__(self, sender_id, buddies, modem):
        """
        Create an application instance bound to a LoRa modem.

        :param sender_id: This device id (0 = not configured, TX disabled).
        :type sender_id: int
        :param buddies: Other device ids expected to ACK reliable TX.
        :type buddies: list
        :param modem: SX1262 (or compatible) modem instance.
        :type modem: object
        """
        self.sender_id = sender_id
        self.buddies = buddies
        self.modem = modem
        self.status = 0x00
        self.confirmation = 0x00
        self.seq = 1
        self.last_tx_seq = None
        self.rx_active = False
        self._communication_broken = False
        self.ack_timeout = ACK_TIMEOUT_MS
        self.ack_timeout_at = None
        self.waiting_for_ack_from = {}
        self.reset_waiting_for_ack_from()
        self.waiting_for_clear_ack = False
        self.last_rx_seq = {}  # buddy_id -> last processed seq
        self._pending_tx = None  # reliable STATE/CLEAR retransmit state
        self.led_states = {
            name: {"on": False, "mode": LED_MODE_STATIC}
            for name in leds
        }
        self._led_notify = None  # non-blocking flash sequence

    @property
    def communication_broken(self):
        """
        Whether the last reliable exchange timed out (fast-blink LED mode).

        :return: True if communication is considered broken.
        :rtype: bool
        """
        return self._communication_broken

    @communication_broken.setter
    def communication_broken(self, broken):
        """
        Set or clear the communication-broken flag.

        When set to True, all LEDs are turned on (then blink via mode update).

        :param broken: New broken state.
        :type broken: bool
        """
        if self._communication_broken == broken:
            return
        print(f"Communication broken: {broken}")
        self._communication_broken = broken
        if broken:
            self.set_all_leds_on()

    # --------- Protocol helpers ---------
    @staticmethod
    def seq_is_newer(new, old):
        """
        Decide whether ``new`` should be processed given last seen ``old``.

        Handles 16-bit sequence wraparound using half-range comparison.

        :param new: Incoming sequence number.
        :type new: int
        :param old: Last processed sequence for that buddy, or None if none.
        :type old: int or None
        :return: True if ``new`` is unseen or ahead of ``old``.
        :rtype: bool
        """
        if old is None:
            return True
        if new == old:
            return False
        return ((new - old) & SEQ_MAX) < SEQ_HALF

    def next_seq(self):
        """
        Advance the outbound sequence number (1..SEQ_MAX, then wrap to 1).
        """
        self.seq = 1 if self.seq >= SEQ_MAX else self.seq + 1

    # --------- Protocol functions ---------
    def reset_waiting_for_ack_from(self):
        """
        Clear per-buddy ACK expectations and cancel pending reliable TX.
        """
        self.waiting_for_ack_from = {buddy: None for buddy in self.buddies}
        self.reset_ack_timeout()
        self._pending_tx = None

    def set_buddies(self, buddies):
        """
        Replace the buddy list and reset ACK wait state.

        :param buddies: New list of peer device ids.
        :type buddies: list
        """
        self.buddies = buddies
        self.reset_waiting_for_ack_from()

    def waiting_for_ack(self):
        """
        Check whether any buddy still owes an ACK for the current TX.

        :return: True if at least one expected seq is still pending.
        :rtype: bool
        """
        return any(seq is not None for seq in self.waiting_for_ack_from.values())

    def set_ack_timeout(self):
        """
        Arm the ACK deadline from now using ``self.ack_timeout``.
        """
        self.ack_timeout_at = time.ticks_add(time.ticks_ms(), self.ack_timeout)

    def reset_ack_timeout(self):
        """
        Disarm the ACK deadline.
        """
        self.ack_timeout_at = None

    def start_listening(self):
        """
        Enter continuous LoRa receive if not already listening.

        On modem failure, marks communication broken and leaves RX inactive.
        """
        if self.rx_active:
            return
        try:
            self.modem.start_recv(continuous=True)
            self.rx_active = True
        except Exception as e:
            print(f"LoRa start_recv failed: {e}")
            self.rx_active = False
            self.communication_broken = True

    def check_rx(self):
        """
        Poll the modem once and dispatch ACKs or application messages.

        Duplicate/old sequences still receive an ACK but do not update state.
        """
        if not self.rx_active:
            return
        try:
            result = self.modem.poll_recv()
        except Exception as e:
            print(f"LoRa poll_recv failed: {e}")
            self.rx_active = False
            self.communication_broken = True
            return
        if result and result is not True:
            parsed = lora_msg.unpack(result)
            if parsed:
                buddy_id, sequence, message_type, data = parsed
                type_name = lora_msg.MSG_TYPE_NAMES.get(message_type)
                print(f"RX from={buddy_id} seq={sequence} type={type_name} data={hex(data)} RSSI={result.rssi}")
                if message_type == lora_msg.MSG_TYPE_ACK:
                    self.process_incoming_ack(buddy_id, sequence, data)
                else:
                    self.communication_broken = False
                    last = self.last_rx_seq.get(buddy_id)
                    if self.seq_is_newer(sequence, last):
                        self.last_rx_seq[buddy_id] = sequence
                        self.process_incoming_message(message_type, data)
                    else:
                        print(f"Duplicate/old seq={sequence} from={buddy_id} (last={last}) — ACK only")
                    self.send_ACK(sequence)

    def process_incoming_ack(self, buddy_id, sequence, data=0):
        """
        Handle an ACK from a buddy for an expected sequence.

        :param buddy_id: Sender id of the ACK.
        :type buddy_id: int
        :param sequence: Sequence being acknowledged.
        :type sequence: int
        :param data: ACK attempt number carried in the payload (informational).
        :type data: int
        """
        if buddy_id not in self.waiting_for_ack_from:
            return
        expected = self.waiting_for_ack_from[buddy_id]
        # None means already ACKed / not waiting; otherwise must match seq
        if expected is None or expected != sequence:
            return
        self.waiting_for_ack_from[buddy_id] = None
        print(f"ACK received from={buddy_id} seq={sequence} attempt={data}")
        if not self.waiting_for_ack():
            self._pending_tx = None

    def process_incoming_message(self, message_type, data):
        """
        Apply a non-ACK application message to local state.

        :param message_type: ``MSG_TYPE_STATE``, ``MSG_TYPE_CLEAR``, or other.
        :type message_type: int
        :param data: Payload byte (state nibble packing for STATE).
        :type data: int
        """
        if message_type == lora_msg.MSG_TYPE_STATE:
            self.set_state(byte=data)
            return
        if message_type == lora_msg.MSG_TYPE_CLEAR:
            self.clear_state()
            return
        print(f"Unknown message type: {message_type}, ACK send, but message not processed")

    def is_configured(self):
        """
        Whether this node has a non-zero sender id and may transmit.

        :return: True if ``sender_id`` is not 0.
        :rtype: bool
        """
        return self.sender_id != 0

    def _send_packet(self, msg_type, seq, data):
        """
        Pack and send one LoRa frame; leaves continuous RX until restarted.

        :param msg_type: Message type constant from ``lora_msg``.
        :type msg_type: int
        :param seq: Sequence number for this packet.
        :type seq: int
        :param data: Single payload data byte.
        :type data: int
        """
        self.rx_active = False
        msg = lora_msg.pack(self.sender_id, seq, msg_type, data)
        try:
            self.modem.send(msg)
        except Exception as e:
            print(f"LoRa send failed: {e}")
            self.communication_broken = True

    def _begin_reliable_tx(self, msg_type, data, clear_ack=False):
        """
        Send STATE/CLEAR and schedule retransmits until ACKed or timeout.

        :param msg_type: ``MSG_TYPE_STATE`` or ``MSG_TYPE_CLEAR``.
        :type msg_type: int
        :param data: Payload data byte for the first and retry sends.
        :type data: int
        :param clear_ack: If True, show clear LED while waiting for ACKs.
        :type clear_ack: bool
        """
        if not self.is_configured():
            print("Cannot TX: sender_id is 0 (not configured)")
            return
        if not self.buddies:
            print("No buddies configured — TX will not wait for ACKs")
        self.communication_broken = False
        seq = self.seq
        self.last_tx_seq = seq
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
        """
        Reliably transmit the current status|confirmation state to buddies.
        """
        self._begin_reliable_tx(
            lora_msg.MSG_TYPE_STATE,
            self.status | self.confirmation,
            clear_ack=False,
        )

    def send_clear(self):
        """
        Reliably transmit a CLEAR message to buddies.
        """
        self._begin_reliable_tx(
            lora_msg.MSG_TYPE_CLEAR,
            0,
            clear_ack=True,
        )

    def send_ACK(self, received_seq):
        """
        Send ACK_ATTEMPTS copies of an ACK for ``received_seq``.

        :param received_seq: Sequence number being acknowledged.
        :type received_seq: int
        """
        if not self.is_configured():
            print("Cannot ACK: sender_id is 0 (not configured)")
            return
        for attempt in range(1, ACK_ATTEMPTS + 1):
            self._send_packet(lora_msg.MSG_TYPE_ACK, received_seq, attempt)
            print(f"TX type=ACK seq={received_seq} attempt={attempt}/{ACK_ATTEMPTS}")

    def expect_ack(self, seq):
        """
        Start waiting for each buddy to ACK ``seq`` within the ACK timeout.

        :param seq: Sequence number expected in buddy ACKs.
        :type seq: int
        """
        self.waiting_for_ack_from = {buddy: seq for buddy in self.buddies}
        self.set_ack_timeout()

    def check_retransmit(self):
        """
        Resend pending STATE/CLEAR when the retry interval elapses.
        """
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
        """
        Flash all LEDs ``n`` times (non-blocking).

        Call anytime, e.g. on BLE toggle. Overrides normal LED rendering until done.

        :param n: Number of full on/off flashes.
        :type n: int
        :param ms: Half-period in ms; defaults to ``LED_NOTIFY_MS``.
        :type ms: int or None
        """
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
        """
        Mark a named LED as logically on (rendered by ``apply_leds``).

        :param led_name: Key in ``leds`` (e.g. ``"yes"``, ``"fuel"``).
        :type led_name: str
        """
        self.led_states[led_name]["on"] = True

    def set_led_off(self, led_name):
        """
        Mark a named LED as logically off.

        :param led_name: Key in ``leds``.
        :type led_name: str
        """
        self.led_states[led_name]["on"] = False

    def set_all_leds_off(self):
        """
        Mark every LED as logically off.
        """
        for name in leds:
            self.set_led_off(name)

    def set_all_leds_on(self):
        """
        Mark every LED as logically on.
        """
        for name in leds:
            self.set_led_on(name)

    def update_led_mode(self, led_name):
        """
        Set blink/static mode for one LED from app wait/broken state.

        :param led_name: Key in ``leds``.
        :type led_name: str
        """
        if self.communication_broken:
            self.led_states[led_name]["mode"] = LED_MODE_BLINK_FAST
        elif self.waiting_for_ack():
            self.led_states[led_name]["mode"] = LED_MODE_BLINK_SLOW
        else:
            self.led_states[led_name]["mode"] = LED_MODE_STATIC

    def update_leds_mode(self):
        """
        Refresh blink/static mode for all LEDs.
        """
        for name in leds:
            self.update_led_mode(name)

    def apply_leds(self):
        """
        Drive GPIO from logical LED state, blink phase, or notify sequence.
        """
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
        """
        Map status/confirmation/clear-wait onto which LEDs are logically on.

        Skips updates while a notify flash or communication-broken display is active.
        """
        if self._led_notify is not None:
            return
        if self.communication_broken:
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
        """
        Handle ACK retransmit schedule and ACK timeout / success cleanup.
        """
        if self.waiting_for_ack():
            self.check_retransmit()
            if self.ack_timeout_at is not None and time.ticks_diff(time.ticks_ms(), self.ack_timeout_at) > 0:
                self.clear_state()
                self.communication_broken = True
                self.reset_waiting_for_ack_from()
                print("Timeout waiting for ACKs")
        elif self.ack_timeout_at is not None:
            # all ACKs received before timeout (or no buddies to wait for)
            self.reset_ack_timeout()
            self.waiting_for_clear_ack = False
            self._pending_tx = None
            self.communication_broken = False

    # --------- State functions ---------
    def clear_state(self):
        """
        Clear local status and confirmation (and clear-wait LED flag).
        """
        self.status = 0x00
        self.confirmation = 0x00
        self.waiting_for_clear_ack = False

    def state_byte(self):
        """
        Pack status and confirmation into one payload byte.

        :return: ``status | confirmation``.
        :rtype: int
        """
        return self.status | self.confirmation

    def set_state(self, status=None, confirmation=None, byte=None):
        """
        Update local status and/or confirmation.

        If ``byte`` is given, it overrides and splits into low/high nibbles.

        :param status: New status nibble, or None to leave unchanged.
        :type status: int or None
        :param confirmation: New confirmation nibble, or None to leave unchanged.
        :type confirmation: int or None
        :param byte: Packed state byte (``status | confirmation``).
        :type byte: int or None
        """
        if byte is not None:
            self.status = byte & 0x0F
            self.confirmation = byte & 0xF0
            return
        if status is not None:
            self.status = status
        if confirmation is not None:
            self.confirmation = confirmation
