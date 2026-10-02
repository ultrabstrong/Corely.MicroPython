"""Sensors - one async shape for every board, and a sampler that owns them.

Sensors are read, not switched, so they are not Actions. They follow Corely's
other two shapes instead:

	Sensor         base class owns error handling; subclasses implement read(),
	               the way TaskAction owns the task and subclasses run()
	SensorSampler  long-running, started with create_task(sampler.run()),
	               like Button and WiFiMonitor

Every read returns a flat dict of named values, and the sampler merges them:

	bme = Bme280(i2c)
	sampler = SensorSampler([bme, Tsl2591(i2c), Sgp40(i2c, climate=bme)])
	asyncio.create_task(sampler.run())

	readings = await sampler.next()   # {'temperature': 24.4, 'lux': 60.3, ...}

| Board   | Keys                                         |
|---------|----------------------------------------------|
| Bme280  | temperature (C), humidity (%), pressure (hPa)|
| Tsl2591 | lux, light_full, light_ir (raw counts)       |
| Sgp40   | voc_index (None while warming up), voc_raw   |

The register maps and compensation maths come from the vendored drivers;
these classes only make them async and give them one shape. Each imports its
driver when created, so a project using one sensor never loads the others.

Opening sensors is the application's job: a constructor raises if its chip is
absent, and the app decides whether to carry on without it.
"""

import asyncio
import time


class Sensor:
	"""Something read on demand, returning a dict of named readings.

	Subclasses implement read() and let I/O errors propagate; update() catches
	them, so one loose wire empties one sensor's readings rather than stopping
	whoever is sampling.
	"""

	name = "sensor"
	errors = (OSError, RuntimeError)	# What counts as a failed read

	def __init__(self, debug=False):
		"""
		Args:
			debug: If True, prints failed reads
		"""
		self.debug = debug
		self.latest = {}
		self.error = None

	async def read(self):
		"""Override: return a dict of named readings. May raise."""
		raise NotImplementedError("Subclasses must implement read()")

	async def update(self):
		"""Read into self.latest.

		A failed read empties latest - so a display shows nothing rather than a
		stale number - and keeps the exception in self.error.

		Returns:
			The new readings, {} on failure
		"""
		try:
			self.latest = await self.read()
			self.error = None
		except self.errors as e:
			self.latest = {}
			self.error = e
			if self.debug:
				print(f"{self.name}: read failed: {e}")
		return self.latest


class Bme280(Sensor):
	"""Temperature, humidity and pressure from a Bosch BME280.

	Runs the chip in normal mode - measuring continuously, about once a second
	- so a read is a register fetch with nothing to wait for. The vendored
	driver's forced mode would poll with a blocking sleep instead.
	"""

	name = "BME280"

	def __init__(self, i2c, address=0x76, debug=False):
		"""
		Args:
			i2c: The machine.I2C bus the chip is on
			address: 0x76 with SDO to GND, 0x77 with SDO to 3V3
			debug: If True, prints failed reads

		Raises:
			OSError: If nothing answers at the address
		"""
		super().__init__(debug)
		self._chip = _continuous_bme280(i2c, address)

	async def read(self):
		temperature, pressure, humidity = self._chip.read_compensated_data()
		if not self._chip.fresh:
			# The first measurement has not finished since power-up.
			return {}
		return {
			'temperature': temperature,
			'humidity': humidity,
			'pressure': pressure / 100,	# Pa -> hPa
		}


class Tsl2591(Sensor):
	"""Light level from an ams TSL2591.

	The chip integrates continuously, so a read returns its last finished
	measurement without waiting.
	"""

	name = "TSL2591"

	# Saturation at the driver's default gain (25x) and 100ms integration.
	# Brighter light reports this instead of raising, so "saturated" reads as
	# "as bright as it measures" - a torch, or direct sun.
	MAX_LUX = 6000

	def __init__(self, i2c, debug=False):
		"""
		Args:
			i2c: The machine.I2C bus the chip is on
			debug: If True, prints failed reads

		Raises:
			OSError: If nothing answers at 0x29
			RuntimeError: If the chip at 0x29 is not a TSL2591
		"""
		super().__init__(debug)
		from tsl2591 import TSL2591
		self._chip = TSL2591(i2c)

	async def read(self):
		full, ir = self._chip.raw_luminosity
		try:
			lux = max(0.0, self._chip.lux)
		except RuntimeError:
			# The driver raises on overflow.
			lux = self.MAX_LUX
		return {'lux': lux, 'light_full': full, 'light_ir': ir}

	def disable(self):
		"""Power the chip down. It stays off until re-created."""
		self._chip.disable()


class Sgp40(Sensor):
	"""Air quality from a Sensirion SGP40, as a VOC index.

	The index is Sensirion's: 100 is the room's typical air, higher is worse,
	lower is cleaner. The algorithm learns that baseline from one sample a
	second - read() must be called at that rate, which is SensorSampler's
	default - and needs hours to settle. voc_index is None for its first 45
	samples, while it reports nothing meaningful.
	"""

	name = "SGP40"

	MEASURE_MS = 30	# The chip's measurement time, from the datasheet
	WARMUP_SAMPLES = 45	# The algorithm's initial blackout
	DEFAULT_HUMIDITY = 50
	DEFAULT_TEMPERATURE = 25

	def __init__(self, i2c, climate=None, debug=False):
		"""
		Args:
			i2c: The machine.I2C bus the chip is on
			climate: Optional Sensor whose latest readings supply humidity and
				temperature for compensation - a Bme280, typically. Without
				one, or before its first reading, the chip's defaults (50%,
				25C) are used.
			debug: If True, prints failed reads

		Raises:
			Exception: The driver's NotFoundException if nothing is at 0x59
		"""
		super().__init__(debug)
		from voc_algorithm import VOCAlgorithm
		self._chip = _async_sgp40(i2c)
		self.errors = Sensor.errors + (self._chip.CRCException,)
		self.climate = climate
		self._voc = VOCAlgorithm()
		self._voc.vocalgorithm_init()
		self._samples = 0

	async def read(self):
		humidity, temperature = self._compensation()
		self._chip.start_raw(humidity=humidity, temperature=temperature)
		await asyncio.sleep_ms(self.MEASURE_MS)
		raw = self._chip.finish_raw()

		index = self._voc.vocalgorithm_process(raw)
		self._samples += 1
		if self._samples <= self.WARMUP_SAMPLES:
			index = None
		return {'voc_index': index, 'voc_raw': raw}

	def _compensation(self):
		"""Humidity and temperature to compensate with."""
		latest = self.climate.latest if self.climate else {}
		return (
			latest.get('humidity', self.DEFAULT_HUMIDITY),
			latest.get('temperature', self.DEFAULT_TEMPERATURE),
		)


class SensorSampler:
	"""Owns a set of sensors and samples them all on an interval.

	Create one for the life of the program, so sensors that learn over time
	(the SGP40's VOC baseline) keep learning however the app changes around
	them.

	Keys must be unique across sensors. On a clash the later sensor in the
	list wins.
	"""

	def __init__(self, sensors, interval_ms=1000, debug=False):
		"""
		Args:
			sensors: The Sensor objects to sample, in order
			interval_ms: Time from one sample's start to the next. Keep it at
				1000 if an Sgp40 is included - its algorithm assumes that.
			debug: If True, prints every sample
		"""
		self.sensors = list(sensors)
		self.interval_ms = interval_ms
		self.debug = debug
		self.readings = {}
		self._sampled = asyncio.Event()

	async def sample(self):
		"""Read every sensor once, now.

		Returns:
			The merged readings. A sensor whose read failed is left out.
		"""
		readings = {}
		for sensor in self.sensors:
			readings.update(await sensor.update())
		self.readings = readings
		if self.debug:
			print(f"Sensors: {readings}")

		# A fresh Event per sample, so every waiter wakes once and none of them
		# has to clear it for the others.
		sampled, self._sampled = self._sampled, asyncio.Event()
		sampled.set()
		return readings

	async def next(self):
		"""Wait for the next sample.

		Returns:
			The merged readings from that sample
		"""
		await self._sampled.wait()
		return self.readings

	async def run(self):
		"""Sample forever. Start this with asyncio.create_task()."""
		while True:
			start = time.ticks_ms()
			await self.sample()
			# Hold the interval steady however long the reads took.
			elapsed = time.ticks_diff(time.ticks_ms(), start)
			await asyncio.sleep_ms(max(0, self.interval_ms - elapsed))


def _continuous_bme280(i2c, address):
	"""The vendored BME280 driver, switched to continuous measurement.

	Subclasses rather than edits the driver: only read_raw_data() changes, so
	the calibration and compensation maths are the driver's, untouched.
	"""
	from bme280 import BME280, BME280_OSAMPLE_1

	class ContinuousBME280(BME280):
		_CTRL_HUM = 0xF2
		_CTRL_MEAS = 0xF4
		_CONFIG = 0xF5
		_DATA = 0xF7
		_MODE_NORMAL = 3
		_STANDBY_1000MS = 0b101 << 5
		# The value each register holds until its first measurement completes.
		_TEMP_RESET = 0x80000

		def __init__(self, i2c, address):
			# 1x oversampling: Bosch's recommended setting for weather
			# monitoring, and the fastest measurement.
			super().__init__(mode=BME280_OSAMPLE_1, address=address, i2c=i2c)
			self.fresh = False
			# The driver leaves the chip asleep. Set the standby time while it
			# still is (config writes can be ignored in normal mode), then
			# humidity, then start measuring - ctrl_hum only takes effect on
			# the ctrl_meas write that follows it.
			self._write(self._CONFIG, self._STANDBY_1000MS)
			self._write(self._CTRL_HUM, self._mode_hum)
			self._write(
				self._CTRL_MEAS,
				self._mode_temp << 5 | self._mode_press << 2 | self._MODE_NORMAL,
			)

		def _write(self, register, value):
			self._l1_barray[0] = value
			self.i2c.writeto_mem(self.address, register, self._l1_barray)

		def read_raw_data(self, result):
			"""Fetch the latest finished measurement - no forcing, no waiting."""
			self.i2c.readfrom_mem_into(self.address, self._DATA, self._l8_barray)
			r = self._l8_barray
			result[0] = ((r[3] << 16) | (r[4] << 8) | r[5]) >> 4	# temperature
			result[1] = ((r[0] << 16) | (r[1] << 8) | r[2]) >> 4	# pressure
			result[2] = (r[6] << 8) | r[7]							# humidity
			self.fresh = result[0] != self._TEMP_RESET

	return ContinuousBME280(i2c, address)


def _async_sgp40(i2c):
	"""The vendored SGP40 driver, with its measurement split in two.

	measure_raw() sends the command, sleeps 30ms and reads. Splitting it lets
	the caller await the 30ms instead. The parameter encoding mirrors
	measure_raw(); the CRC is the driver's own.
	"""
	import struct
	from math import ceil
	from sgp40 import SGP40

	def private(obj, name):
		# CPython mangles SGP40's __crc to _SGP40__crc; MicroPython does not
		# implement name mangling, so on the device it is plain __crc.
		return getattr(obj, '_SGP40' + name, None) or getattr(obj, name)

	class AsyncSGP40(SGP40):
		def start_raw(self, humidity, temperature):
			"""Send the measure command, compensated for humidity (%) and
			temperature (C). Read the result with finish_raw() 30ms later."""
			crc = private(self, '__crc')
			paramh = struct.pack(">H", ceil(humidity * 0xffff / 100))
			paramt = struct.pack(">H", ceil((temperature + 45) * 0xffff / 175))
			data = (
				paramh + bytes([crc(paramh[0], paramh[1])])
				+ paramt + bytes([crc(paramt[0], paramt[1])])
			)
			self.i2c.writeto_mem(self.addr, self.MEASUREMENT_RAW, data, addrsize=16)

		def finish_raw(self):
			"""The raw VOC signal from the measurement start_raw() began."""
			raw = self.i2c.readfrom(self.addr, 3)
			private(self, '__check_crc')(raw)
			return struct.unpack(">H", raw[:2])[0]

	return AsyncSGP40(i2c)
