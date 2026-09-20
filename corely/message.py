"""Actions that print, useful for logging or as the "off" step in a cycle."""

from corely.action import Action


class PrintMessage(Action):
	"""Prints a message when activated."""

	def __init__(self, message, off_message=None):
		"""
		Args:
			message: Text to print when activated
			off_message: Optional text to print when deactivated
		"""
		self.message = message
		self.off_message = off_message

	def on(self):
		if self.message:
			print(self.message)

	def off(self):
		if self.off_message:
			print(self.off_message)
