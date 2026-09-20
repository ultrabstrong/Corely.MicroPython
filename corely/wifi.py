"""WiFi connection, connect/disconnect actions, and connectivity monitoring."""

import asyncio
import network
import time

from corely.action import Action, TaskAction


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
		if not self.ssid or not self.password:
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

	def disconnect(self):
		"""Disconnect from WiFi."""
		self.wlan.disconnect()
		if self.debug:
			print("Disconnected from WiFi")

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
