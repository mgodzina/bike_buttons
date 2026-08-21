"""
LoRa packet pack/unpack and Heltec Wireless Stick Lite V3 modem factory.
"""
import struct
from machine import SPI, Pin
from lora import SX1262

# Heltec Wireless Stick Lite V3 pin mapping
_SPI_ID = 2
_SCK = 9
_MOSI = 10
_MISO = 11
_CS = 8
_RST = 12
_BUSY = 13
_DIO1 = 14
_TCXO_MV = 1800

# Message: sender_id(1) + seq(2) + msg_type(1) + data(1) = 5 bytes
MSG_FMT = ">BHBB"
MSG_SIZE = struct.calcsize(MSG_FMT)

MSG_TYPE_STATE = 0x01
MSG_TYPE_ACK = 0x02
MSG_TYPE_CLEAR = 0x03

MSG_TYPE_NAMES = {
    MSG_TYPE_STATE: "STATE",
    MSG_TYPE_ACK: "ACK",
    MSG_TYPE_CLEAR: "CLEAR",
}


def pack(sender_id, seq, msg_type, data):
    """
    Pack a 5-byte application LoRa frame.

    :param sender_id: Sender device id (1 byte).
    :type sender_id: int
    :param seq: Sequence number (2 bytes, big-endian).
    :type seq: int
    :param msg_type: Message type (STATE / ACK / CLEAR).
    :type msg_type: int
    :param data: Payload data byte.
    :type data: int
    :return: Packed frame bytes.
    :rtype: bytes
    """
    return struct.pack(MSG_FMT, sender_id, seq, msg_type, data)


def unpack(raw):
    """
    Unpack a frame from modem RX bytes.

    :param raw: Received buffer (must be at least ``MSG_SIZE`` bytes).
    :type raw: bytes or bytearray
    :return: ``(sender_id, seq, msg_type, data)``, or None if too short.
    :rtype: tuple or None
    """
    if len(raw) < MSG_SIZE:
        return None
    sender_id, seq, msg_type, data = struct.unpack(MSG_FMT, raw[:MSG_SIZE])
    return sender_id, seq, msg_type, data


def create_modem(freq_khz=868000, sf=7, bw="125", output_power=14):
    """
    Create and configure an SX1262 modem for the Heltec V3 pinout.

    :param freq_khz: RF frequency in kHz.
    :type freq_khz: int
    :param sf: Spreading factor.
    :type sf: int
    :param bw: Bandwidth string accepted by the lora driver (e.g. ``"125"``).
    :type bw: str
    :param output_power: TX power in dBm.
    :type output_power: int
    :return: Configured ``SX1262`` instance.
    :rtype: lora.SX1262
    """
    lora_cfg = {
        "freq_khz": freq_khz,
        "sf": sf,
        "bw": bw,
        "coding_rate": 5,
        "preamble_len": 8,
        "output_power": output_power,
        "crc_en": True,
        "syncword": 0x12,
    }
    spi = SPI(_SPI_ID, baudrate=2_000_000,
              sck=Pin(_SCK), mosi=Pin(_MOSI), miso=Pin(_MISO))
    return SX1262(
        spi=spi,
        cs=Pin(_CS),
        busy=Pin(_BUSY),
        dio1=Pin(_DIO1),
        reset=Pin(_RST),
        dio3_tcxo_millivolts=_TCXO_MV,
        lora_cfg=lora_cfg,
    )
