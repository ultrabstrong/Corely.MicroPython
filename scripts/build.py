"""Compile every module with mpy-cross, and zip the release assets.

	python scripts/build.py              # compile into dist/, zip both bundles
	python scripts/build.py --check      # compile only: fails on syntax MicroPython lacks

The host tests run on CPython, which accepts things MicroPython does not.
mpy-cross is MicroPython's own compiler, so compiling every module catches
those before a board does.

Assets, for copying to a board's /lib by hand:

	dist/Corely.MicroPython-<version>-mpy.zip   corely/*.mpy, precompiled
	dist/Corely.MicroPython-<version>-src.zip   corely/*.py
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist')


def version():
	with open(os.path.join(ROOT, 'package.json')) as f:
		return json.load(f)['version']


def sources():
	folder = os.path.join(ROOT, 'corely')
	return sorted(os.path.join(folder, name) for name in os.listdir(folder) if name.endswith('.py'))


def compile_all(out_dir):
	"""Compile each module into out_dir/corely/. Exits on the first failure."""
	target = os.path.join(out_dir, 'corely')
	os.makedirs(target, exist_ok=True)
	failed = []
	for source in sources():
		name = os.path.splitext(os.path.basename(source))[0] + '.mpy'
		result = subprocess.run(
			[sys.executable, '-m', 'mpy_cross', source, '-o', os.path.join(target, name)],
			capture_output=True, text=True)
		if result.returncode != 0:
			failed.append(result.stderr.strip() or source)
	if failed:
		sys.exit("mpy-cross failed:\n" + "\n".join(failed))
	return target


def zip_folder(folder, archive, arcroot):
	with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
		for name in sorted(os.listdir(folder)):
			z.write(os.path.join(folder, name), f'{arcroot}/{name}')


def main():
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument('--check', action='store_true', help="compile only, build nothing")
	args = parser.parse_args()

	scratch = tempfile.mkdtemp()
	try:
		compiled = compile_all(scratch)
		count = len(os.listdir(compiled))
		if args.check:
			print(f"All {count} modules compile with mpy-cross.")
			return

		shutil.rmtree(DIST, ignore_errors=True)
		os.makedirs(DIST)
		stem = f'Corely.MicroPython-{version()}'
		zip_folder(compiled, os.path.join(DIST, f'{stem}-mpy.zip'), 'corely')
		with zipfile.ZipFile(os.path.join(DIST, f'{stem}-src.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
			for source in sources():
				z.write(source, 'corely/' + os.path.basename(source))
		for name in sorted(os.listdir(DIST)):
			print(f"  dist/{name}")
	finally:
		shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
	main()
