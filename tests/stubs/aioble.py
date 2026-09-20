"""Fake `aioble` - only enough to test Corely's own state wiring.

This deliberately does not simulate BLE. It exists so the peripheral and
central classes can be driven through their connect / disconnect / cancel
paths, including aioble's real quirk of returning None from advertise() when
advertising is stopped from outside.
"""

import asyncio


registered_services = []

# Set by tests: what the next advertise() call returns. None mimics aioble
# swallowing a CancelledError.
next_connection = None
advertise_calls = []


def reset():
	global next_connection
	registered_services.clear()
	advertise_calls.clear()
	next_connection = None


class Characteristic:
	def __init__(self, service, uuid, read=False, write=False, notify=False, capture=False):
		self.service = service
		self.uuid = uuid
		# Stored under can_* so the flags do not shadow the methods below.
		self.can_read = read
		self.can_write = write
		self.can_notify = notify
		self.capture = capture
		self.written_values = []
		self.local_value = None
		self.notified = False
		self._incoming = []
		self._event = asyncio.Event()

	# --- server side (what the peripheral calls) ---

	def write(self, data, send_update=False):
		self.local_value = data
		self.notified = send_update
		self.written_values.append(data)

	async def written(self):
		"""Wait for the next value a client wrote."""
		while not self._incoming:
			self._event.clear()
			await self._event.wait()
		return self._incoming.pop(0)

	# --- test helper ---

	def client_writes(self, connection, data):
		self._incoming.append((connection, data))
		self._event.set()


class Service:
	def __init__(self, uuid):
		self.uuid = uuid


class Connection:
	def __init__(self, device='fake-device'):
		self.device = device
		self._connected = True
		self._disconnected = asyncio.Event()
		self.entered = False
		self.exited = False

	def is_connected(self):
		return self._connected

	async def disconnected(self, timeout_ms=None):
		await self._disconnected.wait()

	def drop(self):
		"""Test helper: simulate the peer disconnecting."""
		self._connected = False
		self._disconnected.set()

	async def __aenter__(self):
		self.entered = True
		return self

	async def __aexit__(self, *args):
		self.exited = True
		self._connected = False


def register_services(*services):
	registered_services.extend(services)


async def advertise(interval_us, name=None, services=None, **kwargs):
	advertise_calls.append({'interval_us': interval_us, 'name': name, 'services': services})
	await asyncio.sleep(0)
	return next_connection


def stop():
	pass
