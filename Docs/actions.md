# Actions

An Action is anything that can be switched on and off. State changes (a button, a connection, a sleep) flip Actions, so an LED, a screen label or a radio are interchangeable wherever one is accepted.

## Features
- **One contract**: `on()` and `off()`, both non-blocking, with `off()` safe to call twice
- **Task lifecycle handled**: `TaskAction` starts a task on `on()` and cancels it on `off()`
- **Composition**: `ActionCycler` runs one of a list at a time, `ActionGroup` switches several as one
- **Views**: one object owns a pin and hands out an Action per state

## Usage

```python
class Blinker(TaskAction):
    async def run(self):
        while True:
            self.pin.toggle()
            await asyncio.sleep_ms(self.interval_ms)

    def cleanup(self):
        self.pin.value(0)
```

`run()` is the ongoing work. `cleanup()` returns the hardware to rest, and `off()` calls it directly, because cancellation only lands at the task's next `await`.

### Cycling and grouping

```python
modes = ActionCycler([Led(16), Led(17, blink_interval_ms=250)])
modes.on()             # the first mode
modes.move_next()      # off with the current, on with the next

connected = ActionGroup(green_led, rgb.steady('green'), screen.status("Connected"))
```

`ActionCycler` is an Action itself, so cyclers nest and go inside groups.

### Views

Where several states drive one LED, the LED hands out views rather than a second object fighting over the pin:

```python
onboard = Led("LED")
peripheral = BleUartPeripheral(
    advertising_action=onboard.blinking(500),
    connected_action=onboard.steady(),
)
```

## Notes
- **Long-running components that are not Actions** (buttons, monitors, BLE roles) expose `async def run()`. Start them with `asyncio.create_task()` and combine them with `asyncio.gather()`.
- **When two states share a pin**, switch the old one off before the new one on. `ActionCycler` does.
- `PrintMessage` is an Action that prints, useful as a placeholder or as the "off" step of a cycle.
