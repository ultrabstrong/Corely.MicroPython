# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Part of the Corely suite: asyncio building blocks for MicroPython devices, imported as `corely.*`. See `README.md` for what it does and `Docs/index.md` for usage. Developed against a Raspberry Pi Pico 2 W; the `Raspberry-Pi` repository (private) consumes it through a pinned release and is where it is tried on hardware.

- **Board agnostic.** It may rely on `machine`, `network` and `aioble`, but not on anything Pico specific, and its docs say "device", not "Pico". Wiring assumptions (LED and button polarity) belong in constructor arguments.
- **No I/O it was not given.** Credentials, settings and file paths are the application's: `WiFiConnection` takes an ssid and password, `BootGuard` takes the path of its count.

Plans for reviewable changes live in `Plans/{New,InProgress,Completed}/`.

## Test

```bash
cd tests && python -m unittest discover -s . -t .
python scripts/build.py --check     # every module through MicroPython's own compiler
python scripts/package.py --check   # package.json lists every module
```

- `tests/harness.py` stubs `machine`, `network`, `bluetooth` and `aioble`, and patches the MicroPython only `time.ticks_ms`, `asyncio.sleep_ms` and `asyncio.wait_for_ms`. Import it before any Corely module.
- Timings in the async tests are deliberately generous: a PC event loop has much coarser timer granularity than a device (about 15ms on Windows). When a test fails intermittently, widen the window; do not just re-run it.
- BLE is not host testable and no emulator covers it. Hardware behaviour cannot be verified here; say so rather than implying code was tested on a device.

## Releasing

Bump `"version"` in `package.json`, then tag `<PackageId>-v<Version>`: `git tag Corely.MicroPython-v1.0.1 && git push origin Corely.MicroPython-v1.0.1`. The tag triggers `release.yml`, which fails unless the tag's version equals `package.json`'s, then tests, compiles with `mpy-cross` and publishes a GitHub release with the `.mpy` and source bundles. Tags are pushed only with the owner's say-so. `ci.yml` runs the same checks on every push, and `scripts/check-package-versions.sh` reports a change since the last tag without a version bump.

The repository is the package feed: `mip` installs from it at a tag, so it must stay public. A new module needs `python scripts/package.py` to list it; CI fails until it does. A new micropython-lib dependency goes in `DEPS` in that script.

## Module Layout

- **Group related classes in one module, not one class per file.** On MicroPython every imported module costs RAM and import time, and related classes are nearly always imported together. Split only when a module stops being about one idea.
- **Prefer one class with a mode over near duplicate classes.** `Led` covers solid, blinking and pulsing, so one object owns a pin for the life of the program. Where a state machine needs an Action per state, hand out views (`Led.blinking()`, `Led.steady()`).
- Modules are flat files in the `corely` package, imported as `from corely.led import Led`.
- `corely/__init__.py` stays free of re-exports: importing everything there would drag the BLE modules and aioble into RAM for a project that only blinks an LED.
- Optional drivers are imported where used, not at module top, so `corely.sensors` costs nothing for boards a project lacks.

## Async Conventions

- asyncio everywhere. **Nothing may block the event loop**: no `time.sleep`, no blocking sockets. Use `asyncio.sleep_ms` and `asyncio.wait_for_ms`.
- An Action is anything switchable: `on()` and `off()`, both non-blocking, with `off()` safe to call twice. Ongoing work subclasses `TaskAction` and implements `run()` plus `cleanup()`.
- Task cancellation only lands at the next `await`, so `off()` does its deterministic cleanup itself rather than trusting the dying task.
- Long running non-Actions (buttons, monitors, BLE roles) expose `async def run()`.
- One object owns a pin. Several states driving it get views; one state driving several devices gets an `ActionGroup`. Turn the old action off before the new one on.

## Use the Ecosystem for Protocols

**Anything with a wire format, a spec, or timing rules is a package, not a weekend project.** The BLE code here started as raw `bluetooth` IRQs with fragile handle arithmetic and two callbacks that could never fire on the Pico W; `aioble` deleted all of it.

| Need | Use | Not |
|------|-----|-----|
| BLE | `aioble` | raw `bluetooth` IRQs |
| HTTP requests | `aiohttp` (micropython-lib, asyncio) | hand-rolled sockets, `urequests` |
| Serving web pages | `microdot` | a socket server |
| MQTT | `umqtt.simple` / `umqtt.robust` | anything hand-rolled |
| Clock sync | `ntptime` (built in) | parsing NTP packets |
| Addressable LED strips | `neopixel` (built in) | bit-banging WS2812 timing |

**GPIO level behaviour is the exception.** LEDs, buttons, PWM colour mixing and connection state machines have no hidden spec, so Corely owning them is deliberate: it is what makes everything interchangeable through `Action`.

Make a driver non-blocking by subclassing it, never by editing it: `Bme280` overrides one method to use normal mode, `Sgp40` splits the measurement around an `await`.

## Hardware Notes

- **Light sleep does not sleep with WiFi on**: `lightsleep(ms)` returns within milliseconds every time while the radio is active. `WiFiStayConnected.off()` switches the radio off. Bluetooth on but idle does not disturb it.
- `lightsleep(ms)` can return early (right after a radio switches off), and a pin interrupt that wakes it has its soft handler run about 1ms after it returns. `SleepCycle` handles both; hand written sleep code must too.
- Wake sources are pin interrupts only. Never poll a sensor to decide to wake; it defeats the sleep.
- A sensor alarm is a latching alarm clock: clearing it alone loops if the reading is still out of range. `ThresholdAlarm` swaps between crossing and recovery thresholds; never hand-roll the swap.
- TSL2591 thresholds take effect only from a fresh measurement (set them with the ALS off), 0xFFFF trips the flags regardless, and they compare the raw full spectrum count including infrared. Arm relative to `raw_full_spectrum()`.
- Deep sleep reboots on every wake. `wake_reason()` must run before anything re-arms an alarm, and the `BootGuard` must be passed or the short boots read as a boot loop.
- On the RP2, `machine.reset()` reports as a watchdog reset; `system.reset(reason, path)` leaves a marker.
- No BLE pairing in the stock Pico W firmware (`gap_pair`, `gap_passkey` absent). A phone writes 20 bytes at a time unless it negotiates more.
- RGB channels are not equally efficient. `channel_scale` was tuned by eye; colour balance is a judgement call, so ask rather than guess at a number.

## MicroPython Gaps the Host Tests Cannot Catch

CPython runs the tests, so these pass on a PC and fail on a device. `scripts/build.py --check` catches syntax; these it cannot:

- No `format()` builtin: use `"{:.1f}".format(x)` or f-strings.
- No private name mangling: a driver's `self.__crc` is `__crc` on the device but `_SGP40__crc` under CPython. Look up both (see `_async_sgp40`).
- `bytes.find()` takes only bytes, not an int.
- `str.partition` may be missing from smaller builds; prefer `split(sep, 1)`.

## Style

- Tabs for indentation, docstrings on classes and public methods with an `Args:` block.
- Log through `logging` once per incident, never per reading or retry: on a device every line is a flash write.

## Documentation

`Docs/` describes **how the current version works**. Nothing else.

- **No version numbers of this library.** Migration guides are the sole exception and live at the repository root.
- **No references to `Plans/`.**
- **Match the house style.** Terse and code-forward: a short orienting paragraph, then examples. Read the neighbouring files in `Docs/` before adding one.
- **No dashes as punctuation, in anything written.** No em dash, no en dash, and no hyphen standing in for one. Use a colon, a comma, parentheses or a new sentence. Hyphens inside words are fine. Existing code comments predate this rule; new writing follows it.

The full guide is `DOCUMENTATION-STYLE.md` in the Corely.IAM repository.
