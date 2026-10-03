# Buttons

`Button` polls and debounces a pin and calls a plain function per gesture. No subclassing, no Action required.

## Features
- **Gestures**: press, release, long press, double press, key repeat
- **Hold lengths**: several long presses, each firing as its length is reached
- **Latency only when asked**: a plain press fires the moment the button goes down
- **Any wiring**: active low with a pull-up by default

## Usage

```python
Button(1, on_press=modes.move_next)                   # fires on the way down
Button(1, on_press=next_mode,
       on_long_press=reset,                            # once, while still held
       on_double_press=go_back,                        # second press in 400ms
       on_release=show_released)                       # every time it comes up
Button(1, on_press=volume_up, repeat_ms=150)           # key repeat while held
Button(1, long_presses={1000: settings,                # several hold lengths,
                        10000: factory_reset})         # each as it is reached
```

Start it with `asyncio.create_task(button.run())`.

## When `on_press` Fires

Telling gestures apart costs latency, so it is only paid for when asked:

| Also set | `on_press` fires |
|----------|------------------|
| nothing (or only `on_release`) | the moment the button goes down |
| `repeat_ms` | on the way down, then every `repeat_ms` while held |
| `on_long_press` or `long_presses` | on release, if it was not a long press |
| `on_double_press` | `double_press_ms` after release, if no second press came |

## Wiring

| Wiring | Arguments |
|--------|-----------|
| Button to GND (default) | none: active low, internal pull-up |
| Button to 3V3 | `active_low=False` (picks a pull-down) |
| External resistors | `pull=None` |

## Notes
- A long press never also counts as a press, and neither half of a double press does.
- `long_presses={1000: a, 5000: b}` held for 6s calls `a` at 1s and `b` at 5s: "hold for settings, keep holding to reset".
- `repeat_ms` cannot be combined with long or double presses, since both hold `on_press` back.
- `button.is_pressed` reads the pin directly.
