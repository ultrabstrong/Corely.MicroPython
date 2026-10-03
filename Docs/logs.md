# Logs

`RotatingFileHandler` logs to flash through the standard `logging` API, size capped so it can never fill the filesystem.

## Features
- **Size capped**: rotates at 16KB with 3 numbered backups, 64KB at most by default
- **Crash safe**: each line is opened, written and closed, so nothing waits in a buffer
- **Boot numbered**: lines carry the boot number and uptime, and the UTC time once the clock is set
- **Shippable**: `closed_files()` lists rotated files for a log shipper to send and delete

## Usage

```python
boot = boot_number("/boot.txt")
handler = RotatingFileHandler("/log.txt", boot=boot,
    wall_clock=lambda: utc_stamp() if clock_is_set() else None)
logging.getLogger().addHandler(handler)
```

Lines read:

```text
#12 +3602.4s ERROR corely.sensors: BME280 read failed: [Errno 5] EIO
2026-10-03T02:58:19Z #12 +3605.0s INFO corely.wifi: WiFi joined home
```

## Notes
- **Log incidents, not readings.** Every line is a flash write. Corely logs a failure when it starts and ends, never per attempt.
- `level` defaults to `WARNING`; pass `logging.INFO` to keep more.
- `tail(lines)` reads the last few lines without loading the whole file.
- `format_exception()` turns an exception and its traceback into text on MicroPython or CPython.
