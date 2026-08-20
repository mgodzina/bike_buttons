# LoRa driver is vendored in lib/lora (lora-sx126x + lora-sync from micropython-lib).
import lora_msg
import ble_terminal
import system_configurator as config
from terminal import Terminal, StatePrinter
from hardware import Buttons
from process import Device
from config_hardware import BLE_TOGGLE_BTN, BLE_TOGGLE_HOLD_MS

# ----- Identity / network (config.json on flash) -----
_cfg = config.load()
term = Terminal(_cfg["sender_id"], _cfg["devices"])
print(f"Sender ID: {term.sender_id}, devices: {term.devices}, buddies: {term.buddies}")
if term.sender_id == 0:
    print("Sender ID is 0 (not configured). Set with terminal: i then 1-4")
elif term.sender_id not in term.devices:
    print(f"Warning: sender_id {term.sender_id} is not in devices {term.devices}")

# ----- Hardware / radio -----
print("Initializing LoRa...")
modem = lora_msg.create_modem()
print("LoRa ready")
device = Device(term.sender_id, term.buddies, modem)
device.set_all_leds_off()
buttons = Buttons()

ble_terminal.configure(
    name=lambda: "lora-{}".format(term.sender_id),
    on_start=lambda: device.led_notify(3),
    on_stop=lambda: device.led_notify(2),
)
term.on_ble_toggle = ble_terminal.toggle

state_printer = StatePrinter()
term.print_help()
print("BLE: hold", BLE_TOGGLE_BTN, "for", BLE_TOGGLE_HOLD_MS // 1000, "s to toggle")

# ----- Main loop -----
while True:
    buttons.loop()
    buttons.check_buttons(device)
    ble = ble_terminal.get()
    term.poll(buttons, device, ble)
    device.start_listening()
    device.check_rx()
    device.check_timers()
    device.update_leds_state()
    device.update_leds_mode()
    device.apply_leds()
    state_printer.print_state(device)
    if ble is not None:
        ble.poll_tx()
