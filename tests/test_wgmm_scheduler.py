"""WGMM 调频决策测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.constants import FALLBACK_INTERVAL
from wgmm_monitor.wgmm.scheduler import decide_next_frequency


class WgmmSchedulerTest(unittest.TestCase):
	"""验证调频结果."""

	def test_empty_data_uses_learning_fallback(self) -> None:
		now = 1700000000
		config = WgmmConfig()

		decision = decide_next_frequency(config, [], [], now, dev_mode=True)

		self.assertTrue(decision.learning_mode)
		self.assertEqual(decision.next_check_time, now + FALLBACK_INTERVAL)

	def test_scheduler_returns_future_next_check_time(self) -> None:
		now = 1700000000
		events = [now - i * 604800 for i in range(12)]
		config = WgmmConfig(is_manual_run=False)

		decision = decide_next_frequency(config, events, [], now, dev_mode=False)

		self.assertGreater(decision.next_check_time, now)
		self.assertFalse(decision.learning_mode)
		self.assertTrue(decision.should_save_miss)

	def test_scheduler_supports_custom_periods(self) -> None:
		now = 1700000000
		period = 270000
		events = [now - i * period for i in range(60)]
		config = WgmmConfig(discovered_periods=[float(period)], is_manual_run=False)

		decision = decide_next_frequency(config, events, [], now, dev_mode=True)

		self.assertGreater(decision.next_check_time, now)
		self.assertIn("custom_0", decision.config.dimension_weights)
		self.assertIn("custom_0", decision.config.sigmas)


if __name__ == "__main__":
	unittest.main()
