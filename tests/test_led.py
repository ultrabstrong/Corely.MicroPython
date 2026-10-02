"""Led drives the pin, switches modes, and stops cleanly.

Timings are deliberately generous - a PC event loop has much coarser timer
granularity than the device, so tight intervals only add flakiness.
"""

import asyncio
import unittest

import harness  # noqa: F401

from corely.led import Led


BLINK_MS = 10
SETTLE_MS = 80


class SolidLedTests(unittest.TestCase):
	def test_on_and_off_drive_the_pin(self):
		led = Led(18)

		led.on()
		self.assertEqual(led.led.value(), 1)

		led.off()
		self.assertEqual(led.led.value(), 0)

	def test_solid_is_the_default(self):
		led = Led(18)

		self.assertFalse(led.is_blinking)

	def test_tracks_whether_it_is_on(self):
		led = Led(18)
		self.assertFalse(led.is_on)

		led.on()
		self.assertTrue(led.is_on)

		led.off()
		self.assertFalse(led.is_on)


class BrightnessTests(unittest.IsolatedAsyncioTestCase):
	def test_full_brightness_stays_digital(self):
		led = Led(18)

		led.on()

		self.assertIsNone(led._pwm)
		self.assertEqual(led.led.value(), 1)

	def test_dimming_switches_to_pwm(self):
		led = Led(18, brightness=0.5)

		led.on()

		self.assertIsNotNone(led._pwm)
		self.assertTrue(0 < led._pwm.duty_u16() < 65535)

	def test_dimming_while_lit_applies_immediately(self):
		led = Led(18)
		led.on()

		led.set_brightness(0.25)

		self.assertLess(led._pwm.duty_u16(), 65535 // 2)

	def test_off_darkens_a_dimmed_led(self):
		led = Led(18, brightness=0.5)
		led.on()

		led.off()

		self.assertEqual(led._pwm.duty_u16(), 0)

	def test_rejects_out_of_range_brightness(self):
		led = Led(18)

		with self.assertRaises(ValueError):
			led.set_brightness(1.5)
		with self.assertRaises(ValueError):
			led.set_brightness(-0.1)

	async def test_blinking_respects_brightness(self):
		led = Led(18, blink_interval_ms=BLINK_MS, brightness=0.5)

		led.on()
		await asyncio.sleep_ms(SETTLE_MS)
		duties = list(led._pwm.duties)
		led.off()

		self.assertIn(0, duties)
		self.assertTrue(any(0 < duty < 65535 for duty in duties))


class BlinkingLedTests(unittest.IsolatedAsyncioTestCase):
	async def test_blinks_while_on(self):
		led = Led(18, blink_interval_ms=BLINK_MS)

		led.on()
		await asyncio.sleep_ms(SETTLE_MS)
		led.off()

		self.assertGreater(len(led.led.writes), 2)
		self.assertIn(1, led.led.writes)
		self.assertIn(0, led.led.writes)

	async def test_off_leaves_led_dark_and_quiet(self):
		led = Led(18, blink_interval_ms=BLINK_MS)

		led.on()
		await asyncio.sleep_ms(SETTLE_MS)
		led.off()
		settled = len(led.led.writes)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(led.led.value(), 0)
		self.assertEqual(len(led.led.writes), settled)

	async def test_is_on_covers_blinking(self):
		led = Led(18, blink_interval_ms=BLINK_MS)

		led.on()
		self.assertTrue(led.is_on)

		led.off()
		self.assertFalse(led.is_on)


class ModeSwitchTests(unittest.IsolatedAsyncioTestCase):
	async def test_blink_then_solid_stops_toggling(self):
		led = Led(18, blink_interval_ms=BLINK_MS)
		led.on()
		await asyncio.sleep_ms(SETTLE_MS)

		led.solid()
		await asyncio.sleep_ms(SETTLE_MS)
		settled = len(led.led.writes)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertFalse(led.is_blinking)
		self.assertEqual(led.led.value(), 1)
		self.assertEqual(len(led.led.writes), settled)

		led.off()

	async def test_solid_then_blink_starts_toggling(self):
		led = Led(18)
		led.on()

		led.blink(BLINK_MS)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertTrue(led.is_blinking)
		self.assertGreater(len(led.led.writes), 2)

		led.off()

	async def test_mode_change_while_off_does_not_light_the_led(self):
		led = Led(18)

		led.blink(BLINK_MS)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertFalse(led.is_on)
		self.assertEqual(led.led.value(), 0)

	async def test_blink_without_interval_uses_a_default(self):
		led = Led(18)

		led.blink()

		self.assertEqual(led.blink_interval_ms, Led.DEFAULT_BLINK_MS)

	async def test_blinking_view_inherits_the_leds_interval(self):
		led = Led(18, blink_interval_ms=BLINK_MS)

		view = led.blinking()

		self.assertEqual(view.blink_interval_ms, BLINK_MS)


class PolarityTests(unittest.IsolatedAsyncioTestCase):
	"""active_high=False: the LED lights when the pin goes low."""

	def test_active_low_inverts_levels(self):
		led = Led(18, active_high=False)

		led.on()
		self.assertEqual(led.led.value(), 0)

		led.off()
		self.assertEqual(led.led.value(), 1)

	def test_construction_leaves_led_off(self):
		self.assertEqual(Led(18).led.value(), 0)
		self.assertEqual(Led(18, active_high=False).led.value(), 1)

	async def test_active_low_blink_rests_off(self):
		led = Led(18, blink_interval_ms=BLINK_MS, active_high=False)

		led.on()
		await asyncio.sleep_ms(SETTLE_MS)
		led.off()

		self.assertIn(0, led.led.writes)
		self.assertEqual(led.led.value(), 1)

	def test_active_low_dimming_inverts_the_duty(self):
		led = Led(18, brightness=0.25, active_high=False)

		led.on()
		self.assertGreater(led._pwm.duty_u16(), 65535 // 2)

		led.off()
		self.assertEqual(led._pwm.duty_u16(), 65535)


PULSE_MS = 200
# Coarse enough that each step (12ms) is not swallowed by the PC timer, fine
# enough for several distinct levels on the way up.
PULSE_STEPS = 16


class PulseTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self._steps = Led.PULSE_STEPS
		Led.PULSE_STEPS = PULSE_STEPS

	def tearDown(self):
		Led.PULSE_STEPS = self._steps

	async def pulse_duties(self, led, cycles=1.5):
		led.on()
		await asyncio.sleep_ms(int(PULSE_MS * cycles))
		duties = list(led._pwm.duties)
		led.off()
		return duties

	async def test_pulse_writes_levels_in_between(self):
		led = Led(18)
		led.pulse(PULSE_MS)

		duties = await self.pulse_duties(led)

		in_between = {duty for duty in duties if 0 < duty < 65535}
		self.assertGreater(len(in_between), 5)

	async def test_pulse_rises_and_falls(self):
		led = Led(18)
		led.pulse(PULSE_MS)

		duties = await self.pulse_duties(led)

		rises = any(b > a for a, b in zip(duties, duties[1:]))
		falls = any(b < a for a, b in zip(duties, duties[1:]))
		self.assertTrue(rises and falls)

	async def test_brightness_caps_the_pulse(self):
		led = Led(18, brightness=0.5)
		led.pulse(PULSE_MS)

		duties = await self.pulse_duties(led)

		self.assertLessEqual(max(duties), 65535 // 2 + 1)

	def test_pulse_sets_up_pwm(self):
		led = Led(18)
		self.assertIsNone(led._pwm)

		led.pulse(PULSE_MS)

		self.assertIsNotNone(led._pwm)
		self.assertTrue(led.is_pulsing)
		self.assertFalse(led.is_blinking)

	async def test_blinking_stays_digital(self):
		"""The onboard LED has no PWM; blink must not need it."""
		led = Led(18, blink_interval_ms=BLINK_MS)

		led.on()
		await asyncio.sleep_ms(SETTLE_MS)
		led.off()

		self.assertIsNone(led._pwm)
		self.assertEqual(set(led.led.writes), {0, 1})

	async def test_pulse_then_solid_stops_the_fade(self):
		led = Led(18)
		led.pulse(PULSE_MS)
		led.on()
		await asyncio.sleep_ms(SETTLE_MS)

		led.solid()
		settled = len(led._pwm.duties)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(len(led._pwm.duties), settled)
		self.assertEqual(led._pwm.duty_u16(), 65535)
		led.off()

	async def test_off_stops_pulsing_dark(self):
		led = Led(18)
		led.pulse(PULSE_MS)
		led.on()
		await asyncio.sleep_ms(SETTLE_MS)

		led.off()
		settled = len(led._pwm.duties)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(led._pwm.duty_u16(), 0)
		self.assertEqual(len(led._pwm.duties), settled)

	async def test_pulsing_view_in_a_cycler(self):
		from corely.action import ActionCycler
		led = Led(18)
		cycler = ActionCycler([led.steady(), led.pulsing(PULSE_MS)])

		cycler.on()
		self.assertFalse(led.is_pulsing)
		cycler.move_next()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertTrue(led.is_pulsing)
		self.assertTrue(led.is_on)

		cycler.off()
		self.assertFalse(led.is_on)


class SharedLedTests(unittest.IsolatedAsyncioTestCase):
	async def test_two_states_share_one_pin(self):
		"""The BLE demo's case: blinking while advertising, solid when connected."""
		led = Led(18)
		advertising = led.blinking(BLINK_MS)
		connected = led.steady()

		advertising.on()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertTrue(led.is_blinking)
		self.assertTrue(led.is_on)

		# The state machine turns the old action off, then the new one on.
		advertising.off()
		connected.on()
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertFalse(led.is_blinking)
		self.assertTrue(led.is_on)
		self.assertEqual(led.led.value(), 1)

		connected.off()
		self.assertFalse(led.is_on)
		self.assertEqual(led.led.value(), 0)

	async def test_steady_leaves_no_task_running(self):
		led = Led(18)
		connected = led.steady()

		connected.on()
		settled = len(led.led.writes)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(len(led.led.writes), settled)

		connected.off()


if __name__ == '__main__':
	unittest.main()
