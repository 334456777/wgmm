"""WGMM 调频决策."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.models import FrequencyDecision, WgmmConfig
from wgmm_monitor.utils.time import format_frequency_interval
from wgmm_monitor.wgmm.constants import (
	FALLBACK_INTERVAL,
	HAZARD_CAP_FLOOR,
	HAZARD_CAP_K,
	HAZARD_CAP_MAX,
	HAZARD_CAP_NN_M,
	HAZARD_CAP_TAIL_ALPHA,
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
			raw_peak_indices = np.where(raw_peaks_mask)[0] + 1

			if len(raw_peak_indices) > 0:
				# 下一次发布 = 视野内"首个显著峰"(得分 > 扫描均值), 而非全局最高峰:
				# 全局众数在多模态周期信号上系统性偏远, 不是"下一到达时间"
				# 应有的数学对象. 无显著峰则退回得分最高的 raw peak.
				peak_scores = scan_scores[raw_peak_indices]
				significant = raw_peak_indices[peak_scores > score_mean]
				if len(significant) > 0:
					best_peak_idx = int(significant[0])
				else:
					best_peak_idx = int(raw_peak_indices[np.argmax(peak_scores)])
				best_peak_score = float(scan_scores[best_peak_idx])
				best_peak_time = float(scan_times[best_peak_idx])
			else:
				global_best_idx = int(np.argmax(scan_scores))
				best_peak_score = float(scan_scores[global_best_idx])
				best_peak_time = float(scan_times[global_best_idx])

	return best_peak_time, best_peak_score, scan_stats


def estimate_hazard_cap(
	positive_events: list[int],
	current_timestamp: int,
) -> float:
	"""基于经验风险率给出检查间隔上限(秒).

	周期得分在低分时段会把间隔拉到峰值距离(最远 15 天), 但"距上次发布
	已等待 tau"本身携带最强的条件信息(重尾间隔分布). 最优巡检理论的
	驻点条件是检查速率 r*(t) ∝ sqrt(h(t)), 即间隔 ∝ h(tau)^-0.5:

	- h(tau) 用幸存间隔(历史间隔中 > tau 者)的 m 近邻跨度估计;
	- tau 超出历史最大间隔后按 Pareto 尾 h=alpha/tau 退化, 间隔 ∝ sqrt(tau);
	- 结果裁剪到 [HAZARD_CAP_FLOOR, HAZARD_CAP_MAX].

	Args:
		positive_events: 正向发布事件时间戳列表.
		current_timestamp: 当前时间戳.

	Returns:
		允许的最大检查间隔(秒).
	"""
	events = sorted(positive_events)
	intervals = np.diff(np.array(events, dtype=np.float64))
	intervals = intervals[intervals > 0]
	if len(intervals) == 0:
		return float(FALLBACK_INTERVAL)
	tau = max(float(current_timestamp) - float(events[-1]), 0.0)
	survivors = np.sort(intervals[intervals > tau]) - tau
	m = min(HAZARD_CAP_NN_M, len(survivors))
	if m >= 1:
		nn_span = max(float(survivors[m - 1]), 60.0)
		hazard = (m / len(survivors)) / nn_span
	else:
		hazard = HAZARD_CAP_TAIL_ALPHA / max(tau, 3600.0)
	interval_cap = HAZARD_CAP_K * hazard**-0.5
	return float(np.clip(interval_cap, HAZARD_CAP_FLOOR, HAZARD_CAP_MAX))


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

	if not in_peak_response:
		final_frequency_sec = max(final_frequency_sec, min_check_interval)

	# 风险率上限(ADR 008): 等待越久允许的间隔越大, 但绝不允许周期得分
	# 把间隔直接拉到峰值距离; 702 天回测均值检测延迟 -57%, P90 -65%.
	hazard_cap = estimate_hazard_cap(positive_events, current_timestamp)
	final_frequency_sec = min(final_frequency_sec, hazard_cap)

	# 阻抗保护(慢网络退避)施加在最后, 不被风险率上限抵消
	impedance_factor = 1.0
	if last_ytdlp_duration > normal_ytdlp_duration * 2.0:
		impedance_ratio = last_ytdlp_duration / max(normal_ytdlp_duration, 1.0)
		impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)
	final_frequency_sec = float(final_frequency_sec * impedance_factor)

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
