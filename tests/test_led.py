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
