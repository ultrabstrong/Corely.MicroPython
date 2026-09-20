"""ActionCycler: one action active at a time, in order."""

import unittest

import harness  # noqa: F401

from corely.action import Action
from corely.cycler import ActionCycler


class RecordingAction(Action):
	"""Records on/off calls into a shared log so ordering can be asserted."""

	def __init__(self, name, log):
		self.name = name
		self.log = log
		self.is_on = False

	def on(self):
		self.is_on = True
		self.log.append(f"{self.name}.on")

	def off(self):
		self.is_on = False
		self.log.append(f"{self.name}.off")


class ActionCyclerTests(unittest.TestCase):
	def setUp(self):
		self.log = []
		self.a = RecordingAction('a', self.log)
		self.b = RecordingAction('b', self.log)
		self.c = RecordingAction('c', self.log)
		self.cycler = ActionCycler([self.a, self.b, self.c])

	def test_activate_current_turns_on_first_only(self):
		self.cycler.activate_current()

		self.assertEqual(self.log, ['a.on'])
		self.assertTrue(self.a.is_on)
		self.assertFalse(self.b.is_on)

	def test_move_next_turns_off_before_on(self):
		self.cycler.activate_current()
		self.log.clear()

		self.cycler.move_next()

		# Order matters when two actions share a pin.
		self.assertEqual(self.log, ['a.off', 'b.on'])
		self.assertFalse(self.a.is_on)
		self.assertTrue(self.b.is_on)

	def test_move_next_wraps_around(self):
		self.cycler.activate_current()
		for _ in range(3):
			self.cycler.move_next()

		self.assertEqual(self.cycler.current_index, 0)
		self.assertTrue(self.a.is_on)
		self.assertFalse(self.b.is_on)
		self.assertFalse(self.c.is_on)

	def test_only_one_action_on_at_a_time(self):
		self.cycler.activate_current()
		for _ in range(5):
			self.cycler.move_next()
			active = [a for a in (self.a, self.b, self.c) if a.is_on]
			self.assertEqual(len(active), 1)

	def test_stop_turns_off_current(self):
		self.cycler.activate_current()
		self.cycler.stop()

		self.assertFalse(self.a.is_on)

	def test_set_index_does_not_trigger_actions(self):
		self.cycler.set_index(2)

		self.assertEqual(self.cycler.current_index, 2)
		self.assertEqual(self.log, [])

	def test_set_index_ignores_out_of_range(self):
		self.cycler.set_index(99)
		self.cycler.set_index(-1)

		self.assertEqual(self.cycler.current_index, 0)


if __name__ == '__main__':
	unittest.main()
