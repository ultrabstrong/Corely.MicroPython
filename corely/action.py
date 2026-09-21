"""Async action primitives.

An Action is anything that can be switched on and off. Work that needs to keep
running lives in a task the action owns, so nothing has to be pumped from a
main loop and two owners can never double-update the same action.

Contract:
	on()  - activate. Must not block. Starts a task if there is ongoing work.
	off() - deactivate. Must not block, and must be safe to call twice.

`ActionCycler` steps through a list of actions, one active at a time.
"""

import asyncio


class Action:
	"""Base class for anything that can be switched on and off."""

	def on(self):
		"""Override to define what happens when the action is activated."""
		raise NotImplementedError("Subclasses must implement on()")

	def off(self):
		"""Override to define what happens when the action is deactivated."""
		raise NotImplementedError("Subclasses must implement off()")


class TaskAction(Action):
	"""An Action whose work runs in a task for as long as it is on.

	Subclasses implement run() (the ongoing work) and usually cleanup()
	(returning hardware to its resting state).
	"""

	def __init__(self):
		self._task = None
		self._generation = 0

	@property
	def is_on(self):
		return self._task is not None

	def on(self):
		"""Start the work task. Ignored if already on."""
		if self._task is not None:
			return
		self._generation += 1
		self._task = asyncio.create_task(self._run_wrapped(self._generation))

	def off(self):
		"""Cancel the work task and return to the resting state."""
		task = self._task
		self._task = None
		# Retiring the generation hands ownership away from the dying task, so
		# it neither cleans up a second time nor disturbs a later on().
		self._generation += 1
		if task is not None:
			task.cancel()
		# Cancellation only takes effect at the task's next await, so do the
		# deterministic cleanup here rather than relying on the task to do it.
		self.cleanup()

	async def run(self):
		"""Override with the work to do while this action is on."""
		raise NotImplementedError("Subclasses must implement run()")

	def cleanup(self):
		"""Override to return hardware to its resting state.

		Called by off(), and again when run() ends on its own. Must be
		idempotent.
		"""
		pass

	async def _run_wrapped(self, generation):
		try:
			await self.run()
		except asyncio.CancelledError:
			pass
		finally:
			# Only clean up if a newer on() has not already taken ownership.
			if generation == self._generation:
				self._task = None
				self.cleanup()


class ActionGroup(Action):
	"""Switches several actions together, as if they were one.

	Useful where one state should show up in more than one place:

		connected = ActionGroup(green_led, rgb.steady(GREEN))
	"""

	def __init__(self, *actions):
		"""
		Args:
			*actions: The Action objects to switch together
		"""
		self.actions = actions

	def on(self):
		for action in self.actions:
			action.on()

	def off(self):
		for action in self.actions:
			action.off()


class ActionCycler:
	"""Activates one action at a time from an ordered list."""

	def __init__(self, actions):
		"""
		Args:
			actions: List of Action objects to cycle through
		"""
		self.actions = actions
		self.current_index = 0
		self._running = False

	@property
	def current(self):
		"""The action the cycle is currently on, running or not."""
		return self.actions[self.current_index]

	@property
	def is_running(self):
		"""True while one of the actions is on."""
		return self._running

	def start(self):
		"""Turn on the current action. Does nothing if already running."""
		if not self._running:
			self._running = True
			self.current.on()

	def stop(self):
		"""Turn off the current action. Does nothing if already stopped."""
		if self._running:
			self._running = False
			self.current.off()

	def move_next(self):
		"""Turn off the current action and turn on the next one (wraps around).

		Starts the cycle if it is not running yet, so a forgotten start() shows
		up as a late first action rather than a cycler whose idea of "current"
		disagrees with the hardware.
		"""
		if not self._running:
			self.start()
			return

		self.current.off()
		self.current_index = (self.current_index + 1) % len(self.actions)
		self.current.on()
