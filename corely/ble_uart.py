"""Nordic UART Service (NUS) UUIDs, shared by the BLE peripheral and central.

These are well-known UUIDs created by Nordic Semiconductor for serial-like
communication over BLE. Think of them like "port 80 for HTTP" - a standard that
both ends agree on so they can find each other.

Why fixed UUIDs instead of random ones?
- BLE discovery works by UUID: "find me a device with THIS service"
- Using Nordic's UUIDs means phone apps (nRF Connect, Serial Bluetooth
  Terminal) recognise the device as a "UART" and know how to talk to it
- Random UUIDs would work, but both ends would need to agree on them ahead of
  time and no off-the-shelf app would understand them

The three UUIDs, named from the peripheral's point of view:
- Service (0001): "this device offers UART-like communication"
- RX (0002): the mailbox the central writes into
- TX (0003): the mailbox the peripheral publishes from (read/notify)
"""

import bluetooth

UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
UART_RX_UUID = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
UART_TX_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
