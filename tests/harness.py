"""Makes Corely importable and runnable on a PC.

Two gaps to bridge:

1. Module layout - `machine` and `network` only exist on the device, and the
   `corely` package sits next to this folder rather than in `/lib`. Both are
   handled by putting `tests/stubs` and the repo root on sys.path.
2. MicroPython-only API - `time.ticks_ms()`, `asyncio.sleep_ms()` and
   `asyncio.wait_for_ms()` are not in CPython, so they are patched in here.

Import this module before importing anything from Corely.
"""

import asyncio
import os
import sys
import time

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_TESTS_DIR)
_STUBS_DIR = os.path.join(_TESTS_DIR, 'stubs')

for path in (_STUBS_DIR, _ROOT_DIR):
	if path not in sys.path:
		sys.path.insert(0, path)


def _ticks_ms():
	return int(time.monotonic() * 1000)


def _ticks_diff(a, b):
	return a - b


def _ticks_add(ticks, delta):
	return ticks + delta


async def _sleep_ms(ms):
	await asyncio.sleep(ms / 1000)


async def _wait_for_ms(awaitable, timeout_ms):
	return await asyncio.wait_for(awaitable, timeout_ms / 1000)


# MicroPython's time module has monotonic tick helpers; CPython's does not.
if not hasattr(time, 'ticks_ms'):
	time.ticks_ms = _ticks_ms
	time.ticks_diff = _ticks_diff
	time.ticks_add = _ticks_add
	time.sleep_us = lambda us: time.sleep(us / 1_000_000)

# MicroPython's gc reports heap use; CPython's does not. Fixed numbers are
# enough for the code that reads them.
import gc  # noqa: E402
if not hasattr(gc, 'mem_free'):
	gc.mem_free = lambda: 400000
	gc.mem_alloc = lambda: 50000

# MicroPython's asyncio has millisecond variants; CPython's does not.
if not hasattr(asyncio, 'sleep_ms'):
	asyncio.sleep_ms = _sleep_ms
	asyncio.wait_for_ms = _wait_for_ms
