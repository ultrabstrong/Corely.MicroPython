"""Over-the-air download and staging, against a fake web server."""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import unittest

import harness  # noqa: F401

from corely import update
from corely.update import Updater, UpdateError


def entry(path, data):
	return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class FakeServer:
	"""Serves a release from a dict, in small chunks like a real socket."""

	def __init__(self, files, version='v2'):
		self.files = dict(files)
		self.manifest = {'version': version, 'files': [entry(p, d) for p, d in files.items()]}
		self.requests = []

	async def fetch(self, url, sink):
		path = url.split('/', 3)[3]
		self.requests.append(path)
		if path == 'manifest.json':
			body = json.dumps(self.manifest).encode()
		elif path in self.files:
			body = self.files[path]
		else:
			raise UpdateError(url + ' answered 404')
		for start in range(0, len(body), 7):
			await asyncio.sleep(0)
			sink(body[start:start + 7])


class UpdaterTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp().replace(os.sep, '/')
		self.staging = self.dir + '/update'
		self.server = FakeServer({
			'main.py': b'print("v2")\n',
			'lib/corely/led.py': b'# led v2\n' * 50,
		})

	def tearDown(self):
		shutil.rmtree(self.dir)

	def updater(self, version='v1', free=10 ** 6):
		return Updater('http://pc:8000', version, staging=self.staging,
			fetch=self.server.fetch, free_bytes=lambda: free)

	def read(self, path):
		with open(self.staging + '/' + path, 'rb') as f:
			return f.read()

	async def test_up_to_date_is_none(self):
		self.assertIsNone(await self.updater(version='v2').check())

	async def test_a_new_version_is_offered(self):
		manifest = await self.updater().check()

		self.assertEqual(manifest['version'], 'v2')

	async def test_downloads_and_stages_every_file(self):
		updater = self.updater()
		manifest = await updater.check()
		seen = []

		await updater.download(manifest, progress=lambda done, total: seen.append((done, total)))
		updater.stage(manifest)

		self.assertEqual(self.read('main.py'), b'print("v2")\n')
		self.assertEqual(self.read('lib/corely/led.py'), b'# led v2\n' * 50)
		self.assertEqual(self.read('READY'), b'v2')
		self.assertEqual(seen, [(1, 2), (2, 2)])

	async def test_a_corrupted_file_throws_the_download_away(self):
		updater = self.updater()
		manifest = await updater.check()
		self.server.files['main.py'] = b'print("tampered")\n'

		with self.assertRaises(UpdateError):
			await updater.download(manifest)

		self.assertFalse(os.path.exists(self.staging))

	async def test_a_missing_file_throws_the_download_away(self):
		updater = self.updater()
		manifest = await updater.check()
		del self.server.files['lib/corely/led.py']

		with self.assertRaises(UpdateError):
			await updater.download(manifest)

		self.assertFalse(os.path.exists(self.staging))

	async def test_refuses_what_will_not_fit(self):
		updater = self.updater(free=1000)
		manifest = await updater.check()

		with self.assertRaises(UpdateError):
			await updater.download(manifest)

		self.assertEqual(self.server.requests, ['manifest.json'])

	async def test_rejects_paths_outside_the_filesystem(self):
		self.server.manifest['files'].append(entry('../boot.py', b'x'))

		with self.assertRaises(UpdateError):
			await self.updater().check()

	async def test_an_unreachable_server_is_an_update_error(self):
		async def fetch(url, sink):
			raise OSError(113)

		updater = Updater('http://pc:8000', 'v1', staging=self.staging, fetch=fetch)

		with self.assertRaises(UpdateError):
			await updater.check()


class HelperTests(unittest.TestCase):
	def test_join(self):
		self.assertEqual(update.join('/', 'main.py'), '/main.py')
		self.assertEqual(update.join('/update', 'lib/x.py'), '/update/lib/x.py')


if __name__ == '__main__':
	unittest.main()
