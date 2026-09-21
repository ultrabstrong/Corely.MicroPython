"""LED actions.

`pin_number` accepts anything `machine.Pin` does: a GPIO number (18), or a
board-specific pin name where the port provides one ("LED" is the onboard LED
on the Pico W and Pico 2 W).

Full brightness drives the pin digitally. Anything dimmer needs PWM, which the
LED sets up on demand - so a pin that cannot do PWM (the Pico W's onboard LED
lives on the wireless chip, not a GPIO) can only be full brightness.
"""

import asyncio
from machine import Pin, PWM

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
	PWM_FREQ = 1000

	def __init__(self, pin_number, blink_interval_ms=None, brightness=1.0, debug=False):
		"""
		Args:
			pin_number: GPIO pin number (or board pin name) for the LED
			blink_interval_ms: Time between toggles, or None for solid
			brightness: 0.0 to 1.0. Below 1.0 switches the pin to PWM, which
				the board's onboard LED pin may not support.
			debug: If True, prints debug messages when the LED changes state
		"""
		super().__init__()
		self.pin_number = pin_number
		self.pin = Pin(pin_number, Pin.OUT)
		self.led = self.pin  # Kept for callers that poke the pin directly
		self.blink_interval_ms = blink_interval_ms
		self.debug = debug
		self._active = False
		self._pwm = None
		self._brightness = 1.0

		if brightness != 1.0:
			self.set_brightness(brightness)

	@property
	def is_on(self):
		"""True while the LED is meant to be lit, blinking included."""
		return self._active

	@property
	def is_blinking(self):
		return self.blink_interval_ms is not None

	@property
	def brightness(self):
		return self._brightness

	def set_brightness(self, brightness):
		"""Set brightness from 0.0 to 1.0, taking effect immediately if lit.

		Anything below full brightness needs PWM, which is set up the first
		time it is asked for.

		Raises:
			ValueError: If brightness is outside 0.0-1.0
			OSError/TypeError: If the pin cannot do PWM (e.g. the Pico W's
				onboard LED, which lives on the wireless chip)
		"""
		if not 0.0 <= brightness <= 1.0:
			raise ValueError("brightness must be between 0.0 and 1.0")

		self._brightness = brightness
		if brightness < 1.0 and self._pwm is None:
			self._pwm = PWM(self.pin)
			self._pwm.freq(self.PWM_FREQ)

		if self._active and not self.is_blinking:
			self._light()

	def on(self):
		self._active = True
		if self.is_blinking:
			super().on()
		else:
			self._light()
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
			self._light()

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
			self._light()
			await asyncio.sleep_ms(self.blink_interval_ms)
			self._darken()
			await asyncio.sleep_ms(self.blink_interval_ms)

	def cleanup(self):
		self._darken()

	def _light(self):
		"""Light the LED at the current brightness."""
		if self._pwm is None:
			self.pin.value(1)
		else:
			self._pwm.duty_u16(int(65535 * self._brightness))

	def _darken(self):
		if self._pwm is None:
			self.pin.value(0)
		else:
			self._pwm.duty_u16(0)


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
