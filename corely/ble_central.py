"""BLE central (UART service) built on aioble.

Use this when:
- This device connects to another board or a BLE sensor
- This device initiates the connection rather than waiting to be connected to

When something else connects to this device instead - a phone, say - use
BleUartPeripheral from corely.ble_peripheral.

Requires the aioble package on the device.

Status: only partly verified on hardware. Scanning has been exercised on a real
board; connecting, service discovery, subscribing and notifications have not,
because that needs a second BLE device to talk to.
"""

import asyncio
import aioble

from corely.ble_uart import UART_SERVICE_UUID, UART_RX_UUID, UART_TX_UUID


class BleUartCentral:
	"""Scans for a named UART peripheral, connects, and exchanges data.

	Scanning and connected states each drive an Action, the same way
	WiFiMonitor drives them.
	"""

	def __init__(self, on_notify=None, scanning_action=None,
				 connected_action=None, debug=False):
		"""
		Args:
			on_notify: Plain function called with bytes pushed by the peripheral.
				It must not block - to do async work, use asyncio.create_task.
			scanning_action: Action active while scanning (optional)
			connected_action: Action active while connected (optional)
			debug: If True, prints debug messages
		"""
		self.on_notify = on_notify
		self.scanning_action = scanning_action
		self.connected_action = connected_action
		self.debug = debug

		self._connection = None
		self._rx = None  # Write to this to reach the peripheral
		self._tx = None  # Read/notifications come from this

	@property
	def is_connected(self):
		return self._connection is not None and self._connection.is_connected()

	async def find(self, name, timeout_ms=5000):
		"""Scan for a peripheral advertising the UART service under `name`.

		Returns:
			An aioble Device, or None if it was not seen before the timeout
		"""
		if self.scanning_action:
			self.scanning_action.on()
		if self.debug:
			print(f"BLE Central: Scanning for '{name}'...")

		try:
			# Active scan picks up the scan response, where a long name or the
			# 128-bit service UUID may have landed.
			async with aioble.scan(timeout_ms, interval_us=30000, window_us=30000, active=True) as scanner:
				async for result in scanner:
					if result.name() == name and UART_SERVICE_UUID in result.services():
						if self.debug:
							print(f"BLE Central: Found '{name}' at {result.device}")
						return result.device
		finally:
			if self.scanning_action:
				self.scanning_action.off()

		if self.debug:
			print(f"BLE Central: '{name}' not found")
		return None

	async def send(self, data, response=False):
		"""Write data to the connected peripheral.

		Args:
			data: Bytes to send. Silently ignored if nothing is connected.
			response: If True, wait for the peripheral to acknowledge the write
		"""
		if not self.is_connected or self._rx is None:
			if self.debug:
				print("BLE Central: send ignored, nothing connected")
			return
		await self._rx.write(data, response=response)
		if self.debug:
			print(f"BLE Central: Sent {len(data)} bytes")

	async def read(self, timeout_ms=1000):
		"""Read the peripheral's current value, or None if not connected."""
		if not self.is_connected or self._tx is None:
			return None
		return bytes(await self._tx.read(timeout_ms=timeout_ms))

	async def run(self, name, reconnect=True, retry_delay_ms=1000):
		"""Find `name`, stay connected to it, and pump notifications.

		Start this with asyncio.create_task(), or await it directly if it is
		the only thing the program does.

		Args:
			name: Device name to look for
			reconnect: If True, keep retrying after failures and disconnects
			retry_delay_ms: Pause before retrying
		"""
		while True:
			connected = await self._connect_once(name)

			if not reconnect:
				return connected
			await asyncio.sleep_ms(retry_delay_ms)

	async def _connect_once(self, name):
		"""One find/connect/serve cycle. Returns True if it got as far as connecting."""
		device = await self.find(name)
		if device is None:
			return False

		try:
			connection = await device.connect(timeout_ms=5000)
		except asyncio.TimeoutError:
			if self.debug:
				print("BLE Central: Timeout connecting")
			return False

		async with connection:
			self._connection = connection
			if self.connected_action:
				self.connected_action.on()
			if self.debug:
				print("BLE Central: Connected, discovering services...")

			try:
				if not await self._discover(connection):
					return True
				await self._tx.subscribe(notify=True)
				if self.debug:
					print("BLE Central: Subscribed, waiting for notifications")

				while connection.is_connected():
					data = await self._tx.notified()
					if self.debug:
						print(f"BLE Central: Notification ({len(data)} bytes)")
					if self.on_notify:
						self.on_notify(bytes(data))
			except asyncio.TimeoutError:
				if self.debug:
					print("BLE Central: Timeout talking to peripheral")
			finally:
				self._connection = None
				self._rx = None
				self._tx = None
				if self.connected_action:
					self.connected_action.off()
				if self.debug:
					print("BLE Central: Disconnected")

		return True

	async def _discover(self, connection):
		"""Resolve the UART characteristics. Returns False if the peer lacks them."""
		service = await connection.service(UART_SERVICE_UUID)
		if service is None:
			if self.debug:
				print("BLE Central: Peer has no UART service")
			return False

		self._rx = await service.characteristic(UART_RX_UUID)
		self._tx = await service.characteristic(UART_TX_UUID)

		if self._rx is None or self._tx is None:
			if self.debug:
				print("BLE Central: UART characteristics missing")
			return False
		return True
