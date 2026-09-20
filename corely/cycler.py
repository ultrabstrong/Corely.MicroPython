"""Cycles through a sequence of actions, one active at a time."""


class ActionCycler:
	"""Activates one action at a time from an ordered list."""

	def __init__(self, actions):
		"""
		Args:
			actions: List of Action objects to cycle through
		"""
		self.actions = actions
		self.current_index = 0

	def move_next(self):
		"""Turn off the current action and turn on the next one (wraps around)."""
		self.actions[self.current_index].off()
		self.current_index = (self.current_index + 1) % len(self.actions)
		self.actions[self.current_index].on()

	def activate_current(self):
		"""Turn on the current action without advancing."""
		self.actions[self.current_index].on()

	def stop(self):
		"""Turn off the current action."""
		self.actions[self.current_index].off()

	def set_index(self, index):
		"""Set the current index without triggering on/off."""
		if 0 <= index < len(self.actions):
			self.current_index = index
