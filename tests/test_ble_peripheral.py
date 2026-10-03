"""BLE peripheral state wiring, against a fake aioble.

This does not test BLE - it tests what Corely does around it: which action is
on in which state, that writes reach the callback, and that a stopped advertise
does not crash. The radio itself only means anything on hardware.
"""

import asyncio
import unittest

import harness  # noqa: F401

import aioble  # the stub
from corely.action import Action
from corely.ble_peripheral import BleUartPeripheral


class FlagAction(Action):
	def __init__(self):
		self.is_on = False

	def on(self):
		self.is_on = True

	def off(self):
		self.is_on = False


class BleUartPeripheralTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		aioble.reset()
		self.advertising = FlagAction()
		self.connected = FlagAction()
		self.received = []
		self.peripheral = BleUartPeripheral(
			name='PicoTest',
			on_write=self.received.append,
			advertising_action=self.advertising,
			connected_action=self.connected,
		)

	async def test_registers_one_service(self):
		self.assertEqual(len(aioble.registered_services), 1)

	async def test_advertises_with_name_and_service(self):
		aioble.next_connection = aioble.Connection()
		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)
		task.cancel()

		self.assertEqual(aioble.advertise_calls[0]['name'], 'PicoTest')
		self.assertEqual(len(aioble.advertise_calls[0]['services']), 1)

	async def test_stopped_advertising_is_not_an_error(self):
		"""aioble returns None from advertise() when advertising is stopped."""
		aioble.next_connection = None

		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		self.assertTrue(task.done())
		self.assertIsNone(task.exception())
		self.assertFalse(self.advertising.is_on)

	async def test_connection_switches_actions(self):
		connection = aioble.Connection()
		aioble.next_connection = connection

		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		self.assertFalse(self.advertising.is_on)
		self.assertTrue(self.connected.is_on)
		self.assertTrue(self.peripheral.is_connected)

		task.cancel()

	async def test_disconnect_turns_connected_action_off(self):
		connection = aioble.Connection()
		aioble.next_connection = connection

		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		# Next advertise returns None, so run() stands down after the drop.
		aioble.next_connection = None
		connection.drop()
		await asyncio.sleep_ms(50)

		self.assertFalse(self.connected.is_on)
		self.assertFalse(self.peripheral.is_connected)
		task.cancel()

	async def test_write_reaches_the_callback(self):
		connection = aioble.Connection()
		aioble.next_connection = connection

		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		self.peripheral._rx.client_writes(connection, b'hello')
		await asyncio.sleep_ms(50)

		self.assertEqual(self.received, [b'hello'])
		task.cancel()

	async def test_send_notifies_when_connected(self):
		connection = aioble.Connection()
		aioble.next_connection = connection

		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		self.peripheral.send(b'pong')

		self.assertEqual(self.peripheral._tx.local_value, b'pong')
		self.assertTrue(self.peripheral._tx.notified)
		task.cancel()

	async def test_send_is_ignored_when_not_connected(self):
		self.peripheral.send(b'nobody there')

		self.assertIsNone(self.peripheral._tx.local_value)

	async def test_writes_can_carry_a_wifi_password(self):
		self.assertEqual(self.peripheral._rx.max_len, 128)

	async def test_a_long_reply_is_split_to_fit_the_mtu(self):
		connection = aioble.Connection()
		aioble.next_connection = connection
		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		self.peripheral.send("x" * 45)		# Default MTU: 20 bytes a packet
		connection.mtu = 103
		self.peripheral.send("y" * 150)		# Negotiated: 100 a packet

		self.assertEqual([len(v) for v in self.peripheral._tx.written_values], [20, 20, 5, 100, 50])
		task.cancel()

	async def test_disconnect_drops_the_central(self):
		connection = aioble.Connection()
		aioble.next_connection = connection
		task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(50)

		aioble.next_connection = None
		self.peripheral.disconnect()
		await asyncio.sleep_ms(50)

		self.assertEqual(connection.disconnect_calls, 1)
		self.assertFalse(self.peripheral.is_connected)
		task.cancel()


class LineTests(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		aioble.reset()
		self.lines = []
		self.peripheral = BleUartPeripheral(name='PicoTest', on_line=self.lines.append, line_pause_ms=60)
		self.connection = aioble.Connection()
		aioble.next_connection = self.connection
		self.task = asyncio.create_task(self.peripheral.run())
		await asyncio.sleep_ms(30)

	async def asyncTearDown(self):
		self.task.cancel()

	async def write(self, data):
		self.peripheral._rx.client_writes(self.connection, data)
		await asyncio.sleep_ms(20)

	async def test_a_line_split_across_writes_arrives_whole(self):
		await self.write(b'pass correct-hor')
		await self.write(b'se-battery\r\n')

		self.assertEqual(self.lines, ['pass correct-horse-battery'])

	async def test_several_lines_in_one_write(self):
		await self.write(b'ssid home\npass secret\n')

		self.assertEqual(self.lines, ['ssid home', 'pass secret'])

	async def test_a_pause_ends_a_line_with_no_newline(self):
		await self.write(b'help')
		self.assertEqual(self.lines, [])

		await asyncio.sleep_ms(150)

		self.assertEqual(self.lines, ['help'])


if __name__ == '__main__':
	unittest.main()
