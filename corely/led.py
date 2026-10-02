"""LED actions.

`pin_number` accepts anything `machine.Pin` does: a GPIO number (18), or a
board-specific pin name where the port provides one ("LED" is the onboard LED
on the Pico W and Pico 2 W).

Three modes, all one waveform walk under the hood: solid, blink (a square
wave) and pulse (a sine - a slow breath). Blink only ever asks for full or
nothing, which a plain digital pin can do; pulse needs the levels in between,
so it needs PWM. That is why blinking works on the Pico W's onboard LED, which
lives on the wireless chip and has no PWM, and pulsing does not.

Full brightness drives the pin digitally. Anything dimmer, or pulsing, needs
PWM, which the LED sets up on demand.

Wiring: active-high by default - the pin drives the LED's anode. For an LED
that lights when the pin goes low (most ESP32 and ESP8266 onboard LEDs) pass
active_high=False.
"""

import asyncio
from math import cos, pi
from machine import Pin, PWM

from corely.action import Action, TaskAction


_SOLID = 'solid'
_BLINK = 'blink'
_PULSE = 'pulse'


def square_wave(fraction):
	"""Blink: lit for the first half of each cycle, dark for the second."""
	return 1.0 if fraction < 0.5 else 0.0


def sine_wave(fraction):
	"""Pulse: dark at the start and end of each cycle, full in the middle."""
	return (1 - cos(2 * pi * fraction)) / 2


class Led(TaskAction):
	"""One LED: solid, blinking or pulsing.

	Solid is the default and starts no task, so it costs nothing to run:

		Led(18)                          # on() lights it
		Led(18, blink_interval_ms=250)   # on() blinks it
		Led(18).pulse(2000)              # on() breathes, a 2s cycle

	The mode can change while the LED is on, so one object owns the pin for the
	life of the program rather than several fighting over it.
	"""

	DEFAULT_BLINK_MS = 500
	DEFAULT_PULSE_MS = 2000
	PULSE_STEPS = 50		# Levels per pulse cycle; more is smoother
	PWM_FREQ = 1000

	def __init__(self, pin_number, blink_interval_ms=None, brightness=1.0,
				 debug=False, active_high=True):
		"""
		Args:
			pin_number: GPIO pin number (or board pin name) for the LED
			blink_interval_ms: Time between toggles, or None for solid
			brightness: 0.0 to 1.0. Below 1.0 switches the pin to PWM, which
				the board's onboard LED pin may not support.
			debug: If True, prints debug messages when the LED changes state
			active_high: True if the pin drives the LED high to light it,
				False for an LED that lights when the pin goes low
		"""
		super().__init__()
		self.pin_number = pin_number
		self.active_high = active_high
		self.pin = Pin(pin_number, Pin.OUT)
		self.led = self.pin  # Kept for callers that poke the pin directly
		self.blink_interval_ms = blink_interval_ms
		self.pulse_ms = self.DEFAULT_PULSE_MS
		self.debug = debug
		self._mode = _BLINK if blink_interval_ms is not None else _SOLID
		self._active = False
		self._pwm = None
		self._brightness = 1.0

		# A new output pin reads low, which lights an active-low LED. Start
		# dark whatever the wiring.
		self._write_level(0.0)

		if brightness != 1.0:
			self.set_brightness(brightness)

	@property
	def is_on(self):
		"""True while the LED is meant to be lit, blinking or pulsing included."""
		return self._active

	@property
	def is_blinking(self):
		return self._mode == _BLINK

	@property
	def is_pulsing(self):
		return self._mode == _PULSE

	@property
	def brightness(self):
		return self._brightness

	def set_brightness(self, brightness):
		"""Set brightness from 0.0 to 1.0, taking effect immediately if lit.

		Anything below full brightness needs PWM, which is set up the first
		time it is asked for. Pulsing peaks at this level.

		Raises:
			ValueError: If brightness is outside 0.0-1.0
			OSError/TypeError: If the pin cannot do PWM (e.g. the Pico W's
				onboard LED, which lives on the wireless chip)
		"""
		if not 0.0 <= brightness <= 1.0:
			raise ValueError("brightness must be between 0.0 and 1.0")

		self._brightness = brightness
		if brightness < 1.0:
			self._ensure_pwm()

		if self._active and self._mode == _SOLID:
			self._write_level(1.0)

	def on(self):
		self._active = True
		if self._mode == _SOLID:
			self._write_level(1.0)
		else:
			super().on()
		if self.debug:
			print(f"LED on pin {self.pin_number} {self._describe()}")

	def off(self):
		self._active = False
		# Cancels the blink or pulse task if there is one, and cleanup()
		# darkens the pin.
		super().off()
		if self.debug:
			print(f"LED on pin {self.pin_number} OFF")

	def solid(self):
		"""Switch to steady, taking effect immediately if the LED is on."""
		self._switch_mode(_SOLID)

	def blink(self, interval_ms=None):
		"""Switch to blinking, taking effect immediately if the LED is on.

		Args:
			interval_ms: New interval, or None to keep the current one
		"""
		if interval_ms is not None:
			self.blink_interval_ms = interval_ms
		elif self.blink_interval_ms is None:
			self.blink_interval_ms = self.DEFAULT_BLINK_MS
		self._switch_mode(_BLINK)

	def pulse(self, period_ms=None):
		"""Switch to pulsing - fading up and down - taking effect immediately
		if the LED is on.

		Needs PWM, so it raises on a pin without it, such as the Pico W's
		onboard LED.

		Args:
			period_ms: Time for one full breath, dark to full to dark, or None
				to keep the current one (DEFAULT_PULSE_MS at first)
		"""
		if period_ms is not None:
			self.pulse_ms = period_ms
		self._ensure_pwm()
		self._switch_mode(_PULSE)

	def blinking(self, interval_ms=None):
		"""An Action that blinks this LED while active.

		Lets two states share one LED without fighting over the pin - a state
		machine holds one of these per state:

			onboard = Led("LED")
			advertising_action = onboard.blinking(500)
			connected_action = onboard.steady()
		"""
		return _LedMode(self, _BLINK, interval_ms or self.blink_interval_ms or self.DEFAULT_BLINK_MS)

	def steady(self):
		"""An Action that lights this LED steadily while active."""
		return _LedMode(self, _SOLID)

	def pulsing(self, period_ms=None):
		"""An Action that pulses this LED while active. Needs PWM."""
		return _LedMode(self, _PULSE, period_ms or self.pulse_ms)

	async def run(self):
		if self._mode == _PULSE:
			shape, steps, period_ms = sine_wave, self.PULSE_STEPS, self.pulse_ms
		else:
			# Two steps of one interval each: exactly the old blink.
			shape, steps, period_ms = square_wave, 2, 2 * self.blink_interval_ms

		step_ms = max(1, period_ms // steps)
		step = 0
		while True:
			self._write_level(shape(step / steps))
			step = (step + 1) % steps
			await asyncio.sleep_ms(step_ms)

	def cleanup(self):
		self._write_level(0.0)

	def _switch_mode(self, mode):
		"""Change mode, restarting the task if the LED is lit."""
		self._mode = mode
		if self._active:
			super().off()
			if mode == _SOLID:
				self._write_level(1.0)
			else:
				super().on()

	def _ensure_pwm(self):
		if self._pwm is None:
			self._pwm = PWM(self.pin)
			self._pwm.freq(self.PWM_FREQ)

	def _write_level(self, fraction):
		"""Light the LED to a fraction (0.0-1.0) of its brightness.

		The one place a level becomes a pin write, so polarity and brightness
		are applied the same way for every mode.
		"""
		if self._pwm is None:
			lit = fraction >= 0.5
			self.pin.value(1 if lit == self.active_high else 0)
		else:
			duty = int(65535 * fraction * self._brightness)
			self._pwm.duty_u16(duty if self.active_high else 65535 - duty)

	def _describe(self):
		if self._mode == _BLINK:
			return f"BLINKING at {self.blink_interval_ms}ms"
		if self._mode == _PULSE:
			return f"PULSING every {self.pulse_ms}ms"
		return "ON"


class _LedMode(Action):
	"""Drives a shared Led into one mode while active.

	Created by Led.steady(), .blinking() and .pulsing() rather than directly.
	"""

	def __init__(self, led, mode, interval_ms=None):
		self.led = led
		self.mode = mode
		self.interval_ms = interval_ms

	@property
	def blink_interval_ms(self):
		"""The blink interval, for a blinking view."""
		return self.interval_ms if self.mode == _BLINK else None

	def on(self):
		if self.mode == _SOLID:
			self.led.solid()
		elif self.mode == _BLINK:
			self.led.blink(self.interval_ms)
		else:
			self.led.pulse(self.interval_ms)
		self.led.on()

	def off(self):
		self.led.off()
