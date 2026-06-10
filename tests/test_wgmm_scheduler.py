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
