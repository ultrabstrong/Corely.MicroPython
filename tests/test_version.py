"""The version a board reports (corely.__version__) is the version that was released.

package.json's version is the one the release tag checks; corely.__version__ is the one code on
a board can read. Release 1.0.0 shipped with __version__ still at 0.1.0, found on the board.
"""

import json
import os
import unittest

import harness  # noqa: F401

import corely

PACKAGE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "package.json")


class VersionTest(unittest.TestCase):

	def test_version_matches_package_json(self):
		with open(PACKAGE_JSON, encoding="utf-8") as f:
			released = json.load(f)["version"]
		self.assertEqual(corely.__version__, released)


if __name__ == "__main__":
	unittest.main()
