# Sensors

`SensorSampler` owns every sensor for the life of the program and reads them on one schedule. Each board is a `Sensor` subclass implementing `async def read()`; the base class owns error handling.

## Features
- **Nothing blocks**: the BME280 measures continuously, the SGP40's 30ms measurement is awaited
- **Flat readings**: one dict of named values across every sensor
- **Bad readings rejected**: values a chip should never produce count as failures
- **Recovery**: a failing sensor is reopened, and a stuck I2C bus is freed
- **Logged once per incident**: when a failure streak starts and ends, never per reading

## Usage

```python
bme = Bme280(i2c)
sampler = SensorSampler([bme, Tsl2591(i2c), Sgp40(i2c, climate=bme)])
asyncio.create_task(sampler.run())          # one sample a second

readings = sampler.readings                 # latest, any time
readings = await sampler.next()             # or wait for the next sample
```

## Readings

| Class | Keys |
|-------|------|
| `Bme280` | `temperature` (C), `humidity` (%), `pressure` (hPa) |
| `Tsl2591` | `lux`, `light_full`, `light_ir` (raw counts) |
| `Sgp40` | `voc_index` (`None` while warming up), `voc_raw` |

A failed read empties that sensor's keys rather than raising or leaving a stale number. `sensor.error` keeps the exception.

## Recovery

```python
sampler = SensorSampler(sensors, recover_bus=lambda: recover_i2c(scl_pin=7, sda_pin=6))
```

- **`validate()`** rejects impossible values: a reading on the BME280 driver's clamps, infrared above full spectrum, a saturated SGP40 signal.
- **`stuck_after`** flags a reading unchanged for a minute (BME280, SGP40).
- **After 3 failures in a row** the sampler reopens that sensor.
- **When every sensor is failing** it calls `recover_bus`, typically `recover_i2c()`: the I2C spec's nine clock recovery. Re-create the `machine.I2C` afterwards.

## Drivers

Each class imports its driver when created, so `corely.sensors` costs nothing for boards a project does not use. The drivers are optional, installed with:

```bash
mpremote mip install github:ultrabstrong/Corely.MicroPython/sensors.json@Corely.MicroPython-v1.0.0
```

## Notes
- **Create the sampler once.** The SGP40's VOC index learns its baseline over hours from one sample a second; recreating it starts over. Keep `interval_ms` at 1000 with an `Sgp40`.
- `Sgp40.get_state()` and `set_state()` carry the VOC baseline across a reset. Where it is kept is the app's call.
- `Sgp40(climate=...)` compensates with another sensor's humidity and temperature, falling back to 50% and 25C.
- A constructor raises if its chip is missing. Whether to carry on without it is the app's call.
- `Tsl2591` saturates at `Tsl2591.MAX_LUX` (about 6000 at the default gain) and reports that rather than raising.
- `Tsl2591` implements the alarm contract. See [Threshold Alarms](threshold-alarms.md).
