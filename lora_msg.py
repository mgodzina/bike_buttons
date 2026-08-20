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
    MSG_TYPE_CLEAR: "CLEAR"
}


def pack(sender_id, seq, msg_type, data):
    return struct.pack(MSG_FMT, sender_id, seq, msg_type, data)


def unpack(raw):
    if len(raw) < MSG_SIZE:
        return None
    sender_id, seq, msg_type, data = struct.unpack(MSG_FMT, raw[:MSG_SIZE])
    return sender_id, seq, msg_type, data


def create_modem(freq_khz=868000, sf=7, bw="125", output_power=14):
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
