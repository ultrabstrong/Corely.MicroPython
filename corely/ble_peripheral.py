"""BLE peripheral (UART service) built on aioble.

Use this when:
- A phone/tablet connects to this device
- This device is the "server" hosting data/commands
- You want to advertise and wait for connections

When this device initiates instead - to another board or a sensor - use
BleUartCentral from corely.ble_central.

Requires the aioble package on the device.
"""

import asyncio
import aioble

from corely.ble_uart import UART_SERVICE_UUID, UART_RX_UUID, UART_TX_UUID

# Advertising interval in microseconds (250ms).
_ADV_INTERVAL_US = 250_000


class BleUartPeripheral:
	"""Advertises a UART service and exchanges data with whatever connects.

	Advertising and connected states each drive an Action, the same way
	WiFiMonitor drives them.
	"""

	def __init__(self, name, on_write=None, advertising_action=None,
				 connected_action=None, debug=False):
		"""
		Args:
			name: Device name shown while advertising
			on_write: Plain function called with the bytes the central sent.
				It must not block - to do async work, use asyncio.create_task.
			advertising_action: Action active while advertising (optional)
			connected_action: Action active while connected (optional)
			debug: If True, prints debug messages
		"""
		self.name = name
		self.on_write = on_write
		self.advertising_action = advertising_action
		self.connected_action = connected_action
		self.debug = debug

		self._service = aioble.Service(UART_SERVICE_UUID)
		# capture=True makes written() hand back the value along with the
		# connection, so fast successive writes are not lost.
		self._rx = aioble.Characteristic(self._service, UART_RX_UUID, write=True, capture=True)
		self._tx = aioble.Characteristic(self._service, UART_TX_UUID, read=True, notify=True)
		aioble.register_services(self._service)

		self._connection = None

	@property
	def is_connected(self):
		return self._connection is not None and self._connection.is_connected()

	def send(self, data):
		"""Publish data to the connected central and notify it.

		Args:
			data: Bytes to send. Silently ignored if nothing is connected.
		"""
		if not self.is_connected:
			if self.debug:
				print("BLE Peripheral: send ignored, nothing connected")
			return
		self._tx.write(data, send_update=True)
		if self.debug:
			print(f"BLE Peripheral: Sent {len(data)} bytes")

	async def run(self):
		"""Advertise, serve one connection at a time, forever.

		Start this with asyncio.create_task(), or await it directly if it is
		the only thing the program does.
		"""
		while True:
			if self.advertising_action:
				self.advertising_action.on()
			if self.debug:
				print(f"BLE Peripheral: Advertising as '{self.name}'")

			connection = await aioble.advertise(
				_ADV_INTERVAL_US,
				name=self.name,
				services=[UART_SERVICE_UUID],
			)

			if connection is None:
				# aioble swallows CancelledError and returns None when
				# advertising is stopped from outside, so this is how a
				# cancelled run() arrives. Stand down rather than blowing up.
				if self.advertising_action:
					self.advertising_action.off()
				if self.debug:
					print("BLE Peripheral: Advertising stopped")
				return

			async with connection:
				self._connection = connection
				if self.advertising_action:
					self.advertising_action.off()
				if self.connected_action:
					self.connected_action.on()
				if self.debug:
					print("BLE Peripheral: Connected to", connection.device)

				# Receiving runs in its own task so a disconnect can cancel it;
				# written() would otherwise wait forever for a write that can
				# no longer arrive.
				receive_task = asyncio.create_task(self._receive_loop())
				try:
					await connection.disconnected(timeout_ms=None)
				finally:
					receive_task.cancel()
					self._connection = None
					if self.connected_action:
						self.connected_action.off()
					if self.debug:
						print("BLE Peripheral: Disconnected")

	async def _receive_loop(self):
		while True:
			_, data = await self._rx.written()
			if self.debug:
				print(f"BLE Peripheral: Received {len(data)} bytes")
			if self.on_write:
				self.on_write(bytes(data))
