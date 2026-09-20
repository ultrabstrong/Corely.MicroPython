"""Button handlers: one event per press, no repeat while held.

Timings here are deliberately generous: these tests run on a PC event loop
whose timer granularity is far coarser than the Pico's, so short polls would
make them flaky rather than meaningful.
"""

import asyncio
import unittest

import harness  # noqa: F401

from corely.action import Action
from corely.button import ButtonPressed, ButtonCycle
from corely.cycler import ActionCycler


POLL_MS = 5
DEBOUNCE_MS = 5
SETTLE_MS = 60


class FlagAction(Action):
	def __init__(self):
		self.is_on = False

	def on(self):
		self.is_on = True

	def off(self):
		self.is_on = False


async def start(button):
	"""Start the poll task and let it take its first reading."""
	task = asyncio.create_task(button.run())
	await asyncio.sleep_ms(SETTLE_MS)
	return task


async def tap(pin):
	"""Press and release the fake button, leaving time for the poll to see both."""
	pin.press()
	await asyncio.sleep_ms(SETTLE_MS)
	pin.release()
	await asyncio.sleep_ms(SETTLE_MS)


class ButtonPressedTests(unittest.IsolatedAsyncioTestCase):
	def make(self):
		presses = []
		button = ButtonPressed(
			0, lambda: presses.append(1), debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS
		)
		return button, presses

	async def test_calls_action_once_per_press(self):
		button, presses = self.make()
		task = await start(button)

		await tap(button.button)
		await tap(button.button)
		task.cancel()

		self.assertEqual(len(presses), 2)

	async def test_holding_does_not_repeat(self):
		button, presses = self.make()
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(SETTLE_MS * 4)
		task.cancel()

		self.assertEqual(len(presses), 1)

	async def test_starts_idle_when_button_already_held(self):
		"""A button held at startup must not fire until it is released first."""
		button, presses = self.make()
		button.button.press()

		task = asyncio.create_task(button.run())
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(presses, [])

		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		await tap(button.button)
		task.cancel()

		self.assertEqual(len(presses), 1)


class ButtonCycleTests(unittest.IsolatedAsyncioTestCase):
	async def test_press_advances_the_cycler(self):
		first, second = FlagAction(), FlagAction()
		cycler = ActionCycler([first, second])
		cycler.activate_current()

		button = ButtonCycle(1, cycler, debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS)
		task = await start(button)

		await tap(button.button)
		task.cancel()

		self.assertFalse(first.is_on)
		self.assertTrue(second.is_on)
		self.assertEqual(cycler.current_index, 1)


if __name__ == '__main__':
	unittest.main()
