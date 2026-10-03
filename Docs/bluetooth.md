# Bluetooth

A Nordic UART Service in both roles, built on `aioble`. `BleUartPeripheral` advertises and serves a phone or another board; `BleUartCentral` connects out to a peripheral.

## Features
- **Off the shelf apps**: the Nordic UART UUIDs are what nRF Connect and Serial Bluetooth Terminal recognise
- **States as Actions**: advertising and connected each drive an Action
- **Whole lines**: writes split by a small MTU are joined back into lines
- **Long replies**: `send()` splits to fit the connection

## Usage

```python
peripheral = BleUartPeripheral(
    name="Pico",
    on_line=lambda line: peripheral.send("Echo: " + line + "\n"),
    advertising_action=onboard.blinking(500),
    connected_action=onboard.steady(),
)
asyncio.create_task(peripheral.run())
```

`on_write` receives each write's bytes as they arrive; `on_line` receives text lines without their endings. A line ends at a newline or a pause (`line_pause_ms`), because terminal apps differ on sending one.

## Message Sizes

| Setting | Default | Meaning |
|---------|---------|---------|
| `rx_size` | 128 | the most bytes one write can carry |
| connection MTU | 23 | what the phone negotiated; `send()` splits to MTU minus 3 |

A phone writes 20 bytes at a time unless it negotiates more, so a WiFi password usually arrives in pieces.

## Notes
- **No pairing on the stock Pico W firmware.** It lacks `gap_pair` and `gap_passkey`, so the link is unencrypted. Anything that needs a lock builds one in the app, such as a code shown on a screen.
- `peripheral.disconnect()` drops the connected central; advertising resumes after.
- `aioble.advertise()` returns `None` when advertising is stopped from outside, and `run()` stands down cleanly when it does.
- `BleUartCentral` has run its scanning path on hardware; connecting needs a second device to verify.
