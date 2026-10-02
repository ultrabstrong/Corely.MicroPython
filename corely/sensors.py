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

Staying up unattended:

- Each sensor rejects readings its chip should never produce (validate()),
  and some spot a reading that has stopped changing - both count as failed
  reads.
- After `reopen_after` failures in a row the sampler re-opens that sensor;
  when every sensor is failing it recovers the I2C bus first (recover_i2c,
  given to it by the app).
- Failures are logged through `logging` once per incident - when a streak
  starts and when it ends - never every second.
"""

import asyncio
import logging
import time

_log = logging.getLogger("corely.sensors")


class SensorError(Exception):
	"""A reading the chip should never produce. Counts as a failed read."""


class Sensor:
	"""Something read on demand, returning a dict of named readings.

	Subclasses implement open() and read(), and may implement validate().
	They let I/O errors propagate; update() catches them, so one loose wire
	empties one sensor's readings rather than stopping whoever is sampling.
	"""

	name = "sensor"
	errors = (OSError, RuntimeError, SensorError)	# What counts as a failed read
	stuck_after = None	# Identical reads in a row that mean "stopped updating"

	def __init__(self, debug=False):
		"""
		Args:
			debug: If True, prints failed reads as well as logging them
		"""
		self.debug = debug
		self.latest = {}
		self.error = None
		self.failures = 0				# Ever
		self.consecutive_failures = 0	# In the current streak
		self.reopens = 0
		self._last = None
		self._repeats = 0

	def open(self):
		"""Override: create the driver. Called once by the constructor, and
		again by reopen()."""

	async def read(self):
		"""Override: return a dict of named readings. May raise."""
		raise NotImplementedError("Subclasses must implement read()")

	def validate(self, readings):
		"""Override: raise SensorError for a reading the chip should never
		produce. The default accepts everything."""

	def reopen(self):
		"""Rebuild the driver - for a chip that browned out and lost its
		configuration, or a bus that was just recovered."""
		self.open()
		self.reopens += 1
		self._last = None
		self._repeats = 0

	async def update(self):
		"""Read into self.latest.

		A failed read empties latest - so a display shows nothing rather than a
		stale number - keeps the exception in self.error, and counts towards
		the sampler re-opening this sensor.

		Returns:
			The new readings, {} on failure
		"""
		try:
			readings = await self.read()
			if readings:
				self.validate(readings)
				self._check_stuck(readings)
		except self.errors as e:
			self.latest = {}
			self.error = e
			self.failures += 1
			self.consecutive_failures += 1
			reason = str(e) or type(e).__name__	# Some driver errors carry no message
			if self.consecutive_failures == 1:
				_log.warning("%s read failed: %s", self.name, reason)
			if self.debug:
				print(f"{self.name}: read failed: {reason}")
			return self.latest

		if self.consecutive_failures:
			_log.warning("%s recovered after %d failed reads", self.name, self.consecutive_failures)
		self.consecutive_failures = 0
		self.latest = readings
		self.error = None
		return readings

	def _check_stuck(self, readings):
		if self.stuck_after is None:
			return
		self._repeats = self._repeats + 1 if readings == self._last else 0
		self._last = readings
		if self._repeats >= self.stuck_after:
			raise SensorError(f"same reading {self._repeats + 1} times running")


class Bme280(Sensor):
	"""Temperature, humidity and pressure from a Bosch BME280.

	Runs the chip in normal mode - measuring continuously, about once a second
	- so a read is a register fetch with nothing to wait for. The vendored
	driver's forced mode would poll with a blocking sleep instead.

	A reading exactly on one of the driver's clamps (-40/85C, 0/100%,
	300/1100 hPa) is a failure, not weather: the maths went out of range.
	Real readings always jitter, so a minute of identical ones is a failure
	too.
	"""

	name = "BME280"
	stuck_after = 60

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
		self.i2c = i2c
		self.address = address
		self.open()

	def open(self):
		self._chip = _continuous_bme280(self.i2c, self.address)

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

	def validate(self, readings):
		clamped = (
			readings['temperature'] in (-40, 85)
			or readings['humidity'] in (0, 100)
			or readings['pressure'] in (300, 1100)
		)
		if clamped:
			raise SensorError(f"reading on a driver clamp: {readings}")


class Tsl2591(Sensor):
	"""Light level from an ams TSL2591.

	The chip integrates continuously, so a read returns its last finished
	measurement without waiting. No stuck check: a dark room reads 0 for
	hours, legitimately.
	"""

	name = "TSL2591"

	# Saturation at the driver's default gain (25x) and 100ms integration.
	# Brighter light reports this instead of raising, so "saturated" reads as
	# "as bright as it measures" - a torch, or direct sun.
	MAX_LUX = 6000

	ADDRESS = 0x29

	# Registers and commands, from Adafruit's Arduino TSL2591 library
	# (registerInterrupt / clearInterrupt), which implements the datasheet.
	_COMMAND = 0xA0
	_ENABLE = 0x00
	_THRESHOLDS = 0x04		# AILTL, AILTH, AIHTL, AIHTH: low then high, LE
	_NP_THRESHOLDS = 0x08	# The same four for the no-persist interrupt
	_PERSIST = 0x0C
	_STATUS = 0x13
	_ALS_INTERRUPT_FLAG = 0x10	# AINT in the status register
	# "No upper limit". Not 0xFFFF: on the board a 0xFFFF threshold tripped
	# the chip's interrupt flags with the reading nowhere near it, while
	# 60000 behaved. Readings top out at 36863 at 100ms integration anyway.
	_NO_LIMIT = 60000
	_CLEAR_INTERRUPT = 0xE7	# Special function: clear both ALS interrupts
	_POWER_ONLY = 0x01		# PON - powered, not measuring
	_POWER_AND_ALS = 0x03	# PON | AEN - measuring, interrupts off
	_ALS_INTERRUPT = 0x10	# AIEN - the persist-filtered interrupt only

	# Gain register value -> multiplier, and the lux maths' DF, for turning
	# a lux threshold into the raw counts the chip compares against.
	_GAINS = {0x00: 1, 0x10: 25, 0x20: 428, 0x30: 9876}
	_LUX_DF = 408.0

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
		self.i2c = i2c
		self._interrupt = None
		self.open()

	def open(self):
		from tsl2591 import TSL2591
		self._chip = TSL2591(self.i2c)
		# The driver switches on both ALS interrupts but sets no thresholds
		# for the no-persist one, which leaves INT held low forever. Start
		# with interrupts off; re-arm one a reopen would otherwise lose.
		self._write(self._ENABLE, self._POWER_AND_ALS)
		if self._interrupt:
			self.set_light_interrupt(*self._interrupt)

	def raw_full_spectrum(self):
		"""The full-spectrum count right now - what the thresholds compare."""
		return self._chip.raw_luminosity[0]

	# The alarm contract (see ThresholdAlarm in corely.alarms), in raw
	# full-spectrum counts - the units the chip itself compares.

	def alarm_value(self):
		"""The reading the alarm compares, now."""
		return self.raw_full_spectrum()

	def arm_alarm(self, below=None, above=None):
		"""Latch INT when the count leaves (below, above). Either may be None."""
		self.set_light_interrupt(below_counts=below, above_counts=above)

	def clear_alarm(self):
		"""Release the latch. It latches again if still out of range."""
		self.clear_interrupt()

	def disarm_alarm(self):
		self.disable_interrupt()

	def alarm_latched(self):
		"""True if the alarm has latched and not been cleared.

		Read from the chip's status register, not the INT pin: re-opening the
		sensor (as a reboot does) switches the interrupt output off and frees
		the pin, but the status bit stays set - checked on the board - so a
		program starting after a deep sleep can still tell the alarm fired.
		"""
		status = self.i2c.readfrom_mem(self.ADDRESS, self._COMMAND | self._STATUS, 1)[0]
		return bool(status & self._ALS_INTERRUPT_FLAG)

	def set_light_interrupt(self, below_lux=None, above_lux=None, persist=3,
							below_counts=None, above_counts=None):
		"""Pull INT low when the light leaves a range - a hardware wake source.

		The chip holds INT low until clear_interrupt(), so it is a level a
		pin interrupt can catch even mid-sleep.

		Thresholds are compared against the raw full-spectrum count, not
		lux, so they are converted with the lux maths' constants ignoring
		infrared. Approximate: "below 5 lux" trips near 5, not exactly - and
		under infrared-heavy light (a hand over the sensor lets a lot
		through) the count runs well above what the lux reading suggests.
		Pass below_counts / above_counts to set a threshold in the chip's own
		terms instead, e.g. relative to raw_full_spectrum().

		Args:
			below_lux: Fire when the light falls below this, or None
			above_lux: Fire when the light rises above this, or None
			persist: The chip's persistence filter - readings in a row outside
				the range before it fires. 3 (300ms at the default timing) lets
				a passing shadow through. The chip's codes: 1-3 are 1-3
				readings, then 4=5, 5=10, ... up to 15=60.
			below_counts: As below_lux, in raw counts; wins over below_lux
			above_counts: As above_lux, in raw counts; wins over above_lux
		"""
		low = 0
		if below_counts is not None:
			low = below_counts
		elif below_lux is not None:
			low = self.lux_to_counts(below_lux)
		high = self._NO_LIMIT
		if above_counts is not None:
			high = above_counts
		elif above_lux is not None:
			high = self.lux_to_counts(above_lux)
		low = max(0, min(self._NO_LIMIT, int(low)))
		high = max(0, min(self._NO_LIMIT, int(high)))
		self._interrupt = (below_lux, above_lux, persist, below_counts, above_counts)

		# Measuring stops while the thresholds change. On the board, changing
		# them mid-measurement left the chip comparing against the old range
		# for the next cycle - it fired straight after arming - so the
		# measurement restarts from scratch on the new one. The no-persist
		# interrupt stays disabled, but gets the same range so the chip's
		# status flags tell the truth.
		self._write(self._ENABLE, self._POWER_ONLY)
		limits = (low & 0xFF, low >> 8, high & 0xFF, high >> 8)
		for base in (self._THRESHOLDS, self._NP_THRESHOLDS):
			for offset, byte in enumerate(limits):
				self._write(base + offset, byte)
		self._write(self._PERSIST, persist)
		self.clear_interrupt()
		self._write(self._ENABLE, self._POWER_AND_ALS | self._ALS_INTERRUPT)

	def clear_interrupt(self):
		"""Release INT. If the light is still out of range it fires again."""
		self.i2c.writeto(self.ADDRESS, bytes([self._CLEAR_INTERRUPT]))

	def disable_interrupt(self):
		"""Stop the light interrupt, leaving INT high."""
		self._interrupt = None
		self._write(self._ENABLE, self._POWER_AND_ALS)
		self.clear_interrupt()

	def lux_to_counts(self, lux):
		"""Roughly the raw full-spectrum count this much light gives."""
		gain = self._GAINS.get(getattr(self._chip, "_gain", 0x10), 25)
		atime = 100 * (getattr(self._chip, "_integration", 0) + 1)
		counts_per_lux = atime * gain / self._LUX_DF
		return max(0, min(self._NO_LIMIT, int(lux * counts_per_lux)))

	def _write(self, register, value):
		self.i2c.writeto(self.ADDRESS, bytes([self._COMMAND | register, value]))

	async def read(self):
		full, ir = self._chip.raw_luminosity
		try:
			lux = max(0.0, self._chip.lux)
		except RuntimeError:
			# The driver raises on overflow.
			lux = self.MAX_LUX
		return {'lux': lux, 'light_full': full, 'light_ir': ir}

	def validate(self, readings):
		# The full-spectrum channel includes infrared, so it can never be less.
		if readings['light_ir'] > readings['light_full']:
			raise SensorError(f"infrared above full spectrum: {readings}")

	def disable(self):
		"""Power the chip down. It stays off until re-opened."""
		self._chip.disable()


class Sgp40(Sensor):
	"""Air quality from a Sensirion SGP40, as a VOC index.

	The index is Sensirion's: 100 is the room's typical air, higher is worse,
	lower is cleaner. The algorithm learns that baseline from one sample a
	second - read() must be called at that rate, which is SensorSampler's
	default - and needs hours to settle. voc_index is None for its first 45
	samples, while it reports nothing meaningful.

	get_state()/set_state() carry the learned baseline across a reboot; where
	it is kept is the app's choice.
	"""

	name = "SGP40"
	stuck_after = 60

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
		self.i2c = i2c
		self.climate = climate
		self.open()
		# The algorithm outlives reopen(): a re-opened chip keeps the baseline.
		self._voc = VOCAlgorithm()
		self._voc.vocalgorithm_init()
		self._samples = 0

	def open(self):
		self._chip = _async_sgp40(self.i2c)
		self.errors = Sensor.errors + (self._chip.CRCException,)

	async def read(self):
		humidity, temperature = self._compensation()
		self._chip.start_raw(humidity=humidity, temperature=temperature)
		await asyncio.sleep_ms(self.MEASURE_MS)
		raw = self._chip.finish_raw()
		# Validate before the algorithm sees it, so a bad raw value never
		# skews the learned baseline.
		if raw in (0, 0xFFFF):
			raise SensorError(f"raw signal {raw} is no measurement")

		index = self._voc.vocalgorithm_process(raw)
		self._samples += 1
		if self._samples <= self.WARMUP_SAMPLES:
			index = None
		return {'voc_index': index, 'voc_raw': raw}

	def get_state(self):
		"""The algorithm's learned baseline, as two ints, to save."""
		return self._voc._vocalgorithm_get_states(0, 0)

	def set_state(self, state):
		"""Restore a baseline from get_state().

		Only worth it after a short interruption - Sensirion's guidance is
		under ten minutes, or the room may have changed under it.
		"""
		# Mirrors Sensirion's VocAlgorithm_set_states. The vendored port's own
		# _vocalgorithm_set_states passes its params object as an extra
		# argument and raises TypeError, so it cannot be used.
		mean, std = state
		voc = self._voc
		voc._vocalgorithm__mean_variance_estimator__set_states(
			mean, std, voc._f16(self._PERSISTENCE_UPTIME_GAMMA))
		voc.params.msraw = mean

	# Sensirion's constant; the port's copy is a MicroPython const() with a
	# leading underscore, which is not importable on the device.
	_PERSISTENCE_UPTIME_GAMMA = 3 * 3600

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

	def __init__(self, sensors, interval_ms=1000, reopen_after=3,
				 recover_bus=None, debug=False):
		"""
		Args:
			sensors: The Sensor objects to sample, in order
			interval_ms: Time from one sample's start to the next. Keep it at
				1000 if an Sgp40 is included - its algorithm assumes that.
			reopen_after: Failed reads in a row before a sensor is re-opened,
				and samples with every sensor failing before the bus is
				recovered. Repeats at each multiple.
			recover_bus: Optional function that frees a stuck bus - typically
				recover_i2c() for the bus's pins, then re-creating the
				machine.I2C. Called when every sensor is failing.
			debug: If True, prints every sample
		"""
		self.sensors = list(sensors)
		self.interval_ms = interval_ms
		self.reopen_after = reopen_after
		self.recover_bus = recover_bus
		self.debug = debug
		self.readings = {}
		self.bus_recoveries = 0
		self._all_failing = 0
		self._sampled = asyncio.Event()

	async def sample(self):
		"""Read every sensor once, now, then deal with any that keep failing.

		Returns:
			The merged readings. A sensor whose read failed is left out.
		"""
		readings = {}
		for sensor in self.sensors:
			readings.update(await sensor.update())
		self.readings = readings
		if self.debug:
			print(f"Sensors: {readings}")
		self._recover()

		# A fresh Event per sample, so every waiter wakes once and none of them
		# has to clear it for the others.
		sampled, self._sampled = self._sampled, asyncio.Event()
		sampled.set()
		return readings

	def _recover(self):
		"""Re-open sensors on a failure streak; recover the bus if all are."""
		every = self.reopen_after
		all_failing = bool(self.sensors) and all(s.consecutive_failures for s in self.sensors)
		self._all_failing = self._all_failing + 1 if all_failing else 0

		if self.recover_bus and self._all_failing and self._all_failing % every == 0:
			_log.warning("Every sensor failing - recovering the I2C bus")
			try:
				self.recover_bus()
				self.bus_recoveries += 1
			except Exception as e:
				_log.warning("I2C bus recovery failed: %s", e)
			for sensor in self.sensors:
				self._reopen(sensor)
			return

		for sensor in self.sensors:
			if sensor.consecutive_failures and sensor.consecutive_failures % every == 0:
				self._reopen(sensor)

	def _reopen(self, sensor):
		try:
			sensor.reopen()
		except Exception as e:
			# Still gone - try again after the next streak of failures.
			if self.debug:
				print(f"{sensor.name}: reopen failed: {e}")
			return
		if sensor.reopens == 1 or self.debug:
			_log.warning("%s re-opened after %d failed reads", sensor.name, sensor.consecutive_failures)

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


def recover_i2c(scl_pin, sda_pin, half_period_us=5):
	"""Free an I2C bus a slave is holding stuck.

	If a transfer is cut off mid-byte (a glitch, a reset at the wrong moment),
	a slave can be left driving SDA low, waiting for clocks that never come -
	and every device on the bus fails. The I2C specification's remedy
	(UM10204, section 3.1.16): clock SCL by hand until SDA is released, up to
	nine pulses, then send a STOP.

	Afterwards the pins are plain GPIOs; re-create the machine.I2C to hand
	them back to the I2C peripheral. On the RP2 that re-initialises the same
	bus object everything else already holds.

	Args:
		scl_pin: The bus's SCL GPIO number
		sda_pin: The bus's SDA GPIO number
		half_period_us: Half a clock period; 5us is 100kHz

	Returns:
		The clock pulses it took to free SDA
	"""
	from machine import Pin

	sda = Pin(sda_pin, Pin.IN, Pin.PULL_UP)
	scl = Pin(scl_pin, Pin.OPEN_DRAIN)
	scl.value(1)
	pulses = 0
	while not sda.value() and pulses < 9:
		scl.value(0)
		time.sleep_us(half_period_us)
		scl.value(1)
		time.sleep_us(half_period_us)
		pulses += 1

	# STOP: SDA rises while SCL is high.
	sda = Pin(sda_pin, Pin.OPEN_DRAIN)
	sda.value(0)
	time.sleep_us(half_period_us)
	scl.value(1)
	time.sleep_us(half_period_us)
	sda.value(1)
	time.sleep_us(half_period_us)
	return pulses


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
