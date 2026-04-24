"""WGMM 时间特征提取."""

from __future__ import annotations

import numpy as np

from wgmm_monitor.utils.time import get_local_timezone_offset


def vectorized_time_features_numpy(
	timestamps_array: np.ndarray,
	extra_periods: list[float] | None = None,
) -> dict[str, np.ndarray]:
	"""向量化提取周期性时间特征."""
	empty: dict[str, np.ndarray] = {
		"day_sin": np.array([], dtype=np.float64),
		"day_cos": np.array([], dtype=np.float64),
		"week_sin": np.array([], dtype=np.float64),
		"week_cos": np.array([], dtype=np.float64),
		"month_week_sin": np.array([], dtype=np.float64),
		"month_week_cos": np.array([], dtype=np.float64),
		"year_month_sin": np.array([], dtype=np.float64),
		"year_month_cos": np.array([], dtype=np.float64),
	}
	if len(timestamps_array) == 0:
		for k, _period in enumerate(extra_periods or []):
			empty[f"custom_{k}_sin"] = np.array([], dtype=np.float64)
			empty[f"custom_{k}_cos"] = np.array([], dtype=np.float64)
		return empty

	ts_arr = np.array(timestamps_array, dtype=np.float64)
	offset = get_local_timezone_offset()
	dt64_local = (ts_arr + offset).astype("datetime64[s]")

	seconds_in_day = (dt64_local.astype("int64") % 86400).astype(np.float64)
	days_since_epoch = dt64_local.astype("datetime64[D]").astype("int64")
	weekday = (days_since_epoch + 3) % 7
	dates_m = dt64_local.astype("datetime64[M]")
	months = (dates_m - dates_m.astype("datetime64[Y]")).astype(int) + 1

	day_of_month = (
		dt64_local.astype("datetime64[D]") - dates_m.astype("datetime64[D]")
	).astype(int) + 1
	first_day_epoch = dates_m.astype("datetime64[D]").astype("int64")
	first_weekday = (first_day_epoch + 3) % 7
	current_week_of_month = (day_of_month - 1 + first_weekday) // 7 + 1
	current_second_of_week = weekday * 86400.0 + seconds_in_day

	features = {}
	const_2pi = 2 * np.pi
	features["day_sin"] = np.sin(const_2pi * seconds_in_day / 86400.0)
	features["day_cos"] = np.cos(const_2pi * seconds_in_day / 86400.0)
	features["week_sin"] = np.sin(const_2pi * current_second_of_week / 604800.0)
	features["week_cos"] = np.cos(const_2pi * current_second_of_week / 604800.0)
	features["month_week_sin"] = np.sin(const_2pi * current_week_of_month / 6.0)
	features["month_week_cos"] = np.cos(const_2pi * current_week_of_month / 6.0)
	features["year_month_sin"] = np.sin(const_2pi * months / 12.0)
	features["year_month_cos"] = np.cos(const_2pi * months / 12.0)

	for k, period in enumerate(extra_periods or []):
		phase = const_2pi * ts_arr / period
		features[f"custom_{k}_sin"] = np.sin(phase)
		features[f"custom_{k}_cos"] = np.cos(phase)

	return features


def get_raw_time_components(
	timestamps_array: np.ndarray,
	extra_periods: list[float] | None = None,
) -> dict[str, np.ndarray]:
	"""提取离散时间维度值, 用于权重学习."""
	empty: dict[str, np.ndarray] = {
		"day": np.array([], dtype=np.int64),
		"week": np.array([], dtype=np.int64),
		"month_week": np.array([], dtype=np.int64),
		"year_month": np.array([], dtype=np.int64),
	}
	if len(timestamps_array) == 0:
		for k in range(len(extra_periods or [])):
			empty[f"custom_{k}"] = np.array([], dtype=np.int64)
		return empty

	ts_arr = np.array(timestamps_array, dtype=np.float64)
	offset = get_local_timezone_offset()
	dt64_local = (ts_arr + offset).astype("datetime64[s]")

	seconds_in_day = dt64_local.astype("int64") % 86400
	days_since_epoch = dt64_local.astype("datetime64[D]").astype("int64")
	dates_m = dt64_local.astype("datetime64[M]")

	hours = (seconds_in_day // 3600).astype(np.int64)
	weekday = (days_since_epoch + 3) % 7
	months = (dates_m - dates_m.astype("datetime64[Y]")).astype(int) + 1

	day_of_month = (
		dt64_local.astype("datetime64[D]") - dates_m.astype("datetime64[D]")
	).astype(int) + 1
	first_day_epoch = dates_m.astype("datetime64[D]").astype("int64")
	first_weekday = (first_day_epoch + 3) % 7
	month_week = (day_of_month - 1 + first_weekday) // 7 + 1

	raw_components: dict[str, np.ndarray] = {
		"day": hours,
		"week": weekday,
		"month_week": month_week,
		"year_month": months,
	}

	n_buckets = 24
	for k, period in enumerate(extra_periods or []):
		phase_bucket = (ts_arr % period) / period * n_buckets
		raw_components[f"custom_{k}"] = np.clip(
			phase_bucket.astype(np.int64),
			0,
			n_buckets - 1,
		)

	return raw_components
