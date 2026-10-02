"""Fake `sgp40` - agners' driver's names and private CRC helpers.

Corely's subclass calls the driver's name-mangled __crc and __check_crc, so
they are reproduced here with the real CRC-8 (polynomial 0x31, init 0xFF).
"""


def crc8(msb, lsb):
	"""Sensirion's CRC-8, as used for every 16-bit word on the bus."""
	crc = 0xFF
	for byte in (msb, lsb):
		crc ^= byte
		for _ in range(8):
			crc = ((crc << 1) ^ 0x31) if crc & 0x80 else (crc << 1)
			crc &= 0xFF
	return crc


class SGP40:

	class NotFoundException(Exception):
		pass

	class CRCException(Exception):
		pass

	MEASUREMENT_RAW = 0x260f

	def __init__(self, i2c, addr=0x59):
		self.i2c = i2c
		self.addr = addr

	def measure_raw(self, humidity=50, temperature=25):
		raise AssertionError("Corely must not use the blocking measure_raw()")

	def __check_crc(self, arr):
		if self.__crc(arr[0], arr[1]) != arr[2]:
			raise self.CRCException

	def __crc(self, msb, lsb):
		return crc8(msb, lsb)
