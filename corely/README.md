# Corely

Asyncio building blocks for MicroPython devices: actions, LEDs, buttons, WiFi
and BLE. Nothing in here is board-specific - it is developed against a
Raspberry Pi Pico 2 W, but only relies on `machine`, `network` and `aioble`.

Corely lives here for now, but it is meant to move into its own repo, so it
stays free of project-specific code.

## Tests

```
cd ../tests
python -m unittest discover -s . -t .
```

See [../tests/README.md](../tests/README.md).

## Getting it onto a device

`python deploy.py` from the repo root copies this folder to `/lib/corely/`,
along with the vendored packages it needs. The BLE modules need `aioble`, which
is committed in `vendor/aioble/` and deployed the same way - nothing is
downloaded, by your PC or by the device.

## The Action pattern

An Action is anything that can be switched on and off:

```python
action.on()   # activate - must not block
action.off()  # deactivate - must not block, safe to call twice
```

Anything that changes state (a button, WiFi connectivity, a BLE connection)
just flips Actions on and off, so an LED, a print, or a buzzer are
interchangeable wherever an Action is accepted.

Work that keeps running (blinking, connecting, monitoring) lives in a task the
Action owns. Subclass `TaskAction`, implement `run()` and `cleanup()`, and
`on()`/`off()` handle the task lifecycle:

```python
class Led(TaskAction):
    async def run(self):
        while True:
            self.led.value(1)
            await asyncio.sleep_ms(self.blink_interval_ms)
            self.led.value(0)
            await asyncio.sleep_ms(self.blink_interval_ms)

    def cleanup(self):
        self.led.value(0)
```

`Led` is solid by default and only starts that task when it is blinking, so
steady LEDs cost nothing to run.

Where two states share one LED, `blinking()` and `steady()` hand out Actions
that drive the same pin, so the states cannot fight over it:

```python
onboard = Led("LED")
peripheral = BleUartPeripheral(
    advertising_action=onboard.blinking(500),
    connected_action=onboard.steady(),
)
```

Long-running components that are not Actions (buttons, monitors, BLE roles)
expose `async def run()`; start them with `asyncio.create_task()` and combine
them with `asyncio.gather()`.

## Usage in projects

MicroPython automatically searches `/lib/` for modules:

```python
from corely.action import Action, ActionCycler, TaskAction
from corely.button import Button
from corely.led import Led
from corely.message import PrintMessage
from corely.wifi import WiFiConnection, WiFiConnectAction, WiFiDisconnectAction, WiFiMonitor
from corely.ble_peripheral import BleUartPeripheral
from corely.ble_central import BleUartCentral
```

Typical shape of a project:

```python
import asyncio

async def main():
    led = Led("LED", blink_interval_ms=250)
    button = Button(pin_number=1, on_press=cycler.move_next)

    led.on()
    await asyncio.gather(
        asyncio.create_task(button.run()),
    )

asyncio.run(main())
```

## Structure

Every module is a flat file in this folder:

- `action.py` - `Action` and `TaskAction` base classes, plus `ActionCycler`,
  which activates one action at a time
- `led.py` - `Led`, solid or blinking, with `blinking()`/`steady()` views so two
  states can share one LED
- `message.py` - `PrintMessage`
- `button.py` - `Button`, polled and debounced, calling any function on press
- `wifi.py` - connection, connect/disconnect actions, `WiFiMonitor`
- `ble_uart.py` - Nordic UART Service UUIDs
- `ble_peripheral.py` - `BleUartPeripheral` (something connects to this device)
- `ble_central.py` - `BleUartCentral` (this device connects to a peripheral)

## Projects using this library

- `pico2/demos`
