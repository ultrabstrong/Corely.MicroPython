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
class Blinker(TaskAction):
    async def run(self):
        while True:
            self.pin.value(1)
            await asyncio.sleep_ms(self.interval_ms)
            self.pin.value(0)
            await asyncio.sleep_ms(self.interval_ms)

    def cleanup(self):
        self.pin.value(0)
```

`Led` is solid by default and only starts its task when blinking or pulsing,
so steady LEDs cost nothing to run:

```python
Led(18)                            # solid
Led(18, blink_interval_ms=250)     # blinking
Led(18).pulse(2000)                # pulsing: a 2s fade up and down
Led(2, active_high=False)          # an LED that lights when the pin goes low
```

Blink and pulse are one waveform walk - a square wave and a sine. Blink only
asks for full or nothing, so it works on a plain digital pin (the Pico W's
onboard LED has no PWM); pulse needs the levels in between, so it sets up PWM
and raises on a pin without it. `brightness` is the waveform's peak.

`active_high=False` is for LEDs wired to sink current through the pin - most
ESP32 and ESP8266 onboard LEDs. A new LED starts dark whichever way it is
wired.

Where two states share one LED, `blinking()`, `pulsing()` and `steady()` hand
out Actions that drive the same pin, so the states cannot fight over it:

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
rgb.pulse(period_ms=2000, colour='purple')  # fades the colour, keeping its hue
rgb.rainbow(cycle_ms=3000)         # sweeps the hue wheel, 60 steps per lap
rgb.off()
```

It has the same `steady()` / `blinking()` / `pulsing()` views as `Led`, plus
`cycling()` for the rainbow, so one RGB LED can show a whole state machine:

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

## Buttons

`Button` calls a plain function per gesture - no subclassing, no Action
required:

```python
Button(1, on_press=modes.move_next)                   # fires on the way down
Button(1, on_press=next_mode,
       on_long_press=reset,                            # once, while still held
       on_double_press=go_back,                        # second press in 400ms
       on_release=show_released)                       # every time it comes up
Button(1, on_press=volume_up, repeat_ms=150)           # key-repeat while held
Button(1, long_presses={1000: settings,                # several hold lengths,
                        10000: factory_reset})         # each as it is reached
```

`long_presses` fires each callback once, while still held, as its length is
reached - a 6s hold with `{1000: a, 5000: b}` calls `a` at 1s and `b` at 5s,
which is how boards give "hold for settings, keep holding to reset" feedback.
`on_long_press` joins it at `long_press_ms`.

Telling gestures apart costs latency, so it is only paid for when asked:

| Also set | `on_press` fires |
|----------|------------------|
| nothing (or only `on_release`) | the moment the button goes down |
| `repeat_ms` | on the way down, then every `repeat_ms` while held |
| `on_long_press` or `long_presses` | on release, if it was not a long press |
| `on_double_press` | `double_press_ms` after release, if no second press came |

**Wiring.** Active-low with an internal pull-up by default (button to GND).
`active_low=False` is for a button to 3V3 and picks a pull-down; `pull=None`
turns the internal pull off for boards with their own resistors.

A long press never also counts as a press, and neither half of a double press
does. `repeat_ms` cannot be combined with either, since both hold `on_press`
back. `button.is_pressed` reads the pin directly.

## Sensors

Sensors are read, not switched, so they are not Actions. They follow Corely's
other two shapes: a `Sensor` base class owns error handling while each board
implements `async def read()` (as `TaskAction` owns the task and subclasses
implement `run()`), and a long-running `SensorSampler` reads them all from its
own `run()` (as `Button` and `WiFiMonitor` do).

```python
bme = Bme280(i2c)
sampler = SensorSampler([bme, Tsl2591(i2c), Sgp40(i2c, climate=bme)])
asyncio.create_task(sampler.run())          # one sample a second

readings = sampler.readings                 # latest, any time
readings = await sampler.next()             # or wait for the next sample
```

Every reading is a flat dict of named values:

| Class | Keys |
|-------|------|
| `Bme280` | `temperature` (C), `humidity` (%), `pressure` (hPa) |
| `Tsl2591` | `lux`, `light_full`, `light_ir` (raw counts) |
| `Sgp40` | `voc_index` (`None` while warming up), `voc_raw` |

- **Nothing blocks.** The BME280 measures continuously so a read is a register
  fetch, and the SGP40's 30ms measurement is awaited. Both are small
  subclasses of the vendored drivers, which stay unedited.
- **A failed read empties that sensor's keys** rather than raising or leaving
  a stale number. `sensor.error` keeps the exception.
- **Create the sampler once, for the life of the program.** The SGP40's VOC
  index learns its baseline from one sample a second over hours; recreating
  it starts that over. Keep `interval_ms` at 1000 when an `Sgp40` is in it.
- **`Sgp40(climate=...)` compensates** with another sensor's latest humidity
  and temperature, falling back to the chip's defaults (50%, 25C).
- **Opening sensors is the app's job.** A constructor raises if its chip is
  missing; whether to carry on without it is the application's call.
- **Tsl2591 saturates at `Tsl2591.MAX_LUX`** (about 6000 at the default gain)
  and reports that rather than raising.

**Staying up unattended.** Each sensor rejects readings its chip should never
produce (`validate()` - a value on the BME280 driver's clamps, infrared above
full spectrum, a saturated SGP40 signal), and the BME280 and SGP40 flag a
reading unchanged for a minute (`stuck_after`). Both count as failed reads.
After 3 failures in a row the sampler re-opens that sensor; when every sensor
is failing it calls `recover_bus` - typically `recover_i2c(scl, sda)`, the I2C
spec's nine-clock bus recovery, then re-creating the `machine.I2C`. Failures
are logged once per incident, when the streak starts and ends.

`Sgp40.get_state()` / `set_state()` carry the VOC baseline across a reset;
where it is kept, and whether a restore is fresh enough, is the app's call.

Each class imports its driver when created, so `corely.sensors` costs nothing
for boards a project does not use. The drivers - `bme280`, `tsl2591`, `sgp40`
and `voc_algorithm` - are vendored; see `vendor/README.md`.

## Sleep cycles

`SleepCycle` runs awake, then asleep until the timer or a trigger, round and
round. It is an Action: `on()` starts it, `off()` stops it with everything it
drives switched off.

```python
cycle = SleepCycle(awake_ms=5000, asleep_ms=15000,
                   awake_action=ActionGroup(screen_on, green_led),
                   on_wake=lambda reason: print(reason))   # 'timer', 'button', 'dark'
cycle.wake_on("button", PinTrigger(1))
cycle.wake_on("dark", PinTrigger(2, rearm=light.clear_interrupt))
light.set_light_interrupt(below_lux=5)
cycle.on()

Button(1, on_press=cycle.keep_awake, on_long_press=cycle.sleep_now)
```

- **Waking is hardware only.** A sleeping CPU cannot check anything, so every
  trigger is a pin interrupt - a button, or a chip's INT line such as the
  TSL2591's light threshold (`Tsl2591.set_light_interrupt`). There are no
  polled triggers: waking to look would spend what sleeping saves.
- **Going to sleep is ordinary code.** `sleep_now()` is a plain callable for a
  button or state machine; `keep_awake()` restarts the awake timer, which
  makes an idle timeout out of activity.
- **False wakes are slept through.** `lightsleep` returns early when, for
  instance, the wireless chip settles after a radio switches off; only a
  fired trigger or the timer ends a sleep. A trigger already asserted when the
  cycle goes to sleep (a latched INT, a held button) wakes it at once.
- **The sleep call is `sleep_fn`**, `machine.lightsleep` by default - the
  board-specific part. Light sleep keeps the program; a deep sleep that
  restarts it (the ESP32's) needs a different design.
- **It refuses to start under a watchdog** whose timeout a sleep would
  outlast, rather than be reset mid-sleep.

`set_light_interrupt()` thresholds are raw counts converted from lux, so they
trip near the asked-for level, not exactly. The chip holds INT low until
`clear_interrupt()` - hence `rearm`.

## Logs and system health

For a device that runs for months unattended:

```python
boot = boot_number("/boot.txt")
logging.getLogger().addHandler(RotatingFileHandler("/log.txt", boot=boot))

reason = last_reset("/reset.txt")     # 'power-on', 'watchdog', 'crash', ...
guard = BootGuard("/boots.txt")       # .tripped after 3 boots that die early
log_task_errors(logging.getLogger("app"))
monitor = SystemMonitor()             # loop lag, memory low-water, uptime
asyncio.create_task(Watchdog().run()) # production only - see below
```

- **`RotatingFileHandler`** works with the standard `logging` API
  (micropython-lib's, vendored). Size-capped with numbered backups - 64KB of
  flash at most by default - and each line is opened, written and closed, so
  a crash cannot strand it in a buffer. Lines carry the boot number and
  uptime, since there is no wall clock across a reset. `closed_files()` lists
  rotated files for a future log shipper to send and delete.
- **`Watchdog`** feeds `machine.WDT` from inside the event loop, so a hung
  loop resets the board. It cannot be stopped once started, including by
  `mpremote` - production builds only.
- **`last_reset()` / `reset()`**: on the RP2 `machine.reset()` reports as a
  watchdog reset, so `reset(reason, path)` leaves a marker that
  `last_reset()` reports instead.
- **`BootGuard`** counts boots that do not last a minute, so the app can fall
  back to a safe mode rather than crash forever.
- **`log_task_errors()`** logs an exception escaping any asyncio task, with
  its traceback.
- **`SystemMonitor`** measures event-loop lag and samples memory after a
  collection, keeping the lowest seen. `memory()`, `storage()` and
  `firmware()` read the rest.

Paths are the app's: Corely does no I/O it was not given.

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
from corely.sensors import Bme280, Tsl2591, Sgp40, SensorSampler, recover_i2c
from corely.logs import RotatingFileHandler, boot_number, format_exception
from corely.system import Watchdog, BootGuard, SystemMonitor, last_reset, reset
from corely.sleep import SleepCycle, PinTrigger
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
- `led.py` - `Led`, solid, blinking or pulsing, dimmable, `active_high` for
  LEDs that sink current, with `steady()`/`blinking()`/`pulsing()` views so
  several states can share one LED
- `rgb_led.py` - `RgbLed` and the colour palette: any colour over PWM, plus
  blink, pulse and rainbow modes
- `message.py` - `PrintMessage`
- `button.py` - `Button`, polled and debounced, calling a function per
  gesture: press, release, long press, double press, key-repeat; `active_low`
  and `pull` for other wirings
- `wifi.py` - connection, connect/disconnect actions, `WiFiMonitor`
- `ble_uart.py` - Nordic UART Service UUIDs
- `ble_peripheral.py` - `BleUartPeripheral` (something connects to this device)
- `ble_central.py` - `BleUartCentral` (this device connects to a peripheral)
- `sensors.py` - the `Sensor` base, `Bme280`, `Tsl2591` and `Sgp40`, the
  `SensorSampler` that owns them, and `recover_i2c()`
- `sleep.py` - `SleepCycle` and `PinTrigger`
- `logs.py` - `RotatingFileHandler`, `boot_number()`, `format_exception()`
- `system.py` - `Watchdog`, `BootGuard`, `last_reset()`/`reset()`,
  `log_task_errors()`, `SystemMonitor`, and `memory()`/`storage()`/`firmware()`

## Projects using this library

- `pico2/demos`
