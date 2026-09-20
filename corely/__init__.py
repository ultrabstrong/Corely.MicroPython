"""Corely - asyncio building blocks for MicroPython devices.

Import submodules directly so a project only pays for what it uses:

	from corely.led import LedBlinking
	from corely.wifi import WiFiConnection

This file stays empty of re-exports on purpose. Pulling every module in here
would drag the BLE modules (and their aioble dependency) into RAM even for a
project that only blinks an LED.
"""

__version__ = '0.1.0'
