"""Fake `voc_algorithm` - records what it is fed and returns a fixed index."""


class VOCAlgorithm:
	INDEX = 100

	def __init__(self):
		self.processed = []

	def vocalgorithm_init(self):
		self.processed.clear()

	def vocalgorithm_process(self, sraw):
		self.processed.append(sraw)
		return self.INDEX
