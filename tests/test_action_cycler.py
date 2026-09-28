"""ActionCycler: one action active at a time, in order. And ActionGroup."""

import unittest

import harness  # noqa: F401

from corely.action import Action, ActionCycler, ActionGroup


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

	def test_on_turns_on_first_only(self):
		self.cycler.on()

		self.assertEqual(self.log, ['a.on'])
		self.assertTrue(self.a.is_on)
		self.assertFalse(self.b.is_on)

	def test_on_twice_does_not_reactivate(self):
		self.cycler.on()
		self.cycler.on()

		self.assertEqual(self.log, ['a.on'])

	def test_move_next_turns_off_before_on(self):
		self.cycler.on()
		self.log.clear()

		self.cycler.move_next()

		# Order matters when two actions share a pin.
		self.assertEqual(self.log, ['a.off', 'b.on'])
		self.assertFalse(self.a.is_on)
		self.assertTrue(self.b.is_on)

	def test_move_next_wraps_around(self):
		self.cycler.on()
		for _ in range(3):
			self.cycler.move_next()

		self.assertEqual(self.cycler.current_index, 0)
		self.assertTrue(self.a.is_on)
		self.assertFalse(self.b.is_on)
		self.assertFalse(self.c.is_on)

	def test_only_one_action_on_at_a_time(self):
		self.cycler.on()
		for _ in range(5):
			self.cycler.move_next()
			active = [a for a in (self.a, self.b, self.c) if a.is_on]
			self.assertEqual(len(active), 1)

	def test_off_turns_off_current(self):
		self.cycler.on()
		self.cycler.off()

		self.assertFalse(self.a.is_on)
		self.assertFalse(self.cycler.is_on)

	def test_off_twice_is_safe(self):
		self.cycler.on()
		self.cycler.off()
		self.log.clear()

		self.cycler.off()

		self.assertEqual(self.log, [])

	def test_move_next_turns_on_an_off_cycle(self):
		"""A forgotten on() must not desync the cycler from the hardware."""
		self.cycler.move_next()

		self.assertEqual(self.log, ['a.on'])
		self.assertEqual(self.cycler.current_index, 0)
		self.assertTrue(self.a.is_on)

	def test_move_next_after_off_resumes_where_it_left_off(self):
		self.cycler.on()
		self.cycler.move_next()
		self.cycler.off()
		self.log.clear()

		self.cycler.move_next()

		self.assertEqual(self.log, ['b.on'])
		self.assertTrue(self.b.is_on)

	def test_current_exposes_the_active_action(self):
		self.cycler.on()
		self.assertIs(self.cycler.current, self.a)

		self.cycler.move_next()
		self.assertIs(self.cycler.current, self.b)

	def test_is_on_tracks_state(self):
		self.assertFalse(self.cycler.is_on)

		self.cycler.on()
		self.assertTrue(self.cycler.is_on)

		self.cycler.off()
		self.assertFalse(self.cycler.is_on)


class ActionCyclerAsActionTests(unittest.TestCase):
	"""A cycler is an Action, so it goes anywhere an Action does."""

	def setUp(self):
		self.log = []
		self.a = RecordingAction('a', self.log)
		self.b = RecordingAction('b', self.log)
		self.cycler = ActionCycler([self.a, self.b])

	def test_is_an_action(self):
		self.assertIsInstance(self.cycler, Action)

	def test_nests_inside_another_cycler(self):
		"""Leaving the outer step switches off whatever the inner one is on."""
		c = RecordingAction('c', self.log)
		outer = ActionCycler([self.cycler, c])

		outer.on()
		self.cycler.move_next()
		self.assertTrue(self.b.is_on)

		outer.move_next()
		self.assertFalse(self.a.is_on)
		self.assertFalse(self.b.is_on)
		self.assertTrue(c.is_on)

		# Coming back resumes the inner cycler where it left off.
		outer.move_next()
		self.assertTrue(self.b.is_on)
		self.assertFalse(c.is_on)

	def test_works_inside_a_group(self):
		c = RecordingAction('c', self.log)
		group = ActionGroup(self.cycler, c)

		group.on()
		self.assertTrue(self.a.is_on)
		self.assertTrue(c.is_on)

		group.off()
		self.assertFalse(self.a.is_on)
		self.assertFalse(c.is_on)


class ActionGroupTests(unittest.TestCase):
	def setUp(self):
		self.log = []
		self.a = RecordingAction('a', self.log)
		self.b = RecordingAction('b', self.log)
		self.group = ActionGroup(self.a, self.b)

	def test_on_switches_every_member(self):
		self.group.on()

		self.assertEqual(self.log, ['a.on', 'b.on'])
		self.assertTrue(self.a.is_on)
		self.assertTrue(self.b.is_on)

	def test_off_switches_every_member(self):
		self.group.on()
		self.log.clear()

		self.group.off()

		self.assertEqual(self.log, ['a.off', 'b.off'])
		self.assertFalse(self.a.is_on)
		self.assertFalse(self.b.is_on)

	def test_works_inside_a_cycler(self):
		"""A group is an Action, so a cycler cannot tell the difference."""
		other = RecordingAction('c', self.log)
		cycler = ActionCycler([self.group, other])

		cycler.on()
		self.assertTrue(self.a.is_on)

		cycler.move_next()
		self.assertFalse(self.a.is_on)
		self.assertFalse(self.b.is_on)
		self.assertTrue(other.is_on)

	def test_empty_group_is_harmless(self):
		empty = ActionGroup()

		empty.on()
		empty.off()


if __name__ == '__main__':
	unittest.main()
