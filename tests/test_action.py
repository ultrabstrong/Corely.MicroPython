"""TaskAction lifecycle: start, cancel, cleanup, restart.

Timings are deliberately generous. A PC event loop has much coarser timer
granularity than the device (~15ms on Windows), so a short work interval plus a
short wait is a coin flip rather than a test.
"""

import asyncio
import unittest

import harness  # noqa: F401  (sets up sys.path and MicroPython shims)

from corely.action import TaskAction


WORK_MS = 5     # how often the fake work loops
SETTLE_MS = 80  # long enough for several loops, whatever the host granularity


class CountingAction(TaskAction):
	"""Counts loop iterations and cleanups so tests can see the lifecycle."""

	def __init__(self):
		super().__init__()
		self.iterations = 0
		self.cleanups = 0

	async def run(self):
		while True:
			self.iterations += 1
			await asyncio.sleep_ms(WORK_MS)

	def cleanup(self):
		self.cleanups += 1


class FinishingAction(TaskAction):
	"""Work that ends on its own rather than running forever."""

	def __init__(self):
		super().__init__()
		self.finished = False
		self.cleanups = 0

	async def run(self):
		await asyncio.sleep_ms(WORK_MS)
		self.finished = True

	def cleanup(self):
		self.cleanups += 1


class TaskActionTests(unittest.IsolatedAsyncioTestCase):
	async def test_on_starts_work(self):
		action = CountingAction()
		self.assertFalse(action.is_on)

		action.on()
		self.assertTrue(action.is_on)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertGreater(action.iterations, 1)

	async def test_off_stops_work_and_cleans_up(self):
		action = CountingAction()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)

		action.off()
		self.assertFalse(action.is_on)
		self.assertEqual(action.cleanups, 1)

		stopped_at = action.iterations
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(action.iterations, stopped_at)

	async def test_on_twice_starts_one_task(self):
		action = CountingAction()
		action.on()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)
		first_run = action.iterations

		action.off()
		await asyncio.sleep_ms(SETTLE_MS)

		# A second task would have kept counting past the stop.
		self.assertEqual(action.iterations, first_run)

	async def test_off_is_safe_to_call_twice(self):
		action = CountingAction()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)

		action.off()
		action.off()

		self.assertFalse(action.is_on)

	async def test_restart_keeps_only_the_new_task(self):
		"""off() then on() must not let the dying task clean up the new one."""
		action = CountingAction()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)

		action.off()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertTrue(action.is_on)
		running = action.iterations
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertGreater(action.iterations, running)

	async def test_cleanup_runs_when_work_ends_on_its_own(self):
		action = FinishingAction()
		action.on()
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertTrue(action.finished)
		self.assertEqual(action.cleanups, 1)
		self.assertFalse(action.is_on)


if __name__ == '__main__':
	unittest.main()
