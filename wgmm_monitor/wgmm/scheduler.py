"""WGMM 调频决策."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.models import FrequencyDecision, WgmmConfig
from wgmm_monitor.utils.time import format_frequency_interval
from wgmm_monitor.wgmm.constants import (
	FALLBACK_INTERVAL,
	LAMBDA_BASE,
	LOOKAHEAD_DAYS,
	MAPPING_CURVE,
	MIN_HISTORY_COUNT,
	SECONDS_IN_DAY,
)
from wgmm_monitor.wgmm.learning import (
	calculate_adaptive_lambda,
	discover_periods,
	initialize_wgmm_dimensions,
	learn_adaptive_sigmas,
	learn_dimension_weights,
	sync_discovered_periods,
)
from wgmm_monitor.wgmm.scoring import batch_calculate_scores, calculate_point_score

MIN_BURST_EVENTS = 20


def scan_future_peak(
	current_timestamp: int,
	lookahead_days: int,
	gaussian_width: float,
	current_score: float,
	positive_events: list[int],
	negative_events: list[int],
	dimension_weights: dict[str, float],
	pos_lambda: float,
	neg_lambda: float,
	sigmas: dict[str, float],
	resistance_coefficient: float,
	extra_periods: list[float] | None = None,
) -> tuple[float, float, dict[str, float]]:
	"""扫描未来时间段寻找最佳峰值."""
	lookahead_seconds = lookahead_days * SECONDS_IN_DAY
	lookahead_end = current_timestamp + lookahead_seconds
	min_step = float(gaussian_width * 0.25)
	scan_start = float(current_timestamp)

	best_peak_time = float(scan_start)
	best_peak_score = 0.0
	scan_stats: dict[str, float] = {}
	score_mean = 0.0
	score_std = 0.0

	score_threshold = 0.5
	if lookahead_end > scan_start:
		scan_step = min_step if current_score > score_threshold else min_step * 2
		scan_times = np.arange(
			scan_start,
			lookahead_end + scan_step,
			scan_step,
			dtype=np.float64,
		)
		scan_scores = batch_calculate_scores(
			scan_times,
			positive_events,
			negative_events,
			dimension_weights,
			pos_lambda,
			neg_lambda,
			sigmas,
			resistance_coefficient,
			extra_periods,
		)

		if len(scan_scores) > 0:
			score_mean = float(np.mean(scan_scores))
			score_std = float(np.std(scan_scores))
			scan_stats = {
				"min": float(np.min(scan_scores)),
				"max": float(np.max(scan_scores)),
			}

		if len(scan_scores) == 1:
			best_peak_score = float(scan_scores[0])
			best_peak_time = float(scan_times[0])
		elif len(scan_scores) > 1:
			gradients = np.diff(scan_scores)
			raw_peaks_mask = (gradients[:-1] > 0) & (gradients[1:] < 0)
			peak_score_threshold = score_mean + 1.5 * score_std
			gradient_threshold = 0.05
			filtered_mask = raw_peaks_mask.copy()
			for i in range(len(filtered_mask)):
				if filtered_mask[i]:
					scan_idx = i + 1
					score_condition = scan_scores[scan_idx] > peak_score_threshold
					gradient_condition = abs(gradients[i]) < gradient_threshold
					filtered_mask[i] = score_condition and gradient_condition

			peak_indices = np.where(filtered_mask)[0] + 1
			if len(peak_indices) == 0:
				peak_indices = np.where(raw_peaks_mask)[0] + 1

			if len(peak_indices) > 0:
				peak_scores = scan_scores[peak_indices]
				best_idx_in_peaks = np.argmax(peak_scores)
				best_peak_idx = int(peak_indices[best_idx_in_peaks])
				best_peak_score = float(peak_scores[best_idx_in_peaks])
				best_peak_time = float(scan_times[best_peak_idx])
			else:
				global_best_idx = int(np.argmax(scan_scores))
				best_peak_score = float(scan_scores[global_best_idx])
				best_peak_time = float(scan_times[global_best_idx])

	return best_peak_time, best_peak_score, scan_stats




def compute_burst_adjustment(current_timestamp: int, positive_events: list[int]) -> float:
	"""Compute burst-state adjustment factor based on recent publish intensity."""
	if len(positive_events) < MIN_BURST_EVENTS:
		return 1.0
	recent_72h = sum(
		1
		for ts in positive_events
		if current_timestamp - 72 * 3600 <= ts <= current_timestamp
	)
	recent_7d = sum(
		1
		for ts in positive_events
		if current_timestamp - 7 * SECONDS_IN_DAY <= ts <= current_timestamp
	)
	baseline_daily = max(recent_7d / 7.0, 1e-6)
	recent_daily = recent_72h / 3.0
	ratio = recent_daily / baseline_daily
	return float(np.clip(ratio, 0.6, 1.6))


def decide_next_frequency(
	config: WgmmConfig,
	positive_events: list[int],
	negative_events: list[int],
	current_timestamp: int,
	found_new_content: bool = False,
	dev_mode: bool = False,
	last_ytdlp_duration: float = 0.0,
	normal_ytdlp_duration: float = 60.0,
) -> FrequencyDecision:
	"""根据历史事件生成下一次检查决策."""
	dimension_weights_from_config, sigmas_from_config = initialize_wgmm_dimensions(config)

	if dev_mode:
		is_manual_run = True
	else:
		is_manual_run = config.is_manual_run
		if is_manual_run:
			config.is_manual_run = False

	if len(positive_events) < MIN_HISTORY_COUNT:
		if positive_events or negative_events:
			combined_events = np.array(
				sorted(positive_events + negative_events),
				dtype=np.float64,
			)
		else:
			combined_events = np.array([], dtype=np.float64)
		if len(combined_events) > 1:
			combined_intervals = np.diff(combined_events)
			combined_intervals = combined_intervals[combined_intervals > 0]
			if len(combined_intervals) > 0:
				learning_interval = float(np.percentile(combined_intervals, 50))
			else:
				learning_interval = float(FALLBACK_INTERVAL)
		else:
			learning_interval = float(FALLBACK_INTERVAL)
		next_check_time = current_timestamp + int(learning_interval)
		config.next_check_time = next_check_time
		log_message = f"正向数据不足({len(positive_events)}条), 进入学习期模式"
		return FrequencyDecision(
			config=config,
			next_check_time=next_check_time,
			final_frequency_sec=learning_interval,
			found_new_content=found_new_content,
			should_save_miss=False,
			miss_timestamp=None,
			log_message=log_message,
			positive_count=len(positive_events),
			negative_count=len(negative_events),
			learning_mode=True,
		)

	learning_rate = max(0.02, min(0.2, 0.3 - len(positive_events) * 0.001))

	last_pos_variance = config.last_pos_variance
	pos_lambda, pos_current_variance = calculate_adaptive_lambda(
		positive_events,
		last_pos_variance,
		LAMBDA_BASE,
	)
	last_neg_variance = config.last_neg_variance
	neg_lambda, neg_current_variance = calculate_adaptive_lambda(
		negative_events,
		last_neg_variance,
		LAMBDA_BASE,
	)

	discovered_periods = discover_periods(positive_events)
	config.discovered_periods = sync_discovered_periods(
		config.discovered_periods,
		discovered_periods,
	)
	extra_periods = list(config.discovered_periods)
	dimension_weights_from_config, sigmas_from_config = initialize_wgmm_dimensions(config)

	dimension_weights = learn_dimension_weights(
		positive_events,
		dimension_weights_from_config,
		learning_rate,
		extra_periods,
	)
	learned_sigmas = learn_adaptive_sigmas(
		positive_events,
		sigmas_from_config,
		extra_periods,
	)
	sigmas = {key: float(value) for key, value in learned_sigmas.items()}

	intervals = np.diff(np.array(sorted(positive_events), dtype=np.float64))
	cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 0 else 1.0
	resistance_coefficient = 0.7 + 0.2 / (1.0 + cv)
	resistance_coefficient = float(np.clip(resistance_coefficient, 0.5, 0.95))

	current_score = calculate_point_score(
		current_timestamp,
		positive_events,
		negative_events,
		dimension_weights,
		pos_lambda,
		neg_lambda,
		sigmas,
		resistance_coefficient,
		extra_periods,
	)

	gaussian_width = (sigmas["day"] * SECONDS_IN_DAY / 24.0) * 2.0
	best_peak_time, best_peak_score, scan_stats = scan_future_peak(
		current_timestamp=current_timestamp,
		lookahead_days=LOOKAHEAD_DAYS,
		gaussian_width=gaussian_width,
		current_score=current_score,
		positive_events=positive_events,
		negative_events=negative_events,
		dimension_weights=dimension_weights,
		pos_lambda=pos_lambda,
		neg_lambda=neg_lambda,
		sigmas=sigmas,
		resistance_coefficient=resistance_coefficient,
		extra_periods=extra_periods,
	)

	positive_intervals = intervals[intervals > 0]
	if len(positive_intervals) > 0:
		min_check_interval = float(np.percentile(positive_intervals, 20))
	else:
		min_check_interval = float(FALLBACK_INTERVAL)
	peak_distance = max(best_peak_time - current_timestamp, 0.0)
	max_check_interval = max(peak_distance, min_check_interval)

	scan_min = scan_stats.get("min", 0.0)
	scan_max = scan_stats.get("max", current_score)
	score_range = scan_max - scan_min
	near_zero = 1e-9
	if score_range > near_zero:
		relative_score = float(np.clip((current_score - scan_min) / score_range, 0.0, 1.0))
	else:
		relative_score = 0.5

	burst_adjustment = compute_burst_adjustment(current_timestamp, positive_events)
	relative_score = float(np.clip(relative_score / burst_adjustment, 0.0, 1.0))
	exponential_score = relative_score**MAPPING_CURVE
	check_interval = (
		max_check_interval - (max_check_interval - min_check_interval) * exponential_score
	)

	final_frequency_sec = check_interval
	in_peak_response = False
	best_peak_threshold = current_score * 1.2
	if best_peak_score > best_peak_threshold:
		peak_interval = best_peak_time - current_timestamp
		peak_window_ratio = 1.0 + best_peak_score
		if peak_interval < check_interval * peak_window_ratio:
			peak_advance_sec = max(float(last_ytdlp_duration), float(normal_ytdlp_duration))
			advanced_time = best_peak_time - peak_advance_sec
			advanced_interval = advanced_time - current_timestamp
			final_frequency_sec = float(max(advanced_interval, 0.0))
			in_peak_response = True

	impedance_factor = 1.0
	if last_ytdlp_duration > normal_ytdlp_duration * 2.0:
		impedance_ratio = last_ytdlp_duration / max(normal_ytdlp_duration, 1.0)
		impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)

	final_frequency_sec = float(final_frequency_sec * impedance_factor)
	if not in_peak_response:
		final_frequency_sec = max(final_frequency_sec, min_check_interval)

	next_check_time = current_timestamp + int(final_frequency_sec)
	config.last_update = current_timestamp
	config.next_check_time = next_check_time
	config.dimension_weights = dimension_weights
	config.sigmas = sigmas
	config.last_lambda = pos_lambda
	config.last_pos_variance = pos_current_variance
	config.last_neg_variance = neg_current_variance

	should_save_miss = not found_new_content and not is_manual_run
	polling_interval_str = format_frequency_interval(final_frequency_sec)
	return FrequencyDecision(
		config=config,
		next_check_time=next_check_time,
		final_frequency_sec=final_frequency_sec,
		found_new_content=found_new_content,
		should_save_miss=should_save_miss,
		miss_timestamp=current_timestamp if should_save_miss else None,
		log_message=f"WGMM调频 - 轮询间隔: {polling_interval_str}",
		positive_count=len(positive_events),
		negative_count=len(negative_events),
	)
