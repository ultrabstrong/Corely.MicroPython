"""Fake `machine` module so lib code can be imported on a PC."""

PWRON_RESET = 1
WDT_RESET = 3

# Set by tests: what reset_cause() reports, and every reset() requested.
next_reset_cause = PWRON_RESET
resets = []


def reset_cause():
	return next_reset_cause


def reset():
	resets.append(True)


class WDT:
	"""Fake watchdog that counts feeds."""

	def __init__(self, timeout=5000):
		self.timeout = timeout
		self.feeds = 0

	def feed(self):
		self.feeds += 1


class Pin:
	OUT = 'OUT'
	IN = 'IN'
	OPEN_DRAIN = 'OPEN_DRAIN'
	IRQ_FALLING = 'IRQ_FALLING'
	IRQ_RISING = 'IRQ_RISING'

	def irq(self, handler=None, trigger=None):
		"""Records the handler; tests call fire_irq() to invoke it."""
		self.irq_handler = handler
		self.irq_trigger = trigger

	def fire_irq(self):
		if getattr(self, 'irq_handler', None):
			self.irq_handler(self)
	PULL_UP = 'PULL_UP'
	PULL_DOWN = 'PULL_DOWN'

	def __init__(self, id, mode=None, pull=None):
		self.id = id
		self.mode = mode
		self.pull = pull
		# History of every value written, so tests can assert on blink patterns.
		self.writes = []
		# An input rests where its pull holds it: high with a pull-up, low
		# with a pull-down or (in this fake) no pull.
		self._rest = 1 if pull == Pin.PULL_UP else 0
		self._value = self._rest

	def value(self, val=None):
		if val is None:
			return self._value
		self._value = val
		self.writes.append(val)
		return None

	def press(self):
		"""Test helper: simulate the button being held down - the pin leaves
		its resting level, whichever way it is pulled."""
		self._value = 1 - self._rest

	def release(self):
		"""Test helper: simulate the button being released."""
		self._value = self._rest


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
