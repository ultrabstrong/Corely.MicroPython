"""Fake `machine` module so lib code can be imported on a PC."""


class Pin:
	OUT = 'OUT'
	IN = 'IN'
	PULL_UP = 'PULL_UP'

	def __init__(self, id, mode=None, pull=None):
		self.id = id
		self.mode = mode
		self.pull = pull
		# History of every value written, so tests can assert on blink patterns.
		self.writes = []
		self._value = 1 if pull == Pin.PULL_UP else 0

	def value(self, val=None):
		if val is None:
			return self._value
		self._value = val
		self.writes.append(val)
		return None

	def press(self):
		"""Test helper: simulate the button being held down (active low)."""
		self._value = 0

	def release(self):
		"""Test helper: simulate the button being released."""
		self._value = 1


class PWM:
	"""Fake PWM channel that records every duty cycle written to it."""

	def __init__(self, pin, freq=None, duty_u16=0):
		self.pin = pin
		self._freq = freq
		self._duty = duty_u16
		# History of every duty written, so tests can assert on colour changes.
		self.duties = []

	def freq(self, value=None):
		if value is None:
			return self._freq
		self._freq = value
		return None

	def duty_u16(self, value=None):
		if value is None:
			return self._duty
		self._duty = value
		self.duties.append(value)
		return None

	def deinit(self):
		self._duty = 0
