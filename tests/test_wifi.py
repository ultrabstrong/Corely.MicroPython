"""WiFi connection handling and the connectivity state machine."""

import asyncio
import unittest
from unittest import mock

import harness  # noqa: F401

from corely.action import Action
from corely.wifi import (
	WiFiConnection,
	WiFiConnectAction,
	WiFiDisconnectAction,
	WiFiMonitor,
)


class FlagAction(Action):
	def __init__(self):
		self.is_on = False
		self.on_calls = 0

	def on(self):
		self.is_on = True
		self.on_calls += 1

	def off(self):
		self.is_on = False


class FakeWiFi:
	"""Stands in for WiFiConnection so the monitor can be driven directly."""

	def __init__(self):
		self.connecting = False
		self.connected = False

	def is_connecting(self):
		return self.connecting

	def is_connected(self):
		return self.connected


class FakeWriter:
	def __init__(self):
		self.closed = False

	def close(self):
		self.closed = True

	async def wait_closed(self):
		pass


class WiFiConnectionTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.wifi = WiFiConnection('net', 'secret')

	async def test_connect_succeeds(self):
		result = await self.wifi.connect(timeout_ms=200)

		self.assertTrue(result)
		self.assertTrue(self.wifi.is_connected())
		self.assertEqual(self.wifi.wlan.connect_calls, [('net', 'secret')])

	async def test_connect_reports_ip(self):
		await self.wifi.connect(timeout_ms=200)

		self.assertEqual(self.wifi.ip(), '192.168.1.50')

	async def test_connect_times_out(self):
		self.wifi.wlan.fail_to_connect = True

		result = await self.wifi.connect(timeout_ms=50)

		self.assertFalse(result)
		self.assertFalse(self.wifi.is_connecting())

	async def test_connecting_flag_is_set_while_connecting(self):
		self.wifi.wlan.fail_to_connect = True
		task = asyncio.create_task(self.wifi.connect(timeout_ms=200))

		await asyncio.sleep_ms(20)
		self.assertTrue(self.wifi.is_connecting())

		task.cancel()

	async def test_connect_does_not_block_other_tasks(self):
		self.wifi.wlan.fail_to_connect = True
		ticks = []

		async def other_work():
			while True:
				ticks.append(1)
				await asyncio.sleep_ms(5)

		worker = asyncio.create_task(other_work())
		await self.wifi.connect(timeout_ms=200)
		worker.cancel()

		# A blocking connect would have pinned this at 1. The window is wide
		# because PC timer granularity is far coarser than the device's.
		self.assertGreater(len(ticks), 3)

	async def test_disconnect(self):
		await self.wifi.connect(timeout_ms=200)

		self.wifi.disconnect()

		self.assertFalse(self.wifi.is_connected())
		self.assertEqual(self.wifi.wlan.disconnect_calls, 1)


class WiFiMonitorTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.wifi = FakeWiFi()
		self.connected = FlagAction()
		self.disconnected = FlagAction()
		self.no_internet = FlagAction()
		self.monitor = WiFiMonitor(
			self.wifi,
			connected_action=self.connected,
			disconnected_action=self.disconnected,
			no_internet_action=self.no_internet,
			check_interval_ms=20,
			timeout_ms=50,
			poll_ms=5,
		)

	def online(self):
		async def open_connection(host, port):
			return (None, FakeWriter())
		return mock.patch('asyncio.open_connection', open_connection)

	def offline(self):
		async def open_connection(host, port):
			raise OSError('unreachable')
		return mock.patch('asyncio.open_connection', open_connection)

	def hanging(self):
		async def open_connection(host, port):
			await asyncio.sleep(10)
		return mock.patch('asyncio.open_connection', open_connection)

	async def run_monitor(self, ms=60):
		task = asyncio.create_task(self.monitor.run())
		await asyncio.sleep_ms(ms)
		task.cancel()

	async def test_disconnected_state(self):
		await self.run_monitor()

		self.assertEqual(self.monitor.get_current_state(), WiFiMonitor.STATE_DISCONNECTED)
		self.assertTrue(self.disconnected.is_on)

	async def test_connecting_state_uses_ephemeral_action(self):
		self.wifi.connecting = True

		await self.run_monitor()

		self.assertEqual(self.monitor.get_current_state(), WiFiMonitor.STATE_CONNECTING)
		self.assertTrue(self.no_internet.is_on)

	async def test_connected_with_internet(self):
		self.wifi.connected = True

		with self.online():
			await self.run_monitor()

		self.assertEqual(self.monitor.get_current_state(), WiFiMonitor.STATE_CONNECTED)
		self.assertTrue(self.connected.is_on)
		self.assertFalse(self.disconnected.is_on)

	async def test_connected_without_internet(self):
		self.wifi.connected = True

		with self.offline():
			await self.run_monitor()

		self.assertEqual(self.monitor.get_current_state(), WiFiMonitor.STATE_NO_INTERNET)
		self.assertTrue(self.no_internet.is_on)

	async def test_transition_turns_old_action_off(self):
		self.wifi.connected = True

		with self.online():
			task = asyncio.create_task(self.monitor.run())
			await asyncio.sleep_ms(40)
			self.assertTrue(self.connected.is_on)

			self.wifi.connected = False
			await asyncio.sleep_ms(40)
			task.cancel()

		self.assertFalse(self.connected.is_on)
		self.assertTrue(self.disconnected.is_on)

	async def test_state_is_not_reactivated_while_unchanged(self):
		self.wifi.connected = True

		with self.online():
			await self.run_monitor(ms=120)

		# Several check intervals elapsed, but the action was turned on once.
		self.assertEqual(self.connected.on_calls, 1)

	async def test_slow_internet_check_does_not_block_other_tasks(self):
		"""The old blocking socket froze buttons and LEDs; this must not."""
		self.wifi.connected = True
		ticks = []

		async def other_work():
			while True:
				ticks.append(1)
				await asyncio.sleep_ms(5)

		with self.hanging():
			worker = asyncio.create_task(other_work())
			await self.run_monitor(ms=200)
			worker.cancel()

		# A blocking check would have pinned this at 1. The window is wide
		# because PC timer granularity is far coarser than the device's.
		self.assertGreater(len(ticks), 3)

	async def test_hanging_check_eventually_reports_no_internet(self):
		self.wifi.connected = True

		with self.hanging():
			await self.run_monitor(ms=120)

		self.assertEqual(self.monitor.get_current_state(), WiFiMonitor.STATE_NO_INTERNET)


class WiFiActionTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.wifi = WiFiConnection('net', 'secret')

	async def test_connect_action_connects(self):
		action = WiFiConnectAction(self.wifi, timeout_ms=200)

		action.on()
		await asyncio.sleep_ms(30)

		self.assertTrue(self.wifi.is_connected())

	async def test_connect_action_off_cancels_attempt(self):
		self.wifi.wlan.fail_to_connect = True
		action = WiFiConnectAction(self.wifi, timeout_ms=1000)

		action.on()
		await asyncio.sleep_ms(10)
		action.off()
		await asyncio.sleep_ms(10)

		self.assertFalse(action.is_on)

	async def test_disconnect_action_disconnects(self):
		await self.wifi.connect(timeout_ms=200)
		action = WiFiDisconnectAction(self.wifi)

		action.on()

		self.assertFalse(self.wifi.is_connected())


if __name__ == '__main__':
	unittest.main()
