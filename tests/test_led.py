"""LED actions drive the pin, and stop cleanly."""

import asyncio
import unittest

import harness  # noqa: F401

from corely.led import LedSolid, LedBlinking


class LedSolidTests(unittest.TestCase):
	def test_on_and_off_drive_the_pin(self):
		led = LedSolid(18)

		led.on()
		self.assertEqual(led.led.value(), 1)

		led.off()
		self.assertEqual(led.led.value(), 0)


class LedBlinkingTests(unittest.IsolatedAsyncioTestCase):
	async def test_blinks_while_on(self):
		led = LedBlinking(18, blink_interval_ms=5)

		led.on()
		await asyncio.sleep_ms(40)
		led.off()

		# Expect several alternating writes, not one steady state.
		self.assertGreater(len(led.led.writes), 2)
		self.assertIn(1, led.led.writes)
		self.assertIn(0, led.led.writes)

	async def test_off_leaves_led_dark(self):
		led = LedBlinking(18, blink_interval_ms=5)

		led.on()
		await asyncio.sleep_ms(20)
		led.off()
		await asyncio.sleep_ms(20)

		self.assertEqual(led.led.value(), 0)

	async def test_off_stops_further_writes(self):
		led = LedBlinking(18, blink_interval_ms=5)

		led.on()
		await asyncio.sleep_ms(20)
		led.off()

		settled = len(led.led.writes)
		await asyncio.sleep_ms(30)

		self.assertEqual(len(led.led.writes), settled)

	async def test_restart_resumes_blinking(self):
		led = LedBlinking(18, blink_interval_ms=5)

		led.on()
		await asyncio.sleep_ms(20)
		led.off()
		led.on()
		await asyncio.sleep_ms(20)

		writes_while_running = len(led.led.writes)
		await asyncio.sleep_ms(20)
		self.assertGreater(len(led.led.writes), writes_while_running)

		led.off()


if __name__ == '__main__':
	unittest.main()
