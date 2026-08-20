# Application / LoRa payload and reliable-delivery constants.

# ----- Message payload -----
CONFIRMATION_YES = 0x10
CONFIRMATION_NO = 0x20
STATUS_FUEL = 0x01
STATUS_PARKING = 0x02
STATUS_EMERGENCY = 0x03

# ----- Reliable delivery -----
ACK_TIMEOUT_MS = 3000
TX_ATTEMPTS = 3       # STATE/CLEAR sends during the timeout window
ACK_ATTEMPTS = 3      # how many times to send each ACK
SEQ_MAX = 0xFFFF
SEQ_HALF = 0x8000
