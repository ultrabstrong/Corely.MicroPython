"""SleepCycle: wakes for the right reason, sleeps through false wakes, and
switches its Actions in order."""

import asyncio
import time
import unittest

import harness  # noqa: F401

from corely.action import Action
from corely.sleep import TIMER, PinTrigger, SleepCycle
from corely.system import Watchdog


class FakeTrigger:
	"""A wake source the test fires by hand."""

	def __init__(self, active=False):
		self.fired = False
		self.active = active
		self.armed = False
		self.rearm = None
		self.arms = 0

	def arm(self):
		self.armed = True
		self.fired = False
		self.arms += 1

	def disarm(self):
		self.armed = False


class FakeSleep:
	"""Stands in for lightsleep: sleeps for real, briefly, and can be told to
	fire a trigger or wake falsely on a given call."""

	def __init__(self):
		self.calls = []
		self.plan = {}		# call number -> trigger to fire, or 'false'

	def __call__(self, ms=None):
		call = len(self.calls)
		self.calls.append(ms)
		event = self.plan.get(call)
		if event == 'false':
			time.sleep(0.001)
			return
		if event is not None:
			time.sleep(0.001)
			event.fired = True
			return
		time.sleep((ms or 10) / 1000)


class Recorder(Action):
	def __init__(self, name, log):
		self.name = name
		self.log = log

	def on(self):
		self.log.append(self.name + ".on")

	def off(self):
		self.log.append(self.name + ".off")


class SleepCycleTestCase(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		Watchdog.running_timeout_ms = None
		self.sleep = FakeSleep()
		self.wakes = []

	def make(self, **kwargs):
		kwargs.setdefault('awake_ms', 30)
		kwargs.setdefault('asleep_ms', 60)
		cycle = SleepCycle(sleep_fn=self.sleep, on_wake=self.wakes.append, **kwargs)
		cycle.POLL_MS = 5
		return cycle

	async def run_until(self, cycle, wakes, timeout=2):
		cycle.on()
		deadline = time.monotonic() + timeout
		while len(self.wakes) < wakes and time.monotonic() < deadline:
			await asyncio.sleep(0.01)
		cycle.off()


class WakeReasonTests(SleepCycleTestCase):
	async def test_timer_wake(self):
		cycle = self.make()

		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes[0], TIMER)
		self.assertEqual(cycle.last_wake, TIMER)

	async def test_a_trigger_ends_the_sleep_early(self):
		cycle = self.make(asleep_ms=10_000)
		button = FakeTrigger()
		cycle.wake_on("button", button)
		self.sleep.plan[0] = button

		start = time.monotonic()
		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes, ["button"])
		self.assertLess(time.monotonic() - start, 2)

	async def test_a_false_wake_is_slept_through(self):
		"""lightsleep returns early when the radio stirs; that is not a wake."""
		cycle = self.make(asleep_ms=60)
		cycle.wake_on("button", FakeTrigger())
		self.sleep.plan[0] = 'false'

		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes, [TIMER])
		self.assertGreaterEqual(len(self.sleep.calls), 2)
		# At least the planted one. Windows' monotonic clock moves in ~15ms
		# steps, so a full sleep can also look early there; the device's
		# ticks_ms has no such slack.
		self.assertGreaterEqual(cycle.false_wakes, 1)

	async def test_an_already_asserted_trigger_wakes_at_once(self):
		"""An edge cannot wake a board that slept after it - check the level."""
		cycle = self.make(asleep_ms=10_000)
		cycle.wake_on("dark", FakeTrigger(active=True))

		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes, ["dark"])
		self.assertEqual(self.sleep.calls, [])

	async def test_sleeps_until_a_trigger_when_there_is_no_timer(self):
		cycle = self.make(asleep_ms=None)
		button = FakeTrigger()
		cycle.wake_on("button", button)
		self.sleep.plan[0] = button

		await self.run_until(cycle, 1)

		self.assertEqual(self.sleep.calls[0], None)
		self.assertEqual(self.wakes, ["button"])

	async def test_rearm_runs_for_the_trigger_that_woke_it(self):
		cycle = self.make(asleep_ms=10_000)
		dark, button = FakeTrigger(), FakeTrigger()
		rearmed = []
		dark.rearm = lambda: rearmed.append("dark")
		button.rearm = lambda: rearmed.append("button")
		cycle.wake_on("dark", dark)
		cycle.wake_on("button", button)
		self.sleep.plan[0] = dark

		await self.run_until(cycle, 1)

		self.assertEqual(rearmed, ["dark"])

	async def test_triggers_are_disarmed_while_awake(self):
		cycle = self.make()
		trigger = FakeTrigger()
		cycle.wake_on("button", trigger)

		await self.run_until(cycle, 2)

		self.assertGreaterEqual(trigger.arms, 2)
		self.assertFalse(trigger.armed)


class SleepTriggerTests(SleepCycleTestCase):
	"""Going to sleep is ordinary code: sleep_now() and keep_awake()."""

	async def test_sleep_now_skips_the_rest_of_the_awake_time(self):
		cycle = self.make(awake_ms=10_000)
		cycle.on()
		await asyncio.sleep(0.05)
		self.assertEqual(self.sleep.calls, [])

		cycle.sleep_now()
		await asyncio.sleep(0.3)
		cycle.off()

		self.assertGreaterEqual(len(self.sleep.calls), 1)

	async def test_keep_awake_pushes_sleep_back(self):
		cycle = self.make(awake_ms=150)
		cycle.on()
		for _ in range(6):
			await asyncio.sleep(0.05)
			cycle.keep_awake()
		slept = len(self.sleep.calls)
		cycle.off()

		self.assertEqual(slept, 0)


class ToggleTests(SleepCycleTestCase):
	"""toggle_on: the same trigger sleeps an awake board and wakes a sleeping one."""

	def setUp(self):
		super().setUp()
		self.sleeps = []

	def make(self, **kwargs):
		kwargs.setdefault('on_sleep', self.sleeps.append)
		return super().make(**kwargs)

	async def test_firing_while_awake_sleeps_now(self):
		cycle = self.make(awake_ms=10_000)
		button = FakeTrigger()
		cycle.toggle_on("button", button)
		cycle.on()
		await asyncio.sleep(0.2)
		self.assertEqual(self.sleep.calls, [])

		button.fired = True
		await asyncio.sleep(0.2)
		cycle.off()

		self.assertEqual(self.sleeps, ["button"])
		self.assertGreaterEqual(len(self.sleep.calls), 1)

	async def test_firing_while_asleep_wakes(self):
		cycle = self.make(asleep_ms=10_000)
		button = FakeTrigger()
		cycle.toggle_on("button", button)
		self.sleep.plan[0] = button

		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes, ["button"])

	async def test_countdown_runs_out_to_a_timer_sleep(self):
		cycle = self.make(awake_ms=100)
		cycle.toggle_on("button", FakeTrigger())

		await self.run_until(cycle, 1)

		self.assertEqual(self.sleeps[0], TIMER)

	async def test_a_held_toggle_is_let_go_before_it_can_fire_again(self):
		"""The press that woke it must not send it straight back to sleep."""
		cycle = self.make(awake_ms=10_000)
		button = FakeTrigger(active=True)	# Still held
		cycle.toggle_on("button", button)
		cycle.on()
		await asyncio.sleep(0.3)
		self.assertEqual(self.sleeps, [])
		self.assertFalse(button.armed)

		button.active = False				# Let go
		await asyncio.sleep(0.3)
		self.assertTrue(button.armed)
		self.assertEqual(self.sleeps, [])
		cycle.off()

	async def test_a_trigger_can_turn_down_its_own_firing(self):
		"""confirm() returning False is not an event - it stays awake."""
		cycle = self.make(awake_ms=10_000)
		light = FakeTrigger()
		light.confirm = lambda: False
		cycle.toggle_on("light", light)
		cycle.on()
		await asyncio.sleep(0.2)

		light.fired = True
		await asyncio.sleep(0.2)
		cycle.off()

		self.assertEqual(self.sleeps, [])
		self.assertFalse(light.fired)

	async def test_a_turned_down_firing_while_asleep_sleeps_on(self):
		cycle = self.make(asleep_ms=100)
		light = FakeTrigger()
		light.confirm = lambda: False
		cycle.toggle_on("light", light)
		self.sleep.plan[0] = light

		await self.run_until(cycle, 1)

		self.assertEqual(self.wakes, [TIMER])

	async def test_awake_remaining_counts_down(self):
		cycle = self.make(awake_ms=1000)
		cycle.on()
		await asyncio.sleep(0.2)
		first = cycle.awake_remaining_ms
		await asyncio.sleep(0.2)
		second = cycle.awake_remaining_ms
		cycle.off()

		self.assertLess(second, first)
		self.assertLess(first, 1000)
		self.assertEqual(cycle.awake_remaining_ms, 0)


class ActionTests(SleepCycleTestCase):
	async def test_switches_awake_and_asleep_actions_in_order(self):
		log = []
		cycle = self.make(awake_action=Recorder("awake", log), asleep_action=Recorder("asleep", log))

		await self.run_until(cycle, 1)

		self.assertEqual(log[:5], ["awake.on", "awake.off", "asleep.on", "asleep.off", "awake.on"])

	async def test_starts_awake_without_touching_the_asleep_action(self):
		log = []
		cycle = self.make(awake_action=Recorder("awake", log), asleep_action=Recorder("asleep", log))
		cycle.on()
		await asyncio.sleep(0.01)
		first = log[0]
		cycle.off()

		self.assertEqual(first, "awake.on")

	async def test_off_switches_everything_off(self):
		log = []
		cycle = self.make(awake_action=Recorder("awake", log), asleep_action=Recorder("asleep", log))
		cycle.on()
		await asyncio.sleep(0.01)
		log.clear()

		cycle.off()

		self.assertEqual(log, ["asleep.off", "awake.off"])

	def test_refuses_to_sleep_under_a_shorter_watchdog(self):
		Watchdog.running_timeout_ms = 8000
		try:
			with self.assertRaises(ValueError):
				self.make(asleep_ms=15000).on()
			with self.assertRaises(ValueError):
				self.make(asleep_ms=None).on()
		finally:
			Watchdog.running_timeout_ms = None

	async def test_a_short_sleep_is_fine_under_a_watchdog(self):
		Watchdog.running_timeout_ms = 8000
		try:
			cycle = self.make(asleep_ms=2000)
			cycle.on()
			cycle.off()
		finally:
			Watchdog.running_timeout_ms = None


class PinTriggerTests(unittest.TestCase):
	def test_arming_sets_an_edge_interrupt_that_marks_it_fired(self):
		trigger = PinTrigger(4)
		trigger.arm()

		self.assertEqual(trigger.pin.irq_trigger, trigger.pin.IRQ_FALLING)
		self.assertFalse(trigger.fired)
		trigger.pin.fire_irq()
		self.assertTrue(trigger.fired)

	def test_disarm_removes_the_handler(self):
		trigger = PinTrigger(4)
		trigger.arm()
		trigger.disarm()

		self.assertIsNone(trigger.pin.irq_handler)

	def test_active_reads_the_triggered_level(self):
		trigger = PinTrigger(4)
		self.assertFalse(trigger.active)		# Pulled up, at rest

		trigger.pin.press()
		self.assertTrue(trigger.active)

	def test_pull_follows_the_edge(self):
		self.assertEqual(PinTrigger(4).pin.pull, PinTrigger(4).pin.PULL_UP)
		rising = PinTrigger(4, falling=False)
		self.assertEqual(rising.pin.pull, rising.pin.PULL_DOWN)

		rising.arm()
		self.assertEqual(rising.pin.irq_trigger, rising.pin.IRQ_RISING)


if __name__ == '__main__':
	unittest.main()
