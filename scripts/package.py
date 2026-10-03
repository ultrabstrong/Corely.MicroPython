"""Write package.json from what is in corely/, or check that it is current.

	python scripts/package.py           # rewrite package.json, keeping its version
	python scripts/package.py --check   # exit 1 if package.json is out of date

package.json is what `mip` reads: every module of the package, where to
fetch it, and the micropython-lib packages it needs. Listing the modules by
hand is how one gets left out, so this script owns the list and CI checks it.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_JSON = os.path.join(ROOT, 'package.json')
REPO = 'github:ultrabstrong/Corely.MicroPython'

# From micropython-lib's index. corely.sensors' drivers are not here: they
# are optional, and live in sensors.json.
DEPS = [
	['logging', 'latest'],		# corely.logs, sensors, wifi
	['aioble', 'latest'],		# corely.ble_peripheral, ble_central
	['aiohttp', 'latest'],		# corely.update
]


def modules():
	"""Every module of the package, as paths relative to the repo root."""
	folder = os.path.join(ROOT, 'corely')
	return sorted('corely/' + name for name in os.listdir(folder) if name.endswith('.py'))


def current_version():
	try:
		with open(PACKAGE_JSON) as f:
			return json.load(f)['version']
	except (OSError, ValueError, KeyError):
		return '0.0.0'


def build(version):
	return {
		'urls': [[path, f'{REPO}/{path}'] for path in modules()],
		'deps': DEPS,
		'version': version,
	}


def render(package):
	return json.dumps(package, indent=2) + '\n'


def main():
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument('--check', action='store_true', help="fail if package.json is out of date")
	args = parser.parse_args()

	expected = render(build(current_version()))
	if args.check:
		with open(PACKAGE_JSON) as f:
			if f.read() != expected:
				sys.exit("package.json does not list corely/ as it is. Run: python scripts/package.py")
		print("package.json is current.")
		return

	with open(PACKAGE_JSON, 'w', newline='\n') as f:
		f.write(expected)
	print(f"Wrote package.json: {len(modules())} modules, version {current_version()}")


if __name__ == '__main__':
	main()
