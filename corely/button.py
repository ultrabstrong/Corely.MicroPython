"""Button handlers.

Buttons are polled from their own task. Polling (rather than a pin IRQ) keeps
debouncing simple and keeps callbacks out of interrupt context, and at a 10ms
poll interval the cost is negligible.

Wiring assumption: button shorts the pin to ground, pin uses an internal
pull-up, so a press reads 0.
"""

import asyncio
from machine import Pin


class _ButtonBase:
	def __init__(self, pin_number, debounce_ms=50, poll_ms=10):
		self.button = Pin(pin_number, Pin.IN, Pin.PULL_UP)
		self.debounce_ms = debounce_ms
		self.poll_ms = poll_ms

	async def wait_for_press(self):
		"""Wait for a debounced press (falling edge).

		Waits for release first, so holding the button down never repeats.
		"""
		while self.button.value() == 0:
			await asyncio.sleep_ms(self.poll_ms)

		while self.button.value() == 1:
			await asyncio.sleep_ms(self.poll_ms)

		# Let contact bounce settle before reporting the press.
		await asyncio.sleep_ms(self.debounce_ms)


class ButtonPressed(_ButtonBase):
	"""Calls a function on every button press."""

	def __init__(self, pin_number, action, debounce_ms=50, poll_ms=10):
		"""
		Args:
			pin_number: GPIO pin number for the button
			action: Plain function to call on each press. It must not block -
				to kick off async work, call asyncio.create_task inside it.
			debounce_ms: Debounce time in milliseconds (default 50ms)
			poll_ms: How often to sample the pin (default 10ms)
		"""
		super().__init__(pin_number, debounce_ms, poll_ms)
		self.action = action

	async def run(self):
		"""Run forever. Start this with asyncio.create_task()."""
		while True:
			await self.wait_for_press()
			self.action()


class ButtonCycle(_ButtonBase):
	"""Advances an ActionCycler on every button press."""

	def __init__(self, pin_number, action_cycler, debounce_ms=50, poll_ms=10):
		"""
		Args:
			pin_number: GPIO pin number for the button
			action_cycler: ActionCycler instance to advance
			debounce_ms: Debounce time in milliseconds (default 50ms)
			poll_ms: How often to sample the pin (default 10ms)
		"""
		super().__init__(pin_number, debounce_ms, poll_ms)
		self.action_cycler = action_cycler

	async def run(self):
		"""Run forever. Start this with asyncio.create_task()."""
		while True:
			await self.wait_for_press()
			self.action_cycler.move_next()
