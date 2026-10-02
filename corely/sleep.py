"""Sleep cycles - awake for a while, asleep until something happens.

	SleepCycle   the cycle: an Action, so it switches on and off like the rest
	PinTrigger   a pin edge that wakes the chip in hardware

A trigger is registered one of two ways:

	wake_on(name, trigger)    wakes the board while it sleeps
	toggle_on(name, trigger)  while awake, sends it to sleep; while asleep,
	                          wakes it - one button for both directions

Waking needs hardware: a sleeping CPU cannot check anything, so every trigger
is an interrupt - a button's pin, or a sensor's interrupt output such as the
TSL2591's light threshold. Nothing is polled while asleep.

A trigger may judge its own firings: if it has confirm(), the cycle calls it
when the trigger fires, and False means "not an event" - the cycle carries on
as it was (still asleep, or still awake). That is how a latching sensor can be
quietly re-armed: wake for a millisecond, reconfigure, sleep on.

Going to sleep can also come from code: sleep_now() is a plain callable, and
keep_awake() restarts the awake countdown, so activity can hold off sleep.

	cycle = SleepCycle(awake_ms=5000, asleep_ms=15000, on_wake=report)
	cycle.toggle_on("button", PinTrigger(1))
	cycle.on()

The sleep itself is one argument, sleep_fn, machine.lightsleep by default -
the part that differs between boards. Light sleep keeps the program running;
a deep sleep that restarts it (as on the ESP32) needs a different design.
"""

import asyncio
import time

from corely.action import TaskAction

TIMER = 'timer'


class PinTrigger:
	"""Wakes the board when a pin changes - a button, or a chip's INT line.

	The interrupt does the waking; its handler only notes that it fired,
	since almost nothing is safe inside an interrupt.
	"""

	def __init__(self, pin_number, falling=True, pull=None, rearm=None):
		"""
		Args:
			pin_number: The GPIO to watch
			falling: True to fire when it goes low (a button to GND, an
				active-low INT), False when it goes high
			pull: Pin.PULL_UP or Pin.PULL_DOWN; by default the one that holds
				the pin at rest - up for falling, down for rising
			rearm: Optional function run after this trigger woke the board,
				for sources that latch until told to clear
		"""
		from machine import Pin
		self._Pin = Pin
		if pull is None:
			pull = Pin.PULL_UP if falling else Pin.PULL_DOWN
		self.pin = Pin(pin_number, Pin.IN, pull)
		self.falling = falling
		self.rearm = rearm
		self.fired = False

	@property
	def active(self):
		"""True while the pin sits at its triggered level - a held button, a
		latched INT. An edge cannot wake a board that slept after it, so the
		cycle checks this too."""
		return self.pin.value() == (0 if self.falling else 1)

	def arm(self, deep=False):
		"""Arm the interrupt.

		Args:
			deep: True when the board is about to deep-sleep rather than
				light-sleep. Only matters on ports that need telling which
				sleep a pin may wake (the ESP32); the RP2 wakes on any.
		"""
		self.fired = False
		edge = self._Pin.IRQ_FALLING if self.falling else self._Pin.IRQ_RISING
		try:
			import machine
			wake = machine.DEEPSLEEP if deep else machine.SLEEP
			self.pin.irq(handler=self._interrupt, trigger=edge, wake=wake)
		except (TypeError, AttributeError):
			self.pin.irq(handler=self._interrupt, trigger=edge)

	def disarm(self):
		self.pin.irq(handler=None)

	def _interrupt(self, pin):
		self.fired = True


class SleepCycle(TaskAction):
	"""Awake, then asleep until the timer or a trigger, round and round.

	An Action: on() starts the cycle awake, off() stops it with everything it
	drives switched off and every trigger disarmed.

	Switching between awake and asleep switches two Actions given to it -
	"screen on" one way, "screen off" the other - so what sleeping means is
	the app's to say.
	"""

	POLL_MS = 50		# How often the awake phase checks its countdown
	EARLY_MS = 5		# A wake with more than this left is a false wake
	DEBOUNCE_MS = 80	# Settle after a toggle before it can fire again
	RELEASE_MS = 3000	# Longest to wait for a held toggle to be let go

	def __init__(self, awake_ms=5000, asleep_ms=15000, awake_action=None,
				 asleep_action=None, on_wake=None, on_sleep=None, sleep_fn=None,
				 debug=False):
		"""
		Args:
			awake_ms: Time awake before sleeping, restarted by keep_awake()
			asleep_ms: Time asleep before the timer wakes it, or None to sleep
				until a trigger fires
			awake_action: Action on while awake
			asleep_action: Action on while asleep
			on_wake: Called with the reason after each wake - TIMER or a
				trigger's name
			on_sleep: Called with the reason just before each sleep - TIMER,
				'requested' (sleep_now) or a toggle's name
			sleep_fn: Sleeps for the given ms, or until an interrupt when
				given none. machine.lightsleep by default.
			debug: If True, prints each sleep and wake
		"""
		super().__init__()
		self.awake_ms = awake_ms
		self.asleep_ms = asleep_ms
		self.awake_action = awake_action
		self.asleep_action = asleep_action
		self.on_wake = on_wake
		self.on_sleep = on_sleep
		self.sleep_fn = sleep_fn
		self.debug = debug
		self.awake = False
		self.last_wake = None
		self.last_sleep = None
		self.cycles = 0
		self.false_wakes = 0	# Wakes nothing claimed, slept through
		self._triggers = []		# (name, trigger, toggles)
		self._sleep_requested = False
		self._awake_since = time.ticks_ms()

	def wake_on(self, name, trigger):
		"""Wake the board when this fires while asleep.

		Args:
			name: What last_wake and on_wake report
			trigger: A PinTrigger, or anything with arm(), disarm(), fired
				and active - and optionally confirm() and rearm
		"""
		self._triggers.append((name, trigger, False))

	def toggle_on(self, name, trigger):
		"""Sleep when this fires while awake; wake when it fires while asleep."""
		self._triggers.append((name, trigger, True))

	def sleep_now(self):
		"""Sleep as soon as the cycle next checks - within POLL_MS."""
		self._sleep_requested = True

	def keep_awake(self):
		"""Restart the awake countdown - call on activity for an idle timeout."""
		self._awake_since = time.ticks_ms()

	@property
	def awake_remaining_ms(self):
		"""Time left before sleeping, or 0 while asleep."""
		if not self.awake:
			return 0
		return max(0, self.awake_ms - time.ticks_diff(time.ticks_ms(), self._awake_since))

	def on(self):
		"""Start cycling, awake first.

		Raises:
			ValueError: If a running watchdog would reset the board mid-sleep
		"""
		from corely.system import Watchdog
		limit = Watchdog.running_timeout_ms
		if limit is not None and (self.asleep_ms is None or self.asleep_ms >= limit):
			raise ValueError(
				"a {}ms watchdog would reset the board during a sleep".format(limit))
		super().on()

	async def run(self):
		if self.awake_action:
			self.awake_action.on()
		while True:
			self.awake = True
			self.keep_awake()
			self._sleep_requested = False
			reason = await self._awake_phase()

			self.awake = False
			self.last_sleep = reason
			if self.debug:
				print("SleepCycle: sleeping ({})".format(reason))
			if self.on_sleep:
				self.on_sleep(reason)
			self._switch(awake=False)
			# Let other tasks act on that first - the screen drawing its last
			# frame before it goes dark.
			await asyncio.sleep_ms(100)
			reason = self._sleep()
			self._switch(awake=True)

			self.cycles += 1
			self.last_wake = reason
			if self.debug:
				print("SleepCycle: woke ({})".format(reason))
			for name, trigger, _ in self._triggers:
				if name == reason and getattr(trigger, 'rearm', None):
					trigger.rearm()
			if self.on_wake:
				self.on_wake(reason)

	async def _awake_phase(self):
		"""Count down, watching the toggles. Returns why it is sleeping."""
		toggles = [(n, t, True) for n, t, toggles in self._triggers if toggles]
		await self._settle(toggles)
		for _, trigger, _ in toggles:
			trigger.arm()
		try:
			while True:
				if self._sleep_requested:
					return 'requested'
				name = self._claimed(toggles)
				if name:
					return name
				if self.awake_remaining_ms <= 0:
					return TIMER
				await asyncio.sleep_ms(self.POLL_MS)
		finally:
			self._disarm()

	async def _settle(self, toggles):
		"""Let a held toggle go before arming it, so the press that woke the
		board - or its bounce - does not send it straight back to sleep."""
		start = time.ticks_ms()
		while time.ticks_diff(time.ticks_ms(), start) < self.RELEASE_MS:
			held = False
			for name, trigger, _ in toggles:
				if trigger.active:
					confirm = getattr(trigger, 'confirm', None)
					if confirm is None:
						held = True		# A button still down
					elif confirm():
						self._sleep_requested = True
			if not held:
				break
			await asyncio.sleep_ms(self.POLL_MS)
		await asyncio.sleep_ms(self.DEBOUNCE_MS)

	def _claimed(self, triggers):
		"""The name of a trigger that fired and stands by it, or None."""
		for name, trigger, _ in triggers:
			if trigger.fired or trigger.active:
				trigger.fired = False
				confirm = getattr(trigger, 'confirm', None)
				if confirm is None or confirm():
					return name
		return None

	def cleanup(self):
		self.awake = False
		self._disarm()
		for action in (self.asleep_action, self.awake_action):
			if action:
				action.off()

	def _switch(self, awake):
		"""Off before on, so actions sharing hardware hand it over cleanly."""
		old, new = (self.asleep_action, self.awake_action) if awake else \
			(self.awake_action, self.asleep_action)
		if old:
			old.off()
		if new:
			new.on()

	def _sleep(self):
		"""Sleep until the timer or a trigger, sleeping through false wakes.

		Returns:
			TIMER, or the name of the trigger that fired
		"""
		sleep = self.sleep_fn
		if sleep is None:
			import machine
			sleep = machine.lightsleep

		for _, trigger, _ in self._triggers:
			trigger.arm()
		try:
			deadline = None
			if self.asleep_ms is not None:
				deadline = time.ticks_add(time.ticks_ms(), self.asleep_ms)
			while True:
				name = self._claimed(self._triggers)
				if name:
					return name
				if deadline is None:
					sleep()
				else:
					remaining = time.ticks_diff(deadline, time.ticks_ms())
					if remaining <= 0:
						return TIMER
					sleep(remaining)
				# A pin interrupt wakes the chip at once, but its handler is a
				# scheduled (soft) one: on the Pico it had not run when
				# lightsleep returned, and had 1ms later. Without this, a quick
				# button tap reads as a false wake.
				time.sleep_ms(1)
				# Woke: a trigger (claimed at the top of the loop), the timer,
				# or something else - lightsleep returns early when the radio
				# stirs. Timer rounding can return a millisecond short; that is
				# not a false wake.
				if not any(t.fired or t.active for _, t, _ in self._triggers) and \
						(deadline is None or time.ticks_diff(deadline, time.ticks_ms()) > self.EARLY_MS):
					self.false_wakes += 1
		finally:
			self._disarm()

	def _disarm(self):
		for _, trigger, _ in self._triggers:
			try:
				trigger.disarm()
			except Exception:
				pass
