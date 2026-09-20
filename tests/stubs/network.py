"""Fake `network` module so lib code can be imported on a PC."""

STA_IF = 'STA_IF'

# The most recently constructed WLAN, so tests can drive it.
last_wlan = None


class WLAN:
	def __init__(self, interface):
		global last_wlan
		self.interface = interface
		self._active = False
		self._connected = False
		self.connect_calls = []
		self.disconnect_calls = 0
		# When True, connect() never reaches the connected state (tests timeouts).
		self.fail_to_connect = False
		last_wlan = self

	def active(self, value=None):
		if value is None:
			return self._active
		self._active = value
		return None

	def connect(self, ssid, password):
		self.connect_calls.append((ssid, password))
		if not self.fail_to_connect:
			self._connected = True

	def disconnect(self):
		self.disconnect_calls += 1
		self._connected = False

	def isconnected(self):
		return self._connected

	def ifconfig(self):
		return ('192.168.1.50', '255.255.255.0', '192.168.1.1', '192.168.1.1')
