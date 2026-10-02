"""Fake `bme280` - the parts of robert-hh's driver Corely's subclass relies on.

Mirrors the real driver's structure: read_compensated_data() calls
read_raw_data() and converts what it gets, so overriding read_raw_data()
changes what comes out. The conversion here is a simple linear one, not
Bosch's compensation - the tests check the plumbing, not the maths.
"""

BME280_OSAMPLE_1 = 1
BME280_I2CADDR = 0x76


class BME280:
	def __init__(self, mode=BME280_OSAMPLE_1, address=BME280_I2CADDR, i2c=None, **kwargs):
		self._mode_hum = self._mode_temp = self._mode_press = mode
		self.address = address
		self.i2c = i2c
		self._l1_barray = bytearray(1)
		self._l8_barray = bytearray(8)
		self._l3_resultarray = [0, 0, 0]
		# The real driver leaves the chip in sleep mode.
		self._l1_barray[0] = self._mode_temp << 5 | self._mode_press << 2
		self.i2c.writeto_mem(self.address, 0xF4, self._l1_barray)

	def read_raw_data(self, result):
		raise AssertionError("Corely must override read_raw_data()")

	def read_compensated_data(self, result=None):
		self.read_raw_data(self._l3_resultarray)
		raw_temp, raw_press, raw_hum = self._l3_resultarray
		# temperature C, pressure Pa, humidity %
		return (raw_temp / 10000, raw_press / 10, raw_hum / 1000)
