# Tests

Host-run unit tests for Corely. No device, no pytest, no install:

```
cd tests
python -m unittest discover -s . -t .
```

(From the repo root: `python -m unittest discover -s tests -t tests`.)

## How it works

`harness.py` bridges the two gaps between a MicroPython device and a PC, and
every test module imports it first:

- `stubs/machine.py` and `stubs/network.py` replace the device-only modules.
  The fake `Pin` records every write (so blink patterns can be asserted) and
  can be pressed and released; the fake `PWM` records every duty (so colours
  and brightness can be asserted); the fake `WLAN` can be told to fail to
  connect.
- `time.ticks_ms()`, `asyncio.sleep_ms()` and `asyncio.wait_for_ms()` are
  MicroPython-only, so they are patched onto the CPython modules.
- The repo root goes on `sys.path`, so `corely.*` imports resolve the same way
  they do on the device, where the package is deployed to `/lib/corely`.

Nothing here imports application code: the tests cover the library alone.

## What is covered

| Module | Tests |
|--------|-------|
| `corely/action.py` | task start/cancel, cleanup, restart, double on/off |
| `corely/action.py` (`ActionCycler`) | one action on at a time, off-before-on ordering, wraparound |
| `corely/action.py` (`ActionGroup`) | switching members together, nesting inside a cycler |
| `corely/led.py` | solid and blinking, mode switching, brightness, two states sharing one LED |
| `corely/rgb_led.py` | colour resolution, hue wheel, modes, polarity, channel scaling |
| `corely/button.py` | one event per press, no repeat while held, held-at-startup |
| `corely/wifi.py` | connect/timeout, state machine, non-blocking checks |
| `corely/ble_peripheral.py` | advertising, connect/disconnect actions, writes, notify |

Timings in the button tests are deliberately generous. A PC event loop has much
coarser timer granularity than the device, so tight polls would only make these
flaky.

## BLE

`corely/ble_peripheral.py` is tested against a fake aioble (`stubs/aioble.py`),
which covers the parts that are Corely's own: which action is on in which
state, writes reaching the callback, notifications on send, and aioble's habit
of returning `None` from `advertise()` when advertising is stopped. It does not
test BLE itself - a fake radio would only test the fake.

Verified on hardware separately: advertising, a phone connecting, and the echo
round trip, from a demo application on a Pico 2 W.

`corely/ble_central.py` has no host tests, and only its scanning path has run on
hardware. Connecting, discovery and notifications need a second BLE device.
