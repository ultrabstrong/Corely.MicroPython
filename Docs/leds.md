# LEDs

`Led` drives a single LED solid, blinking or pulsing. `RgbLed` treats a four pin RGB LED as one component, mixing any colour over PWM. Both are [Actions](actions.md).

## Features
- **One object per pin**: modes switch on the same object, so nothing fights over the pin
- **Free when steady**: a solid LED runs no task
- **Dimmable**: `brightness` from 0.0 to 1.0, switching to PWM on demand
- **Either polarity**: `active_high=False` for LEDs that sink current through the pin
- **Views**: `steady()`, `blinking()`, `pulsing()` (and `cycling()` on `RgbLed`)

## Usage

```python
Led(18)                            # solid
Led(18, blink_interval_ms=250)     # blinking
Led(18).pulse(2000)                # a 2s fade up and down
Led(2, active_high=False)          # lights when the pin goes low
```

Blink only needs full or nothing, so it works on a plain digital pin. Pulse needs the levels in between, so it sets up PWM and raises on a pin without it.

### RGB LEDs

```python
rgb = RgbLed(13, 14, 15)                    # common cathode
rgb.solid('orange'); rgb.on()               # a name from COLOURS
rgb.solid((255, 40, 90))                    # or any (r, g, b)
rgb.blink(interval_ms=250, colour='teal')
rgb.pulse(period_ms=2000, colour='purple')  # keeps the hue while fading
rgb.rainbow(cycle_ms=3000)
```

One RGB LED can show a whole state machine through its views:

```python
monitor = WiFiMonitor(
    wifi,
    connected_action=rgb.steady('green'),
    no_internet_action=rgb.blinking('yellow'),
    disconnected_action=rgb.steady('red'),
)
```

## Colour Balance

Green and blue dies are far more efficient than red ones, so equal duty cycles do not look like equal light: yellow comes out green. `channel_scale` corrects it, defaulting to `(1.0, 0.20, 0.5)`, tuned by eye against a real LED.

```python
RgbLed(13, 14, 15, channel_scale=(1.0, 1.0, 1.0))   # raw output
```

## Notes
- A new LED starts dark whichever way it is wired.
- Note: a pin without PWM (the Pico W's onboard LED is on the wireless chip) runs at full brightness only.
