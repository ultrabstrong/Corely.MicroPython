"""Logging to flash that cannot fill it, and survives a crash mid-write.

Uses the standard `logging` API (micropython-lib's, vendored), so Corely and
the app log the way any Python does. This module adds what that lacks:

	RotatingFileHandler  a size-capped log file with numbered backups
	boot_number()        a count of boots, since the clock resets with the board
	format_exception()   a traceback as text, on MicroPython or CPython

Lines carry the boot number and uptime instead of a time of day - there is no
wall clock until something sets one:

	#12 +3602.4s ERROR corely.sensors: BME280 read failed: [Errno 5] EIO

Setting it up is the app's job (Corely does no I/O it was not given):

	handler = RotatingFileHandler("/log.txt", boot=boot_number("/boot.txt"))
	logging.getLogger().addHandler(handler)

Every line opens, appends and closes the file, so nothing sits in a buffer
when the board resets. That costs a little per line, which is why only
warnings and worse are meant to go to flash, never every reading.
"""

import os
import sys
import time

# Levels, matching the logging module's, for the default threshold.
WARNING = 30


def _size(path):
	"""Bytes in a file, or 0 if it does not exist."""
	try:
		return os.stat(path)[6]
	except OSError:
		return 0


def _remove(path):
	try:
		os.remove(path)
	except OSError:
		pass


def boot_number(path):
	"""Count this boot, returning its number (1 for the first ever).

	Args:
		path: A small file that holds the count between boots
	"""
	try:
		with open(path) as f:
			count = int(f.read().strip() or 0)
	except (OSError, ValueError):
		count = 0
	count += 1
	with open(path, "w") as f:
		f.write(str(count))
	return count


def format_exception(error):
	"""An exception and its traceback as text."""
	if hasattr(sys, "print_exception"):
		import io
		buf = io.StringIO()
		sys.print_exception(error, buf)
		return buf.getvalue().rstrip()
	import traceback
	return "".join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip()


class RotatingFileHandler:
	"""A logging handler writing to a file that rotates at a size cap.

	When the file passes max_bytes it becomes path.1, path.1 becomes path.2,
	and so on up to `backups`; the oldest is deleted. The most flash it can
	ever use is (backups + 1) * max_bytes - 64KB with the defaults.
	"""

	def __init__(self, path, max_bytes=16384, backups=3, level=WARNING, boot=0,
				 uptime_s=None):
		"""
		Args:
			path: The live log file, e.g. "/log.txt"
			max_bytes: Size at which the live file rotates
			backups: Rotated files to keep
			level: The least severe level written (WARNING by default)
			boot: The boot number to stamp on each line, from boot_number()
			uptime_s: Function returning seconds since boot. Defaults to
				MicroPython's time.ticks_ms(), which counts from boot.
		"""
		self.path = path
		self.max_bytes = max_bytes
		self.backups = backups
		self.level = level
		self.boot = boot
		self.uptime_s = uptime_s or (lambda: time.ticks_ms() / 1000)
		self._size = _size(path)

	def setLevel(self, level):
		self.level = level

	def setFormatter(self, formatter):
		"""Accepted for compatibility; lines always use this handler's format."""

	def close(self):
		"""Nothing is held open between lines."""

	def format(self, record):
		message = getattr(record, "message", None)
		if message is None:
			message = record.getMessage()	# CPython's LogRecord
		return "#{} +{:.1f}s {} {}: {}".format(
			self.boot, self.uptime_s(), record.levelname, record.name, message)

	def emit(self, record):
		if record.levelno < self.level:
			return
		line = self.format(record) + "\n"
		if self._size and self._size + len(line) > self.max_bytes:
			self.rotate()
		with open(self.path, "a") as f:
			f.write(line)
		self._size += len(line)

	def handle(self, record):
		"""CPython's Logger calls handle(); MicroPython's calls emit()."""
		self.emit(record)

	def rotate(self):
		"""Shift path to path.1, path.1 to path.2, ..., dropping the oldest."""
		_remove(self.backup(self.backups))
		for n in range(self.backups - 1, 0, -1):
			try:
				os.rename(self.backup(n), self.backup(n + 1))
			except OSError:
				pass
		if self.backups:
			try:
				os.rename(self.path, self.backup(1))
			except OSError:
				pass
		else:
			_remove(self.path)
		self._size = 0

	def backup(self, n):
		"""The path of the nth rotated file (1 is the newest)."""
		return "{}.{}".format(self.path, n)

	def closed_files(self):
		"""Rotated files that exist, oldest first - what a log shipper sends
		and then deletes. The live file is never included."""
		files = []
		for n in range(self.backups, 0, -1):
			if _size(self.backup(n)):
				files.append(self.backup(n))
		return files

	def total_bytes(self):
		"""Flash used by the live file and its backups."""
		return _size(self.path) + sum(_size(self.backup(n)) for n in range(1, self.backups + 1))

	def tail(self, lines=3, max_read=1024):
		"""The last few lines of the live file, oldest first.

		Args:
			lines: How many lines
			max_read: Bytes to read from the end - enough for a few lines
				without loading the whole file into RAM
		"""
		size = _size(self.path)
		if not size:
			return []
		with open(self.path) as f:
			start = max(0, size - max_read)
			f.seek(start)
			text = f.read()
		found = text.split("\n")
		if start:
			found = found[1:]	# Drop the partial first line
		return [line for line in found if line][-lines:]
