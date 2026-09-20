"""LED actions.

Pin numbers may be a GPIO number (18) or a name ("LED" for the onboard LED).
"""

import asyncio
from machine import Pin

from corely.action import Action, TaskAction


class LedSolid(Action):
	"""Turns an LED on while active."""

	def __init__(self, pin_number, debug=False):
		"""
		Args:
			pin_number: GPIO pin number (or "LED") for the LED
			debug: If True, prints debug messages when the LED changes state
		"""
		self.pin_number = pin_number
		self.led = Pin(pin_number, Pin.OUT)
		self.debug = debug

	def on(self):
		self.led.value(1)
		if self.debug:
			print(f"LED on pin {self.pin_number} ON")

	def off(self):
		self.led.value(0)
		if self.debug:
			print(f"LED on pin {self.pin_number} OFF")


class LedBlinking(TaskAction):
	"""Blinks an LED at a fixed interval while active."""

	def __init__(self, pin_number, blink_interval_ms=500, debug=False):
		"""
		Args:
			pin_number: GPIO pin number (or "LED") for the LED
			blink_interval_ms: Time in milliseconds between toggles (default 500ms)
			debug: If True, prints debug messages when the LED changes state
		"""
		super().__init__()
		self.pin_number = pin_number
		self.led = Pin(pin_number, Pin.OUT)
		self.blink_interval_ms = blink_interval_ms
		self.debug = debug

	def on(self):
		super().on()
		if self.debug:
			print(f"LED on pin {self.pin_number} BLINKING at {self.blink_interval_ms}ms")

	def off(self):
		super().off()
		if self.debug:
			print(f"LED on pin {self.pin_number} BLINK OFF")

	async def run(self):
		while True:
			self.led.value(1)
			await asyncio.sleep_ms(self.blink_interval_ms)
			self.led.value(0)
			await asyncio.sleep_ms(self.blink_interval_ms)

	def cleanup(self):
		self.led.value(0)
