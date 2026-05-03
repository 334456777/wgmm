"""WGMM 学习逻辑测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.learning import (
	aggregate_publish_events,
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

	def test_aggregate_publish_events_empty(self) -> None:
		self.assertEqual(aggregate_publish_events([], 1000), [])

	def test_aggregate_publish_events_drops_future_timestamps(self) -> None:
		self.assertEqual(aggregate_publish_events([100, 200, 5000], 1000), [100])

	def test_aggregate_publish_events_keeps_unrelated_events(self) -> None:
		# 间隔均超过阈值, 应原样返回
		result = aggregate_publish_events([1000, 5000, 10000], 20000, gap_threshold_sec=600)
		self.assertEqual(result, [1000, 5000, 10000])

	def test_aggregate_publish_events_collapses_burst(self) -> None:
		# 一批 5 个时间戳间隔均小, 应只留最早一条
		burst = [1000, 1010, 1050, 1120, 1300]
		result = aggregate_publish_events(burst, 5000, gap_threshold_sec=600)
		self.assertEqual(result, [1000])

	def test_aggregate_publish_events_chain_extends_within_threshold(self) -> None:
		# 链式扩展: 100→700→1300 每段间隔 600, 整体合为一次事件
		chain = [100, 700, 1300, 5000]
		result = aggregate_publish_events(chain, 10000, gap_threshold_sec=600)
		self.assertEqual(result, [100, 5000])

	def test_aggregate_publish_events_threshold_boundary_inclusive(self) -> None:
		# 间隔恰好 = 阈值, 视为同一事件 (阈值上界包含)
		result = aggregate_publish_events([1000, 1600], 5000, gap_threshold_sec=600)
		self.assertEqual(result, [1000])

	def test_aggregate_publish_events_threshold_exceeded_starts_new_event(self) -> None:
		# 间隔比阈值大 1 秒, 视为新事件
		result = aggregate_publish_events([1000, 1601], 5000, gap_threshold_sec=600)
		self.assertEqual(result, [1000, 1601])

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
