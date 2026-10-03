"""Over-the-air updates: fetch a release, check every byte, stage it.

A release is a folder of files plus `manifest.json`:

	{"version": "aeeaeee+3f9c1a",
	 "files": [{"path": "lib/corely/led.py", "size": 5120, "sha256": "..."}, ...]}

Updater downloads the manifest, then each file into a staging folder,
hashing as it goes; one mismatch throws the whole download away. stage()
then marks it ready. Nothing live changes here - installing (swapping the
staged files in) and rolling back happen at the next boot, in code the app
keeps out of its releases, so a bad update cannot break its own way back.

	updater = Updater("http://192.168.1.20:8000", current_version="aeeaeee")
	manifest = await updater.check()          # None if up to date
	if manifest:
		await updater.download(manifest)      # raises UpdateError
		updater.stage(manifest)               # installed on the next boot

HTTP goes through micropython-lib's aiohttp (vendored), so a download never
blocks the event loop. Plain HTTP checks integrity, not origin: anyone who
can answer for that address can serve a matching manifest. A hosted release
needs HTTPS with the certificate checked.
"""

import asyncio
import json
import os

try:
	import hashlib
except ImportError:		# pragma: no cover - always present on the device
	import uhashlib as hashlib

READY = "READY"				# Written last: the staged release is complete
MANIFEST = "manifest.json"


class UpdateError(Exception):
	"""A release could not be fetched, did not match its manifest, or would
	not fit."""


def join(root, path):
	"""A path under root, with root "/" or "" meaning the filesystem root."""
	root = root.rstrip("/")
	return root + "/" + path if root else "/" + path


def make_dirs(path):
	"""Create every folder above a file path."""
	built = []
	for part in path.split("/")[:-1]:
		built.append(part)
		folder = "/".join(built)
		if folder:		# A leading "/" gives an empty first part
			try:
				os.mkdir(folder)
			except OSError:
				pass	# Already there


def remove_tree(path):
	"""Delete a file or a folder and everything in it. Missing is fine."""
	try:
		mode = os.stat(path)[0]
	except OSError:
		return
	if mode & 0x4000:		# Directory
		for entry in os.listdir(path):
			remove_tree(path + "/" + entry)
		os.rmdir(path)
	else:
		os.remove(path)


def check_manifest(manifest):
	"""Raise UpdateError unless the manifest is well formed and every path
	stays inside the device's filesystem."""
	try:
		version = manifest["version"]
		files = manifest["files"]
		for entry in files:
			path = entry["path"]
			int(entry["size"])
			if len(entry["sha256"]) != 64:
				raise ValueError("bad hash for " + path)
			if path.startswith("/") or ".." in path.split("/") or not path:
				raise ValueError("unsafe path " + path)
	except (KeyError, TypeError, ValueError) as e:
		raise UpdateError("bad manifest: {}".format(e))
	if not isinstance(version, str) or not version:
		raise UpdateError("bad manifest: no version")


async def http_fetch(url, sink, chunk_size=1024, timeout_ms=10000):
	"""GET a URL, handing each chunk of the body to sink(bytes).

	Args:
		url: The address
		sink: Called with each chunk as it arrives
		chunk_size: Bytes per read
		timeout_ms: Longest wait for any one read

	Raises:
		UpdateError: On a status other than 200
	"""
	import aiohttp
	async with aiohttp.ClientSession() as session:
		async with session.get(url) as response:
			if response.status != 200:
				raise UpdateError("{} answered {}".format(url, response.status))
			# A chunked body has to be read through the response, which
			# strips the chunk framing; a plain one is read straight off the
			# stream, since the response's own read() wants the whole length.
			chunked = hasattr(response, "chunk_size")
			while True:
				if chunked:
					read = response.read(chunk_size)
				else:
					read = response.content.read(chunk_size)
				data = await asyncio.wait_for_ms(read, timeout_ms)
				if not data:
					return
				sink(data)


def _hex(digest):
	return "".join("{:02x}".format(b) for b in digest)


class Updater:
	"""Checks a release address and stages a newer release for the next boot."""

	def __init__(self, url, current_version, staging="/update", fetch=None,
				 free_bytes=None, margin_bytes=32768):
		"""
		Args:
			url: The release folder's address, e.g. "http://192.168.1.20:8000"
			current_version: The version running now
			staging: Where to download to - the next boot installs from here
			fetch: async fetch(url, sink) - http_fetch by default
			free_bytes: Function returning free filesystem bytes; from
				os.statvfs by default
			margin_bytes: Space to leave free after the download
		"""
		self.url = url.rstrip("/")
		self.current_version = current_version
		self.staging = staging.rstrip("/")
		self.fetch = fetch or http_fetch
		self.free_bytes = free_bytes or self._statvfs_free
		self.margin_bytes = margin_bytes

	def _statvfs_free(self):
		stat = os.statvfs(self.staging.rsplit("/", 1)[0] or "/")
		return stat[0] * stat[3]

	async def check(self):
		"""Fetch the manifest.

		Returns:
			The manifest if it names a different version, else None

		Raises:
			UpdateError: If it cannot be fetched or is malformed
		"""
		chunks = []
		try:
			await self.fetch(self.url + "/" + MANIFEST, chunks.append)
			manifest = json.loads(b"".join(chunks))
		except UpdateError:
			raise
		except (OSError, ValueError, asyncio.TimeoutError) as e:
			raise UpdateError("cannot fetch the manifest: {}".format(e))
		check_manifest(manifest)
		if manifest["version"] == self.current_version:
			return None
		return manifest

	async def download(self, manifest, progress=None):
		"""Download every file into staging, checking each one's hash.

		Anything already staged is discarded first, and on any failure the
		staging folder is removed again - a half download never installs.

		Args:
			manifest: What check() returned
			progress: Called with (files done, files total) after each file

		Raises:
			UpdateError: Out of space, a fetch failed, or a file did not match
		"""
		check_manifest(manifest)
		files = manifest["files"]
		remove_tree(self.staging)
		needed = sum(int(f["size"]) for f in files) + self.margin_bytes
		free = self.free_bytes()
		if free < needed:
			raise UpdateError("needs {}KB, {}KB free".format(needed // 1024, free // 1024))
		try:
			for done, entry in enumerate(files):
				await self._download_file(entry)
				if progress:
					progress(done + 1, len(files))
		except BaseException:
			remove_tree(self.staging)
			raise

	async def _download_file(self, entry):
		path = join(self.staging, entry["path"])
		make_dirs(path)
		digest = hashlib.sha256()
		size = [0]
		with open(path, "wb") as f:
			def sink(data):
				f.write(data)
				digest.update(data)
				size[0] += len(data)
			try:
				await self.fetch(self.url + "/" + entry["path"], sink)
			except UpdateError:
				raise
			except (OSError, ValueError, asyncio.TimeoutError) as e:
				raise UpdateError("cannot fetch {}: {}".format(entry["path"], e))
		if size[0] != int(entry["size"]) or _hex(digest.digest()) != entry["sha256"]:
			raise UpdateError("{} does not match the manifest".format(entry["path"]))

	def stage(self, manifest):
		"""Mark the download complete: the next boot installs it."""
		with open(join(self.staging, MANIFEST), "w") as f:
			json.dump(manifest, f)
		with open(join(self.staging, READY), "w") as f:
			f.write(manifest["version"])
