"""WGMM 得分测试."""

from __future__ import annotations

import unittest

import numpy as np

from wgmm_monitor.wgmm.constants import DEFAULT_DIMENSION_WEIGHTS, DEFAULT_SIGMAS
from wgmm_monitor.wgmm.scoring import batch_calculate_scores, calculate_point_score


class WgmmScoringTest(unittest.TestCase):
	"""验证单点和批量打分."""

	def test_empty_events_score_is_zero(self) -> None:
		score = calculate_point_score(
			1700000000,
			[],
			[],
			dict(DEFAULT_DIMENSION_WEIGHTS),
			0.0001,
			0.0001,
			dict(DEFAULT_SIGMAS),
			0.8,
		)
		self.assertEqual(score, 0.0)

	def test_point_score_is_in_unit_range_with_custom_period(self) -> None:
		events = [1700000000 - i * 86400 for i in range(20)]
		weights = dict(DEFAULT_DIMENSION_WEIGHTS)
		weights["custom_0"] = 0.2
		sigmas = dict(DEFAULT_SIGMAS)
		sigmas["custom_0"] = 1.0

		score = calculate_point_score(
			1700000000,
			events,
			[],
			weights,
			0.0001,
			0.0001,
			sigmas,
			0.8,
			[270000.0],
		)

		self.assertGreaterEqual(score, 0.0)
		self.assertLessEqual(score, 1.0)

	def test_batch_scores_match_point_scores(self) -> None:
		events = [1700000000 - i * 604800 for i in range(12)]
		scan_times = np.array(
			[1700000000, 1700003600, 1700007200],
			dtype=np.float64,
		)
		weights = dict(DEFAULT_DIMENSION_WEIGHTS)
		sigmas = dict(DEFAULT_SIGMAS)

		batch = batch_calculate_scores(
			scan_times,
			events,
			[],
			weights,
			0.0001,
			0.0001,
			sigmas,
			0.8,
		)
		points = [
			calculate_point_score(
				float(ts),
				events,
				[],
				weights,
				0.0001,
				0.0001,
				sigmas,
				0.8,
			)
			for ts in scan_times
		]

		np.testing.assert_allclose(batch, points, rtol=1e-12, atol=1e-12)


if __name__ == "__main__":
	unittest.main()
