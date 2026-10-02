"""Sensors: one shape per board, errors contained, and a sampler that owns them.

The drivers are stubbed (tests/stubs), so this checks Corely's own wiring -
what each wrapper asks of its driver and what it hands back - not the chips.
"""

import asyncio
import unittest

import harness  # noqa: F401

from corely.sensors import Bme280, Sensor, SensorSampler, Sgp40, Tsl2591
from sgp40 import crc8


class FakeI2C:
	"""Records writes; serves reads from preset register contents."""

	def __init__(self):
		self.writes = []
		self.memory = {}
		self.reads = []
		self.fail = False

	def writeto_mem(self, addr, register, buf, addrsize=8):
		if self.fail:
			raise OSError("I2C write failed")
		self.writes.append((addr, register, bytes(buf)))

	def readfrom_mem_into(self, addr, register, buf):
		if self.fail:
			raise OSError("I2C read failed")
		data = self.memory[(addr, register)]
		buf[:len(data)] = data

	def readfrom(self, addr, count):
		if self.fail:
			raise OSError("I2C read failed")
		return self.reads.pop(0)


def bme280_data(raw_temp, raw_press, raw_hum):
	"""The 8 bytes at 0xF7: pressure and temperature as 20-bit, humidity 16."""
	def twenty(value):
		value <<= 4
		return [(value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF]
	return bytes(twenty(raw_press) + twenty(raw_temp) + [raw_hum >> 8, raw_hum & 0xFF])


def sgp40_reply(raw):
	"""What the SGP40 sends back: the 16-bit signal and its CRC."""
	msb, lsb = raw >> 8, raw & 0xFF
	return bytes([msb, lsb, crc8(msb, lsb)])


class Climate:
	"""Stands in for a Bme280 as the SGP40's compensation source."""

	def __init__(self, latest):
		self.latest = latest


class FixedSensor(Sensor):
	"""Returns set readings, or raises if told to."""

	def __init__(self, name, readings):
		super().__init__()
		self.name = name
		self.readings = readings
		self.fail = False
		self.reads = 0

	async def read(self):
		self.reads += 1
		if self.fail:
			raise OSError("gone")
		return dict(self.readings)


class SensorBaseTests(unittest.IsolatedAsyncioTestCase):
	async def test_update_stores_readings(self):
		sensor = FixedSensor("a", {'x': 1})

		result = await sensor.update()

		self.assertEqual(result, {'x': 1})
		self.assertEqual(sensor.latest, {'x': 1})
		self.assertIsNone(sensor.error)

	async def test_failed_read_empties_latest_and_keeps_the_error(self):
		sensor = FixedSensor("a", {'x': 1})
		await sensor.update()
		sensor.fail = True

		result = await sensor.update()

		self.assertEqual(result, {})
		self.assertEqual(sensor.latest, {})
		self.assertIsInstance(sensor.error, OSError)

	async def test_recovers_after_a_failed_read(self):
		sensor = FixedSensor("a", {'x': 1})
		sensor.fail = True
		await sensor.update()
		sensor.fail = False

		await sensor.update()

		self.assertEqual(sensor.latest, {'x': 1})
		self.assertIsNone(sensor.error)

	async def test_programming_errors_are_not_swallowed(self):
		"""Only I/O errors count as a failed read; a bug must still surface."""
		class Broken(Sensor):
			async def read(self):
				raise NameError("typo")

		with self.assertRaises(NameError):
			await Broken().update()


class Bme280Tests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.i2c = FakeI2C()

	def test_starts_the_chip_measuring_continuously(self):
		Bme280(self.i2c)

		registers = [register for _, register, _ in self.i2c.writes]
		# Config while still asleep, then humidity, then normal mode last.
		self.assertEqual(registers[-3:], [0xF5, 0xF2, 0xF4])
		ctrl_meas = self.i2c.writes[-1][2][0]
		self.assertEqual(ctrl_meas & 0b11, 0b11)

	async def test_reads_named_values_in_hpa(self):
		sensor = Bme280(self.i2c)
		self.i2c.memory[(0x76, 0xF7)] = bme280_data(244000, 836300, 30600)

		readings = await sensor.read()

		self.assertAlmostEqual(readings['temperature'], 24.4)
		self.assertAlmostEqual(readings['pressure'], 836.3)
		self.assertAlmostEqual(readings['humidity'], 30.6)

	async def test_no_reading_before_the_first_measurement(self):
		sensor = Bme280(self.i2c)
		self.i2c.memory[(0x76, 0xF7)] = bme280_data(0x80000, 0x80000, 0x8000)

		self.assertEqual(await sensor.read(), {})

	async def test_address_is_configurable(self):
		sensor = Bme280(self.i2c, address=0x77)
		self.i2c.memory[(0x77, 0xF7)] = bme280_data(244000, 836300, 30600)

		self.assertIn('temperature', await sensor.read())


class Tsl2591Tests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.sensor = Tsl2591(FakeI2C())
		self.chip = self.sensor._chip

	async def test_reads_lux_and_raw_channels(self):
		readings = await self.sensor.read()

		self.assertEqual(readings, {'lux': 60.3, 'light_full': 588, 'light_ir': 133})

	async def test_overflow_reads_as_max_lux(self):
		self.chip.overflow = True

		readings = await self.sensor.read()

		self.assertEqual(readings['lux'], Tsl2591.MAX_LUX)

	async def test_negative_lux_is_clamped(self):
		self.chip.lux_value = -0.4

		self.assertEqual((await self.sensor.read())['lux'], 0.0)

	async def test_i2c_failure_is_a_failed_read(self):
		self.chip.fail = True

		self.assertEqual(await self.sensor.update(), {})
		self.assertIsInstance(self.sensor.error, OSError)

	def test_disable_powers_the_chip_down(self):
		self.sensor.disable()
		self.assertFalse(self.chip.enabled)


class Sgp40Tests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.i2c = FakeI2C()

	def make(self, climate=None, measure_ms=0):
		sensor = Sgp40(self.i2c, climate=climate)
		sensor.MEASURE_MS = measure_ms
		return sensor

	def sent_parameters(self):
		"""(humidity word, temperature word) from the last measure command."""
		_, register, data = self.i2c.writes[-1]
		self.assertEqual(register, 0x260f)
		return (data[0] << 8 | data[1], data[3] << 8 | data[4])

	async def test_reads_raw_signal(self):
		sensor = self.make()
		self.i2c.reads.append(sgp40_reply(26357))

		readings = await sensor.read()

		self.assertEqual(readings['voc_raw'], 26357)

	async def test_sends_valid_crcs(self):
		sensor = self.make()
		self.i2c.reads.append(sgp40_reply(26357))
		await sensor.read()

		_, _, data = self.i2c.writes[-1]
		self.assertEqual(data[2], crc8(data[0], data[1]))
		self.assertEqual(data[5], crc8(data[3], data[4]))

	async def test_compensates_with_the_climate_sensor(self):
		sensor = self.make(climate=Climate({'humidity': 30.0, 'temperature': 24.0}))
		self.i2c.reads.append(sgp40_reply(26357))

		await sensor.read()

		humidity, temperature = self.sent_parameters()
		self.assertEqual(humidity, -(-30.0 * 0xffff // 100))
		self.assertEqual(temperature, -(-(24.0 + 45) * 0xffff // 175))

	async def test_defaults_without_a_climate_reading(self):
		for climate in (None, Climate({})):
			sensor = self.make(climate=climate)
			self.i2c.reads.append(sgp40_reply(26357))

			await sensor.read()

			humidity, temperature = self.sent_parameters()
			self.assertEqual(humidity, -(-50 * 0xffff // 100))
			self.assertEqual(temperature, -(-(25 + 45) * 0xffff // 175))

	async def test_voc_index_is_none_while_warming_up(self):
		sensor = self.make()
		for _ in range(Sgp40.WARMUP_SAMPLES):
			self.i2c.reads.append(sgp40_reply(26357))
			self.assertIsNone((await sensor.read())['voc_index'])

		self.i2c.reads.append(sgp40_reply(26357))
		self.assertEqual((await sensor.read())['voc_index'], 100)

	async def test_every_sample_feeds_the_algorithm(self):
		"""The algorithm learns from warm-up samples too."""
		sensor = self.make()
		for raw in (26000, 26100, 26200):
			self.i2c.reads.append(sgp40_reply(raw))
			await sensor.read()

		self.assertEqual(sensor._voc.processed, [26000, 26100, 26200])

	async def test_bad_crc_is_a_failed_read(self):
		sensor = self.make()
		self.i2c.reads.append(bytes([0x66, 0xF5, 0x00]))

		self.assertEqual(await sensor.update(), {})
		self.assertIsInstance(sensor.error, sensor._chip.CRCException)

	async def test_measurement_wait_does_not_block_the_loop(self):
		sensor = self.make(measure_ms=200)
		self.i2c.reads.append(sgp40_reply(26357))
		ran = []

		async def other():
			ran.append(True)

		task = asyncio.create_task(other())
		await sensor.read()

		self.assertEqual(ran, [True])
		await task


class SensorSamplerTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.a = FixedSensor("a", {'x': 1})
		self.b = FixedSensor("b", {'y': 2})
		self.sampler = SensorSampler([self.a, self.b])

	async def test_sample_merges_every_sensor(self):
		readings = await self.sampler.sample()

		self.assertEqual(readings, {'x': 1, 'y': 2})
		self.assertEqual(self.sampler.readings, readings)

	async def test_a_failed_sensor_is_left_out(self):
		self.a.fail = True

		readings = await self.sampler.sample()

		self.assertEqual(readings, {'y': 2})

	async def test_later_sensor_wins_a_key_clash(self):
		self.b.readings = {'x': 9}

		self.assertEqual(await self.sampler.sample(), {'x': 9})

	async def test_next_wakes_every_waiter_once(self):
		first = asyncio.create_task(self.sampler.next())
		second = asyncio.create_task(self.sampler.next())
		await asyncio.sleep(0)

		await self.sampler.sample()

		self.assertEqual(await first, {'x': 1, 'y': 2})
		self.assertEqual(await second, {'x': 1, 'y': 2})

	async def test_next_waits_for_a_new_sample(self):
		await self.sampler.sample()
		waiter = asyncio.create_task(self.sampler.next())
		await asyncio.sleep(0.05)

		self.assertFalse(waiter.done())
		await self.sampler.sample()
		await asyncio.wait_for(waiter, 1)

	async def test_run_keeps_sampling_through_failures(self):
		sampler = SensorSampler([self.a], interval_ms=50)
		self.a.fail = True
		task = asyncio.create_task(sampler.run())

		await asyncio.sleep(0.3)
		self.a.fail = False
		readings = await asyncio.wait_for(sampler.next(), 1)
		task.cancel()

		self.assertEqual(readings, {'x': 1})
		self.assertGreaterEqual(self.a.reads, 3)


if __name__ == '__main__':
	unittest.main()
