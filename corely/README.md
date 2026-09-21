# Corely

Asyncio building blocks for MicroPython devices: actions, LEDs, RGB LEDs,
buttons, WiFi and BLE. Nothing in here is board-specific - it is developed
against a Raspberry Pi Pico 2 W, but only relies on `machine`, `network` and
`aioble`.

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

`ActionGroup` switches several actions as one, for a state that should show up
in more than one place:

```python
connected = ActionGroup(green_led, rgb.steady('green'))
```

Long-running components that are not Actions (buttons, monitors, BLE roles)
expose `async def run()`; start them with `asyncio.create_task()` and combine
them with `asyncio.gather()`.

## RGB LEDs

`RgbLed` treats a four-pin RGB LED as one component, driving each channel with
PWM so colours mix properly:

```python
rgb = RgbLed(7, 8, 9)              # common cathode; active_high=False for anode
rgb.solid('orange'); rgb.on()      # a name from COLOURS
rgb.solid((255, 40, 90))           # or any (r, g, b), 0-255
rgb.blink(interval_ms=250, colour='teal')
rgb.rainbow(cycle_ms=3000)         # sweeps the hue wheel, 60 steps per lap
rgb.off()
```

It has the same `steady()` / `blinking()` views as `Led`, plus `cycling()` for
the rainbow, so one RGB LED can show a whole state machine:

```python
monitor = WiFiMonitor(
    wifi,
    connected_action=rgb.steady('green'),
    no_internet_action=rgb.blinking('yellow'),
    disconnected_action=rgb.steady('red'),
)
```

**Colour balance.** Green and blue dies are far more efficient than red ones,
so equal duty cycles do not look like equal light - "yellow" comes out green.
`channel_scale` corrects that, defaulting to `(1.0, 0.20, 0.5)`, which was
tuned by eye against a real LED. Pass `(1.0, 1.0, 1.0)` for raw output, or your
own gains if your LED differs.

**Brightness.** Both `Led` and `RgbLed` take `brightness` (0.0-1.0). For `Led`,
anything below full switches the pin to PWM on demand - so a pin without PWM
(the Pico W's onboard LED lives on the wireless chip) can only run at full.

## Usage in projects

MicroPython automatically searches `/lib/` for modules:

```python
from corely.action import Action, ActionCycler, ActionGroup, TaskAction
from corely.button import Button
from corely.led import Led
from corely.rgb_led import RgbLed, RED, GREEN, BLUE, COLOURS
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

- `action.py` - `Action` and `TaskAction` base classes, plus `ActionCycler`
  (one action at a time) and `ActionGroup` (several as one)
- `led.py` - `Led`, solid or blinking, dimmable, with `blinking()`/`steady()`
  views so two states can share one LED
- `rgb_led.py` - `RgbLed` and the colour palette: any colour over PWM, plus
  blink and rainbow modes
- `message.py` - `PrintMessage`
- `button.py` - `Button`, polled and debounced, calling any function on press
- `wifi.py` - connection, connect/disconnect actions, `WiFiMonitor`
- `ble_uart.py` - Nordic UART Service UUIDs
- `ble_peripheral.py` - `BleUartPeripheral` (something connects to this device)
- `ble_central.py` - `BleUartCentral` (this device connects to a peripheral)

## Projects using this library

- `pico2/demos`
