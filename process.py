# Device: LoRa protocol state, ACK/retransmit, and LED rendering.
import time
import lora_msg
from config_hardware import *
from config_protocol import *


class Device:
    def __init__(self, sender_id, buddies, modem):
        self.sender_id = sender_id
        self.buddies = buddies
        self.modem = modem
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
            self.modem.start_recv(continuous=True)
            self.rx_active = True

    def check_rx(self):
        if not self.rx_active:
            return
        result = self.modem.poll_recv()
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
        self.modem.send(msg)

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
