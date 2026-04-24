"""WGMM 学习逻辑测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.learning import (
	discover_periods,
	filter_outliers,
	initialize_wgmm_dimensions,
	learn_adaptive_sigmas,
	learn_dimension_weights,
	sync_discovered_periods,
)

PERIOD_TOLERANCE = 0.2


class WgmmLearningTest(unittest.TestCase):
	"""验证权重学习和周期同步."""

	def test_filter_outliers_keeps_small_sample_without_future_values(self) -> None:
		self.assertEqual(filter_outliers([10, 20, 200], 100), [10, 20])

	def test_sync_discovered_periods_keeps_existing_index(self) -> None:
		result = sync_discovered_periods([270000.0], [271000.0, 900000.0])
		self.assertEqual(result, [270000.0, 900000.0])

	def test_initialize_wgmm_dimensions_adds_custom_keys(self) -> None:
		config = WgmmConfig(discovered_periods=[270000.0])
		weights, sigmas = initialize_wgmm_dimensions(config)

		self.assertEqual(weights["custom_0"], 0.1)
		self.assertEqual(sigmas["custom_0"], 1.0)

	def test_learners_return_custom_dimensions(self) -> None:
		timestamps = [1700000000 + i * 270000 for i in range(25)]
		weights = learn_dimension_weights(
			timestamps,
			{"day": 0.5, "week": 1.0, "month_week": 0.3, "year_month": 0.2},
			0.1,
			[270000.0],
		)
		sigmas = learn_adaptive_sigmas(
			timestamps,
			{"day": 0.8, "week": 1.0, "month_week": 1.5, "year_month": 2.0},
			[270000.0],
		)

		self.assertIn("custom_0", weights)
		self.assertIn("custom_0", sigmas)

	def test_discover_periods_finds_non_calendar_period(self) -> None:
		period = 3 * 86400
		timestamps = [1700000000 + i * period for i in range(60)]

		discovered = discover_periods(timestamps)

		self.assertTrue(
			any(abs(item - period) / period < PERIOD_TOLERANCE for item in discovered)
		)


if __name__ == "__main__":
	unittest.main()
