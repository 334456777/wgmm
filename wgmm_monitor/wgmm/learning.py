"""WGMM 学习与周期发现."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.features import get_raw_time_components


def filter_outliers(timestamps: list[int], current_time: int) -> list[int]:
	"""使用 IQR 方法过滤异常时间间隔."""
	min_count_for_filter = 3
	if len(timestamps) < min_count_for_filter:
		return [ts for ts in timestamps if ts <= current_time]

	sorted_ts = np.array(sorted(timestamps), dtype=np.float64)
	intervals = np.diff(sorted_ts)
	q1 = np.percentile(intervals, 25)
	q3 = np.percentile(intervals, 75)
	iqr = q3 - q1
	lower_bound = q1 - 3.0 * iqr
	upper_bound = q3 + 3.0 * iqr
	mask = (intervals >= lower_bound) & (intervals <= upper_bound)
	filtered_indices = np.concatenate(([0], np.where(mask)[0] + 1))
	filtered_ts = sorted_ts[filtered_indices]
	current_mask = filtered_ts <= current_time
	final_ts = filtered_ts[current_mask]
	return [int(x) for x in final_ts.tolist()]


def aggregate_publish_events(
	timestamps: list[int],
	current_time: int,
	gap_threshold_sec: int = 600,
) -> list[int]:
	"""把视频粒度的时间戳聚合为 UP 主发布事件粒度的时间戳.

	链式扩展: 任意相邻两条时间戳间隔不超过 ``gap_threshold_sec`` 即视作仍在同一次
	发布行为内, 直到出现一次大间隔才开启新事件. 每个事件取最早的时间戳作为代表.
	仅在内存中处理, 不修改持久化文件.
	"""
	valid = sorted(ts for ts in timestamps if ts <= current_time)
	if not valid:
		return []

	aggregated: list[int] = [valid[0]]
	prev = valid[0]
	for ts in valid[1:]:
		if ts - prev > gap_threshold_sec:
			aggregated.append(ts)
		prev = ts
	return aggregated


def calculate_adaptive_lambda(
	timestamps: list[int],
	last_variance: float,
	lambda_base: float,
) -> tuple[float, float]:
	"""根据间隔方差自适应计算遗忘速度."""
	min_count_for_lambda = 2
	if len(timestamps) < min_count_for_lambda:
		return float(lambda_base), 0.0

	timestamps_arr = np.array(sorted(timestamps), dtype=np.float64)
	intervals = np.diff(timestamps_arr)
	current_variance = np.var(intervals, dtype=np.float64)
	mean_interval = np.mean(intervals)
	cv = np.std(intervals) / mean_interval if mean_interval > 0 else 1.0

	lambda_min = lambda_base * 0.3
	lambda_max = lambda_base * (1.0 + cv * 4.0)
	lambda_max = min(lambda_max, lambda_base * 15.0)

	if last_variance > 0:
		variance_trend_normalized = (current_variance - last_variance) / last_variance
	else:
		variance_trend_normalized = 0.0

	seconds_in_day_sq = 86400**2
	normalized_variance = current_variance / seconds_in_day_sq
	if normalized_variance > 0:
		lambda_factor = np.log(1 + normalized_variance * 10) / np.log(11)
	else:
		lambda_factor = 0

	base_adaptive_lambda = lambda_min + (lambda_max - lambda_min) * lambda_factor
	trend_correction = variance_trend_normalized * 0.3 * base_adaptive_lambda
	adaptive_lambda = base_adaptive_lambda + trend_correction
	final_lambda = np.clip(adaptive_lambda, lambda_min, lambda_max)
	return float(final_lambda), float(current_variance)


def discover_periods(timestamps: list[int]) -> list[float]:
	"""通过自相关发现隐含发布周期."""
	min_samples = 50
	max_periods = 3
	min_autocorr = 0.02
	tolerance = 0.2
	min_harmonic_ratio = 2
	min_lag_hours = 48
	max_lag_days = 90
	min_span_hours = 168
	existing_periods = [86400.0, 604800.0, 2592000.0, 31536000.0]

	if len(timestamps) < min_samples:
		return []

	ts_arr = np.array(sorted(timestamps), dtype=np.float64)
	span_hours = int((ts_arr[-1] - ts_arr[0]) / 3600) + 1
	if span_hours < min_span_hours:
		return []

	signal = np.zeros(span_hours, dtype=np.float64)
	for ts in ts_arr:
		idx = min(int((ts - ts_arr[0]) / 3600), span_hours - 1)
		signal[idx] += 1.0

	fft_signal = np.fft.rfft(signal)
	power = np.abs(fft_signal) ** 2
	autocorr = np.fft.irfft(power, n=span_hours)
	if autocorr[0] == 0:
		return []
	autocorr = autocorr / autocorr[0]

	max_lag = min(max_lag_days * 24, span_hours // 2)
	if max_lag <= min_lag_hours:
		return []

	seg = autocorr[min_lag_hours:max_lag]
	peaks: list[tuple[int, float]] = [
		(i + min_lag_hours, float(seg[i]))
		for i in range(1, len(seg) - 1)
		if seg[i] > seg[i - 1] and seg[i] > seg[i + 1] and seg[i] > min_autocorr
	]
	if not peaks:
		return []

	peaks.sort(key=lambda x: -x[1])
	novel: list[float] = []
	for lag, _val in peaks:
		period = lag * 3600.0
		skip = False
		for anchor in existing_periods:
			if abs(period / anchor - 1.0) < tolerance:
				skip = True
				break
		if skip:
			continue
		for selected in novel:
			ratio = max(period, selected) / min(period, selected)
			nearest = round(ratio)
			if nearest >= min_harmonic_ratio and abs(ratio - nearest) < tolerance:
				skip = True
				break
		if skip:
			continue
		novel.append(float(period))
		if len(novel) >= max_periods:
			break

	return novel


def sync_discovered_periods(
	stored_periods: list[float],
	new_periods: list[float],
) -> list[float]:
	"""稳定同步发现周期, 避免 custom_N 索引漂移."""
	match_tol = 0.1
	unmatched_new = list(new_periods)
	result: list[float] = []
	for stored in stored_periods:
		match = next(
			(
				period
				for period in unmatched_new
				if abs(period - stored) / max(stored, 1.0) < match_tol
			),
			None,
		)
		if match is not None:
			result.append(stored)
			unmatched_new.remove(match)
	result.extend(unmatched_new)
	return result


def initialize_wgmm_dimensions(
	config: WgmmConfig,
) -> tuple[dict[str, float], dict[str, float]]:
	"""同步 custom_N 权重和 sigma."""
	dimension_weights = dict(config.dimension_weights)
	sigmas = dict(config.sigmas)
	discovered = config.discovered_periods

	for key in [key for key in list(dimension_weights) if key.startswith("custom_")]:
		suffix = key[len("custom_") :]
		if suffix.isdigit() and int(suffix) >= len(discovered):
			dimension_weights.pop(key, None)
			sigmas.pop(key, None)

	for i in range(len(discovered)):
		key = f"custom_{i}"
		if key not in dimension_weights:
			dimension_weights[key] = 0.1
		if key not in sigmas:
			sigmas[key] = 1.0

	return dimension_weights, sigmas


def learn_dimension_weights(
	timestamps: list[int],
	old_weights: dict[str, float],
	learning_rate: float,
	extra_periods: list[float] | None = None,
) -> dict[str, float]:
	"""动态学习各时间维度权重."""
	min_count_for_learning = 20
	if len(timestamps) < min_count_for_learning:
		return old_weights

	raw_components = get_raw_time_components(
		np.array(timestamps, dtype=np.float64),
		extra_periods,
	)
	dimension_scores = {}
	for dim in raw_components:
		keys = raw_components.get(dim, np.array([], dtype=np.int64))
		if len(keys) == 0:
			dimension_scores[dim] = 0.0
			continue

		_, counts = np.unique(keys, return_counts=True)
		counts_arr = counts.astype(np.float64)
		mean_val = np.mean(counts_arr)
		if mean_val == 0:
			dimension_scores[dim] = 0.0
		else:
			std_dev = np.std(counts_arr)
			if std_dev > 0:
				dimension_scores[dim] = float(mean_val / std_dev)
			else:
				dimension_scores[dim] = float(mean_val)

	scores_array = np.array(list(dimension_scores.values()), dtype=np.float64)
	total_score = np.sum(scores_array, dtype=np.float64)
	if total_score > 0:
		normalized_scores = scores_array / total_score * 2.0
		new_weights = dict(zip(dimension_scores.keys(), normalized_scores, strict=True))
	else:
		new_weights = old_weights

	smoothed_weights = {}
	for key in dimension_scores:
		old_weight = old_weights.get(key, 0.1)
		new_weight = new_weights.get(key, 0.1)
		smoothed = old_weight * (1 - learning_rate) + new_weight * learning_rate
		smoothed_weights[key] = float(smoothed)

	return smoothed_weights


def learn_adaptive_sigmas(
	timestamps: list[int],
	old_sigmas: dict[str, float],
	extra_periods: list[float] | None = None,
) -> dict[str, float]:
	"""根据数据离散度学习 sigma."""
	min_learn_count = 20
	min_sigma_samples = 3
	if len(timestamps) < min_learn_count:
		return old_sigmas

	raw_components = get_raw_time_components(
		np.array(timestamps, dtype=np.float64),
		extra_periods,
	)
	new_sigmas = {}
	for dim in raw_components:
		values = raw_components.get(dim, np.array([], dtype=np.int64))
		if len(values) >= min_sigma_samples:
			value_range = float(np.max(values) - np.min(values))
			if value_range > 0:
				normalized = (values.astype(np.float64) - np.min(values)) / value_range
				std = float(np.std(normalized))
				adaptive_sigma = max(0.2, min(std * 3.0, 3.0))
				old_sigma = old_sigmas.get(dim, 1.0)
				new_sigmas[dim] = old_sigma * 0.7 + adaptive_sigma * 0.3
			else:
				new_sigmas[dim] = old_sigmas.get(dim, 1.0)
		else:
			new_sigmas[dim] = old_sigmas.get(dim, 1.0)

	return new_sigmas
