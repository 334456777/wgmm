"""WGMM 得分计算."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.wgmm.features import vectorized_time_features_numpy

NEAR_ZERO = 1e-12


def _cyclic_similarity_to_reference(
	reference_timestamp: float,
	event_timestamps: np.ndarray,
	dimension_weights: dict[str, float],
	sigmas: dict[str, float],
	extra_periods: list[float] | None = None,
) -> np.ndarray:
	"""计算历史事件与参考事件的周期相似度."""
	if len(event_timestamps) == 0:
		return np.array([], dtype=np.float64)

	reference_feat = vectorized_time_features_numpy(
		np.array([reference_timestamp], dtype=np.float64),
		extra_periods,
	)
	events_feat = vectorized_time_features_numpy(event_timestamps, extra_periods)
	combined = np.zeros(len(event_timestamps), dtype=np.float64)
	for dim, weight in dimension_weights.items():
		sigma = sigmas.get(dim, 1.0)
		dist_sq = (reference_feat[f"{dim}_sin"][0] - events_feat[f"{dim}_sin"]) ** 2 + (
			reference_feat[f"{dim}_cos"][0] - events_feat[f"{dim}_cos"]
		) ** 2
		combined += weight * np.exp(-dist_sq / (2 * sigma**2), dtype=np.float64)

	max_possible = max(sum(dimension_weights.values()), NEAR_ZERO)
	return np.clip(combined / max_possible, 0.0, 1.0)


def _conditional_interval_scores(
	target_timestamps: np.ndarray,
	pos_events: list[int],
	dimension_weights: dict[str, float],
	pos_lambda: float,
	sigmas: dict[str, float],
	extra_periods: list[float] | None = None,
) -> np.ndarray:
	"""根据相似历史发布状态后的下一跳间隔, 预测目标时间得分."""
	min_interval_count = 3
	if len(pos_events) < min_interval_count + 1:
		return np.ones(len(target_timestamps), dtype=np.float64)

	events_arr = np.array(sorted(set(pos_events)), dtype=np.float64)
	start_events = events_arr[:-1]
	intervals = np.diff(events_arr)
	valid_intervals = intervals > 0
	start_events = start_events[valid_intervals]
	intervals = intervals[valid_intervals]
	if len(intervals) < min_interval_count:
		return np.ones(len(target_timestamps), dtype=np.float64)

	last_event = float(events_arr[-1])
	elapsed = np.asarray(target_timestamps, dtype=np.float64) - last_event
	scores = np.zeros(len(target_timestamps), dtype=np.float64)
	valid_targets = elapsed > 0
	if not np.any(valid_targets):
		return scores

	state_similarity = _cyclic_similarity_to_reference(
		last_event,
		start_events,
		dimension_weights,
		sigmas,
		extra_periods,
	)
	ages_hours = (last_event - start_events) / 3600.0
	recency_weights = np.exp(-pos_lambda * ages_hours, dtype=np.float64)
	weights = state_similarity * recency_weights
	if np.sum(weights) <= NEAR_ZERO:
		weights = np.ones(len(intervals), dtype=np.float64)

	log_intervals = np.log(intervals)
	weight_sum = float(np.sum(weights))
	weighted_mean = float(np.sum(weights * log_intervals) / weight_sum)
	weighted_var = float(
		np.sum(weights * (log_intervals - weighted_mean) ** 2) / weight_sum
	)
	effective_n = float(weight_sum**2 / max(np.sum(weights**2), NEAR_ZERO))
	bandwidth = 1.06 * np.sqrt(weighted_var) * (effective_n ** (-1 / 5))
	bandwidth = max(float(bandwidth), 0.1)

	training_z = (log_intervals[:, np.newaxis] - log_intervals[np.newaxis, :]) / bandwidth
	training_density = (
		np.sum(
			weights[np.newaxis, :] * np.exp(-0.5 * training_z**2),
			axis=1,
		)
		/ weight_sum
	)
	normalizer = max(float(np.max(training_density)), NEAR_ZERO)

	log_elapsed = np.log(elapsed[valid_targets])
	z = (log_elapsed[:, np.newaxis] - log_intervals[np.newaxis, :]) / bandwidth
	density = np.sum(weights[np.newaxis, :] * np.exp(-0.5 * z**2), axis=1) / weight_sum
	scores[valid_targets] = np.clip(density / normalizer, 0.0, 1.0)
	return scores


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
	interval_score = float(
		_conditional_interval_scores(
			np.array([target_timestamp]),
			pos_events,
			dimension_weights,
			pos_lambda,
			sigmas,
			extra_periods,
		)[0]
	)
	combined_pos_score = np.sqrt(max(pos_score * interval_score, 0.0))
	return float(
		np.clip(
			combined_pos_score - (resistance_coefficient * neg_score),
			0.0,
			1.0,
		)
	)


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
	interval_scores = _conditional_interval_scores(
		scan_times,
		pos_events,
		dimension_weights,
		pos_lambda,
		sigmas,
		extra_periods,
	)
	combined_pos_scores = np.sqrt(np.clip(pos_scores * interval_scores, 0.0, 1.0))
	return np.clip(
		combined_pos_scores - (resistance_coefficient * neg_scores),
		0.0,
		1.0,
	)
