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

	# The real port's names, private but the only way in to its state.
	def _vocalgorithm_get_states(self, state0, state1):
		return getattr(self, "states", (1234, 567))

	def _vocalgorithm_set_states(self, state0, state1):
		raise TypeError("the real port's version is broken; Corely must not call it")

	def _vocalgorithm__mean_variance_estimator__set_states(self, mean, std, uptime_gamma):
		self.states = (mean, std)
		self.uptime_gamma = uptime_gamma

	def _f16(self, x):
		return int(x * 65536.0 + 0.5)

	class _Params:
		msraw = 0

	params = _Params()
