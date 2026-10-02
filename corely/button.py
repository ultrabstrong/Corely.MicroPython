"""Button input - press, release, long press, double press and key repeat.

Buttons are polled from their own task. Polling (rather than a pin IRQ) keeps
debouncing simple and keeps callbacks out of interrupt context, and at a 10ms
poll interval the cost is negligible.

Wiring assumption: the button shorts the pin to ground and the pin uses an
internal pull-up, so a press reads 0.

When on_press fires depends on what else the button listens for:

| Also set                     | on_press fires                                  |
|------------------------------|-------------------------------------------------|
| nothing (or only on_release) | the moment the button goes down                 |
| repeat_ms                    | on the way down, then every repeat_ms while held|
| on_long_press / long_presses | on release, if it was not a long press          |
| on_double_press              | double_press_ms after release, if no 2nd press  |

The last two are the price of telling gestures apart: a press cannot be
called short until it is released, or single until the window for a second
press has passed. That is why both default to unset.
"""

import asyncio
import time
from machine import Pin

# When on_press fires, by which other gestures are set.
_ON_DOWN = 'down'				# Nothing to tell apart: straight away
_ON_RELEASE = 'release'			# Long presses: once it was not one
_AFTER_WINDOW = 'window'		# Double press: once no second press came


class Button:
	"""Calls a function per gesture: press, release, long press, double press.

	What each function does is the caller's business - print something, or
	step an ActionCycler:

		Button(0, on_press=lambda: print("pressed"))
		Button(1, on_press=led_cycler.move_next)
		Button(1, on_press=next_mode, on_long_press=reset, on_double_press=back)

	Several hold lengths can each do something, the way boards hold a button
	for settings and longer still for a factory reset:

		Button(1, long_presses={1000: settings, 10000: factory_reset})
	"""

	def __init__(self, pin_number, on_press=None, on_release=None,
				 on_long_press=None, on_double_press=None,
				 long_press_ms=1000, double_press_ms=400, repeat_ms=None,
				 long_presses=None, debounce_ms=50, poll_ms=10):
		"""
		Args:
			pin_number: GPIO pin number for the button
			on_press: Called for a press. When depends on the other gestures -
				see the module docstring.
			on_release: Called every time the button comes back up
			on_long_press: Called once, while still held, after long_press_ms.
				That press then does not also count as a press.
			on_double_press: Called when a second press starts within
				double_press_ms of the first one's release. Neither press
				then counts as a press. Delays on_press by double_press_ms.
			long_press_ms: How long a hold makes a long press
			double_press_ms: How soon after a release a second press must
				start to make a double press
			repeat_ms: If set, on_press repeats on this interval while held,
				like a held key. Cannot be combined with on_long_press,
				long_presses or on_double_press.
			long_presses: dict of hold length in ms to callback, for several
				long presses on one button. Each fires once, while still held,
				as its length is reached - so a 6s hold with {1000: a, 5000: b}
				calls a at 1s, then b at 5s. on_long_press joins it at
				long_press_ms.
			debounce_ms: Debounce time in milliseconds (default 50ms)
			poll_ms: How often to sample the pin (default 10ms)

		Every callback is a plain function that must not block - to kick off
		async work, call asyncio.create_task inside it. Any may be None.

		Raises:
			ValueError: If repeat_ms is combined with a long or double press,
				which both need on_press held back, or if two long presses
				share a length
		"""
		holds = dict(long_presses or {})
		if on_long_press is not None:
			if long_press_ms in holds:
				raise ValueError(f"Two long presses at {long_press_ms}ms")
			holds[long_press_ms] = on_long_press
		# (ms, callback), shortest first, so they fire in order while held.
		self._long_presses = sorted(holds.items(), key=lambda hold: hold[0])

		if repeat_ms is not None and (self._long_presses or on_double_press):
			raise ValueError(
				"repeat_ms fires on_press while held, so it cannot be combined "
				"with a long press or on_double_press"
			)

		self.button = Pin(pin_number, Pin.IN, Pin.PULL_UP)
		self.on_press = on_press
		self.on_release = on_release
		self.on_double_press = on_double_press
		self.double_press_ms = double_press_ms
		self.repeat_ms = repeat_ms
		self.debounce_ms = debounce_ms
		self.poll_ms = poll_ms

		# When on_press fires, settled once here rather than re-derived per
		# press - see the table in the module docstring.
		if on_double_press is not None:
			self._press_at = _AFTER_WINDOW
		elif self._long_presses:
			self._press_at = _ON_RELEASE
		else:
			self._press_at = _ON_DOWN

	@property
	def is_pressed(self):
		"""True while the button is held down."""
		return self.button.value() == 0

	async def wait_for_press(self):
		"""Wait for a debounced press (falling edge).

		Waits for release first, so holding the button down never repeats.
		"""
		await self._wait_until(False)
		await self._wait_until(True)

		# Let contact bounce settle before reporting the press.
		await asyncio.sleep_ms(self.debounce_ms)

	async def run(self):
		"""Run forever. Start this with asyncio.create_task()."""
		# A button held at startup is ignored until it is released.
		await self._wait_until(False)

		while True:
			await self._wait_until(True)
			await asyncio.sleep_ms(self.debounce_ms)
			long_pressed = await self._hold()
			await self._released()

			if long_pressed:
				continue	# A long press is never also a press
			if self._press_at == _ON_RELEASE:
				self._call(self.on_press)
			elif self._press_at == _AFTER_WINDOW:
				await self._single_or_double()

	async def _hold(self):
		"""Handle the time the button is down: the immediate press, key
		repeat, and each long press as its length is reached.

		Returns:
			True if it became a long press
		"""
		start = last_repeat = time.ticks_ms()
		if self._press_at == _ON_DOWN:
			self._call(self.on_press)

		reached = 0	# How many long presses have fired this hold
		while self.is_pressed:
			now = time.ticks_ms()
			held_ms = time.ticks_diff(now, start)
			while (reached < len(self._long_presses)
					and held_ms >= self._long_presses[reached][0]):
				self._call(self._long_presses[reached][1])
				reached += 1
			if (self.repeat_ms is not None
					and time.ticks_diff(now, last_repeat) >= self.repeat_ms):
				last_repeat = now
				self._call(self.on_press)
			await asyncio.sleep_ms(self.poll_ms)
		return reached > 0

	async def _single_or_double(self):
		"""After a release, wait out the double-press window.

		A second press inside it is a double press - reported on the way down,
		with its own release after. No second press means the first was single.
		"""
		if not await self._pressed_within(self.double_press_ms):
			self._call(self.on_press)
			return

		await asyncio.sleep_ms(self.debounce_ms)
		self._call(self.on_double_press)
		await self._wait_until(False)
		await self._released()

	async def _released(self):
		"""The button just came up: settle, then report the release."""
		await asyncio.sleep_ms(self.debounce_ms)
		self._call(self.on_release)

	async def _pressed_within(self, window_ms):
		"""True if a press starts within window_ms."""
		start = time.ticks_ms()
		while time.ticks_diff(time.ticks_ms(), start) < window_ms:
			if self.is_pressed:
				return True
			await asyncio.sleep_ms(self.poll_ms)
		return False

	async def _wait_until(self, pressed):
		while self.is_pressed != pressed:
			await asyncio.sleep_ms(self.poll_ms)

	@staticmethod
	def _call(callback):
		if callback is not None:
			callback()
