"""ThresholdAlarm: one event per crossing, with recovery, across reboots."""

import asyncio
import unittest

import harness  # noqa: F401

from corely.alarms import ABOVE, BELOW, RECOVERING, WATCHING, ThresholdAlarm


class FakeAlarmSensor:
	"""Implements the alarm contract; tests set the reading."""

	def __init__(self, value=1000):
		self.value = value
		self.armed = None		# (below, above) last armed
		self.clears = 0
		self.disarmed = False
		self.latched = False

	def alarm_value(self):
		return self.value

	def arm_alarm(self, below=None, above=None):
		self.armed = (below, above)

	def clear_alarm(self):
		self.clears += 1

	def disarm_alarm(self):
		self.disarmed = True

	def alarm_latched(self):
		return self.latched


def make(sensor, **kwargs):
	return ThresholdAlarm(sensor, 2, **kwargs)


class SwapTests(unittest.TestCase):
	def test_arms_for_the_crossing(self):
		sensor = FakeAlarmSensor()
		alarm = make(sensor, below=300, recover=100)

		self.assertEqual(sensor.armed, (300, None))
		self.assertEqual(alarm.state, WATCHING)

	def test_a_crossing_is_one_event_then_arms_the_recovery(self):
		sensor = FakeAlarmSensor()
		events = []
		alarm = make(sensor, below=300, recover=100, on_event=events.append)

		sensor.value = 150
		self.assertTrue(alarm.confirm())

		self.assertEqual(events, [BELOW])
		self.assertEqual(sensor.armed, (None, 400))		# back at 300 + 100
		self.assertEqual(alarm.state, RECOVERING)

	def test_the_recovery_is_not_an_event_and_rearms_the_crossing(self):
		sensor = FakeAlarmSensor()
		events = []
		alarm = make(sensor, below=300, recover=100, on_event=events.append)
		sensor.value = 150
		alarm.confirm()

		sensor.value = 900
		self.assertFalse(alarm.confirm())

		self.assertEqual(events, [BELOW])
		self.assertEqual(sensor.armed, (300, None))
		self.assertEqual(alarm.state, WATCHING)

	def test_rising_above_recovers_below_the_threshold(self):
		sensor = FakeAlarmSensor(value=20)
		alarm = make(sensor, above=30, recover=5)

		sensor.value = 35
		alarm.confirm()

		self.assertEqual(alarm.last_event, ABOVE)
		self.assertEqual(sensor.armed, (25, None))

	def test_recover_as_a_function_of_the_threshold(self):
		sensor = FakeAlarmSensor()
		alarm = make(sensor, below=300, recover=lambda threshold: threshold * 2)

		sensor.value = 100
		alarm.confirm()

		self.assertEqual(sensor.armed, (None, 600))

	def test_thresholds_as_functions_of_the_reading(self):
		"""The finger rule: a quarter of whatever the room reads."""
		sensor = FakeAlarmSensor(value=2897)
		make(sensor, below=lambda now: max(120, now // 4), recover=lambda t: t * 2)

		self.assertEqual(sensor.armed, (724, None))

	def test_function_thresholds_follow_the_room_on_rearm(self):
		sensor = FakeAlarmSensor(value=2000)
		alarm = make(sensor, below=lambda now: now // 4, recover=lambda t: t * 2)
		sensor.value = 100
		alarm.confirm()

		sensor.value = 4000		# Brighter room now
		alarm.confirm()

		self.assertEqual(sensor.armed, (1000, None))

	def test_a_band_fires_either_way(self):
		sensor = FakeAlarmSensor(value=20)
		events = []
		alarm = make(sensor, below=10, above=30, recover=2, on_event=events.append)

		sensor.value = 35
		alarm.confirm()
		sensor.value = 20
		alarm.confirm()
		sensor.value = 5
		alarm.confirm()

		self.assertEqual(events, [ABOVE, BELOW])
		self.assertEqual(sensor.armed, (None, 12))

	def test_a_blip_already_back_counts_the_nearer_threshold(self):
		sensor = FakeAlarmSensor(value=20)
		alarm = make(sensor, below=10, above=30, recover=2)

		sensor.value = 12		# Latched, but back in range by the time it reads
		alarm.confirm()

		self.assertEqual(alarm.last_event, BELOW)

	def test_needs_a_threshold_and_a_recovery(self):
		with self.assertRaises(ValueError):
			make(FakeAlarmSensor(), recover=1)
		with self.assertRaises(ValueError):
			make(FakeAlarmSensor(), below=10)

	def test_stop_switches_the_alarm_off(self):
		sensor = FakeAlarmSensor()
		alarm = make(sensor, below=300, recover=100)

		alarm.stop()

		self.assertTrue(sensor.disarmed)


class RebootTests(unittest.TestCase):
	"""Deep sleep reboots; the alarm carries on from a snapshot."""

	def test_restoring_a_recovering_alarm_rearms_the_recovery(self):
		sensor = FakeAlarmSensor()
		alarm = make(sensor, below=300, recover=100)
		sensor.value = 150
		alarm.confirm()
		snapshot = alarm.snapshot()

		fresh_sensor = FakeAlarmSensor(value=150)
		restored = make(fresh_sensor, below=300, recover=100, restore=snapshot)

		self.assertEqual(restored.state, RECOVERING)
		self.assertEqual(fresh_sensor.armed, (None, 400))
		self.assertEqual(restored.events, 1)

	def test_restoring_a_watching_alarm_keeps_its_limits(self):
		"""Not recomputed from the reading - the room may be dark right now."""
		sensor = FakeAlarmSensor(value=2897)
		alarm = make(sensor, below=lambda now: now // 4, recover=lambda t: t * 2)
		snapshot = alarm.snapshot()

		fresh_sensor = FakeAlarmSensor(value=50)
		make(fresh_sensor, below=lambda now: now // 4, recover=lambda t: t * 2, restore=snapshot)

		self.assertEqual(fresh_sensor.armed, (724, None))

	def test_latched_reads_the_sensor(self):
		sensor = FakeAlarmSensor()
		alarm = make(sensor, below=300, recover=100)

		sensor.latched = True
		self.assertTrue(alarm.latched)


class AwakeTests(unittest.IsolatedAsyncioTestCase):
	async def test_run_reports_crossings_while_awake(self):
		sensor = FakeAlarmSensor()
		events = []
		alarm = make(sensor, below=300, recover=100, on_event=events.append, poll_ms=5)
		task = asyncio.create_task(alarm.run())
		await asyncio.sleep(0.05)

		sensor.value = 100
		alarm._pin.pin.fire_irq()
		await asyncio.sleep(0.05)
		task.cancel()

		self.assertEqual(events, [BELOW])


if __name__ == '__main__':
	unittest.main()
