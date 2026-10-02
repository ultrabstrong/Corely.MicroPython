"""System: watchdog feeding, boot-loop detection, reset reasons, task errors."""

import asyncio
import os
import shutil
import tempfile
import unittest
from collections import namedtuple
from unittest import mock

import harness  # noqa: F401

import machine
from corely import system
from corely.system import BootGuard, SystemMonitor, Watchdog, last_reset, reset


class FileTestCase(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp()
		machine.next_reset_cause = machine.PWRON_RESET
		machine.resets.clear()

	def tearDown(self):
		shutil.rmtree(self.dir)

	def path(self, name):
		return os.path.join(self.dir, name)


class WatchdogTests(unittest.IsolatedAsyncioTestCase):
	async def test_feeds_while_the_loop_runs(self):
		dog = Watchdog(timeout_ms=200)
		task = asyncio.create_task(dog.run())

		await asyncio.sleep(0.3)
		task.cancel()

		self.assertGreaterEqual(dog._wdt.feeds, 4)
		self.assertEqual(dog._wdt.timeout, 200)

	async def test_feeds_every_quarter_timeout_by_default(self):
		self.assertEqual(Watchdog(timeout_ms=8000).feed_ms, 2000)


class BootGuardTests(FileTestCase):
	def test_trips_after_too_many_early_deaths(self):
		path = self.path("boots.txt")
		results = [BootGuard(path, limit=3).tripped for _ in range(4)]

		self.assertEqual(results, [False, False, False, True])

	def test_a_stable_boot_clears_the_count(self):
		path = self.path("boots.txt")
		BootGuard(path, limit=3)
		BootGuard(path, limit=3)
		guard = BootGuard(path, limit=3, stable_ms=10)

		asyncio.run(guard.run())

		self.assertTrue(guard.stable)
		self.assertFalse(BootGuard(path, limit=3).tripped)
		self.assertEqual(BootGuard(path, limit=3).count, 2)

	def test_a_garbled_count_starts_again(self):
		path = self.path("boots.txt")
		with open(path, "w") as f:
			f.write("??")

		self.assertEqual(BootGuard(path).count, 1)


class ResetReasonTests(FileTestCase):
	def test_hardware_causes_have_names(self):
		marker = self.path("reset.txt")

		machine.next_reset_cause = machine.PWRON_RESET
		self.assertEqual(last_reset(marker), system.POWER_ON)
		machine.next_reset_cause = machine.WDT_RESET
		self.assertEqual(last_reset(marker), system.WATCHDOG)
		machine.next_reset_cause = 99
		self.assertEqual(last_reset(marker), system.OTHER)

	def test_a_deliberate_reset_is_told_apart_from_the_watchdog(self):
		"""On the RP2 machine.reset() reports as a watchdog reset."""
		marker = self.path("reset.txt")

		reset("crash", marker)
		machine.next_reset_cause = machine.WDT_RESET

		self.assertEqual(machine.resets, [True])
		self.assertEqual(last_reset(marker), "crash")
		# The marker is used up: the next reset is the hardware's again.
		self.assertEqual(last_reset(marker), system.WATCHDOG)


class TaskErrorTests(unittest.TestCase):
	def test_a_crashed_task_is_logged_with_its_traceback(self):
		logger = mock.Mock()

		async def scenario():
			system.log_task_errors(logger)

			async def broken():
				raise ValueError("sensor gone")

			task = asyncio.get_event_loop().create_task(broken())
			await asyncio.sleep(0.05)
			del task	# CPython reports an unretrieved exception on collection
			import gc
			gc.collect()
			await asyncio.sleep(0.05)

		asyncio.run(scenario())

		logged = " ".join(str(arg) for call in logger.error.call_args_list for arg in call.args)
		self.assertIn("ValueError: sensor gone", logged)


class HelperTests(unittest.TestCase):
	def test_memory_reports_free_and_used(self):
		self.assertEqual(set(system.memory()), {'free', 'used'})

	def test_storage_from_statvfs(self):
		statvfs = (4096, 4096, 640, 499, 499, 0, 0, 0, 0, 255)
		with mock.patch.object(system.os, "statvfs", create=True, return_value=statvfs):
			self.assertEqual(system.storage(), {'total': 640 * 4096, 'free': 499 * 4096})

	def test_firmware_from_uname(self):
		Uname = namedtuple("Uname", "sysname nodename release version machine")
		uname = Uname("rp2", "rp2", "1.27.0", "v1.27.0", "Raspberry Pi Pico 2 W with RP2350")
		with mock.patch.object(system.os, "uname", create=True, return_value=uname):
			self.assertEqual(system.firmware(), ("1.27.0", "Raspberry Pi Pico 2 W with RP2350"))


class SystemMonitorTests(unittest.IsolatedAsyncioTestCase):
	async def test_measures_lag_and_uptime(self):
		monitor = SystemMonitor(interval_ms=20, memory_every_ms=60)
		start = monitor.uptime_ms
		task = asyncio.create_task(monitor.run())

		await asyncio.sleep(0.25)
		task.cancel()

		self.assertGreater(monitor.uptime_ms - start, 150)
		self.assertGreaterEqual(monitor.max_lag_ms, 0)
		self.assertGreaterEqual(monitor.collections, 1)

	async def test_sees_a_blocked_loop(self):
		import time
		monitor = SystemMonitor(interval_ms=20)
		task = asyncio.create_task(monitor.run())
		await asyncio.sleep(0.05)

		time.sleep(0.2)		# Block the loop, the way a careless driver would
		await asyncio.sleep(0.05)
		task.cancel()

		self.assertGreaterEqual(monitor.max_lag_ms, 150)

	def test_reset_max_starts_a_fresh_measurement(self):
		monitor = SystemMonitor()
		monitor.max_lag_ms = 99

		monitor.reset_max()

		self.assertEqual(monitor.max_lag_ms, 0)


if __name__ == '__main__':
	unittest.main()
