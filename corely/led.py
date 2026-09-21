"""LED actions.

`pin_number` accepts anything `machine.Pin` does: a GPIO number (18), or a
board-specific pin name where the port provides one ("LED" is the onboard LED
on the Pico W and Pico 2 W).
"""

import asyncio
from machine import Pin

from corely.action import Action, TaskAction


class Led(TaskAction):
	"""One LED, solid or blinking.

	Solid is the default and starts no task, so it costs nothing to run:

		Led(18)                          # on() lights it
		Led(18, blink_interval_ms=250)   # on() blinks it

	The mode can change while the LED is on, so one object owns the pin for the
	life of the program rather than several fighting over it.
	"""

	DEFAULT_BLINK_MS = 500

	def __init__(self, pin_number, blink_interval_ms=None, debug=False):
		"""
		Args:
			pin_number: GPIO pin number (or board pin name) for the LED
			blink_interval_ms: Time between toggles, or None for solid
			debug: If True, prints debug messages when the LED changes state
		"""
		super().__init__()
		self.pin_number = pin_number
		self.led = Pin(pin_number, Pin.OUT)
		self.blink_interval_ms = blink_interval_ms
		self.debug = debug
		self._active = False

	@property
	def is_on(self):
		"""True while the LED is meant to be lit, blinking included."""
		return self._active

	@property
	def is_blinking(self):
		return self.blink_interval_ms is not None

	def on(self):
		self._active = True
		if self.is_blinking:
			super().on()
		else:
			self.led.value(1)
		if self.debug:
			mode = f"BLINKING at {self.blink_interval_ms}ms" if self.is_blinking else "ON"
			print(f"LED on pin {self.pin_number} {mode}")

	def off(self):
		self._active = False
		# Cancels the blink task if there is one, and cleanup() darkens the pin.
		super().off()
		if self.debug:
			print(f"LED on pin {self.pin_number} OFF")

	def blink(self, interval_ms=None):
		"""Switch to blinking, taking effect immediately if the LED is on.

		Args:
			interval_ms: New interval, or None to keep the current one
		"""
		if interval_ms is not None:
			self.blink_interval_ms = interval_ms
		elif self.blink_interval_ms is None:
			self.blink_interval_ms = self.DEFAULT_BLINK_MS

		if self._active:
			super().off()
			super().on()

	def solid(self):
		"""Switch to steady, taking effect immediately if the LED is on."""
		self.blink_interval_ms = None
		if self._active:
			super().off()
			self.led.value(1)

	def blinking(self, interval_ms=None):
		"""An Action that blinks this LED while active.

		Lets two states share one LED without fighting over the pin - a state
		machine holds one of these per state:

			onboard = Led("LED")
			advertising_action = onboard.blinking(500)
			connected_action = onboard.steady()
		"""
		return _LedMode(self, interval_ms or self.blink_interval_ms or self.DEFAULT_BLINK_MS)

	def steady(self):
		"""An Action that lights this LED steadily while active."""
		return _LedMode(self, None)

	async def run(self):
		while True:
			self.led.value(1)
			await asyncio.sleep_ms(self.blink_interval_ms)
			self.led.value(0)
			await asyncio.sleep_ms(self.blink_interval_ms)

	def cleanup(self):
		self.led.value(0)


class _LedMode(Action):
	"""Drives a shared Led into one mode while active.

	Created by Led.blinking() and Led.steady() rather than directly.
	"""

	def __init__(self, led, blink_interval_ms):
		self.led = led
		self.blink_interval_ms = blink_interval_ms

	def on(self):
		if self.blink_interval_ms is None:
			self.led.solid()
		else:
			self.led.blink(self.blink_interval_ms)
		self.led.on()

	def off(self):
		self.led.off()
