"""Keeping a device alive unattended - and knowing what happened when it was not.

	Watchdog         resets the board if the event loop stops running
	BootGuard        notices a boot loop, so the app can fall back to safe mode
	last_reset()     why the board last reset, as a name
	reset()          a deliberate reset that the next boot can tell apart
	log_task_errors  a crashed task is logged, not just printed and forgotten
	SystemMonitor    event-loop lag, memory low-water mark and uptime

Board-agnostic: machine.WDT and machine.reset_cause exist on the RP2 and the
ESP32 alike. Anything chip-specific (core temperature, battery voltage) is the
app's business.

Files these use (the boot-guard count, the reset marker) are paths the app
hands in - Corely does no I/O it was not given.
"""

import asyncio
import gc
import os
import time

import machine


def _read(path, default=""):
	try:
		with open(path) as f:
			return f.read().strip()
	except OSError:
		return default


def _write(path, text):
	with open(path, "w") as f:
		f.write(text)


def _remove(path):
	try:
		os.remove(path)
	except OSError:
		pass


class Watchdog:
	"""The hardware watchdog, fed from inside the event loop.

	If anything blocks the loop, or the feeding task dies, feeding stops and
	the hardware resets the board after timeout_ms.

	Starting one cannot be undone until the board resets - including by
	`mpremote`, whose interrupt stops the feeding mid-upload. Keep it to
	production builds; see the app's safe mode for getting back in.
	"""

	# The timeout of the watchdog started this boot, or None. There is only
	# one hardware watchdog, and once started it runs until reset, so this is
	# what anything planning a long pause (a SleepCycle) checks.
	running_timeout_ms = None

	def __init__(self, timeout_ms=8000, feed_ms=None):
		"""
		Args:
			timeout_ms: How long without feeding before the reset. The RP2's
				maximum is about 8300.
			feed_ms: How often to feed - a quarter of the timeout by default
		"""
		self.timeout_ms = timeout_ms
		self.feed_ms = feed_ms or timeout_ms // 4
		self._wdt = machine.WDT(timeout=timeout_ms)
		Watchdog.running_timeout_ms = timeout_ms

	async def run(self):
		"""Feed forever. Start this with asyncio.create_task()."""
		while True:
			self._wdt.feed()
			await asyncio.sleep_ms(self.feed_ms)


class BootGuard:
	"""Counts boots that do not stay up, to catch a boot loop.

	Each boot adds one to a count on flash; staying up for stable_ms clears
	it. If the count passes `limit`, the last few boots all fell over early -
	`tripped` says so, and the app should come up in a safe, minimal mode
	instead of crashing again.

		guard = BootGuard("/boots.txt")
		if guard.tripped:
			safe_mode()
		asyncio.create_task(guard.run())
	"""

	def __init__(self, path, limit=3, stable_ms=60000):
		"""
		Args:
			path: A small file that holds the count between boots
			limit: Early deaths in a row before tripping
			stable_ms: How long a boot must last to count as healthy
		"""
		self.path = path
		self.limit = limit
		self.stable_ms = stable_ms
		try:
			self.count = int(_read(path, "0") or 0) + 1
		except ValueError:
			self.count = 1
		_write(path, str(self.count))
		self.tripped = self.count > limit
		self.stable = False

	async def run(self):
		"""Wait out stable_ms, then clear the count. Start with create_task()."""
		await asyncio.sleep_ms(self.stable_ms)
		_write(self.path, "0")
		self.stable = True


# Reset causes, named. On the RP2 machine.reset() is implemented with the
# watchdog, so a deliberate reset reports as one; reset() below leaves a
# marker so the next boot can tell them apart.
POWER_ON = 'power-on'
WATCHDOG = 'watchdog'
DEEP_SLEEP = 'deep-sleep'
OTHER = 'other'


def last_reset(marker_path):
	"""Why the board last reset.

	A reason left by reset() wins - 'crash', or whatever was passed. Otherwise
	the hardware's cause: 'power-on', 'watchdog' (which on the RP2 also covers
	an `mpremote reset`), 'deep-sleep' or 'other'.

	Args:
		marker_path: The file reset() writes its reason to
	"""
	reason = _read(marker_path)
	if reason:
		_remove(marker_path)
		return reason

	cause = machine.reset_cause()
	if cause == getattr(machine, "PWRON_RESET", None):
		return POWER_ON
	if cause == getattr(machine, "WDT_RESET", None):
		return WATCHDOG
	if cause == getattr(machine, "DEEPSLEEP_RESET", None):
		return DEEP_SLEEP
	return OTHER


def reset(reason, marker_path):
	"""Reset the board, leaving a reason for last_reset() to report.

	Args:
		reason: A short word, e.g. 'crash'
		marker_path: Where to leave it
	"""
	_write(marker_path, reason)
	machine.reset()


def log_task_errors(logger):
	"""Log any exception that escapes an asyncio task, with its traceback.

	Without this, a crashed task prints a line to a console nobody is watching
	and is gone, while everything else carries on as if nothing happened.

	Args:
		logger: A logging.Logger to report to
	"""
	from corely.logs import format_exception

	def handler(loop, context):
		error = context.get("exception")
		if error is None:
			logger.error("Task failed: %s", context.get("message"))
		else:
			logger.error("Task failed:\n%s", format_exception(error))

	asyncio.get_event_loop().set_exception_handler(handler)


def memory():
	"""Heap bytes free and in use, after a collection."""
	gc.collect()
	return {'free': gc.mem_free(), 'used': gc.mem_alloc()}


def storage(path="/"):
	"""Filesystem bytes total and free."""
	block, fragment, blocks, free = os.statvfs(path)[:4]
	size = fragment or block
	return {'total': blocks * size, 'free': free * size}


def firmware():
	"""What is running: (release, machine), e.g. ('1.27.0', 'Raspberry Pi
	Pico 2 W with RP2350')."""
	info = os.uname()
	return info.release, info.machine


class SystemMonitor:
	"""Watches the event loop and memory while the program runs.

	Every interval it measures how late its own sleep woke - the event loop's
	lag, which grows when something blocks it. Every `memory_every` it
	collects garbage and records free memory, keeping the lowest seen: a
	steadily falling low-water mark is a leak, a jagged one fragmentation.
	"""

	def __init__(self, interval_ms=100, memory_every_ms=10000):
		"""
		Args:
			interval_ms: How often to measure lag
			memory_every_ms: How often to collect and sample memory
		"""
		self.interval_ms = interval_ms
		self.memory_every_ms = memory_every_ms
		self.uptime_ms = time.ticks_ms()	# Since boot, to start with
		self.max_lag_ms = 0
		self.avg_lag_ms = 0.0
		self.collections = 0
		# Collect before the first reading, or uncollected garbage shows up as
		# a false low-water mark.
		self.mem_low = None
		self.sample_memory()

	@property
	def uptime_s(self):
		return self.uptime_ms / 1000

	def reset_max(self):
		"""Start a fresh worst-lag measurement, e.g. per stats line."""
		self.max_lag_ms = 0

	def sample_memory(self):
		gc.collect()
		self.collections += 1
		self.mem_free = gc.mem_free()
		self.mem_low = self.mem_free if self.mem_low is None else min(self.mem_low, self.mem_free)

	async def run(self):
		"""Monitor forever. Start this with asyncio.create_task()."""
		since_memory = 0
		while True:
			start = time.ticks_ms()
			await asyncio.sleep_ms(self.interval_ms)
			elapsed = time.ticks_diff(time.ticks_ms(), start)
			# Uptime accumulates deltas, so it outlives ticks_ms wrapping.
			self.uptime_ms += elapsed
			lag = max(0, elapsed - self.interval_ms)
			self.max_lag_ms = max(self.max_lag_ms, lag)
			self.avg_lag_ms += (lag - self.avg_lag_ms) * 0.05
			since_memory += elapsed
			if since_memory >= self.memory_every_ms:
				since_memory = 0
				self.sample_memory()
