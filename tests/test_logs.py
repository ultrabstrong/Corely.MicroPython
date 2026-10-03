"""Logs: rotation caps the flash used, lines carry boot and uptime."""

import logging
import os
import shutil
import tempfile
import unittest

import harness  # noqa: F401

from corely.logs import RotatingFileHandler, boot_number, format_exception, utc_stamp


class Record:
	"""What MicroPython's logging hands a handler."""

	def __init__(self, message, levelno=40, levelname="ERROR", name="test"):
		self.message = message
		self.levelno = levelno
		self.levelname = levelname
		self.name = name


class LogTestCase(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp()
		self.path = os.path.join(self.dir, "log.txt")

	def tearDown(self):
		shutil.rmtree(self.dir)

	def make(self, **kwargs):
		kwargs.setdefault("uptime_s", lambda: 12.34)
		return RotatingFileHandler(self.path, **kwargs)

	def read(self, path=None):
		with open(path or self.path) as f:
			return f.read()


class LineFormatTests(LogTestCase):
	def test_line_carries_boot_uptime_level_and_name(self):
		handler = self.make(boot=7)

		handler.emit(Record("BME280 read failed", name="corely.sensors"))

		self.assertEqual(self.read(), "#7 +12.3s ERROR corely.sensors: BME280 read failed\n")

	def test_below_the_level_is_not_written(self):
		handler = self.make()

		handler.emit(Record("chatty", levelno=20, levelname="INFO"))

		self.assertFalse(os.path.exists(self.path))

	def test_works_as_a_cpython_logging_handler(self):
		"""Corely's own modules log through whatever `logging` is present."""
		handler = self.make(boot=1)
		logger = logging.getLogger("test.logs")
		logger.addHandler(handler)
		logger.propagate = False
		try:
			logger.error("from %s", "cpython")
		finally:
			logger.removeHandler(handler)

		self.assertIn("ERROR test.logs: from cpython", self.read())

	def test_starts_with_utc_once_the_clock_is_set(self):
		stamp = [None]
		handler = self.make(boot=7, wall_clock=lambda: stamp[0])

		handler.emit(Record("before"))
		stamp[0] = utc_stamp(1790996299)
		handler.emit(Record("after"))

		self.assertEqual(self.read(),
			"#7 +12.3s ERROR test: before\n"
			"2026-10-03T02:58:19Z #7 +12.3s ERROR test: after\n")


class RotationTests(LogTestCase):
	def fill(self, handler, lines):
		for i in range(lines):
			handler.emit(Record("line {:03d} ".format(i) + "x" * 40))

	def test_rotates_at_the_size_cap(self):
		handler = self.make(max_bytes=500, backups=2)

		self.fill(handler, 20)

		self.assertLessEqual(os.path.getsize(self.path), 500)
		self.assertTrue(os.path.exists(handler.backup(1)))

	def test_never_keeps_more_than_the_backups(self):
		handler = self.make(max_bytes=200, backups=2)

		self.fill(handler, 100)

		self.assertTrue(os.path.exists(handler.backup(2)))
		self.assertFalse(os.path.exists(handler.backup(3)))
		self.assertLessEqual(handler.total_bytes(), 3 * 200)

	def test_newest_lines_are_in_the_live_file(self):
		handler = self.make(max_bytes=300, backups=1)

		self.fill(handler, 30)

		self.assertIn("line 029", self.read())
		self.assertNotIn("line 029", self.read(handler.backup(1)))

	def test_no_backups_just_truncates(self):
		handler = self.make(max_bytes=200, backups=0)

		self.fill(handler, 30)

		self.assertLessEqual(os.path.getsize(self.path), 200)
		self.assertEqual(handler.closed_files(), [])

	def test_closed_files_lists_rotated_files_oldest_first(self):
		handler = self.make(max_bytes=200, backups=3)

		self.fill(handler, 100)

		self.assertEqual(handler.closed_files(), [handler.backup(3), handler.backup(2), handler.backup(1)])

	def test_picks_up_an_existing_file_size(self):
		with open(self.path, "w") as f:
			f.write("x" * 190 + "\n")
		handler = self.make(max_bytes=200, backups=1)

		self.fill(handler, 1)

		self.assertTrue(os.path.exists(handler.backup(1)))


class TailTests(LogTestCase):
	def test_tail_returns_the_last_lines(self):
		handler = self.make()
		for word in ("one", "two", "three", "four"):
			handler.emit(Record(word))

		tail = handler.tail(2)

		self.assertEqual(len(tail), 2)
		self.assertTrue(tail[0].endswith("three"))
		self.assertTrue(tail[1].endswith("four"))

	def test_tail_of_nothing_is_empty(self):
		self.assertEqual(self.make().tail(), [])

	def test_tail_skips_a_partial_first_line(self):
		handler = self.make()
		for i in range(50):
			handler.emit(Record("entry {}".format(i)))

		tail = handler.tail(50, max_read=100)

		self.assertTrue(all(line.startswith("#") for line in tail))


class BootNumberTests(LogTestCase):
	def test_counts_up_from_one(self):
		path = os.path.join(self.dir, "boot.txt")

		self.assertEqual(boot_number(path), 1)
		self.assertEqual(boot_number(path), 2)
		self.assertEqual(boot_number(path), 3)

	def test_a_garbled_file_starts_again(self):
		path = os.path.join(self.dir, "boot.txt")
		with open(path, "w") as f:
			f.write("not a number")

		self.assertEqual(boot_number(path), 1)


class FormatExceptionTests(unittest.TestCase):
	def test_includes_the_error_and_where(self):
		try:
			raise ValueError("bad reading")
		except ValueError as e:
			text = format_exception(e)

		self.assertIn("ValueError: bad reading", text)
		self.assertIn("test_logs.py", text)


if __name__ == '__main__':
	unittest.main()
