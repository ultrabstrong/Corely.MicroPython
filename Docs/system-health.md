# System Health

Keeping a device alive unattended, and knowing what happened when it was not. Paths are the app's: Corely does no I/O it was not given.

## Features
- **`Watchdog`**: resets the board if the event loop stops running
- **`BootGuard`**: notices a boot loop, so the app can fall back to a safe mode
- **`last_reset()` and `reset()`**: why the board last reset, telling a deliberate reset from a hang
- **`log_task_errors()`**: an exception escaping any task is logged with its traceback
- **`SystemMonitor`**: event loop lag, memory low water mark, uptime

## Usage

```python
reason = last_reset("/reset.txt")     # 'power-on', 'watchdog', 'crash', ...
guard = BootGuard("/boots.txt")       # .tripped after 3 boots that die early
if guard.tripped:
    safe_mode()
log_task_errors(logging.getLogger("app"))
monitor = SystemMonitor()
asyncio.create_task(guard.run())
asyncio.create_task(monitor.run())
asyncio.create_task(Watchdog().run()) # production only
```

## Reset Reasons

| Reason | Meaning |
|--------|---------|
| `'power-on'` | power applied |
| `'watchdog'` | the watchdog fired (on the RP2, also `mpremote reset`) |
| `'deep-sleep'` | woke from `deep_sleep()` |
| anything passed to `reset()` | a deliberate reset, e.g. `reset("crash", "/reset.txt")` |

On the RP2, `machine.reset()` reports as a watchdog reset, so `reset()` leaves a marker that `last_reset()` reports instead.

## Notes
- **The watchdog cannot be stopped once started**, including by `mpremote` interrupting the program to upload. Production builds only.
- **`BootGuard.mark_stable()`** counts a boot healthy early, for one that ends on purpose (a deep sleep). `deep_sleep(guard=...)` calls it.
- A steadily falling memory low water mark is a leak; a jagged one is fragmentation.
- `memory()`, `storage()` and `firmware()` read the rest.
- [Sleep](sleep.md) covers `deep_sleep()` and `wake_reason()`.
