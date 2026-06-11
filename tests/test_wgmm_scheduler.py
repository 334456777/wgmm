"""WGMM 调频决策测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.constants import (
	FALLBACK_INTERVAL,
	HAZARD_CAP_FLOOR,
	HAZARD_CAP_MAX,
)
from wgmm_monitor.wgmm.scheduler import decide_next_frequency, estimate_hazard_cap


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

	def test_peak_response_advances_check_before_peak(self) -> None:
		"""低相位时刻 + 临近显著峰: 检查应提前到峰前(扣除 yt-dlp 提前量)."""
		day = 86400
		base = 1700000000 - (1700000000 % day) + 12 * 3600
		events = [base + i * day for i in range(30)]
		now = events[-1] + day - 8 * 3600
		config = WgmmConfig(is_manual_run=False)

		decision = decide_next_frequency(
			config,
			events,
			[],
			now,
			last_ytdlp_duration=30.0,
			normal_ytdlp_duration=60.0,
		)

		# 下一峰在 +8h, 提前量取 max(last, normal)=60s
		self.assertAlmostEqual(
			decision.final_frequency_sec,
			8 * 3600 - 60,
			delta=3600,
		)

	def test_hazard_cap_grows_with_waiting_time(self) -> None:
		"""重尾间隔下: 等待越久风险率越低, 允许的检查间隔上限越大."""
		now = 1700000000
		day = 86400
		intervals = [7200] * 20 + [5 * day] * 6
		events = [now]
		for interval in intervals:
			events.append(events[-1] - interval)
		events.sort()

		cap_early = estimate_hazard_cap(events, now)
		cap_late = estimate_hazard_cap(events, now + int(2.5 * day))

		self.assertGreater(cap_late, cap_early)

	def test_hazard_cap_respects_floor_and_max(self) -> None:
		"""上限被裁剪到 [HAZARD_CAP_FLOOR, HAZARD_CAP_MAX]."""
		now = 1700000000
		burst_events = [now - i * 60 for i in range(6)]
		cap_floor = estimate_hazard_cap(burst_events, now)
		self.assertEqual(cap_floor, HAZARD_CAP_FLOOR)

		sparse_events = [now - i * 90 * 86400 for i in range(1, 12)]
		cap_max = estimate_hazard_cap(sparse_events, now + 1500 * 86400)
		self.assertEqual(cap_max, HAZARD_CAP_MAX)

	def test_hazard_cap_uses_tail_formula_beyond_history(self) -> None:
		"""等待超出历史最大间隔后按 Pareto 尾退化, 上限随 sqrt(tau) 增长."""
		now = 1700000000
		day = 86400
		events = [now - i * day for i in range(1, 20)]

		cap_a = estimate_hazard_cap(events, now + 3 * day)
		cap_b = estimate_hazard_cap(events, now + 12 * day)

		self.assertGreater(cap_b, cap_a)
		self.assertLessEqual(cap_b, HAZARD_CAP_MAX)
		self.assertAlmostEqual(cap_b / cap_a, 2.0, delta=0.2)

	def test_decide_bounds_interval_by_hazard_cap(self) -> None:
		"""周期得分驱动的长间隔被风险率上限约束."""
		now = 1700000000
		week = 604800
		events = [now - i * week for i in range(24)]
		config = WgmmConfig(is_manual_run=False)

		decision = decide_next_frequency(config, events, [], now, dev_mode=True)

		self.assertLessEqual(
			decision.final_frequency_sec,
			estimate_hazard_cap(events, now) + 1.0,
		)

	def test_slow_ytdlp_applies_impedance_factor(self) -> None:
		"""yt-dlp 耗时超过正常值 2 倍时, 轮询间隔按阻抗系数拉长."""
		day = 86400
		base = 1700000000 - (1700000000 % day) + 12 * 3600
		events = [base + i * day for i in range(30)]
		now = events[-1] + day - 1800
		config = WgmmConfig(is_manual_run=False)

		baseline = decide_next_frequency(
			WgmmConfig(is_manual_run=False),
			list(events),
			[],
			now,
			last_ytdlp_duration=30.0,
			normal_ytdlp_duration=60.0,
		)
		slowed = decide_next_frequency(
			config,
			list(events),
			[],
			now,
			last_ytdlp_duration=200.0,
			normal_ytdlp_duration=60.0,
		)

		self.assertGreater(slowed.final_frequency_sec, baseline.final_frequency_sec)


if __name__ == "__main__":
	unittest.main()
