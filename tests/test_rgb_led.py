"""RgbLed: colours, modes, polarity, and the rainbow sweep.

Timings are deliberately generous - a PC event loop has much coarser timer
granularity than the device.
"""

import asyncio
import unittest

import harness  # noqa: F401

from corely.rgb_led import (
	BLACK,
	BLUE,
	GREEN,
	RED,
	RgbLed,
	hue_to_colour,
	resolve_colour,
)


BLINK_MS = 10
SETTLE_MS = 80
FULL = 65535


RAW = (1.0, 1.0, 1.0)  # no per-channel correction, so duties are predictable


def levels(rgb):
	"""The current duty of each channel, as 0-65535."""
	return tuple(channel.duty_u16() for channel in rgb._channels)


class ColourHelperTests(unittest.TestCase):
	def test_resolves_names_case_insensitively(self):
		self.assertEqual(resolve_colour('RED'), RED)
		self.assertEqual(resolve_colour('teal'), (0, 255, 120))

	def test_resolves_tuples_unchanged(self):
		self.assertEqual(resolve_colour((12, 34, 56)), (12, 34, 56))

	def test_rejects_unknown_names(self):
		with self.assertRaises(ValueError):
			resolve_colour('octarine')

	def test_rejects_malformed_tuples(self):
		with self.assertRaises(ValueError):
			resolve_colour((255, 0))

	def test_hue_wheel_hits_the_primaries(self):
		self.assertEqual(hue_to_colour(0), (255, 0, 0))
		self.assertEqual(hue_to_colour(120), (0, 255, 0))
		self.assertEqual(hue_to_colour(240), (0, 0, 255))

	def test_hue_wraps(self):
		self.assertEqual(hue_to_colour(360), hue_to_colour(0))
		self.assertEqual(hue_to_colour(480), hue_to_colour(120))


class SolidColourTests(unittest.TestCase):
	def test_starts_dark(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)

		self.assertEqual(levels(rgb), (0, 0, 0))
		self.assertFalse(rgb.is_on)

	def test_on_shows_the_colour(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED)

		rgb.on()

		self.assertEqual(levels(rgb), (FULL, 0, 0))
		self.assertTrue(rgb.is_on)

	def test_off_goes_dark(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=GREEN)
		rgb.on()

		rgb.off()

		self.assertEqual(levels(rgb), (0, 0, 0))

	def test_colour_change_applies_immediately_while_lit(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED)
		rgb.on()

		rgb.solid(BLUE)

		self.assertEqual(levels(rgb), (0, 0, FULL))

	def test_colour_change_while_off_stays_dark(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)

		rgb.solid(BLUE)

		self.assertEqual(levels(rgb), (0, 0, 0))
		self.assertFalse(rgb.is_on)

	def test_named_colours_work(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour='green')

		rgb.on()

		self.assertEqual(levels(rgb), (0, FULL, 0))

	def test_mixed_colours_land_between(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=(255, 128, 0))

		rgb.on()

		red, green, blue = levels(rgb)
		self.assertEqual(red, FULL)
		self.assertEqual(blue, 0)
		self.assertTrue(0 < green < FULL)

	def test_brightness_scales_every_channel(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=(255, 255, 255), brightness=0.5)

		rgb.on()

		for level in levels(rgb):
			self.assertTrue(0 < level < FULL)

	def test_channel_scale_corrects_for_die_efficiency(self):
		"""Equal duty on every channel does not look equal, hence the gains."""
		raw = RgbLed(7, 8, 9, channel_scale=RAW, colour='yellow')
		corrected = RgbLed(10, 11, 12, colour='yellow')

		raw.on()
		corrected.on()

		# Yellow is red + green. Raw drives both to full, which reads as green
		# because the green die is brighter; corrected holds green back.
		self.assertEqual(levels(raw)[:2], (FULL, FULL))
		self.assertEqual(levels(corrected)[0], FULL)
		self.assertLess(levels(corrected)[1], FULL)


class PolarityTests(unittest.TestCase):
	def test_common_anode_inverts_every_channel(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED, active_high=False)

		self.assertEqual(levels(rgb), (FULL, FULL, FULL))  # dark

		rgb.on()

		self.assertEqual(levels(rgb), (0, FULL, FULL))  # red lit


class ModeTests(unittest.IsolatedAsyncioTestCase):
	async def test_blink_toggles_the_channels(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED)
		rgb.blink(BLINK_MS)

		rgb.on()
		await asyncio.sleep_ms(SETTLE_MS)
		rgb.off()

		red_channel = rgb._channels[0]
		self.assertIn(FULL, red_channel.duties)
		self.assertIn(0, red_channel.duties)

	async def test_off_stops_the_blink_task(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED)
		rgb.blink(BLINK_MS)
		rgb.on()
		await asyncio.sleep_ms(SETTLE_MS)

		rgb.off()
		settled = len(rgb._channels[0].duties)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(len(rgb._channels[0].duties), settled)
		self.assertEqual(levels(rgb), (0, 0, 0))

	async def test_rainbow_moves_through_colours(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		rgb.rainbow(cycle_ms=120)

		rgb.on()
		await asyncio.sleep_ms(SETTLE_MS)
		seen = set(zip(*(channel.duties for channel in rgb._channels)))
		rgb.off()

		self.assertGreater(len(seen), 2)

	async def test_switching_mode_while_lit_takes_effect(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW, colour=RED)
		rgb.on()
		self.assertEqual(rgb.mode, 'solid')

		rgb.blink(BLINK_MS)
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(rgb.mode, 'blink')
		self.assertTrue(rgb.is_on)

		rgb.solid()
		await asyncio.sleep_ms(SETTLE_MS)
		settled = len(rgb._channels[0].duties)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(rgb.mode, 'solid')
		self.assertEqual(levels(rgb), (FULL, 0, 0))
		self.assertEqual(len(rgb._channels[0].duties), settled)

		rgb.off()


class SharedRgbTests(unittest.IsolatedAsyncioTestCase):
	async def test_states_share_one_led(self):
		"""A state machine's case: green when connected, red when not."""
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		connected = rgb.steady(GREEN)
		disconnected = rgb.steady(RED)

		connected.on()
		self.assertEqual(levels(rgb), (0, FULL, 0))

		connected.off()
		disconnected.on()
		self.assertEqual(levels(rgb), (FULL, 0, 0))

		disconnected.off()
		self.assertEqual(levels(rgb), (0, 0, 0))

	async def test_blinking_view_blinks_its_colour(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		ephemeral = rgb.blinking(BLUE, interval_ms=BLINK_MS)

		ephemeral.on()
		await asyncio.sleep_ms(SETTLE_MS)
		blue_channel = rgb._channels[2]
		ephemeral.off()

		self.assertIn(FULL, blue_channel.duties)
		self.assertIn(0, blue_channel.duties)

	async def test_cycling_view_runs_the_rainbow(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		party = rgb.cycling(cycle_ms=120)

		party.on()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(rgb.mode, 'rainbow')
		self.assertTrue(rgb.is_on)

		party.off()
		self.assertEqual(levels(rgb), (0, 0, 0))


PULSE_MS = 200


class PulseTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		# Steps coarse enough for the PC timer to see each one.
		self._steps = RgbLed.PULSE_STEPS
		RgbLed.PULSE_STEPS = 16

	def tearDown(self):
		RgbLed.PULSE_STEPS = self._steps

	async def pulse(self, colour):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		rgb.pulse(PULSE_MS, colour=colour)
		rgb.on()
		await asyncio.sleep_ms(int(PULSE_MS * 1.5))
		rgb.off()
		return rgb

	async def test_pulse_writes_levels_in_between(self):
		rgb = await self.pulse(RED)

		red = rgb._channels[0].duties
		self.assertGreater(len({duty for duty in red if 0 < duty < FULL}), 5)
		self.assertTrue(any(b < a for a, b in zip(red, red[1:])))

	async def test_pulse_keeps_the_hue(self):
		"""Both channels of an orange fade together, so it stays orange."""
		rgb = await self.pulse((255, 128, 0))

		red, green, blue = (channel.duties for channel in rgb._channels)
		for r, g in zip(red, green):
			if r > 2000:
				self.assertAlmostEqual(g / r, 128 / 255, delta=0.02)
		self.assertEqual(set(blue), {0})

	async def test_off_stops_pulsing_dark(self):
		rgb = await self.pulse(GREEN)
		settled = len(rgb._channels[1].duties)
		await asyncio.sleep_ms(SETTLE_MS)

		self.assertEqual(levels(rgb), (0, 0, 0))
		self.assertEqual(len(rgb._channels[1].duties), settled)

	async def test_pulsing_view_pulses_its_colour(self):
		rgb = RgbLed(7, 8, 9, channel_scale=RAW)
		view = rgb.pulsing('blue', period_ms=PULSE_MS)

		view.on()
		await asyncio.sleep_ms(SETTLE_MS)
		self.assertEqual(rgb.mode, 'pulse')
		self.assertEqual(rgb.colour, BLUE)

		view.off()
		self.assertEqual(levels(rgb), (0, 0, 0))


if __name__ == '__main__':
	unittest.main()
