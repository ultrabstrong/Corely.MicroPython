"""RGB LED - one component, three channels, any colour.

A four-pin RGB LED is three LEDs sharing a common leg. This drives each channel
with PWM rather than on/off, so colours mix properly instead of being limited
to the eight combinations of full-on channels.

Wiring, common cathode (the long leg goes to GND):

	GP7 -> 220R -> R
	GP8 -> 220R -> G
	GP9 -> 220R -> B
	common -> GND

For a common anode (long leg to 3V3) pass `active_high=False`.

Colours are (red, green, blue) tuples of 0-255, or the name of one of the
constants below:

	rgb.solid(RED)
	rgb.solid("teal")
	rgb.solid((255, 40, 0))
"""

import asyncio
from machine import Pin, PWM

from corely.action import Action, TaskAction


# Named colours, as (red, green, blue) 0-255.
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
WHITE = (255, 255, 255)
ORANGE = (255, 60, 0)
PURPLE = (140, 0, 255)
PINK = (255, 50, 90)
TEAL = (0, 255, 120)

COLOURS = {
	'black': BLACK,
	'off': BLACK,
	'red': RED,
	'green': GREEN,
	'blue': BLUE,
	'yellow': YELLOW,
	'cyan': CYAN,
	'magenta': MAGENTA,
	'white': WHITE,
	'orange': ORANGE,
	'purple': PURPLE,
	'pink': PINK,
	'teal': TEAL,
}

_MODE_SOLID = 'solid'
_MODE_BLINK = 'blink'
_MODE_RAINBOW = 'rainbow'


def resolve_colour(colour):
	"""Turn a colour name or tuple into an (r, g, b) tuple.

	Args:
		colour: A name from COLOURS, or an (r, g, b) tuple of 0-255

	Raises:
		ValueError: If the name is unknown or the tuple is malformed
	"""
	if isinstance(colour, str):
		try:
			return COLOURS[colour.lower()]
		except KeyError:
			raise ValueError(f"Unknown colour '{colour}'")

	if len(colour) != 3:
		raise ValueError("A colour needs three channels: (red, green, blue)")
	return tuple(colour)


def hue_to_colour(hue):
	"""Convert a hue (0-359) to a fully saturated (r, g, b) tuple.

	Used by the rainbow mode. Only hue varies, so this is the simple case of an
	HSV conversion with saturation and value pinned at maximum.
	"""
	hue = hue % 360
	sector, offset = divmod(hue, 60)
	rising = int(offset * 255 / 60)
	falling = 255 - rising

	if sector == 0:
		return (255, rising, 0)
	if sector == 1:
		return (falling, 255, 0)
	if sector == 2:
		return (0, 255, rising)
	if sector == 3:
		return (0, falling, 255)
	if sector == 4:
		return (rising, 0, 255)
	return (255, 0, falling)


class RgbLed(TaskAction):
	"""One RGB LED: on/off, any colour, blinking, or cycling the rainbow.

	Solid is the default and starts no task. Blink and rainbow each run in the
	task this Action owns, so off() stops them.
	"""

	DEFAULT_BLINK_MS = 500
	DEFAULT_RAINBOW_MS = 1000
	RAINBOW_STEPS = 60
	PWM_FREQ = 1000

	# Green and blue dies are far more efficient than red ones, so equal duty
	# cycles do not look like equal light: "yellow" comes out green. These
	# per-channel gains even that out for a typical common-cathode RGB LED.
	DEFAULT_CHANNEL_SCALE = (1.0, 0.20, 0.5)

	def __init__(self, red_pin, green_pin, blue_pin, colour=WHITE,
				 brightness=1.0, active_high=True, channel_scale=None,
				 debug=False):
		"""
		Args:
			red_pin/green_pin/blue_pin: GPIO pin numbers for the three channels
			colour: Starting colour, as a name or (r, g, b) tuple
			brightness: Scales every channel, 0.0 to 1.0
			active_high: True for common cathode (common leg to GND),
				False for common anode (common leg to 3V3)
			channel_scale: Per-channel gains that correct for the dies having
				different efficiencies. Defaults to DEFAULT_CHANNEL_SCALE;
				pass (1.0, 1.0, 1.0) for raw, uncorrected output.
			debug: If True, prints state changes
		"""
		super().__init__()
		self._channels = tuple(
			PWM(Pin(pin)) for pin in (red_pin, green_pin, blue_pin)
		)
		for channel in self._channels:
			channel.freq(self.PWM_FREQ)

		self.pins = (red_pin, green_pin, blue_pin)
		self.colour = resolve_colour(colour)
		self.brightness = brightness
		self.active_high = active_high
		self.channel_scale = channel_scale or self.DEFAULT_CHANNEL_SCALE
		self.debug = debug

		self.blink_interval_ms = self.DEFAULT_BLINK_MS
		self.rainbow_cycle_ms = self.DEFAULT_RAINBOW_MS
		self._mode = _MODE_SOLID
		self._active = False

		# Start dark, whatever the polarity.
		self._write(BLACK)

	@property
	def is_on(self):
		"""True while the LED is meant to be lit, blinking or cycling included."""
		return self._active

	@property
	def mode(self):
		"""One of 'solid', 'blink' or 'rainbow'."""
		return self._mode

	def on(self):
		self._active = True
		if self._mode == _MODE_SOLID:
			self._write(self.colour)
		else:
			super().on()
		if self.debug:
			print(f"RGB on pins {self.pins}: {self._mode} {self.colour}")

	def off(self):
		self._active = False
		super().off()
		if self.debug:
			print(f"RGB on pins {self.pins} OFF")

	def solid(self, colour=None):
		"""Switch to a steady colour, taking effect immediately if lit.

		Args:
			colour: New colour, or None to keep the current one
		"""
		if colour is not None:
			self.colour = resolve_colour(colour)
		self._switch_mode(_MODE_SOLID)

	def blink(self, interval_ms=None, colour=None):
		"""Switch to blinking, taking effect immediately if lit.

		Args:
			interval_ms: Time between toggles, or None to keep the current one
			colour: New colour, or None to keep the current one
		"""
		if interval_ms is not None:
			self.blink_interval_ms = interval_ms
		if colour is not None:
			self.colour = resolve_colour(colour)
		self._switch_mode(_MODE_BLINK)

	def rainbow(self, cycle_ms=None):
		"""Switch to cycling the whole hue wheel, taking effect immediately.

		Args:
			cycle_ms: Time for one full sweep, or None to keep the current one
		"""
		if cycle_ms is not None:
			self.rainbow_cycle_ms = cycle_ms
		self._switch_mode(_MODE_RAINBOW)

	def steady(self, colour):
		"""An Action that shows this colour steadily while active.

		Lets a state machine drive one RGB LED without the states fighting over
		it:

			rgb = RgbLed(7, 8, 9)
			connected_action = rgb.steady(GREEN)
			disconnected_action = rgb.steady(RED)
		"""
		return _RgbMode(self, _MODE_SOLID, colour=colour)

	def blinking(self, colour, interval_ms=None):
		"""An Action that blinks this colour while active."""
		return _RgbMode(self, _MODE_BLINK, colour=colour, interval_ms=interval_ms)

	def cycling(self, cycle_ms=None):
		"""An Action that cycles the rainbow while active."""
		return _RgbMode(self, _MODE_RAINBOW, cycle_ms=cycle_ms)

	async def run(self):
		if self._mode == _MODE_BLINK:
			await self._blink_loop()
		else:
			await self._rainbow_loop()

	def cleanup(self):
		self._write(BLACK)

	async def _blink_loop(self):
		while True:
			self._write(self.colour)
			await asyncio.sleep_ms(self.blink_interval_ms)
			self._write(BLACK)
			await asyncio.sleep_ms(self.blink_interval_ms)

	async def _rainbow_loop(self):
		step_ms = max(1, self.rainbow_cycle_ms // self.RAINBOW_STEPS)
		step_degrees = 360 // self.RAINBOW_STEPS
		hue = 0
		while True:
			self._write(hue_to_colour(hue))
			hue = (hue + step_degrees) % 360
			await asyncio.sleep_ms(step_ms)

	def _switch_mode(self, mode):
		"""Change mode, restarting the task machinery if the LED is lit."""
		was_on = self._active
		if was_on:
			super().off()

		self._mode = mode

		if was_on:
			self._active = True
			if mode == _MODE_SOLID:
				self._write(self.colour)
			else:
				super().on()

	def _write(self, colour):
		"""Drive the three channels, applying scale, brightness and polarity."""
		for channel, value, scale in zip(self._channels, colour, self.channel_scale):
			level = int(value * scale * self.brightness * 257)  # 0-255 -> 0-65535
			level = min(65535, max(0, level))
			channel.duty_u16(level if self.active_high else 65535 - level)


class _RgbMode(Action):
	"""Drives a shared RgbLed into one mode while active.

	Created by RgbLed.steady(), .blinking() and .cycling() rather than directly.
	"""

	def __init__(self, rgb, mode, colour=None, interval_ms=None, cycle_ms=None):
		self.rgb = rgb
		self.mode = mode
		self.colour = resolve_colour(colour) if colour is not None else None
		self.interval_ms = interval_ms
		self.cycle_ms = cycle_ms

	def on(self):
		if self.mode == _MODE_SOLID:
			self.rgb.solid(self.colour)
		elif self.mode == _MODE_BLINK:
			self.rgb.blink(interval_ms=self.interval_ms, colour=self.colour)
		else:
			self.rgb.rainbow(cycle_ms=self.cycle_ms)
		self.rgb.on()

	def off(self):
		self.rgb.off()
