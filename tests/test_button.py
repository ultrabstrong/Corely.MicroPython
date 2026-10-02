"""Button: one event per press, whatever the press is wired to.

Timings here are deliberately generous: these tests run on a PC event loop
whose timer granularity is far coarser than the device's, so short polls would
make them flaky rather than meaningful.
"""

import asyncio
import unittest

import harness  # noqa: F401

from corely.action import Action, ActionCycler
from corely.button import Button


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


class ButtonTests(unittest.IsolatedAsyncioTestCase):
	def make(self):
		presses = []
		button = Button(
			0, lambda: presses.append(1), debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS
		)
		return button, presses

	async def test_calls_on_press_once_per_press(self):
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


LONG_PRESS_MS = 300
DOUBLE_PRESS_MS = 250


class GestureTests(unittest.IsolatedAsyncioTestCase):
	"""Release, long press, double press and repeat.

	Every gesture appends its name to one log, so ordering and exclusivity
	are both visible in a single assertion.
	"""

	def make(self, **gestures):
		log = []

		def record(name):
			return lambda: log.append(name)

		callbacks = {
			name: record(name.replace('on_', ''))
			for name in gestures.pop('listen', ('on_press',))
		}
		button = Button(
			0, debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS,
			long_press_ms=LONG_PRESS_MS, double_press_ms=DOUBLE_PRESS_MS,
			**callbacks, **gestures,
		)
		return button, log

	async def test_only_on_press_still_fires_on_the_way_down(self):
		button, log = self.make()
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(log, ['press'])

		button.button.release()
		task.cancel()

	async def test_release_fires_on_the_way_up(self):
		button, log = self.make(listen=('on_press', 'on_release'))
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(log, ['press'])

		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['press', 'release'])

	async def test_only_on_release_never_needs_on_press(self):
		button, log = self.make(listen=('on_release',))
		task = await start(button)

		await tap(button.button)
		task.cancel()

		self.assertEqual(log, ['release'])

	async def test_long_press_fires_while_held_and_replaces_the_press(self):
		button, log = self.make(listen=('on_press', 'on_long_press', 'on_release'))
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(LONG_PRESS_MS + SETTLE_MS * 2)
		self.assertEqual(log, ['long_press'])	# Still held

		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['long_press', 'release'])

	async def test_long_press_fires_once_however_long_it_is_held(self):
		button, log = self.make(listen=('on_long_press',))
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(LONG_PRESS_MS * 3)
		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['long_press'])

	async def test_short_press_is_a_press_on_release_when_long_press_is_set(self):
		button, log = self.make(listen=('on_press', 'on_long_press'))
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(log, [])	# Cannot tell yet

		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['press'])

	async def test_double_press_fires_on_the_second_press(self):
		button, log = self.make(listen=('on_press', 'on_double_press'))
		task = await start(button)

		await tap(button.button)
		button.button.press()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(log, ['double_press'])

		button.button.release()
		await asyncio.sleep_ms(DOUBLE_PRESS_MS + SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['double_press'])

	async def test_lone_press_fires_after_the_double_press_window(self):
		button, log = self.make(listen=('on_press', 'on_double_press'))
		task = await start(button)

		await tap(button.button)
		self.assertEqual(log, [])	# Window still open

		await asyncio.sleep_ms(DOUBLE_PRESS_MS + SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['press'])

	async def test_double_press_reports_both_releases(self):
		button, log = self.make(listen=('on_double_press', 'on_release'))
		task = await start(button)

		await tap(button.button)
		await tap(button.button)
		task.cancel()

		self.assertEqual(log, ['release', 'double_press', 'release'])

	async def test_long_press_is_never_half_of_a_double_press(self):
		button, log = self.make(listen=('on_press', 'on_long_press', 'on_double_press'))
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(LONG_PRESS_MS + SETTLE_MS)
		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		await tap(button.button)
		await asyncio.sleep_ms(DOUBLE_PRESS_MS + SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['long_press', 'press'])

	async def test_repeat_fires_while_held_and_stops_on_release(self):
		button, log = self.make(repeat_ms=100)
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(450)
		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		count = len(log)
		await asyncio.sleep_ms(300)
		task.cancel()

		# One on the way down plus about four repeats; the PC's timer is too
		# coarse to pin the exact number.
		self.assertGreaterEqual(count, 3)
		self.assertEqual(len(log), count)

	def test_repeat_cannot_combine_with_gestures_that_hold_back_on_press(self):
		with self.assertRaises(ValueError):
			Button(0, on_press=print, on_long_press=print, repeat_ms=100)
		with self.assertRaises(ValueError):
			Button(0, on_press=print, on_double_press=print, repeat_ms=100)
		with self.assertRaises(ValueError):
			Button(0, on_press=print, long_presses={500: print}, repeat_ms=100)


class LongPressesTests(unittest.IsolatedAsyncioTestCase):
	"""Several hold lengths on one button, each firing as it is reached."""

	FIRST_MS = 200
	SECOND_MS = 500

	def make(self, **extra):
		log = []
		button = Button(
			0, debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS,
			on_press=lambda: log.append('press'),
			on_release=lambda: log.append('release'),
			long_presses={
				# Deliberately out of order: they must still fire shortest first.
				self.SECOND_MS: lambda: log.append('extra_long'),
				self.FIRST_MS: lambda: log.append('long'),
			},
			**extra,
		)
		return button, log

	async def test_each_length_fires_in_turn_while_held(self):
		button, log = self.make()
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(self.FIRST_MS + SETTLE_MS)
		self.assertEqual(log, ['long'])

		await asyncio.sleep_ms(self.SECOND_MS - self.FIRST_MS)
		self.assertEqual(log, ['long', 'extra_long'])

		button.button.release()
		await asyncio.sleep_ms(SETTLE_MS)
		task.cancel()

		self.assertEqual(log, ['long', 'extra_long', 'release'])

	async def test_letting_go_early_fires_only_the_lengths_reached(self):
		button, log = self.make()
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(self.FIRST_MS + SETTLE_MS)
		button.button.release()
		await asyncio.sleep_ms(self.SECOND_MS)
		task.cancel()

		self.assertEqual(log, ['long', 'release'])

	async def test_short_press_is_still_a_press(self):
		button, log = self.make()
		task = await start(button)

		await tap(button.button)
		task.cancel()

		self.assertEqual(log, ['release', 'press'])

	async def test_on_long_press_joins_the_lengths(self):
		log = []
		button = Button(
			0, debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS,
			on_long_press=lambda: log.append('long'), long_press_ms=self.FIRST_MS,
			long_presses={self.SECOND_MS: lambda: log.append('extra_long')},
		)
		task = await start(button)

		button.button.press()
		await asyncio.sleep_ms(self.SECOND_MS + SETTLE_MS)
		button.button.release()
		task.cancel()

		self.assertEqual(log, ['long', 'extra_long'])

	def test_two_long_presses_at_one_length_is_an_error(self):
		with self.assertRaises(ValueError):
			Button(0, on_long_press=print, long_press_ms=1000, long_presses={1000: print})

	def test_is_pressed_reads_the_pin(self):
		button = Button(0)
		self.assertFalse(button.is_pressed)
		button.button.press()
		self.assertTrue(button.is_pressed)


class ButtonDrivingACyclerTests(unittest.IsolatedAsyncioTestCase):
	async def test_press_advances_the_cycler(self):
		"""The case that used to need its own class."""
		first, second = FlagAction(), FlagAction()
		cycler = ActionCycler([first, second])
		cycler.on()

		button = Button(1, cycler.move_next, debounce_ms=DEBOUNCE_MS, poll_ms=POLL_MS)
		task = await start(button)

		await tap(button.button)
		task.cancel()

		self.assertFalse(first.is_on)
		self.assertTrue(second.is_on)
		self.assertEqual(cycler.current_index, 1)


if __name__ == '__main__':
	unittest.main()
