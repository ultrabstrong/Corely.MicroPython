# Corely MicroPython
Asyncio building blocks for MicroPython devices: actions, LEDs, buttons, WiFi, Bluetooth, sensors, sleep and unattended running.

## Installation
```bash
mpremote mip install github:ultrabstrong/Corely.MicroPython@Corely.MicroPython-v1.0.0
```

This installs `corely` to the board's `/lib`, with `logging`, `aioble` and `aiohttp` from micropython-lib. The sensor drivers are optional:

```bash
mpremote mip install github:ultrabstrong/Corely.MicroPython/sensors.json@Corely.MicroPython-v1.0.0
```

Each [release](https://github.com/ultrabstrong/Corely.MicroPython/releases) also carries the package precompiled to `.mpy` (MicroPython 1.23 or later) for copying to `/lib` by hand.

## Getting Started
Corely is built around one contract: an Action is anything that can be switched `on()` and `off()`. Buttons, connections and sleep cycles flip Actions, so an LED, a screen label or a radio are interchangeable wherever one is accepted. Everything runs on asyncio, and nothing blocks the event loop.

- Actions, cyclers and groups, with task lifecycles handled
- LEDs and RGB LEDs: solid, blinking, pulsing, any colour
- Buttons with press, release, long, double and repeat gestures
- WiFi that stays connected and sets the clock in UTC
- Bluetooth UART as peripheral or central
- Sensors (BME280, TSL2591, SGP40) under one sampler, with bus recovery
- Sleep cycles woken by pin interrupts, threshold alarms, deep sleep
- Rotating logs, watchdog, boot loop detection, over-the-air updates

Corely relies only on `machine`, `network` and `aioble`, and is developed against a Raspberry Pi Pico 2 W.

## Documentation
Details about each module can be found in the [documentation](https://github.com/ultrabstrong/Corely.MicroPython/blob/master/Docs/index.md).

## Repository
[Corely.MicroPython](https://github.com/ultrabstrong/Corely.MicroPython)

## Contributing
We welcome contributions! Please read our [contributing guidelines](https://github.com/ultrabstrong/Corely.MicroPython/blob/master/CONTRIBUTING.md) to get started.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
