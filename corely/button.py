"""Button input.

Buttons are polled from their own task. Polling (rather than a pin IRQ) keeps
debouncing simple and keeps callbacks out of interrupt context, and at a 10ms
poll interval the cost is negligible.

Wiring assumption: the button shorts the pin to ground and the pin uses an
internal pull-up, so a press reads 0.
"""

import asyncio
from machine import Pin


class Button:
	"""Calls a function on every press.

	What that function does is the caller's business - print something, or step
	an ActionCycler:

		Button(0, on_press=lambda: print("pressed"))
		Button(1, on_press=led_cycler.move_next)
	"""

	def __init__(self, pin_number, on_press, debounce_ms=50, poll_ms=10):
		"""
		Args:
			pin_number: GPIO pin number for the button
			on_press: Plain function called on each press. It must not block -
				to kick off async work, call asyncio.create_task inside it.
			debounce_ms: Debounce time in milliseconds (default 50ms)
			poll_ms: How often to sample the pin (default 10ms)
		"""
		self.button = Pin(pin_number, Pin.IN, Pin.PULL_UP)
		self.on_press = on_press
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

	async def run(self):
		"""Run forever. Start this with asyncio.create_task()."""
		while True:
			await self.wait_for_press()
			self.on_press()
