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
import time

import aioble

from corely.ble_uart import UART_SERVICE_UUID, UART_RX_UUID, UART_TX_UUID

# Advertising interval in microseconds (250ms).
_ADV_INTERVAL_US = 250_000

# The ATT header takes 3 bytes of every packet; 23 is BLE's minimum MTU.
_ATT_HEADER = 3
_MIN_MTU = 23


class BleUartPeripheral:
	"""Advertises a UART service and exchanges data with whatever connects.

	Advertising and connected states each drive an Action, the same way
	WiFiMonitor drives them.

	Data arrives as writes, and one message can span several: a phone sends at
	most MTU-3 bytes a write (20 unless it negotiated more). on_line puts them
	back together into lines - ended by a newline, or by a pause, because
	terminal apps differ on whether they send one.
	"""

	def __init__(self, name, on_write=None, on_line=None, advertising_action=None,
				 connected_action=None, rx_size=128, line_pause_ms=150, debug=False):
		"""
		Args:
			name: Device name shown while advertising
			on_write: Plain function called with the bytes of each write. It
				must not block - to do async work, use asyncio.create_task.
			on_line: Plain function called with each complete line, as text
				without its line ending. Same rules as on_write.
			advertising_action: Action active while advertising (optional)
			connected_action: Action active while connected (optional)
			rx_size: The most bytes one write can carry. BLE's default is 20; a
				WiFi password alone can be 63.
			line_pause_ms: A pause this long ends a line that has no newline
			debug: If True, prints debug messages
		"""
		self.name = name
		self.on_write = on_write
		self.on_line = on_line
		self.advertising_action = advertising_action
		self.connected_action = connected_action
		self.line_pause_ms = line_pause_ms
		self.debug = debug

		self._service = aioble.Service(UART_SERVICE_UUID)
		# capture=True makes written() hand back the value along with the
		# connection, so fast successive writes are not lost.
		self._rx = aioble.BufferedCharacteristic(
			self._service, UART_RX_UUID, write=True, capture=True, max_len=rx_size)
		self._tx = aioble.Characteristic(self._service, UART_TX_UUID, read=True, notify=True)
		aioble.register_services(self._service)

		self._connection = None
		self._pending = b""
		self._last_write_ms = 0

	@property
	def is_connected(self):
		return self._connection is not None and self._connection.is_connected()

	def send(self, data):
		"""Publish data to the connected central and notify it.

		Split into packets the connection can carry, so a long reply arrives
		whole rather than cut off at 20 bytes.

		Args:
			data: Bytes (or text) to send. Silently ignored if nothing is
				connected.
		"""
		if not self.is_connected:
			if self.debug:
				print("BLE Peripheral: send ignored, nothing connected")
			return
		if isinstance(data, str):
			data = data.encode()
		size = (getattr(self._connection, "mtu", None) or _MIN_MTU) - _ATT_HEADER
		for start in range(0, len(data), size):
			self._tx.write(data[start:start + size], send_update=True)
		if self.debug:
			print(f"BLE Peripheral: Sent {len(data)} bytes")

	def disconnect(self):
		"""Drop the connected central, if any. Advertising resumes after."""
		connection = self._connection
		if connection is not None:
			asyncio.create_task(connection.disconnect())

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
				self._pending = b""
				tasks = [asyncio.create_task(self._receive_loop())]
				if self.on_line:
					tasks.append(asyncio.create_task(self._pause_loop()))
				try:
					await connection.disconnected(timeout_ms=None)
				finally:
					for task in tasks:
						task.cancel()
					self._connection = None
					self._pending = b""
					if self.connected_action:
						self.connected_action.off()
					if self.debug:
						print("BLE Peripheral: Disconnected")

	async def _receive_loop(self):
		while True:
			_, data = await self._rx.written()
			if self.debug:
				print(f"BLE Peripheral: Received {len(data)} bytes")
			data = bytes(data)
			if self.on_write:
				self.on_write(data)
			if self.on_line:
				self._take(data)

	def _take(self, data):
		"""Add a write to the line being assembled; hand on any complete lines."""
		self._pending += data
		self._last_write_ms = time.ticks_ms()
		while True:
			ends = [i for i in (self._pending.find(b"\n"), self._pending.find(b"\r")) if i >= 0]
			if not ends:
				return
			end = min(ends)
			line, self._pending = self._pending[:end], self._pending[end + 1:]
			if line:
				self._emit(line)

	def _emit(self, line):
		self.on_line(line.decode("utf-8", "ignore"))

	async def _pause_loop(self):
		"""End a line with no newline once the writes pause."""
		while True:
			await asyncio.sleep_ms(self.line_pause_ms // 3 or 1)
			if self._pending and time.ticks_diff(time.ticks_ms(), self._last_write_ms) >= self.line_pause_ms:
				line, self._pending = self._pending, b""
				self._emit(line)
