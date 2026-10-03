"""WiFi connection, connect/disconnect actions, connectivity monitoring, and
setting the clock over it.

	WiFiConnection     one network, joined without blocking the event loop
	WiFiStayConnected  an Action: joined and rejoined for as long as it is on
	WiFiMonitor        switches Actions as connectivity changes
	sync_clock()       sets the clock to UTC over NTP
"""

import asyncio
import logging
import network
import time

from corely.action import Action, TaskAction

log = logging.getLogger("corely.wifi")


class WiFiConnection:
	"""Manages a WiFi connection without blocking the event loop.

	Credentials are handed in by the caller. Where they came from - a JSON
	file, hard-coded constants, a provisioning flow - is the application's
	business, not this class's.
	"""

	def __init__(self, ssid, password, debug=False):
		"""
		Args:
			ssid: Network name to join
			password: Network password
			debug: If True, prints debug messages
		"""
		self.ssid = ssid
		self.password = password
		self.debug = debug
		self.wlan = network.WLAN(network.STA_IF)
		self.connecting = False

	async def connect(self, timeout_ms=10000):
		"""Connect to WiFi, waiting up to timeout_ms.

		Returns:
			True if connected, False on timeout or missing credentials
		"""
		if not self.has_credentials:
			print("WiFi credentials not loaded")
			return False

		self.wlan.active(True)

		if self.wlan.isconnected():
			if self.debug:
				print(f"Already connected! IP: {self.ip()}")
			return True

		if self.debug:
			print(f"Connecting to {self.ssid}...")

		self.connecting = True
		try:
			self.wlan.connect(self.ssid, self.password)
			start = time.ticks_ms()
			while not self.wlan.isconnected():
				if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
					print("Failed to connect to WiFi (timeout)")
					return False
				await asyncio.sleep_ms(200)
			if self.debug:
				print(f"Connected! IP: {self.ip()}")
			return True
		finally:
			self.connecting = False

	def disconnect(self, radio_off=False):
		"""Disconnect from WiFi.

		Args:
			radio_off: Also switch the radio off. Light sleep returns at once
				while the radio is on, so anything about to sleep wants this.
		"""
		self.wlan.disconnect()
		if radio_off:
			self.wlan.active(False)
		if self.debug:
			print("Disconnected from WiFi")

	@property
	def has_credentials(self):
		return bool(self.ssid and self.password)

	def set_credentials(self, ssid, password):
		"""Switch to another network. Drops the current link, so whatever keeps
		it connected joins the new one.

		Args:
			ssid: Network name to join
			password: Network password
		"""
		self.ssid = ssid
		self.password = password
		if self.wlan.active():
			self.wlan.disconnect()

	def is_connecting(self):
		return self.connecting

	def is_connected(self):
		return self.wlan.active() and self.wlan.isconnected()

	def ip(self):
		"""Current IP address, or None if not connected."""
		if self.is_connected():
			return self.wlan.ifconfig()[0]
		return None


class WiFiConnectAction(TaskAction):
	"""Connects to WiFi while active."""

	def __init__(self, wifi_connection, timeout_ms=10000, debug=False):
		"""
		Args:
			wifi_connection: WiFiConnection instance to manage
			timeout_ms: How long to wait for the connection
			debug: If True, prints debug messages
		"""
		super().__init__()
		self.wifi = wifi_connection
		self.timeout_ms = timeout_ms
		self.debug = debug

	async def run(self):
		if self.debug:
			print("WiFiConnectAction: Starting connection...")
		await self.wifi.connect(timeout_ms=self.timeout_ms)


class WiFiDisconnectAction(Action):
	"""Disconnects from WiFi when activated."""

	def __init__(self, wifi_connection, debug=False):
		"""
		Args:
			wifi_connection: WiFiConnection instance to manage
			debug: If True, prints debug messages
		"""
		self.wifi = wifi_connection
		self.debug = debug

	def on(self):
		if self.debug:
			print("WiFiDisconnectAction: Disconnecting...")
		self.wifi.disconnect()

	def off(self):
		"""No cleanup needed - the next action handles the state change."""
		pass


class WiFiStayConnected(TaskAction):
	"""Keeps the board on WiFi for as long as it is on.

	Joins, and rejoins whenever the link drops, waiting longer after each
	failure (retry_ms, doubling up to max_retry_ms) so a missing network does
	not keep the radio busy. With no credentials it waits for some - a
	provisioning flow can hand them over with set_credentials() at any time.

	Off disconnects and switches the radio off: light sleep returns at once
	while the radio is on, so a sleep turns this off first.

	Logs once per incident - joined, lost, cannot reach - never per retry.
	"""

	def __init__(self, wifi_connection, on_connect=None, timeout_ms=15000,
				 retry_ms=5000, max_retry_ms=300000, poll_ms=2000):
		"""
		Args:
			wifi_connection: WiFiConnection to keep connected
			on_connect: Called with no arguments each time it joins - to set
				the clock, say. Must not block for long.
			timeout_ms: How long one attempt to join may take
			retry_ms: Wait after the first failure; doubles after each
			max_retry_ms: The longest wait between attempts
			poll_ms: How often to check that a joined link is still up
		"""
		super().__init__()
		self.wifi = wifi_connection
		self.on_connect = on_connect
		self.timeout_ms = timeout_ms
		self.retry_ms = retry_ms
		self.max_retry_ms = max_retry_ms
		self.poll_ms = poll_ms
		self.failures = 0

	async def run(self):
		joined = False
		while True:
			if self.wifi.is_connected():
				if not joined:
					joined = True
					if self.failures:
						log.info("WiFi joined %s after %d failed tries", self.wifi.ssid, self.failures)
					else:
						log.info("WiFi joined %s", self.wifi.ssid)
					self.failures = 0
					if self.on_connect:
						self.on_connect()
				await asyncio.sleep_ms(self.poll_ms)
				continue

			if joined:
				joined = False
				log.warning("WiFi lost %s", self.wifi.ssid)

			if not self.wifi.has_credentials:
				await asyncio.sleep_ms(self.poll_ms)
				continue

			if await self.wifi.connect(timeout_ms=self.timeout_ms):
				continue
			self.failures += 1
			if self.failures == 1:
				log.warning("WiFi cannot reach %s, retrying", self.wifi.ssid)
			await self._wait(self.backoff_ms())

	async def _wait(self, ms):
		"""Wait before retrying - cut short by new credentials, which deserve
		a try straight away rather than after a long backoff."""
		credentials = (self.wifi.ssid, self.wifi.password)
		start = time.ticks_ms()
		while time.ticks_diff(time.ticks_ms(), start) < ms:
			await asyncio.sleep_ms(min(self.poll_ms, ms))
			if (self.wifi.ssid, self.wifi.password) != credentials:
				self.failures = 0
				return

	def backoff_ms(self):
		"""The wait before the next attempt, given the failures so far."""
		return min(self.retry_ms << min(self.failures - 1, 16), self.max_retry_ms)

	def cleanup(self):
		self.failures = 0
		self.wifi.connecting = False
		try:
			self.wifi.disconnect(radio_off=True)
		except OSError:
			pass


class WiFiMonitor:
	"""Watches WiFi/internet connectivity and switches Actions on state change.

	The internet check is a non-blocking socket open, so a slow or dead link
	no longer stalls buttons or LEDs the way a blocking socket did.
	"""

	STATE_DISCONNECTED = 'disconnected'
	STATE_CONNECTING = 'connecting'
	STATE_CONNECTED = 'connected'		# WiFi + internet
	STATE_NO_INTERNET = 'no_internet'	# WiFi but no internet

	def __init__(self, wifi_connection,
				 connected_action=None,
				 disconnected_action=None,
				 connecting_action=None,
				 no_internet_action=None,
				 check_interval_ms=5000,
				 timeout_ms=2000,
				 poll_ms=250,
				 test_host='8.8.8.8',
				 test_port=53,
				 debug=False):
		"""
		Args:
			wifi_connection: WiFiConnection instance to watch
			connected_action: Action for connected-with-internet
			disconnected_action: Action for disconnected
			connecting_action: Action for connecting (defaults to no_internet_action)
			no_internet_action: Action for connected-without-internet
			check_interval_ms: Time between internet checks (default 5000ms)
			timeout_ms: Timeout for the internet check (default 2000ms)
			poll_ms: How often to re-check the cheap link state (default 250ms)
			test_host/test_port: Endpoint used to prove internet access
			debug: If True, prints state transitions
		"""
		self.wifi = wifi_connection
		self.connected_action = connected_action
		self.disconnected_action = disconnected_action
		# Connecting and no-internet are both "ephemeral" states, so they share
		# an action unless told otherwise.
		self.connecting_action = connecting_action if connecting_action else no_internet_action
		self.no_internet_action = no_internet_action
		self.check_interval_ms = check_interval_ms
		self.timeout_ms = timeout_ms
		self.poll_ms = poll_ms
		self.test_host = test_host
		self.test_port = test_port
		self.debug = debug
		self.current_state = None

	async def run(self):
		"""Run forever. Start this with asyncio.create_task()."""
		last_check = None

		while True:
			if self.wifi.is_connecting():
				self._transition_to(self.STATE_CONNECTING)
				last_check = None
			elif not self.wifi.is_connected():
				self._transition_to(self.STATE_DISCONNECTED)
				last_check = None
			else:
				now = time.ticks_ms()
				due = last_check is None or time.ticks_diff(now, last_check) >= self.check_interval_ms
				if due:
					online = await self._has_internet()
					self._transition_to(self.STATE_CONNECTED if online else self.STATE_NO_INTERNET)
					last_check = time.ticks_ms()

			await asyncio.sleep_ms(self.poll_ms)

	def get_current_state(self):
		return self.current_state

	def _action_for_state(self, state):
		if state == self.STATE_CONNECTED:
			return self.connected_action
		elif state == self.STATE_DISCONNECTED:
			return self.disconnected_action
		elif state == self.STATE_CONNECTING:
			return self.connecting_action
		elif state == self.STATE_NO_INTERNET:
			return self.no_internet_action
		return None

	def _transition_to(self, new_state):
		if new_state == self.current_state:
			return

		old_action = self._action_for_state(self.current_state)
		new_action = self._action_for_state(new_state)

		if self.debug:
			print(f"WiFi State: {self.current_state} -> {new_state}")
		self.current_state = new_state

		# Order matters when two states share a pin: off first, then on.
		if old_action and old_action is not new_action:
			old_action.off()
		if new_action:
			new_action.on()

	async def _has_internet(self):
		"""Prove internet access by opening a socket, without blocking the loop."""
		writer = None
		try:
			_, writer = await asyncio.wait_for_ms(
				asyncio.open_connection(self.test_host, self.test_port),
				self.timeout_ms,
			)
			return True
		except Exception:
			return False
		finally:
			if writer is not None:
				try:
					writer.close()
					await writer.wait_closed()
				except Exception:
					pass


_clock_set = False


def sync_clock(host=None):
	"""Set the board's clock to UTC over NTP. Needs a working connection.

	Uses the built-in ntptime, which blocks for one round trip - about 110ms on
	a home network, up to ntptime's 1s timeout when the server does not answer.
	Call it when joining and every few hours, not in a tight loop.

	Args:
		host: NTP server; ntptime's default pool if None

	Returns:
		True if the clock was set
	"""
	global _clock_set
	import ntptime
	if host:
		ntptime.host = host
	try:
		ntptime.settime()
	except (OSError, OverflowError) as e:
		log.warning("Clock sync failed: %s", e)
		return False
	_clock_set = True
	return True


def clock_is_set():
	"""True once sync_clock() has succeeded this boot - until then the board's
	time of day is meaningless."""
	return _clock_set
