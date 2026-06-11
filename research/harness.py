"""闭环监控模拟器: 重放真实发布历史, 度量检测延迟与请求量.

与 ADR 006/007 的单点预测协议不同, 本模拟器复刻生产监控循环:
每次"检查"在时刻 t 发生 -> 检测 (last_check, t] 内的真实发布 -> 按生产数据管线
(aggregate/filter/prune) 准备事件 -> 调用调频决策 -> 推进到下一次检查时刻.

度量:
- 检测延迟 delay = 检查时刻 - 真实发布时刻 (对每个被检测到的发布事件)
- 请求量 checks/day

用法:
    python research/harness.py baseline          # 生产代码基线
    python research/harness.py equivalence       # 自定义 decide 与生产代码等价性校验
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from wgmm_monitor.models import FrequencyDecision, WgmmConfig  # noqa: E402
from wgmm_monitor.utils.time import format_frequency_interval  # noqa: E402
from wgmm_monitor.wgmm.constants import (  # noqa: E402
	FALLBACK_INTERVAL,
	LAMBDA_BASE,
	LOOKAHEAD_DAYS,
	MIN_HISTORY_COUNT,
	PRUNE_THRESHOLD,
	SECONDS_IN_DAY,
)
from wgmm_monitor.wgmm.learning import (  # noqa: E402
	aggregate_publish_events,
	calculate_adaptive_lambda,
	discover_periods,
	filter_outliers,
	initialize_wgmm_dimensions,
	learn_adaptive_sigmas,
	learn_dimension_weights,
	sync_discovered_periods,
)
from wgmm_monitor.wgmm.scheduler import decide_next_frequency, scan_future_peak  # noqa: E402
from wgmm_monitor.wgmm.scoring import calculate_point_score  # noqa: E402

MTIME = REPO / "data" / "mtime.txt"

DEFAULT_PARAMS = {
	"policy": "wgmm",  # wgmm | hazard | hybrid
	"mapping_curve": 2.0,
	"min_interval_pct": 20.0,
	"peak_threshold_mult": 1.2,
	"peak_window_base": 1.0,
	# hazard 策略参数: 每次检查覆盖的条件概率质量
	"hazard_q": 0.15,
	"hazard_floor_sec": 1800.0,
	"hazard_cap_sec": 15 * 86400.0,
	# fixed 参照策略
	"fixed_interval_sec": 7.0 * 3600.0,
	# sqrt_hazard 策略参数
	"sqrth_k": 90.0,
	"nn_m": 5,
	"tail_alpha": 1.2,
	# 可叠加后处理旋钮(None = 关闭, 保持与生产等价)
	"max_interval_cap_sec": None,  # 间隔上限: 修复峰值距离驱动的尾部拉伸
	"burst_window_sec": None,  # 事件后爆发窗口: tau < window 时加密检查
	"burst_interval_sec": 1800.0,
	"sqrt_cap_k": 130.0,  # sqrt_hazard 动态上限: 与生产 HAZARD_CAP_K 对齐(ADR 008)
}


def load_events(path: Path = MTIME) -> list[int]:
	"""加载真实发布时间戳(视频粒度, 去重排序)."""
	raw = [
		int(line.strip())
		for line in path.read_text().splitlines()
		if line.strip().isdigit()
	]
	return sorted(set(raw))


def prune_events(
	events: list[int], last_lambda: float, threshold: float, now: int
) -> list[int]:
	"""复刻 HistoryStore.prune_old_data 的内存逻辑."""
	if not events:
		return events
	arr = np.array(events, dtype=np.float64)
	ages = (float(now) - arr) / 3600.0
	weights = np.exp(-last_lambda * ages)
	mask = (ages >= 0) & (weights >= threshold)
	return arr[mask].astype(int).tolist()


def custom_decide(
	config: WgmmConfig,
	positive_events: list[int],
	negative_events: list[int],
	current_timestamp: int,
	found_new_content: bool,
	params: dict,
	last_ytdlp_duration: float = 0.0,
	normal_ytdlp_duration: float = 60.0,
) -> FrequencyDecision:
	"""decide_next_frequency 的参数化复刻: 学习层完全一致, 映射层可调.

	params 取默认值时必须与生产 decide_next_frequency 产出完全相同的检查序列
	(由 equivalence 模式校验).
	"""
	dimension_weights_from_config, sigmas_from_config = initialize_wgmm_dimensions(config)

	is_manual_run = config.is_manual_run
	if is_manual_run:
		config.is_manual_run = False

	if len(positive_events) < MIN_HISTORY_COUNT:
		if positive_events or negative_events:
			combined = np.array(
				sorted(positive_events + negative_events), dtype=np.float64
			)
		else:
			combined = np.array([], dtype=np.float64)
		if len(combined) > 1:
			ivals = np.diff(combined)
			ivals = ivals[ivals > 0]
			learning_interval = (
				float(np.percentile(ivals, 50)) if len(ivals) else float(FALLBACK_INTERVAL)
			)
		else:
			learning_interval = float(FALLBACK_INTERVAL)
		next_check_time = current_timestamp + int(learning_interval)
		config.next_check_time = next_check_time
		return FrequencyDecision(
			config=config,
			next_check_time=next_check_time,
			final_frequency_sec=learning_interval,
			found_new_content=found_new_content,
			should_save_miss=False,
			miss_timestamp=None,
			log_message="learning mode",
			positive_count=len(positive_events),
			negative_count=len(negative_events),
			learning_mode=True,
		)

	learning_rate = max(0.02, min(0.2, 0.3 - len(positive_events) * 0.001))
	pos_lambda, pos_var = calculate_adaptive_lambda(
		positive_events, config.last_pos_variance, LAMBDA_BASE
	)
	neg_lambda, neg_var = calculate_adaptive_lambda(
		negative_events, config.last_neg_variance, LAMBDA_BASE
	)

	discovered = discover_periods(positive_events)
	config.discovered_periods = sync_discovered_periods(
		config.discovered_periods, discovered
	)
	extra_periods = list(config.discovered_periods)
	dimension_weights_from_config, sigmas_from_config = initialize_wgmm_dimensions(config)

	dimension_weights = learn_dimension_weights(
		positive_events, dimension_weights_from_config, learning_rate, extra_periods
	)
	learned_sigmas = learn_adaptive_sigmas(
		positive_events, sigmas_from_config, extra_periods
	)
	sigmas = {k: float(v) for k, v in learned_sigmas.items()}

	intervals = np.diff(np.array(sorted(positive_events), dtype=np.float64))
	cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 0 else 1.0
	resistance_coefficient = float(np.clip(0.7 + 0.2 / (1.0 + cv), 0.5, 0.95))

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
		min_check_interval = float(
			np.percentile(positive_intervals, params["min_interval_pct"])
		)
	else:
		min_check_interval = float(FALLBACK_INTERVAL)
	peak_distance = max(best_peak_time - current_timestamp, 0.0)
	max_check_interval = max(peak_distance, min_check_interval)

	scan_min = scan_stats.get("min", 0.0)
	scan_max = scan_stats.get("max", current_score)
	score_range = scan_max - scan_min
	near_zero = 1e-9
	if score_range > near_zero:
		relative_score = float(
			np.clip((current_score - scan_min) / score_range, 0.0, 1.0)
		)
	else:
		relative_score = 0.5

	# ---- 映射层(策略钩子) ----
	policy = params["policy"]
	in_peak_response = False
	if policy == "wgmm":
		exponential_score = relative_score ** params["mapping_curve"]
		check_interval = (
			max_check_interval - (max_check_interval - min_check_interval) * exponential_score
		)
		final_frequency_sec = check_interval
		best_peak_threshold = current_score * params["peak_threshold_mult"]
		if best_peak_score > best_peak_threshold:
			peak_interval = best_peak_time - current_timestamp
			peak_window_ratio = params["peak_window_base"] + best_peak_score
			if peak_interval < check_interval * peak_window_ratio:
				peak_advance_sec = max(
					float(last_ytdlp_duration), float(normal_ytdlp_duration)
				)
				advanced_time = best_peak_time - peak_advance_sec
				final_frequency_sec = float(
					max(advanced_time - current_timestamp, 0.0)
				)
				in_peak_response = True
	elif policy == "fixed":
		final_frequency_sec = float(params["fixed_interval_sec"])
		min_check_interval = float(params["fixed_interval_sec"])
	elif policy == "sqrt_hazard":
		final_frequency_sec = sqrt_hazard_interval(
			positive_events, current_timestamp, params
		)
		min_check_interval = params["hazard_floor_sec"]
	elif policy == "hazard":
		final_frequency_sec = hazard_interval(
			positive_events, current_timestamp, params
		)
		min_check_interval = params["hazard_floor_sec"]
	elif policy == "hybrid":
		# WGMM 峰值响应保留, 非峰值区间用 hazard 间隔
		exponential_score = relative_score ** params["mapping_curve"]
		check_interval = (
			max_check_interval - (max_check_interval - min_check_interval) * exponential_score
		)
		hz = hazard_interval(positive_events, current_timestamp, params)
		final_frequency_sec = min(check_interval, hz)
		min_check_interval = min(min_check_interval, max(hz, params["hazard_floor_sec"]))
		best_peak_threshold = current_score * params["peak_threshold_mult"]
		if best_peak_score > best_peak_threshold:
			peak_interval = best_peak_time - current_timestamp
			peak_window_ratio = params["peak_window_base"] + best_peak_score
			if peak_interval < check_interval * peak_window_ratio:
				peak_advance_sec = max(
					float(last_ytdlp_duration), float(normal_ytdlp_duration)
				)
				advanced_time = best_peak_time - peak_advance_sec
				candidate = float(max(advanced_time - current_timestamp, 0.0))
				final_frequency_sec = min(final_frequency_sec, candidate) if candidate > 0 else final_frequency_sec
				in_peak_response = True
	else:
		raise ValueError(f"unknown policy: {policy}")

	impedance_factor = 1.0
	if last_ytdlp_duration > normal_ytdlp_duration * 2.0:
		impedance_ratio = last_ytdlp_duration / max(normal_ytdlp_duration, 1.0)
		impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)

	final_frequency_sec = float(final_frequency_sec * impedance_factor)
	if not in_peak_response:
		final_frequency_sec = max(final_frequency_sec, min_check_interval)

	cap = params.get("max_interval_cap_sec")
	if cap is not None:
		final_frequency_sec = min(final_frequency_sec, float(cap))
	sqrt_cap_k = params.get("sqrt_cap_k")
	if sqrt_cap_k is not None:
		hz_params = dict(params)
		hz_params["sqrth_k"] = float(sqrt_cap_k)
		hz = sqrt_hazard_interval(positive_events, current_timestamp, hz_params)
		final_frequency_sec = min(final_frequency_sec, hz)
	burst_window = params.get("burst_window_sec")
	if burst_window is not None and positive_events:
		tau = float(current_timestamp) - float(max(positive_events))
		if 0.0 <= tau < float(burst_window):
			final_frequency_sec = min(
				final_frequency_sec, float(params["burst_interval_sec"])
			)

	next_check_time = current_timestamp + int(final_frequency_sec)
	config.last_update = current_timestamp
	config.next_check_time = next_check_time
	config.dimension_weights = dimension_weights
	config.sigmas = sigmas
	config.last_lambda = pos_lambda
	config.last_pos_variance = pos_var
	config.last_neg_variance = neg_var

	should_save_miss = not found_new_content and not is_manual_run
	return FrequencyDecision(
		config=config,
		next_check_time=next_check_time,
		final_frequency_sec=final_frequency_sec,
		found_new_content=found_new_content,
		should_save_miss=should_save_miss,
		miss_timestamp=current_timestamp if should_save_miss else None,
		log_message=f"sim - {format_frequency_interval(final_frequency_sec)}",
		positive_count=len(positive_events),
		negative_count=len(negative_events),
	)


def hazard_interval(
	positive_events: list[int], current_timestamp: int, params: dict
) -> float:
	"""基于经验间隔分布的条件分位调度.

	已等待 tau 而无事件时, 下次检查间隔 = 条件分布 P(T - tau <= d | T > tau)
	的 q 分位点: 每次检查覆盖恒定概率质量, 在等请求预算下逼近最小期望延迟.
	"""
	events = sorted(positive_events)
	intervals = np.diff(np.array(events, dtype=np.float64))
	intervals = intervals[intervals > 0]
	if len(intervals) == 0:
		return float(FALLBACK_INTERVAL)
	tau = max(float(current_timestamp) - float(events[-1]), 0.0)
	survivors = intervals[intervals > tau] - tau
	if len(survivors) == 0:
		# 已超出历史最大间隔: 按比例增长等待
		delta = tau * params["hazard_q"]
	else:
		delta = float(np.percentile(survivors, params["hazard_q"] * 100.0))
	return float(np.clip(delta, params["hazard_floor_sec"], params["hazard_cap_sec"]))


def sqrt_hazard_interval(
	positive_events: list[int], current_timestamp: int, params: dict
) -> float:
	"""KKT 最优形态: 检查间隔 ∝ 1/sqrt(经验风险率).

	高频渐近下 E[延迟]≈∫f/(2r)dt, E[检查数]≈∫rS dt, 拉格朗日驻点
	r*(t)=sqrt(h(t)/2λ). 经验 h 用 m 近邻估计; 尾部按 Pareto h=α/t,
	即 Δ∝sqrt(tau), 比几何回退温和.
	"""
	events = sorted(positive_events)
	intervals = np.diff(np.array(events, dtype=np.float64))
	intervals = intervals[intervals > 0]
	if len(intervals) == 0:
		return float(FALLBACK_INTERVAL)
	tau = max(float(current_timestamp) - float(events[-1]), 0.0)
	survivors = np.sort(intervals[intervals > tau]) - tau
	m = min(int(params["nn_m"]), len(survivors))
	if m >= 1:
		d_m = max(float(survivors[m - 1]), 60.0)
		hazard = (m / len(survivors)) / d_m
	else:
		hazard = params["tail_alpha"] / max(tau, 3600.0)
	delta = params["sqrth_k"] * hazard**-0.5
	return float(np.clip(delta, params["hazard_floor_sec"], params["hazard_cap_sec"]))


def simulate(
	all_events: list[int],
	t_start: int,
	t_end: int,
	decide: str | dict = "production",
	min_step: float = 60.0,
) -> dict:
	"""闭环模拟主循环.

	decide = "production" 使用生产 decide_next_frequency;
	decide = params dict 使用 custom_decide.
	"""
	events = sorted(all_events)
	pos_raw = [e for e in events if e <= t_start]
	future = [e for e in events if t_start < e <= t_end]
	neg_raw: list[int] = []
	config = WgmmConfig()
	t = int(t_start)
	records: list[tuple[int, float, bool]] = []  # (event_ts, delay_h, is_session_start)
	check_times: list[int] = []
	clamped = 0
	fi = 0
	runout_limit = t_end + 90 * 86400

	# run-out 协议: 越过 t_end 继续检查直到窗内事件全部检出(消除截断偏差),
	# 但预算只计 t < t_end 的检查.
	while (t < t_end or fi < len(future)) and t < runout_limit:
		check_times.append(t)
		newly = []
		while fi < len(future) and future[fi] <= t:
			newly.append(future[fi])
			fi += 1
		found_new = len(newly) > 0
		for e in newly:
			prev = pos_raw[-1] if pos_raw else None
			is_session_start = prev is None or e - prev > 600
			records.append((e, (t - e) / 3600.0, is_session_start))
			pos_raw.append(e)

		pos = aggregate_publish_events(pos_raw, t)
		neg = filter_outliers(neg_raw, t)
		total = len(pos) + len(neg)
		wthr = max(0.0001, 0.001 * (100 / (total + 50)))
		# 复刻生产 prune_old_data: 仅在实际删除时回写 raw(文件)语义
		if len(pos) >= PRUNE_THRESHOLD:
			pruned = prune_events(pos, config.last_lambda or LAMBDA_BASE, wthr, t)
			if len(pruned) < len(pos):
				pos = pruned
				pos_raw = list(pruned)
		if len(neg) >= PRUNE_THRESHOLD:
			pruned = prune_events(neg, config.last_lambda or LAMBDA_BASE, wthr, t)
			if len(pruned) < len(neg):
				neg = pruned
				neg_raw = list(pruned)

		if decide == "production":
			decision = decide_next_frequency(
				config=config,
				positive_events=pos,
				negative_events=neg,
				current_timestamp=t,
				found_new_content=found_new,
			)
		else:
			decision = custom_decide(config, pos, neg, t, found_new, decide)

		if decision.should_save_miss and decision.miss_timestamp is not None:
			neg_raw.append(decision.miss_timestamp)

		if decision.next_check_time < t + int(min_step):
			clamped += 1
		t = max(decision.next_check_time, t + int(min_step))

	return {
		"t_start": int(t_start),
		"t_end": int(t_end),
		"records": records,
		"check_times": check_times,
		"clamped": clamped,
		"events_undetected_at_end": len(future) - fi,
	}


def slice_metrics(sim: dict, slice_start: int, slice_end: int) -> dict:
	"""按事件时间切片计算指标; 预算只计切片内的检查."""
	recs = [r for r in sim["records"] if slice_start <= r[0] < slice_end]
	checks = [c for c in sim["check_times"] if slice_start <= c < slice_end]
	span_days = (slice_end - slice_start) / 86400.0
	out: dict = {
		"checks": len(checks),
		"checks_per_day": len(checks) / span_days,
		"span_days": span_days,
		"clamped": sim["clamped"],
		"events_undetected_at_end": sim["events_undetected_at_end"],
	}
	for tag, sel in (
		("all", recs),
		("session", [r for r in recs if r[2]]),
	):
		d = np.array([r[1] for r in sel], dtype=np.float64)
		out[f"n_{tag}"] = len(d)
		out[f"mean_{tag}"] = float(np.mean(d)) if len(d) else None
		out[f"median_{tag}"] = float(np.median(d)) if len(d) else None
		out[f"p90_{tag}"] = float(np.percentile(d, 90)) if len(d) else None
		out[f"max_{tag}"] = float(np.max(d)) if len(d) else None
	return out


def span_fraction(events: list[int], frac: float) -> int:
	"""时间轴上 frac 比例处的时间戳."""
	return int(events[0] + (events[-1] - events[0]) * frac)


def run_protocol(overrides: dict | str, start_frac: float = 0.30) -> dict:
	"""标准评估协议: 暖启动单次模拟(含 run-out), 按事件时间切片 train/val.

	train = [30%, 70%), val = [70%, 末事件+1). 预算与延迟均按切片归因.
	"""
	events = load_events()
	t0 = span_fraction(events, start_frac)
	t70 = span_fraction(events, 0.70)
	t_end = events[-1] + 1
	if overrides == "production":
		sim = simulate(events, t0, t_end, "production")
	else:
		params = dict(DEFAULT_PARAMS)
		params.update(overrides)
		sim = simulate(events, t0, t_end, params)
	return {
		"train": slice_metrics(sim, t0, t70),
		"val": slice_metrics(sim, t70, t_end),
		"full": slice_metrics(sim, t0, t_end),
		"records": [[r[0], round(r[1], 3), r[2]] for r in sim["records"]],
	}


def main() -> None:
	"""CLI 入口."""
	mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
	events = load_events()
	t0 = span_fraction(events, 0.30)
	t_end = events[-1] + 1

	if mode == "baseline":
		result = run_protocol("production")
		result.pop("records")
		print(json.dumps(result, indent=2))
	elif mode == "equivalence":
		prod = simulate(events, t0, t_end, "production")
		custom = simulate(events, t0, t_end, dict(DEFAULT_PARAMS))
		same = prod["check_times"] == custom["check_times"]
		print(f"check sequences identical: {same}")
		print(
			f"production checks: {len(prod['check_times'])}, "
			f"custom checks: {len(custom['check_times'])}, "
			f"clamped: prod={prod['clamped']} custom={custom['clamped']}"
		)
		if not same:
			for i, (a, b) in enumerate(
				zip(prod["check_times"], custom["check_times"], strict=False)
			):
				if a != b:
					print(f"first divergence at check #{i}: prod={a} custom={b}")
					break
			sys.exit(1)
	elif mode == "params":
		params_overrides = json.loads(sys.argv[2])
		result = run_protocol(params_overrides)
		result.pop("records")
		print(json.dumps(result, indent=2))
	else:
		print(f"unknown mode: {mode}")
		sys.exit(1)


if __name__ == "__main__":
	main()
