"""WGMM 得分计算."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.wgmm.features import vectorized_time_features_numpy


def calculate_point_score(
	target_timestamp: float,
	pos_events: list[int],
	neg_events: list[int],
	dimension_weights: dict[str, float],
	pos_lambda: float,
	neg_lambda: float,
	sigmas: dict[str, float],
	resistance_coefficient: float,
	extra_periods: list[float] | None = None,
) -> float:
	"""计算单个时间点的发布概率得分."""
	target_feat = vectorized_time_features_numpy(
		np.array([target_timestamp]),
		extra_periods,
	)
	current_features = {key: value[0] for key, value in target_feat.items()}

	def calculate_source_score_vectorized(
		events_array: list[int],
		lambda_decay: float,
	) -> float:
		"""计算一个事件来源对目标时间的得分."""
		if not events_array:
			return 0.0

		events_arr = np.array(events_array, dtype=np.float64)
		events_feat = vectorized_time_features_numpy(events_arr, extra_periods)
		ages_hours = (target_timestamp - events_arr) / 3600.0
		valid_mask = ages_hours >= 0
		if not np.any(valid_mask):
			return 0.0

		valid_ages = ages_hours[valid_mask]
		weights = np.exp(-lambda_decay * valid_ages, dtype=np.float64)

		def dist_sq(key: str) -> np.ndarray:
			"""计算指定维度的 sin/cos 距离平方."""
			return (
				current_features[f"{key}_sin"] - events_feat[f"{key}_sin"][valid_mask]
			) ** 2 + (
				current_features[f"{key}_cos"] - events_feat[f"{key}_cos"][valid_mask]
			) ** 2

		n_valid = int(np.sum(valid_mask))
		combined = np.zeros(n_valid, dtype=np.float64)
		for dim, weight in dimension_weights.items():
			sigma = sigmas.get(dim, 1.0)
			combined += weight * np.exp(
				-dist_sq(dim) / (2 * sigma**2),
				dtype=np.float64,
			)

		near_zero = 1e-12
		weight_sum = np.sum(weights, dtype=np.float64)
		if weight_sum < near_zero:
			return 0.0

		weighted_similarity = np.sum(weights * combined, dtype=np.float64) / weight_sum
		max_possible = sum(dimension_weights.values())
		return float(np.clip(weighted_similarity / max(max_possible, near_zero), 0.0, 1.0))

	pos_score = calculate_source_score_vectorized(pos_events, pos_lambda)
	neg_score = (
		calculate_source_score_vectorized(neg_events, neg_lambda) if neg_events else 0.0
	)
	return float(np.clip(pos_score - (resistance_coefficient * neg_score), 0.0, 1.0))


def batch_calculate_scores(
	scan_times: np.ndarray,
	pos_events: list[int],
	neg_events: list[int],
	dimension_weights: dict[str, float],
	pos_lambda: float,
	neg_lambda: float,
	sigmas: dict[str, float],
	resistance_coefficient: float,
	extra_periods: list[float] | None = None,
) -> np.ndarray:
	"""批量计算多个时间点的 WGMM 得分."""
	if len(scan_times) == 0:
		return np.array([], dtype=np.float64)

	targets_feat = vectorized_time_features_numpy(scan_times, extra_periods)

	def get_source_scores_vectorized(
		events: list[int],
		lambda_decay: float,
	) -> np.ndarray:
		"""计算一个事件来源对所有扫描点的得分."""
		if not events:
			return np.zeros(len(scan_times), dtype=np.float64)

		events_arr = np.array(events, dtype=np.float64)
		events_feat = vectorized_time_features_numpy(events_arr, extra_periods)
		ages = (scan_times[:, np.newaxis] - events_arr[np.newaxis, :]) / 3600.0
		valid_mask = ages >= 0
		weights = np.zeros_like(ages, dtype=np.float64)
		weights[valid_mask] = np.exp(-lambda_decay * ages[valid_mask])

		n_scan = len(scan_times)
		n_events = len(events_arr)
		combined_gaussian = np.zeros((n_scan, n_events), dtype=np.float64)
		for dim, weight in dimension_weights.items():
			s_k = f"{dim}_sin"
			c_k = f"{dim}_cos"
			d_sq = (
				targets_feat[s_k][:, np.newaxis] - events_feat[s_k][np.newaxis, :]
			) ** 2 + (
				targets_feat[c_k][:, np.newaxis] - events_feat[c_k][np.newaxis, :]
			) ** 2
			sigma = sigmas.get(dim, 1.0)
			coeff = -0.5 / (sigma**2)
			combined_gaussian += weight * np.exp(d_sq * coeff, dtype=np.float64)

		raw_scores = weights * combined_gaussian * valid_mask
		near_zero = 1e-12
		weight_sums = np.sum(weights * valid_mask, axis=1, dtype=np.float64)
		weighted_totals = np.sum(raw_scores, axis=1, dtype=np.float64)
		max_possible = sum(dimension_weights.values())
		with np.errstate(divide="ignore", invalid="ignore"):
			weighted_mean = np.where(
				weight_sums > near_zero,
				weighted_totals / weight_sums,
				0.0,
			)
			result = weighted_mean / max(max_possible, near_zero)

		return np.clip(result, 0.0, 1.0)

	pos_scores = get_source_scores_vectorized(pos_events, pos_lambda)
	neg_scores = get_source_scores_vectorized(neg_events, neg_lambda)
	return np.clip(pos_scores - (resistance_coefficient * neg_scores), 0.0, 1.0)
