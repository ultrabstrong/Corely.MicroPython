"""Fake `tsl2591` - readings the tests set directly, plus overflow and failure."""


class TSL2591:
	def __init__(self, i2c, address=0x29):
		self.i2c = i2c
		self.enabled = True
		self.raw = (588, 133)
		self.lux_value = 60.3
		self.overflow = False
		self.fail = False

	@property
	def raw_luminosity(self):
		if self.fail:
			raise OSError("I2C read failed")
		return self.raw

	@property
	def lux(self):
		if self.fail:
			raise OSError("I2C read failed")
		if self.overflow:
			raise RuntimeError('Overflow reading light channels!')
		return self.lux_value

	def disable(self):
		self.enabled = False
