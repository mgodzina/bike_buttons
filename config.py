# Persistent network config on the MicroPython flash filesystem.
import json

CONFIG_FILE = "config.json"
DEFAULT_SENDER_ID = 0  # 0 = not configured
DEFAULT_DEVICES = []
VALID_DEVICE_IDS = (1, 2, 3, 4)
VALID_SENDER_IDS = (0, 1, 2, 3, 4)


def _clean_devices(devices):
    if not isinstance(devices, list):
        return list(DEFAULT_DEVICES)
    cleaned = []
    for d in devices:
        if d == 0:
            print("Ignoring device id 0 (reserved = not configured)")
            continue
        if d not in VALID_DEVICE_IDS:
            print("Ignoring invalid device id:", d)
            continue
        if d not in cleaned:
            cleaned.append(d)
    return cleaned


def _clean_sender_id(sender_id):
    try:
        sender_id = int(sender_id)
    except (TypeError, ValueError):
        return DEFAULT_SENDER_ID
    if sender_id not in VALID_SENDER_IDS:
        print("Invalid sender_id", sender_id, "; using", DEFAULT_SENDER_ID)
        return DEFAULT_SENDER_ID
    return sender_id


def load():
    """Return dict: {"sender_id": int, "devices": [int, ...]}."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except OSError:
        cfg = {"sender_id": DEFAULT_SENDER_ID, "devices": list(DEFAULT_DEVICES)}
        save(cfg["sender_id"], cfg["devices"])
        print("Created", CONFIG_FILE, cfg)
        return cfg
    except ValueError as e:
        print("Invalid", CONFIG_FILE, "-", e, "; using defaults")
        return {"sender_id": DEFAULT_SENDER_ID, "devices": list(DEFAULT_DEVICES)}

    if not isinstance(data, dict):
        print("Invalid", CONFIG_FILE, "root; using defaults")
        return {"sender_id": DEFAULT_SENDER_ID, "devices": list(DEFAULT_DEVICES)}

    sender_id = _clean_sender_id(data.get("sender_id", DEFAULT_SENDER_ID))
    devices = _clean_devices(data.get("devices", DEFAULT_DEVICES))
    return {"sender_id": sender_id, "devices": devices}


def save(sender_id, devices):
    sender_id = _clean_sender_id(sender_id)
    devices = _clean_devices(devices)
    if 0 in devices:
        devices = [d for d in devices if d != 0]
    with open(CONFIG_FILE, "w") as f:
        json.dump({"sender_id": sender_id, "devices": devices}, f)
    print("Saved", CONFIG_FILE, "sender_id:", sender_id, "devices:", devices)
    return {"sender_id": sender_id, "devices": devices}


# Backwards-compatible helpers
def load_devices():
    return load()["devices"]


def save_devices(devices, sender_id=None):
    cfg = load()
    if sender_id is None:
        sender_id = cfg["sender_id"]
    return save(sender_id, devices)
