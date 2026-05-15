"""Evaluate WGMM algorithm variants using release 0.01 data."""

from __future__ import annotations

import random
from pathlib import Path
from statistics import mean

import numpy as np

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm.constants import LAMBDA_BASE, LOOKAHEAD_DAYS, SECONDS_IN_DAY
from wgmm_monitor.wgmm.learning import (
	aggregate_publish_events,
	calculate_adaptive_lambda,
	filter_outliers,
	initialize_wgmm_dimensions,
	learn_adaptive_sigmas,
	learn_dimension_weights,
)
from wgmm_monitor.wgmm.scoring import batch_calculate_scores

MIN_HISTORY = 10
MIN_BURST_HISTORY = 20
BURST_COUNT = 3


def load_ts(path: Path) -> list[int]:
	"""Load unix timestamps from a newline-delimited file."""
	vals: list[int] = []
	for raw_line in path.read_text().splitlines():
		line_str = raw_line.strip()
		if line_str:
			vals.append(int(line_str))
	return sorted(vals)


def fit_common(
	positive_events: list[int],
	negative_events: list[int],
) -> tuple[dict[str, float], dict[str, float], float, float]:
	"""Fit shared WGMM components for offline prediction."""
	config = WgmmConfig.from_dict({})
	dim_weights, sigmas = initialize_wgmm_dimensions(config)
	lr = max(0.02, min(0.2, 0.3 - len(positive_events) * 0.001))
	dim_weights = learn_dimension_weights(positive_events, dim_weights, lr, [])
	sigmas = learn_adaptive_sigmas(positive_events, sigmas, [])
	pos_lambda, _ = calculate_adaptive_lambda(positive_events, 0.0, LAMBDA_BASE)
	neg_lambda, _ = calculate_adaptive_lambda(negative_events, 0.0, LAMBDA_BASE)
	return dim_weights, sigmas, pos_lambda, neg_lambda


def scan_peak(
	current_ts: int,
	pos: list[int],
	neg: list[int],
	dim_weights: dict[str, float],
	sigmas: dict[str, float],
	pos_lambda: float,
	neg_lambda: float,
	resistance: float,
) -> tuple[int, float]:
	"""Scan near-future scores and return highest scoring timestamp."""
	step = max(1800.0, (sigmas.get("day", 1.0) * SECONDS_IN_DAY / 24.0) * 0.5)
	end = float(current_ts + LOOKAHEAD_DAYS * SECONDS_IN_DAY)
	scan_times = np.arange(float(current_ts), end, step, dtype=np.float64)
	scores = batch_calculate_scores(
		scan_times,
		pos,
		neg,
		dim_weights,
		pos_lambda,
		neg_lambda,
		sigmas,
		resistance,
		[],
	)
	if len(scores) == 0:
		return current_ts + 3600, 0.0
	idx = int(np.argmax(scores))
	return int(scan_times[idx]), float(scores[idx])


def predict_baseline(
	current_ts: int,
	pos_raw: list[int],
	neg_raw: list[int],
) -> tuple[int, float]:
	"""Predict with baseline WGMM-like scoring."""
	pos = aggregate_publish_events(pos_raw, current_ts)
	neg = filter_outliers(neg_raw, current_ts)
	if len(pos) < MIN_HISTORY:
		return current_ts + 3600, 0.0
	dim_weights, sigmas, pos_lambda, neg_lambda = fit_common(pos, neg)
	intervals = np.diff(np.array(sorted(pos), dtype=np.float64))
	cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 0 else 1.0
	resistance = float(np.clip(0.7 + 0.2 / (1.0 + cv), 0.5, 0.95))
	return scan_peak(
		current_ts,
		pos,
		neg,
		dim_weights,
		sigmas,
		pos_lambda,
		neg_lambda,
		resistance,
	)


def predict_hazard(
	current_ts: int,
	pos_raw: list[int],
	neg_raw: list[int],
) -> tuple[int, float]:
	"""Predict with burst-aware hazard correction."""
	pred_ts, base_score = predict_baseline(current_ts, pos_raw, neg_raw)
	pos = aggregate_publish_events(pos_raw, current_ts)
	if len(pos) < MIN_BURST_HISTORY:
		return pred_ts, base_score
	recent_72h = sum(1 for x in pos if current_ts - 72 * 3600 <= x <= current_ts)
	recent_7d = sum(1 for x in pos if current_ts - 7 * 86400 <= x <= current_ts)
	baseline = max(recent_7d / 7.0, 1e-6)
	hazard_boost = min(2.0, max(0.5, (recent_72h / 3.0) / baseline))
	shift = int((hazard_boost - 1.0) * 4 * 3600)
	adj_pred = max(current_ts, pred_ts - shift)
	adj_score = float(np.clip(base_score * hazard_boost / 1.5, 0.0, 1.0))
	return adj_pred, adj_score


def predict_cooldown(
	current_ts: int,
	pos_raw: list[int],
	neg_raw: list[int],
) -> tuple[int, float]:
	"""Predict with burst-finished cooldown suppression."""
	pred_ts, base_score = predict_baseline(current_ts, pos_raw, neg_raw)
	pos = aggregate_publish_events(pos_raw, current_ts)
	if len(pos) < MIN_BURST_HISTORY:
		return pred_ts, base_score
	recent_24h = sum(1 for x in pos if current_ts - 24 * 3600 <= x <= current_ts)
	recent_48h = sum(1 for x in pos if current_ts - 48 * 3600 <= x <= current_ts)
	recent_6h = sum(1 for x in pos if current_ts - 6 * 3600 <= x <= current_ts)
	if recent_48h >= BURST_COUNT and recent_6h == 0:
		return pred_ts + 6 * 3600, float(base_score * 0.8)
	if recent_24h >= BURST_COUNT:
		return pred_ts + 3 * 3600, float(base_score * 0.9)
	return pred_ts, base_score


def evaluate(
	events: list[int],
	misses: list[int],
	predictor,
	n_trials: int = 120,
	seed: int = 42,
) -> dict[str, float]:
	"""Run random split replay and return error/hit metrics."""
	rng = random.Random(seed)  # noqa: S311
	min_idx = max(40, int(len(events) * 0.3))
	max_idx = len(events) - 6
	sampled_indices = [rng.randint(min_idx, max_idx) for _ in range(n_trials)]
	abs_errors: list[int] = []
	hit_12h = 0
	hit_24h = 0
	for idx in sampled_indices:
		current = events[idx]
		hist_pos = events[:idx]
		future = events[idx + 1]
		hist_neg = [x for x in misses if x <= current]
		pred, _ = predictor(current, hist_pos, hist_neg)
		err = abs(pred - future)
		abs_errors.append(err)
		if err <= 12 * 3600:
			hit_12h += 1
		if err <= 24 * 3600:
			hit_24h += 1
	return {
		"mae_hours": mean(abs_errors) / 3600,
		"p50_hours": sorted(abs_errors)[len(abs_errors) // 2] / 3600,
		"hit12": hit_12h / n_trials,
		"hit24": hit_24h / n_trials,
	}


def main() -> None:
	"""Entry point for offline variant comparison."""
	events = load_ts(Path("data/mtime.txt"))
	misses = load_ts(Path("data/miss_history.txt"))
	variants = {
		"baseline": predict_baseline,
		"hazard": predict_hazard,
		"cooldown": predict_cooldown,
	}
	for name, predictor in variants.items():
		batches = [
			evaluate(events, misses, predictor, n_trials=80, seed=seed)
			for seed in [11, 22, 33, 44, 55]
		]
		agg = {k: round(mean([x[k] for x in batches]), 4) for k in batches[0]}
		print(name)
		print(agg)


if __name__ == "__main__":
	main()
