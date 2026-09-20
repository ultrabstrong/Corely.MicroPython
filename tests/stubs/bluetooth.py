"""Fake `bluetooth` module - just enough for UUID constants to exist."""


class UUID:
	def __init__(self, value):
		self.value = value

	def __eq__(self, other):
		return isinstance(other, UUID) and other.value == self.value

	def __hash__(self):
		return hash(self.value)

	def __repr__(self):
		return f"UUID({self.value})"
