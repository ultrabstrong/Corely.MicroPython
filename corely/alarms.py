"""Threshold alarms - one event per crossing, from a sensor's latching alarm.

Some sensors watch a threshold themselves and pull an interrupt pin when the
reading leaves a range - the TSL2591's light alarm, and temperature chips
such as the MCP9808 or TMP117. They are alarm clocks, not doorbells: the
signal latches and stays on after the cause is gone, until the CPU clears
it - and if the reading is still out of range, it latches again. Clearing
alone loops; the CPU has to set the *next* alarm.

ThresholdAlarm does that, so each crossing is one event:

	watching     armed for the crossing (below, above, or out of a band)
	  -> it latches: an event; arm the recovery point instead
	recovering   armed for the reading coming back past the recovery point
	  -> it latches: not an event; arm the crossing again

The gap between the crossing and the recovery point stops a reading that
hovers on the line from flapping - hysteresis, a threshold's debounce.

It is a SleepCycle trigger (arm, disarm, fired, active, confirm), and also
runs on its own while awake (run(), calling on_event), the shape Button has.

The sensor side is a small contract, in whatever units the chip compares:

	alarm_value()                     the reading now
	arm_alarm(below=None, above=None) latch when the reading leaves the range
	clear_alarm()                     release the latch
	disarm_alarm()                    switch the alarm off
	alarm_latched()                   latched right now? (from the chip, so it
	                                  survives a reboot - see wake_reason())

corely.sensors.Tsl2591 implements it in raw counts.
"""

import asyncio

from corely.sleep import PinTrigger

BELOW = 'below'
ABOVE = 'above'

WATCHING = 'watching'
RECOVERING = 'recovering'


class ThresholdAlarm:
	"""A sensor's latching alarm, turned into one event per crossing.

		dark = ThresholdAlarm(light, pins.LIGHT_INT,
		                      below=lambda now: max(120, now // 4),
		                      recover=lambda threshold: threshold * 2)
		cycle.toggle_on("dark", dark)
	"""

	def __init__(self, sensor, pin_number, below=None, above=None, recover=None,
				 on_event=None, restore=None, falling=True, poll_ms=50):
		"""
		Args:
			sensor: Anything implementing the alarm contract
			pin_number: The GPIO its interrupt output is wired to
			below: Fire when the reading falls below this - a number, or a
				function of the reading at arming time
			above: Fire when it rises above this, likewise
			recover: Where the reading counts as back: a number is a gap
				(back at threshold + gap after falling below, threshold - gap
				after rising above); a function is given the threshold that
				was crossed and returns the recovery point. Required - no
				default makes sense across counts and degrees.
			on_event: Called with BELOW or ABOVE for each crossing
			restore: A snapshot() from before a reboot, to carry on from
			falling: The interrupt pin's active edge - low for most chips
			poll_ms: How often run() checks, when used awake on its own

		Raises:
			ValueError: Without below or above, or without recover
		"""
		if below is None and above is None:
			raise ValueError("ThresholdAlarm needs below, above, or both")
		if recover is None:
			raise ValueError("ThresholdAlarm needs recover - a gap or a function")
		self.sensor = sensor
		self.below = below
		self.above = above
		self.recover = recover
		self.on_event = on_event
		self.poll_ms = poll_ms
		self.rearm = None
		self.events = 0
		self.last_event = None
		self._pin = PinTrigger(pin_number, falling=falling)
		self._limits = (None, None)
		self.state = None
		if restore:
			self._restore(restore)
		else:
			self._watch()

	# SleepCycle trigger protocol

	@property
	def fired(self):
		return self._pin.fired

	@fired.setter
	def fired(self, value):
		self._pin.fired = value

	@property
	def active(self):
		return self._pin.active

	def arm(self, deep=False):
		self._pin.arm(deep=deep)

	def disarm(self):
		self._pin.disarm()

	def confirm(self):
		"""The alarm latched: was it a crossing? Re-arms for what comes next.

		Returns:
			True for a crossing (an event), False for a recovery
		"""
		now = self.sensor.alarm_value()
		if self.state == WATCHING:
			direction = self._direction(now)
			self.events += 1
			self.last_event = direction
			self._recovery(direction)
			if self.on_event:
				self.on_event(direction)
			return True
		self._watch(now)
		return False

	# Awake use, on its own

	async def run(self):
		"""Watch while awake, calling on_event per crossing. Start with
		create_task(); not needed when a SleepCycle owns the alarm."""
		self.arm()
		try:
			while True:
				if self.fired or self.active:
					self.fired = False
					self.confirm()
				await asyncio.sleep_ms(self.poll_ms)
		finally:
			self.disarm()

	def stop(self):
		"""Disarm the pin and switch the sensor's alarm off."""
		self.disarm()
		self.sensor.disarm_alarm()

	# Surviving a reboot

	def snapshot(self):
		"""What to save before a deep sleep, for restore= after it."""
		return {
			'state': self.state,
			'limits': list(self._limits),
			'last_event': self.last_event,
			'events': self.events,
		}

	def _restore(self, snapshot):
		self._limits = tuple(snapshot['limits'])
		self.last_event = snapshot.get('last_event')
		self.events = snapshot.get('events', 0)
		if snapshot.get('state') == RECOVERING and self.last_event:
			self._recovery(self.last_event)
		else:
			low, high = self._limits
			self.sensor.arm_alarm(below=low, above=high)
			self.state = WATCHING

	# Internals

	def _watch(self, now=None):
		"""Arm for the crossing, working out function thresholds from now."""
		if now is None and (callable(self.below) or callable(self.above)):
			now = self.sensor.alarm_value()
		low = self.below(now) if callable(self.below) else self.below
		high = self.above(now) if callable(self.above) else self.above
		self._limits = (low, high)
		self.sensor.arm_alarm(below=low, above=high)
		self.state = WATCHING

	def _recovery(self, direction):
		"""Arm for the reading coming back past the recovery point."""
		low, high = self._limits
		crossed = low if direction == BELOW else high
		if callable(self.recover):
			back = self.recover(crossed)
		elif direction == BELOW:
			back = crossed + self.recover
		else:
			back = crossed - self.recover
		if direction == BELOW:
			self.sensor.arm_alarm(above=back)
		else:
			self.sensor.arm_alarm(below=back)
		self.state = RECOVERING

	def _direction(self, now):
		"""Which way it crossed. A quick blip may already be back in range by
		the time this reads - then the nearer threshold is the one crossed."""
		low, high = self._limits
		if low is not None and now < low:
			return BELOW
		if high is not None and now > high:
			return ABOVE
		if low is None:
			return ABOVE
		if high is None:
			return BELOW
		return BELOW if abs(now - low) <= abs(now - high) else ABOVE

	@property
	def latched(self):
		return self.sensor.alarm_latched()
